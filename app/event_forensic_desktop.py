from __future__ import annotations

import json
import threading
import traceback
import webbrowser
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import perf_counter
from urllib.parse import parse_qs, urlparse

from app.browser_static_assets import is_browser_vendor_asset_path, load_browser_vendor_asset
from app.config import AppConfig, funding_trace_mode, normalize_funding_trace_mode
from app.event_forensic import EventForensicAnalyzer
from app.local_server import (
    LocalRequestError,
    LocalServerHandle,
    new_session_token,
    open_local_path,
    read_json_body,
    request_has_valid_session,
    require_allowed_path,
    require_local_request,
    safe_child_path,
    session_cookie_header,
    tokenized_local_url,
)
from app.polymarket import PolymarketClient
from app.scanner import ProgressEvent
from app.storage import Storage
from app.case_reviewer import ReviewInputError, review_event_outputs, review_latest_outputs


REVIEW_ARTIFACT_PATTERNS = {
    "review_packets": ("review_packets", "unique_review_packets_*.md"),
    "review_packet_quality": ("analyst_quality_outputs", "review_packet_quality_check_*.md"),
    "wallet_review_queue": ("analyst_quality_outputs", "wallet_review_queue_*.md"),
    "analyst_handoff_bundle": ("analyst_review_bundles", "analyst_review_bundle_*.md"),
    "artifact_manifest": ("artifact_manifests", "review_artifact_manifest_*.md"),
    "false_positive_library": ("false_positive_library", "false_positive_pattern_library_*.md"),
    "source_attribution": ("source_attribution_outputs", "source_attribution_completeness_*.md"),
    "source_schema_repair_plan": ("source_schema_repair_outputs", "source_schema_repair_plan_*.md"),
    "implementation_boundary": ("implementation_boundaries", "implementation_boundary_*.md"),
    "analyst_crosswalk": ("implementation_boundaries", "analyst_crosswalk_*.md"),
    "review_output_index": ("review_index_outputs", "review_output_index_*.md"),
    "schema_normalization": ("schema_normalization_outputs", "review_schema_normalization_check_*.md"),
    "candidate_recall": ("candidate_recall_outputs", "candidate_recall_diagnostic_*.md"),
}


class EventForensicBrowserApp:
    def __init__(self) -> None:
        self.config = AppConfig.load_event_forensic_analyzer()
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)
        self.storage.init()
        self.client = PolymarketClient()
        self.analyzer = EventForensicAnalyzer(self.client, self.storage, self.config)

        self._lock = threading.RLock()
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.current_report: dict[str, object] | None = None
        self.current_output_path: Path | None = None
        self.resolved_target: dict[str, object] | None = None
        self.performance_log_path: Path | None = None
        self.performance_log_started_at: float | None = None
        self.session_token = new_session_token()
        self.scan_status = {
            "running": False,
            "stage": "Ready",
            "detail": "No event analysis running",
            "percent": 0.0,
            "label": "Ready",
            "error": None,
            "progressMetrics": {},
        }
        self.case_review_status = {
            "running": False,
            "stage": "Idle",
            "detail": "No case review has run yet.",
            "error": None,
            "summary": {},
            "outputs": {},
            "llm": {"enabled": False, "status": "not_requested"},
        }
        self.auto_run_case_reviewer = False
        self.auto_run_case_reviewer_use_llm = False
        self.default_filters = {
            "url": "",
            "minSize": "1000",
            "maxEntryProbability": "",
            "startDateTime": "",
            "endDateTime": "",
            "includeRelatedMarkets": True,
            "includeBlockchain": False,
            "fundingTraceMode": funding_trace_mode(),
            "analysisScope": "event",
            "selectedConditionId": "",
            "selectedMarketSlug": "",
            "autoRunReviewer": False,
            "useLLMReviewer": False,
        }
        self.app_meta = {
            "mode": "event-forensic",
            "title": "InsPoly Event Forensic Analyzer",
            "hero": "Completed Event Forensic Laboratory",
            "launchLabel": "InsPoly Event Forensic Analyzer UI",
        }
        self.asset_name = "browser_event_forensic_ui.html"
        self._load_latest_report()

    def launch(self) -> None:
        handle = self.create_server()
        print(f"{handle.label}: {handle.url}")
        webbrowser.open(handle.url)
        try:
            handle.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            handle.close()

    def create_server(self) -> LocalServerHandle:
        asset_path = Path(__file__).with_name(self.asset_name)
        handler = self._make_handler(asset_path)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.session_token = new_session_token()
        url = tokenized_local_url(server.server_port, self.session_token)
        return LocalServerHandle(
            server=server,
            url=url,
            label=self.app_meta["launchLabel"],
        )

    def _make_handler(self, asset_path: Path):
        app = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                try:
                    parsed = urlparse(self.path)
                    if not require_local_request(
                        self,
                        parsed,
                        app.session_token,
                        require_token=parsed.path.startswith("/api/"),
                    ):
                        return
                    if parsed.path == "/":
                        headers = {}
                        if request_has_valid_session(self, parsed, app.session_token):
                            headers["Set-Cookie"] = session_cookie_header(app.session_token)
                        self._send_bytes(asset_path.read_bytes(), "text/html; charset=utf-8", headers=headers)
                        return
                    vendor_asset = load_browser_vendor_asset(parsed.path)
                    if vendor_asset:
                        data, content_type = vendor_asset
                        self._send_bytes(data, content_type)
                        return
                    if is_browser_vendor_asset_path(parsed.path):
                        self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                        return
                    if parsed.path == "/api/bootstrap":
                        self._send_json(app.bootstrap_payload())
                        return
                    if parsed.path == "/api/run":
                        name = parse_qs(parsed.query).get("name", [""])[0]
                        self._send_json(app.load_run(name))
                        return
                    self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                except Exception as exc:
                    app._log_error(f"GET {self.path} failed", exc)
                    self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Internal server error")

            def do_POST(self) -> None:
                try:
                    parsed = urlparse(self.path)
                    if not require_local_request(self, parsed, app.session_token, require_token=True):
                        return
                    payload = read_json_body(self)
                    if parsed.path == "/api/analyze":
                        self._send_json(app.start_analysis(payload))
                        return
                    if parsed.path == "/api/resolve-target":
                        self._send_json(app.resolve_target(payload))
                        return
                    if parsed.path == "/api/stop":
                        self._send_json(app.stop_analysis())
                        return
                    if parsed.path == "/api/open-output":
                        self._send_json(app.open_output(payload))
                        return
                    if parsed.path == "/api/open-exports-dir":
                        self._send_json(app.open_exports_dir())
                        return
                    if parsed.path == "/api/run-case-reviewer":
                        self._send_json(app.run_case_reviewer(payload))
                        return
                    self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                except LocalRequestError as exc:
                    self._send_json({"ok": False, "error": exc.message}, status=int(exc.status))
                except Exception as exc:
                    app._log_error(f"POST {self.path} failed", exc)
                    self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Internal server error")

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

            def _send_json(self, payload: dict[str, object], status: int = 200) -> None:
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _send_bytes(
                self,
                data: bytes,
                content_type: str,
                status: int = 200,
                headers: dict[str, str] | None = None,
            ) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(data)

        return Handler

    def bootstrap_payload(self) -> dict[str, object]:
        with self._lock:
            selected_run = None
            if self.current_report:
                report_json_path = self.current_report.get("report_json_path")
                if report_json_path:
                    selected_run = Path(str(report_json_path)).name
            return {
                "ok": True,
                "appMeta": dict(self.app_meta),
                "filters": self._filters_payload(),
                "status": dict(self.scan_status),
                "recentRuns": self._recent_runs_payload(),
                "currentReport": self.current_report,
                "resolvedTarget": self.resolved_target,
                "selectedRun": selected_run,
                "caseReview": dict(self.case_review_status),
                "reviewArtifacts": self._review_artifact_index_payload(),
            }

    def load_run(self, name: str) -> dict[str, object]:
        if not name:
            return {"ok": False, "error": "Missing run name."}
        try:
            json_path = safe_child_path(self.config.reports_dir, name, suffix=".json")
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if not json_path.exists():
            return {"ok": False, "error": f"Run not found: {name}"}
        try:
            report = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": str(exc)}
        with self._lock:
            self.current_report = self._prepare_report(report, report_name=json_path.name)
            self.current_output_path = self._primary_output_path(self.current_report)
            self.resolved_target = self.current_report.get("target_resolution") or self.resolved_target
        return self.bootstrap_payload()

    def start_analysis(self, payload: dict[str, object]) -> dict[str, object]:
        with self._lock:
            if self.worker and self.worker.is_alive():
                return {"ok": False, "error": "An event analysis is already running."}
        try:
            url = str(payload.get("url") or "").strip()
            if not url:
                raise ValueError("Paste a Polymarket event or market URL.")
            min_amount = self._parse_amount(str(payload.get("minSize", ""))) or Decimal("1000")
            include_related = bool(payload.get("includeRelatedMarkets", True))
            include_blockchain = bool(payload.get("includeBlockchain", True))
            funding_mode = normalize_funding_trace_mode(
                str(payload.get("fundingTraceMode") or ""),
                default=funding_trace_mode(),
            )
            include_blockchain = include_blockchain or funding_mode != "disabled"
            analysis_scope = str(payload.get("analysisScope") or "event").strip().lower() or "event"
            if analysis_scope not in {"event", "market"}:
                raise ValueError("Analysis scope must be Whole event or Single market.")
            selected_condition_id = str(payload.get("selectedConditionId") or "").strip() or None
            selected_market_slug = str(payload.get("selectedMarketSlug") or "").strip() or None
            if analysis_scope != "market":
                selected_condition_id = None
                selected_market_slug = None
            start_at = self._parse_optional_datetime(str(payload.get("startDateTime") or ""))
            end_at = self._parse_optional_datetime(str(payload.get("endDateTime") or ""))
            if start_at is not None and end_at is not None and end_at <= start_at:
                raise ValueError("End datetime must be later than start datetime.")
            auto_run_reviewer = bool(payload.get("autoRunReviewer", False))
            use_llm_reviewer = bool(payload.get("useLLMReviewer", False) or payload.get("useLlm", False))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        with self._lock:
            self.stop_event = threading.Event()
            self.current_report = None
            self.current_output_path = None
            self.auto_run_case_reviewer = auto_run_reviewer
            self.auto_run_case_reviewer_use_llm = use_llm_reviewer
            self.case_review_status = {
                "running": False,
                "stage": "Idle",
                "detail": "No case review has run for this analysis yet.",
                "error": None,
                "summary": {},
                "outputs": {},
                "llm": {"enabled": use_llm_reviewer, "status": "not_requested"},
            }
            started_at = datetime.now().astimezone()
            self.performance_log_path = self.config.data_dir / (
                f"perf_profile_{started_at.strftime('%Y%m%d_%H%M%S')}.log"
            )
            self.performance_log_started_at = perf_counter()
            self.scan_status = {
                "running": True,
                "stage": "Starting analysis",
                "detail": "Preparing event forensic analyzer",
                "percent": 0.0,
                "label": "Analysis starting…",
                "error": None,
            }
            self._append_performance_log(f"Run start {started_at.isoformat()} url={url}")

        worker = threading.Thread(
            target=self._run_analysis_worker,
            args=(
                url,
                min_amount,
                include_related,
                include_blockchain,
                funding_mode,
                analysis_scope,
                selected_condition_id,
                selected_market_slug,
                start_at,
                end_at,
            ),
            daemon=True,
        )
        with self._lock:
            self.worker = worker
        worker.start()
        return {"ok": True}

    def resolve_target(self, payload: dict[str, object]) -> dict[str, object]:
        try:
            url = str(payload.get("url") or "").strip()
            if not url:
                raise ValueError("Paste a Polymarket event or market URL.")
            analysis_scope = str(payload.get("analysisScope") or "").strip().lower() or None
            selected_condition_id = str(payload.get("selectedConditionId") or "").strip() or None
            selected_market_slug = str(payload.get("selectedMarketSlug") or "").strip() or None
            if analysis_scope != "market":
                selected_condition_id = None
                selected_market_slug = None
            include_related = bool(payload.get("includeRelatedMarkets", True))
            resolved_target = self.analyzer.resolve_target(
                url,
                analysis_scope=analysis_scope,
                selected_condition_id=selected_condition_id,
                selected_market_slug=selected_market_slug,
                include_related_markets=include_related,
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        with self._lock:
            self.resolved_target = resolved_target
        return {"ok": True, "resolvedTarget": resolved_target}

    def stop_analysis(self) -> dict[str, object]:
        with self._lock:
            if not (self.worker and self.worker.is_alive()):
                return {"ok": False, "error": "No event analysis is currently running."}
            self.stop_event.set()
            self.scan_status.update(
                {
                    "stage": "Stopping",
                    "detail": "Saving partial forensic bundle",
                    "label": "Stopping analysis…",
                }
            )
        return {"ok": True}

    def open_output(self, payload: dict[str, object]) -> dict[str, object]:
        key = str(payload.get("key") or "")
        allowed_roots = self._allowed_open_roots()
        review_artifacts = self._review_artifact_index_payload().get("outputs") or {}
        if key and key in review_artifacts:
            value = review_artifacts.get(key)
            path = Path(str(value)) if value else None
            try:
                if path is not None:
                    path = require_allowed_path(path, allowed_roots)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            if path is None or not path.exists():
                return {"ok": False, "error": "Review artifact not found."}
            open_local_path(path)
            return {"ok": True}

        review_outputs = self.case_review_status.get("outputs") or {}
        if key and key in review_outputs:
            value = review_outputs.get(key)
            path = Path(str(value)) if value else None
            try:
                if path is not None:
                    path = require_allowed_path(path, allowed_roots)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            if path is None or not path.exists():
                return {"ok": False, "error": "Output file not found."}
            open_local_path(path)
            return {"ok": True}

        report = self.current_report
        if report is None:
            return {"ok": False, "error": "No event analysis is loaded."}
        export_files = report.get("export_files") or {}
        if key:
            value = export_files.get(key)
            path = Path(str(value)) if value else None
        else:
            path = self._primary_output_path(report)
        try:
            if path is not None:
                path = require_allowed_path(path, allowed_roots)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if path is None or not path.exists():
            return {"ok": False, "error": "Output file not found."}
        open_local_path(path)
        return {"ok": True}

    def _allowed_open_roots(self) -> list[Path]:
        root = self.config.outputs_dir.parent
        roots = [self.config.outputs_dir, self.config.reports_dir, root / "ai_review_outputs"]
        roots.extend(root / directory for directory, _pattern in REVIEW_ARTIFACT_PATTERNS.values())
        return roots

    def _review_artifact_index_payload(self) -> dict[str, object]:
        outputs: dict[str, str] = {}
        items: list[dict[str, object]] = []
        root = self.config.outputs_dir.parent
        for key, (directory_name, pattern) in REVIEW_ARTIFACT_PATTERNS.items():
            directory = root / directory_name
            candidates = sorted(
                directory.glob(pattern) if directory.exists() else [],
                key=lambda path: (path.stat().st_mtime, path.name),
                reverse=True,
            )
            if not candidates:
                continue
            path = candidates[0]
            outputs[key] = str(path)
            items.append(
                {
                    "key": key,
                    "label": key.replace("_", " ").title(),
                    "path": str(path),
                    "modifiedAt": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                }
            )
        return {
            "outputs": outputs,
            "items": items,
            "detail": "Latest local review artifacts. These are read-only analyst reports and do not change scoring.",
        }

    def run_case_reviewer(self, payload: dict[str, object]) -> dict[str, object]:
        use_llm = bool(payload.get("useLlm", False) or payload.get("useLLMReviewer", False))
        return self._run_case_reviewer_for_loaded_report(use_llm=use_llm)

    def open_exports_dir(self) -> dict[str, object]:
        if not self.config.outputs_dir.exists():
            return {"ok": False, "error": "Exports directory not found."}
        open_local_path(self.config.outputs_dir)
        return {"ok": True}

    def _run_case_reviewer_for_loaded_report(
        self,
        *,
        use_llm: bool,
        automatic: bool = False,
    ) -> dict[str, object]:
        with self._lock:
            report = deepcopy(self.current_report) if self.current_report else None
            self.case_review_status = {
                "running": True,
                "stage": "Running",
                "detail": "Building compact case packets and running deterministic review.",
                "error": None,
                "summary": {},
                "outputs": {},
                "llm": {"enabled": use_llm, "status": "requested" if use_llm else "not_requested"},
            }

        try:
            outputs = self._review_current_or_latest_outputs(report, use_llm=use_llm)
        except ReviewInputError as exc:
            with self._lock:
                self.case_review_status = {
                    "running": False,
                    "stage": "Failed",
                    "detail": str(exc),
                    "error": str(exc),
                    "summary": {},
                    "outputs": {},
                    "llm": {"enabled": use_llm, "status": "failed"},
                }
                status = dict(self.case_review_status)
            return {"ok": False, "error": str(exc), "caseReview": status}
        except Exception as exc:  # noqa: BLE001 - UI wrapper should report reviewer failures cleanly
            self._log_error("case reviewer failed", exc)
            with self._lock:
                self.case_review_status = {
                    "running": False,
                    "stage": "Failed",
                    "detail": f"{type(exc).__name__}: {exc}",
                    "error": str(exc),
                    "summary": {},
                    "outputs": {},
                    "llm": {"enabled": use_llm, "status": "failed"},
                }
                status = dict(self.case_review_status)
            return {"ok": False, "error": str(exc), "caseReview": status}

        summary = {
            "casesReviewed": outputs.get("cases_reviewed", 0),
            "walletCasesReviewed": outputs.get("wallet_cases_reviewed", 0),
            "tradeCasesReviewed": outputs.get("trade_cases_reviewed", 0),
            "clusterCasesReviewed": outputs.get("cluster_cases_reviewed", 0),
            "likelyFalsePositives": outputs.get("likely_false_positive_count", 0),
            "plausibleInsiderStyleCases": outputs.get("plausible_insider_style_count", 0),
            "ambiguousCases": outputs.get("ambiguous_count", 0),
            "topSuggestedFixes": outputs.get("top_suggested_fixes", []),
            "eventTitle": outputs.get("event_title", ""),
            "eventSlug": outputs.get("event_slug", ""),
            "detectedInputDir": outputs.get("detected_input_dir", ""),
        }
        output_keys = (
            "cases_json_path",
            "review_report_md_path",
            "model_changes_md_path",
            "llm_cases_json_path",
            "llm_review_report_md_path",
            "llm_model_changes_md_path",
            "llm_raw_jsonl_path",
        )
        output_paths = {key: outputs[key] for key in output_keys if outputs.get(key)}
        llm = outputs.get("llm") if isinstance(outputs.get("llm"), dict) else {}
        detail_parts = ["Deterministic review completed."]
        if use_llm:
            if llm.get("status") == "completed":
                detail_parts.append("LLM review completed.")
            elif llm.get("status") == "skipped":
                detail_parts.append("LLM review skipped: no provider/API key configured.")
            elif llm.get("status") == "invalid":
                detail_parts.append(str(llm.get("reason") or "LLM review invalid; raw output was saved."))
            elif llm.get("status"):
                detail_parts.append(str(llm.get("reason") or f"LLM status: {llm.get('status')}"))
        detail_parts.append("No production scoring rules were changed.")
        if automatic:
            detail_parts.insert(0, "Automatic reviewer run finished.")

        with self._lock:
            self.case_review_status = {
                "running": False,
                "stage": "Completed",
                "detail": " ".join(detail_parts),
                "error": None,
                "summary": summary,
                "outputs": output_paths,
                "llm": llm or {"enabled": use_llm, "status": "not_requested"},
            }
            status = dict(self.case_review_status)
        return {"ok": True, "caseReview": status}

    def _review_current_or_latest_outputs(
        self,
        report: dict[str, object] | None,
        *,
        use_llm: bool,
    ) -> dict[str, object]:
        export_files = report.get("export_files") if report else {}
        if isinstance(export_files, dict):
            event_analysis = export_files.get("event_analysis_json_path")
            event_analysis_path = Path(str(event_analysis)) if event_analysis else None
            if event_analysis_path and event_analysis_path.exists():
                return review_event_outputs(
                    event_analysis_json_path=event_analysis_path,
                    suspicious_trades_csv_path=self._optional_export_path(export_files, "suspicious_trades_csv_path"),
                    suspicious_wallets_csv_path=self._optional_export_path(export_files, "suspicious_wallets_csv_path"),
                    wallet_context_csv_path=self._optional_export_path(export_files, "wallet_context_csv_path"),
                    wallet_clusters_csv_path=self._optional_export_path(export_files, "wallet_clusters_csv_path"),
                    wallet_graph_json_path=self._optional_export_path(export_files, "wallet_graph_json_path"),
                    model_gap_report_md_path=self._optional_export_path(export_files, "model_gap_report_md_path"),
                    raw_event_bundle_dir=self._optional_export_path(export_files, "raw_event_bundle_dir"),
                    output_dir=self.config.outputs_dir.parent / "ai_review_outputs",
                    use_llm=use_llm,
                    detected_input_dir=event_analysis_path.parent,
                )
        return review_latest_outputs(
            event_forensic_outputs_dir=self.config.outputs_dir,
            output_dir=self.config.outputs_dir.parent / "ai_review_outputs",
            use_llm=use_llm,
        )

    def _optional_export_path(self, export_files: dict[str, object], key: str) -> Path | None:
        value = export_files.get(key)
        return Path(str(value)) if value else None

    def _run_analysis_worker(
        self,
        url: str,
        min_amount: Decimal,
        include_related: bool,
        include_blockchain: bool,
        funding_trace_mode: str,
        analysis_scope: str,
        selected_condition_id: str | None,
        selected_market_slug: str | None,
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> None:
        try:
            report = self.analyzer.analyze(
                url,
                self.config.reports_dir,
                min_notional=min_amount,
                include_related_markets=include_related,
                include_blockchain=include_blockchain,
                funding_trace_mode=funding_trace_mode,
                analysis_scope=analysis_scope,
                selected_condition_id=selected_condition_id,
                selected_market_slug=selected_market_slug,
                start_at=start_at,
                end_at=end_at,
                progress_callback=self._on_progress,
                stop_event=self.stop_event,
            )
        except Exception as exc:
            self._log_error("event forensic worker failed", exc)
            self._append_performance_log(f"FAILED {type(exc).__name__}: {exc}")
            with self._lock:
                self.scan_status = {
                    "running": False,
                    "stage": "Failed",
                    "detail": str(exc),
                    "percent": 0.0,
                    "label": "Analysis failed",
                    "error": str(exc),
                    "progressMetrics": {},
                }
                self.worker = None
            return

        with self._lock:
            self.current_report = self._prepare_report(report)
            self.current_output_path = self._primary_output_path(self.current_report)
            self.resolved_target = self.current_report.get("target_resolution") or self.resolved_target
            display_trades = (self.current_report.get("display_trades") or [])
            summary = self.current_report.get("summary") or {}
            performance = self.current_report.get("performance") or {}
            candidate_trade_count = int(summary.get("candidate_trade_count") or 0)
            suspicious_trade_count = int(summary.get("forensic_suspicious_trade_count") or 0)
            status_label = "Preview saved" if report.get("status") == "preview_only" else "Analysis complete"
            self.scan_status = {
                "running": False,
                "stage": status_label,
                "detail": (
                    report.get("eligibility", {}).get("reason")
                    if report.get("status") == "preview_only"
                    else self._completed_status_detail(
                        suspicious_trade_count=suspicious_trade_count,
                        display_trade_count=len(display_trades),
                        candidate_trade_count=candidate_trade_count,
                        analysis_scope=str(self.current_report.get("analysis_scope") or "event"),
                        selected_market_title=str(self.current_report.get("selected_market_title") or ""),
                        empty_state_note=str(self.current_report.get("empty_state_note") or ""),
                        compatibility_note=str(self.current_report.get("compatibility_note") or ""),
                        analysis_seconds=float(performance.get("total_seconds") or 0.0),
                    )
                ),
                "percent": 100.0,
                "label": status_label,
                "error": None,
                "progressMetrics": dict(performance.get("trade_collection_progress") or {}),
            }
            self.worker = None
            self._append_performance_log(
                (
                    f"Completed status={report.get('status', 'completed')} "
                    f"candidates={candidate_trade_count} suspicious={suspicious_trade_count} "
                    f"runtime={float(performance.get('total_seconds') or 0.0):.2f}s "
                    f"report={self.current_report.get('report_json_path', '')}"
                )
            )
            auto_run_reviewer = self.auto_run_case_reviewer
            auto_use_llm = self.auto_run_case_reviewer_use_llm

        if auto_run_reviewer:
            self._run_case_reviewer_for_loaded_report(use_llm=auto_use_llm, automatic=True)

    def _on_progress(self, event: ProgressEvent) -> None:
        metrics = getattr(event, "metadata", None)
        metrics = dict(metrics) if isinstance(metrics, dict) else {}
        with self._lock:
            self.scan_status = {
                "running": True,
                "stage": event.stage,
                "detail": event.detail,
                "percent": float(event.percent),
                "label": f"{event.stage} {event.percent:.0f}%",
                "error": None,
                "progressMetrics": metrics,
            }
            self._append_performance_log(
                f"{event.percent:5.1f}% | {event.stage} | {event.detail}"
            )

    def _load_latest_report(self) -> None:
        report_files = sorted(self.config.reports_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not report_files:
            return
        for json_path in report_files:
            try:
                report = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            self.current_report = self._prepare_report(report, report_name=json_path.name)
            self.current_output_path = self._primary_output_path(self.current_report)
            self.resolved_target = self.current_report.get("target_resolution") or self.resolved_target
            return

    def _recent_runs_payload(self) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        report_files = sorted(self.config.reports_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for json_path in report_files[:20]:
            try:
                report = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            event = report.get("event") or {}
            summary = report.get("summary") or {}
            records.append(
                {
                    "name": json_path.name,
                    "displayTime": self._format_timestamp(report.get("generated_at", "")),
                    "eventTitle": event.get("title", "Unknown event"),
                    "eventUrl": event.get("canonicalUrl", ""),
                    "tradeCount": summary.get("candidate_trade_count", 0),
                    "suspiciousTradeCount": summary.get("forensic_suspicious_trade_count", 0),
                    "walletCount": summary.get("suspicious_wallet_count", 0),
                    "status": report.get("status", "completed"),
                    "selected": bool(
                        self.current_report
                        and Path(str(self.current_report.get("report_json_path", ""))).name == json_path.name
                    ),
                }
            )
        return records

    def _filters_payload(self) -> dict[str, object]:
        filters = dict(self.default_filters)
        report = self.current_report or {}
        settings = report.get("analysis_settings") or {}
        filters["url"] = str(report.get("input_url") or filters["url"])
        filters["minSize"] = str(settings.get("min_notional") or filters["minSize"])
        filters["startDateTime"] = self._datetime_local_value(settings.get("start_at"))
        filters["endDateTime"] = self._datetime_local_value(settings.get("end_at"))
        filters["includeRelatedMarkets"] = bool(settings.get("include_related_markets", filters["includeRelatedMarkets"]))
        filters["includeBlockchain"] = bool(settings.get("include_blockchain", filters["includeBlockchain"]))
        filters["fundingTraceMode"] = normalize_funding_trace_mode(
            str(settings.get("funding_trace_mode") or filters["fundingTraceMode"]),
            default=funding_trace_mode(),
        )
        filters["analysisScope"] = str(
            report.get("analysis_scope")
            or settings.get("analysis_scope")
            or filters["analysisScope"]
        )
        filters["selectedConditionId"] = str(
            report.get("selected_condition_id")
            or settings.get("selected_condition_id")
            or filters["selectedConditionId"]
        )
        filters["selectedMarketSlug"] = str(
            report.get("selected_market_slug")
            or settings.get("selected_market_slug")
            or filters["selectedMarketSlug"]
        )
        if filters["analysisScope"] != "market":
            filters["selectedConditionId"] = ""
            filters["selectedMarketSlug"] = ""
        return filters

    def _primary_output_path(self, report: dict[str, object]) -> Path | None:
        export_files = report.get("export_files") or {}
        for key in ("event_report_md_path", "model_gap_report_md_path", "event_analysis_json_path"):
            value = export_files.get(key)
            if value:
                path = Path(str(value))
                if path.exists():
                    return path
        return None

    def _prepare_report(self, report: dict[str, object], report_name: str | None = None) -> dict[str, object]:
        prepared = deepcopy(report)
        if self._has_visible_rankings(prepared):
            self._refresh_report_text(prepared)
            return prepared

        donor_name, donor_report = self._find_compatible_display_report(prepared, exclude_name=report_name)
        if donor_report is not None:
            prepared["display_trades"] = donor_report.get("display_trades") or donor_report.get("suspicious_trades") or []
            prepared["display_wallets"] = donor_report.get("display_wallets") or donor_report.get("suspicious_wallets") or []
            prepared["display_clusters"] = donor_report.get("display_clusters") or donor_report.get("wallet_clusters") or []
            prepared["compatibility_note"] = (
                "Visible rankings were restored from compatible run "
                f"{donor_name} because this saved bundle was generated without display rows."
            )
            prepared["compatibility_restored_from"] = donor_name
            self._refresh_report_text(prepared)
            return prepared

        candidate_trade_count = int((prepared.get("summary") or {}).get("candidate_trade_count") or 0)
        if candidate_trade_count > 0 and prepared.get("status") == "completed":
            prepared["compatibility_note"] = (
                f"This saved bundle has {candidate_trade_count} candidate trades but no visible ranking rows. "
                "It was likely generated by an older Event Forensic backend instance. Restart the app and rerun "
                "the event with the current code to render ranked rows."
            )
        self._refresh_report_text(prepared)
        return prepared

    def _find_compatible_display_report(
        self,
        report: dict[str, object],
        *,
        exclude_name: str | None,
    ) -> tuple[str | None, dict[str, object] | None]:
        event = report.get("event") or {}
        summary = report.get("summary") or {}
        event_slug = str(event.get("slug") or "")
        if not event_slug:
            return None, None

        target_settings = self._compatible_analysis_settings(report.get("analysis_settings") or {})
        target_status = report.get("status")
        target_summary = (
            summary.get("raw_trade_count"),
            summary.get("candidate_trade_count"),
            summary.get("existing_flagged_count"),
            summary.get("forensic_suspicious_trade_count"),
            summary.get("suspicious_wallet_count"),
            summary.get("wallet_cluster_count"),
        )

        report_files = sorted(self.config.reports_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for json_path in report_files:
            if exclude_name and json_path.name == exclude_name:
                continue
            try:
                candidate = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            candidate_event = candidate.get("event") or {}
            if str(candidate_event.get("slug") or "") != event_slug:
                continue
            if candidate.get("status") != target_status:
                continue
            if self._compatible_analysis_settings(candidate.get("analysis_settings") or {}) != target_settings:
                continue
            candidate_summary = candidate.get("summary") or {}
            if (
                candidate_summary.get("raw_trade_count"),
                candidate_summary.get("candidate_trade_count"),
                candidate_summary.get("existing_flagged_count"),
                candidate_summary.get("forensic_suspicious_trade_count"),
                candidate_summary.get("suspicious_wallet_count"),
                candidate_summary.get("wallet_cluster_count"),
            ) != target_summary:
                continue
            if not self._has_visible_rankings(candidate):
                continue
            return json_path.name, candidate
        return None, None

    def _compatible_analysis_settings(self, settings: dict[str, object]) -> dict[str, object]:
        comparable = dict(settings)
        comparable.setdefault("start_at", "")
        comparable.setdefault("end_at", "")
        return comparable

    def _has_visible_rankings(self, report: dict[str, object]) -> bool:
        return any(
            report.get(key)
            for key in ("display_trades", "display_wallets", "display_clusters", "suspicious_trades", "suspicious_wallets", "wallet_clusters")
        )

    def _completed_status_detail(
        self,
        *,
        suspicious_trade_count: int,
        display_trade_count: int,
        candidate_trade_count: int,
        analysis_scope: str,
        selected_market_title: str,
        empty_state_note: str,
        compatibility_note: str,
        analysis_seconds: float,
    ) -> str:
        if suspicious_trade_count > 0:
            visible_phrase = (
                f"; showing top {display_trade_count} rows in the app"
                if display_trade_count and display_trade_count < suspicious_trade_count
                else ""
            )
            runtime_phrase = f" in {analysis_seconds:.2f}s" if analysis_seconds > 0 else ""
            return f"Saved {suspicious_trade_count} suspicious trade rows{visible_phrase}{runtime_phrase}"
        if display_trade_count > 0:
            runtime_phrase = f" in {analysis_seconds:.2f}s" if analysis_seconds > 0 else ""
            return (
                f"Saved {display_trade_count} ranked trade rows; "
                f"{candidate_trade_count} candidate trades were reviewed and none crossed the suspicious threshold"
                f"{runtime_phrase}"
            )
        if compatibility_note:
            return compatibility_note
        if candidate_trade_count > 0:
            runtime_phrase = f" in {analysis_seconds:.2f}s" if analysis_seconds > 0 else ""
            return f"Reviewed {candidate_trade_count} candidate trades; none crossed the suspicious threshold{runtime_phrase}"
        if empty_state_note:
            return empty_state_note
        if analysis_scope == "market" and selected_market_title:
            return f"No candidate trades found for {selected_market_title} under the current minimum trade size."
        return "No candidate trades crossed the configured threshold"

    def _refresh_report_text(self, report: dict[str, object]) -> None:
        try:
            report["event_report_markdown"] = self.analyzer._event_report_markdown(report)
            report["model_gap_markdown"] = self.analyzer._model_gap_markdown(report)
        except Exception:
            return

    def _parse_amount(self, raw: str) -> Decimal | None:
        text = raw.replace(",", "").replace("$", "").strip()
        if not text:
            return None
        try:
            return Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid amount: {raw}") from exc

    def _parse_optional_datetime(self, raw: str) -> datetime | None:
        text = str(raw or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Invalid datetime: {raw}") from exc
        return parsed.astimezone()

    def _datetime_local_value(self, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return ""
        return parsed.astimezone().strftime("%Y-%m-%dT%H:%M")

    def _format_timestamp(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return "Unknown"
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
        return parsed.astimezone().strftime("%b %d, %H:%M")

    def _log_error(self, context: str, exc: Exception) -> None:
        log_path = self.config.data_dir / "app_errors.log"
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        message = (
            f"[{timestamp}] {context}\n"
            f"{type(exc).__name__}: {exc}\n"
            f"{traceback.format_exc()}\n"
        )
        try:
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(message)
        except OSError:
            return

    def _append_performance_log(self, message: str) -> None:
        path = self.performance_log_path
        if path is None:
            return
        elapsed = 0.0
        if self.performance_log_started_at is not None:
            elapsed = perf_counter() - self.performance_log_started_at
        line = f"[{elapsed:8.2f}s] {message}\n"
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:
            return


def launch_event_forensic_browser_app() -> None:
    EventForensicBrowserApp().launch()
