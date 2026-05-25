from __future__ import annotations

import json
import traceback
import subprocess
import threading
import webbrowser
from datetime import datetime
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import median
from urllib.parse import parse_qs, urlparse

from app.archive_scanner import ArchiveResearchScanner, default_archive_range, parse_local_datetime
from app.config import AppConfig, funding_trace_mode, normalize_funding_trace_mode
from app.polymarket import PolymarketClient, WalletPosition
from app.scanner import ProgressEvent, Scanner
from app.side_outcome import normalize_side_outcome
from app.site_categories import SITE_CATEGORY_CANDIDATES, SiteCategory
from app.storage import Storage
from app.wallet_analytics import (
    bot_activity_note,
    compute_wallet_performance,
    economic_history_relevance_note,
    win_rate_clears_threshold,
)


MAX_VISIBLE_WALLET_PREDICTIONS = 100


class BrowserDesktopApp:
    def __init__(
        self,
        *,
        config: AppConfig | None = None,
        scanner: object | None = None,
        app_meta: dict[str, str] | None = None,
        asset_name: str = "browser_ui.html",
    ) -> None:
        self.config = config or AppConfig.load()
        self.config.ensure_dirs()
        self.storage = Storage(self.config.db_path)
        self.storage.init()
        self.client = PolymarketClient()
        self.scanner = scanner or Scanner(self.client, self.storage, self.config)
        self.site_categories = self._load_site_categories()
        self.asset_name = asset_name
        self.app_meta = app_meta or {
            "mode": "scanner",
            "title": "InsPoly Scanner",
            "hero": "Suspicious Trading Review Console",
            "launchLabel": "InsPoly browser UI",
        }

        self._lock = threading.RLock()
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.current_report: dict | None = None
        self.current_output_path: Path | None = None
        self.current_cases: list[dict] = []
        self.visible_cases: list[dict] = []
        self.case_detail_cache: dict[str, dict] = {}
        self.wallet_detail_cache: dict[str, dict] = {}
        self.scan_status = {
            "running": False,
            "stage": "Ready",
            "detail": "No scan running",
            "percent": 0.0,
            "label": "Ready",
            "error": None,
        }
        self.default_filters = self._build_default_filters()
        self._load_latest_report()

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

    def _build_default_filters(self) -> dict[str, object]:
        return {
            "lookback": self.config.default_lookback,
            **self._default_case_filters(),
        }

    def _default_case_filters(self) -> dict[str, object]:
        return {
            "minSize": "10000",
            "maxSize": "",
            "maxEntryProbability": "",
            "includeRelatedMarkets": True,
            "includeBlockchain": True,
            "fundingTraceMode": funding_trace_mode(),
            "risk": "All risks",
            "topics": self._default_topic_labels(),
            "resolutionGapOnly": False,
            "openingOnly": False,
            "excludeLikelyCloses": False,
            "hideYieldLike": False,
            "strongRepricingOnly": False,
            "offHoursOnly": False,
            "deadlineOnly": False,
            "hideBotLike": False,
            "specialistOnly": False,
            "zombieOnly": False,
        }

    def _load_site_categories(self) -> list[SiteCategory]:
        try:
            categories = self.client.fetch_site_categories()
        except Exception:
            categories = []
        if categories:
            return categories
        return [
            SiteCategory(label=label, slug=slug, tag_id=slug)
            for label, slug in SITE_CATEGORY_CANDIDATES
        ]

    def _default_topic_labels(self) -> list[str]:
        preferred = ["Politics", "World", "Ukraine", "Middle East"]
        available = {category.label for category in self.site_categories}
        return [label for label in preferred if label in available] or [category.label for category in self.site_categories[:4]]

    def launch(self) -> None:
        asset_path = Path(__file__).with_name(self.asset_name)
        handler = self._make_handler(asset_path)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        url = f"http://127.0.0.1:{server.server_port}"
        print(f"{self.app_meta.get('launchLabel', 'App UI')}: {url}")
        webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()

    def _make_handler(self, asset_path: Path):
        app = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                try:
                    parsed = urlparse(self.path)
                    if parsed.path == "/":
                        self._send_bytes(asset_path.read_bytes(), "text/html; charset=utf-8")
                        return
                    if parsed.path == "/api/bootstrap":
                        self._send_json(app.bootstrap_payload())
                        return
                    if parsed.path == "/api/run":
                        name = parse_qs(parsed.query).get("name", [""])[0]
                        self._send_json(app.load_run(name))
                        return
                    if parsed.path == "/api/case-detail":
                        trade_id = parse_qs(parsed.query).get("trade_id", [""])[0]
                        self._send_json(app.case_detail_payload(trade_id))
                        return
                    self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                except Exception as exc:
                    app._log_error(f"GET {self.path} failed", exc)
                    self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Internal server error")

            def do_POST(self) -> None:
                try:
                    parsed = urlparse(self.path)
                    length = int(self.headers.get("Content-Length", "0") or 0)
                    body = self.rfile.read(length) if length else b"{}"
                    payload = json.loads(body.decode("utf-8") or "{}")
                    if parsed.path == "/api/scan":
                        self._send_json(app.start_scan(payload))
                        return
                    if parsed.path == "/api/stop":
                        self._send_json(app.stop_scan())
                        return
                    if parsed.path == "/api/open-output":
                        self._send_json(app.open_output(payload))
                        return
                    if parsed.path == "/api/open-exports-dir":
                        self._send_json(app.open_exports_dir())
                        return
                    self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                except Exception as exc:
                    app._log_error(f"POST {self.path} failed", exc)
                    self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Internal server error")

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

            def _send_json(self, payload: dict, status: int = 200) -> None:
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _send_bytes(self, data: bytes, content_type: str, status: int = 200) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        return Handler

    def bootstrap_payload(self) -> dict:
        with self._lock:
            report_payload = self._report_payload(self.current_report, self.visible_cases)
            selected_run = None
            if self.current_report:
                report_json_path = self.current_report.get("report_json_path")
                if report_json_path:
                    selected_run = Path(str(report_json_path)).name
            if selected_run is None and self.current_output_path:
                selected_run = self.current_output_path.name
            return {
                "ok": True,
                "appMeta": dict(self.app_meta),
                "filters": self.default_filters,
                "siteCategories": [category.label for category in self.site_categories],
                "status": dict(self.scan_status),
                "recentRuns": self._recent_runs_payload(),
                "currentReport": report_payload,
                "currentCases": [self._case_card_payload(case) for case in self.visible_cases],
                "selectedRun": selected_run,
            }

    def load_run(self, name: str) -> dict:
        if not name:
            return {"ok": False, "error": "Missing run name."}
        json_path = self.config.reports_dir / name
        if not json_path.exists():
            return {"ok": False, "error": f"Run not found: {name}"}
        try:
            report = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": str(exc)}
        normalized = self._normalize_report(report)
        normalized["report_json_path"] = str(json_path)
        output_path = self._primary_output_path(normalized, json_path)
        with self._lock:
            self.current_report = normalized
            self.current_cases = normalized.get("cases", [])
            self.visible_cases = self._apply_wallet_quality_filters(self.current_cases)
            self.current_output_path = output_path if output_path and output_path.exists() else None
            self.case_detail_cache.clear()
        return self.bootstrap_payload()

    def start_scan(self, payload: dict) -> dict:
        with self._lock:
            if self.worker and self.worker.is_alive():
                return {"ok": False, "error": "A scan is already running."}
        try:
            lookback = str(payload.get("lookback") or self.default_filters["lookback"])
            min_amount = self._parse_amount(str(payload.get("minSize", "")))
            max_amount = self._parse_amount(str(payload.get("maxSize", "")))
            include_related = bool(payload.get("includeRelatedMarkets", True))
            include_blockchain = bool(payload.get("includeBlockchain", True))
            trace_mode = normalize_funding_trace_mode(str(payload.get("fundingTraceMode") or ""), default=funding_trace_mode())
            topic_labels = [str(item) for item in payload.get("topics", []) if str(item).strip()]
            categories = self._selected_categories(topic_labels)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        if min_amount is not None and max_amount is not None and min_amount > max_amount:
            return {"ok": False, "error": "Min size cannot be greater than max size."}

        with self._lock:
            self.stop_event = threading.Event()
            self.case_detail_cache.clear()
            self.visible_cases = []
            self.scan_status = {
                "running": True,
                "stage": "Starting scan",
                "detail": "Preparing scanner",
                "percent": 0.0,
                "label": "Scan starting…",
                "error": None,
            }

        worker = threading.Thread(
            target=self._run_scan_worker,
            args=(lookback, categories, min_amount, max_amount, include_related, include_blockchain, trace_mode),
            daemon=True,
        )
        with self._lock:
            self.worker = worker
        worker.start()
        return {"ok": True}

    def stop_scan(self) -> dict:
        with self._lock:
            if not (self.worker and self.worker.is_alive()):
                return {"ok": False, "error": "No scan is currently running."}
            self.stop_event.set()
            self.scan_status.update(
                {
                    "stage": "Stopping scan",
                    "detail": "Saving partial run",
                    "label": "Stopping scan…",
                }
            )
        return {"ok": True}

    def open_output(self, payload: dict) -> dict:
        name = str(payload.get("name") or "")
        if name:
            path = self.config.outputs_dir / name
        else:
            path = self.current_output_path
        if path is None or not path.exists():
            return {"ok": False, "error": "Output file not found."}
        subprocess.run(["open", str(path)], check=False)
        return {"ok": True}

    def open_exports_dir(self) -> dict:
        if not self.config.outputs_dir.exists():
            return {"ok": False, "error": "Exports directory not found."}
        subprocess.run(["open", str(self.config.outputs_dir)], check=False)
        return {"ok": True}

    def case_detail_payload(self, trade_id: str) -> dict:
        with self._lock:
            case = next((item for item in self.visible_cases if item["trade"]["trade_id"] == trade_id), None)
            if case is None:
                return {"ok": False, "error": "Case not found."}
        detail = self._build_case_detail_payload(case)
        return {"ok": True, "detail": detail}

    def _run_scan_worker(
        self,
        lookback: str,
        categories: tuple[SiteCategory, ...],
        min_amount: Decimal | None,
        max_amount: Decimal | None,
        include_related: bool,
        include_blockchain: bool,
        trace_mode: str,
    ) -> None:
        try:
            report = self.scanner.scan(
                lookback,
                self.config.reports_dir,
                selected_categories=categories,
                min_notional=min_amount,
                max_notional=max_amount,
                include_related_markets=include_related,
                include_blockchain=include_blockchain,
                funding_trace_mode=trace_mode,
                progress_callback=self._on_progress,
                stop_event=self.stop_event,
            )
        except Exception as exc:
            self._log_error("scan worker failed", exc)
            with self._lock:
                self.scan_status = {
                    "running": False,
                    "stage": "Failed",
                    "detail": str(exc),
                    "percent": 0.0,
                    "label": "Scan failed",
                    "error": str(exc),
                }
                self.worker = None
            return

        normalized = self._normalize_report(report)
        output_path = self._primary_output_path(normalized)
        flagged = normalized.get("flagged_case_count", len(normalized.get("cases", [])))
        with self._lock:
            self.current_report = normalized
            self.current_cases = normalized.get("cases", [])
            self.visible_cases = self._apply_wallet_quality_filters(self.current_cases)
            self.current_output_path = output_path if output_path and output_path.exists() else None
            self.case_detail_cache.clear()
            self.scan_status = {
                "running": False,
                "stage": "Run complete",
                "detail": f"Scan completed: {len(self.visible_cases)} visible flagged cases",
                "percent": 100.0,
                "label": f"Completed {len(self.visible_cases)} flagged cases",
                "error": None,
            }
            self.worker = None

    def _on_progress(self, event: ProgressEvent) -> None:
        with self._lock:
            self.scan_status = {
                "running": True,
                "stage": event.stage,
                "detail": event.detail,
                "percent": float(event.percent),
                "label": f"{event.stage} {event.percent:.0f}%",
                "error": None,
            }

    def _load_latest_report(self) -> None:
        report_files = sorted(self.config.reports_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not report_files:
            return
        for json_path in report_files:
            try:
                report = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            normalized = self._normalize_report(report)
            self.current_report = normalized
            self.current_cases = normalized.get("cases", [])
            self.visible_cases = self._apply_wallet_quality_filters(self.current_cases)
            self.current_output_path = self._primary_output_path(normalized, json_path)
            return

    def _normalize_report(self, report: dict) -> dict:
        normalized = dict(report)
        normalized_cases: list[dict] = []
        for case in normalized.get("cases", []):
            if "raw_metrics" in case:
                normalized_case = dict(case)
                raw_metrics = dict(normalized_case.get("raw_metrics", {}))
                legacy_severity = str(case.get("severity", "Low Risk"))
                normalized_case["severity"] = self._normalize_legacy_severity(legacy_severity)
                normalized_case["case_type"] = self._normalize_case_type(
                    case.get("case_type"),
                    legacy_severity,
                    raw_metrics,
                )
                raw_metrics["case_type"] = normalized_case["case_type"] or raw_metrics.get("case_type", "")
                normalized_case["raw_metrics"] = raw_metrics
                normalized_cases.append(normalized_case)
                continue
            trade = dict(case.get("trade", {}))
            market = dict(case.get("market", {}))
            wallet = dict(case.get("wallet_inspection", {}))
            metrics = dict(case.get("metrics", {}))
            legacy_level = case.get("level", "Low Risk")
            case_type = self._normalize_case_type(case.get("case_type"), legacy_level, metrics)
            metrics["case_type"] = case_type or metrics.get("case_type", "")
            normalized_cases.append(
                {
                    "severity": self._normalize_legacy_severity(legacy_level),
                    "case_type": case_type,
                    "suspicion_score": case.get("score", 0),
                    "confidence_score": case.get("confidence_score", 100),
                    "review_priority": case.get("review_priority", "Medium"),
                    "verdict": case.get("verdict", "Needs manual review"),
                    "trade_count_window": case.get("trade_count_window", 0),
                    "window_start": case.get("window_start", trade.get("timestamp", "")),
                    "window_end": case.get("window_end", trade.get("timestamp", "")),
                    "trade": trade,
                    "market": market,
                    "wallet_inspection": wallet,
                    "subscores": case.get("subscores", {}),
                    "flags": case.get("flags", []),
                    "explanation": case.get("reasons", []),
                    "reasons_against": case.get("reasons_against", []),
                    "raw_metrics": metrics,
                }
            )
        normalized["cases"] = normalized_cases
        if "flagged_case_count" not in normalized:
            normalized["flagged_case_count"] = len(normalized_cases)
        if "candidate_trade_count" not in normalized:
            normalized["candidate_trade_count"] = normalized.get("filtered_trade_count", len(normalized_cases))
        if "report_txt_path" not in normalized:
            report_name = normalized.get("report_json_path")
            if report_name:
                stem = Path(report_name).stem
                txt_path = self.config.outputs_dir / f"{stem}.txt"
                normalized["report_txt_path"] = str(txt_path if txt_path.exists() else "")
        return normalized

    def _primary_output_path(self, report: dict, json_path: Path | None = None) -> Path | None:
        output_value = report.get("report_txt_path")
        if output_value:
            path = Path(str(output_value))
            if path.exists():
                return path
        export_files = report.get("export_files") or {}
        summary_value = export_files.get("summary_txt_path")
        if summary_value:
            path = Path(str(summary_value))
            if path.exists():
                return path
        if json_path is not None:
            txt_path = self.config.outputs_dir / f"{json_path.stem}.txt"
            if txt_path.exists():
                return txt_path
        return None

    def _normalize_legacy_severity(self, value: str) -> str:
        mapping = {
            "HIGH": "Strong Risk",
            "MEDIUM": "Worth a Look",
            "LOW": "Low Risk",
            "WORTH A LOOK": "Worth a Look",
            "RESOLUTION-GAP": "Low Risk",
        }
        return mapping.get(str(value).upper(), str(value))

    def _normalize_case_type(self, explicit: object, legacy_severity: object, raw_metrics: dict | None = None) -> str | None:
        raw_metrics = raw_metrics or {}
        explicit_text = str(explicit or raw_metrics.get("case_type", "") or "").strip()
        normalized_explicit = explicit_text.replace("-", " ").strip().title()
        if normalized_explicit == "Resolution Gap":
            return "Resolution Gap"
        if str(legacy_severity).upper() == "RESOLUTION-GAP":
            return "Resolution Gap"
        if raw_metrics.get("resolution_gap_flag") == "Yes":
            return "Resolution Gap"
        return None

    def _report_payload(self, report: dict | None, visible_cases: list[dict]) -> dict | None:
        if report is None:
            return None
        saved_cases = report.get("cases", [])
        saved_case_count = int(report.get("flagged_case_count", len(saved_cases)) or len(saved_cases))
        visible_case_count = len(visible_cases)
        def market_count(cases: object) -> int:
            keys: set[str] = set()
            if not isinstance(cases, list):
                return 0
            for case in cases:
                if not isinstance(case, dict):
                    continue
                trade = case.get("trade", {})
                if not isinstance(trade, dict):
                    continue
                key = str(trade.get("slug") or trade.get("title") or "").strip()
                if key:
                    keys.add(key)
            return len(keys)
        counts = {"Strong Risk": 0, "Worth a Look": 0, "Low Risk": 0}
        case_type_counts = {"Resolution Gap": 0}
        for case in visible_cases:
            case_type = case.get("case_type")
            if case_type == "Resolution Gap":
                case_type_counts["Resolution Gap"] += 1
                continue
            counts[case["severity"]] = counts.get(case["severity"], 0) + 1
        return {
            "fileName": self.current_output_path.name if self.current_output_path else None,
            "lookback": report.get("lookback", self.config.default_lookback),
            "topics": report.get("topic_scope", "Unknown"),
            "rawTradeCount": report.get("raw_trade_count", 0),
            "candidateTradeCount": report.get("candidate_trade_count", 0),
            "flaggedCaseCount": visible_case_count,
            "savedFlaggedCaseCount": saved_case_count,
            "visibleFlaggedCaseCount": visible_case_count,
            "serverHiddenCaseCount": max(0, saved_case_count - visible_case_count),
            "savedMarketCount": market_count(saved_cases),
            "visibleMarketCount": market_count(visible_cases),
            "generatedAt": self._format_timestamp(report.get("generated_at", "")),
            "status": report.get("status", "finished"),
            "tradeCollectionDiagnostics": report.get("trade_collection_diagnostics", {}),
            "analysisSettings": report.get("analysis_settings", {}),
            "fundingTraceMode": (report.get("funding_resolver_health") or {}).get(
                "fundingTraceMode",
                (report.get("analysis_settings") or {}).get("funding_trace_mode", ""),
            ),
            "fundingEvidenceInterpretation": (report.get("funding_resolver_health") or {}).get(
                "fundingEvidenceInterpretation",
                "",
            ),
            "counts": {
                "flagged": len(visible_cases),
                "strong": counts.get("Strong Risk", 0),
                "worth": counts.get("Worth a Look", 0),
                "low": counts.get("Low Risk", 0),
                "resolutionGap": case_type_counts.get("Resolution Gap", 0),
            },
        }

    def _recent_runs_payload(self) -> list[dict]:
        records: list[dict] = []
        report_files = sorted(self.config.reports_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for json_path in report_files[:20]:
            try:
                report = self._normalize_report(json.loads(json_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
            records.append(
                {
                    "name": json_path.name,
                    "displayTime": self._format_timestamp(report.get("generated_at", "")),
                    "lookback": report.get("lookback", "Unknown"),
                    "topics": report.get("topic_scope", "Unknown"),
                    "flagged": report.get("flagged_case_count", 0),
                    "minAmount": self._infer_min_amount(report),
                    "selected": bool(
                        self.current_report
                        and Path(str(self.current_report.get("report_json_path", ""))).name == json_path.name
                    ),
                }
            )
        return records

    def _infer_min_amount(self, report: dict) -> str | None:
        cases = report.get("cases") or []
        if not cases:
            return None
        try:
            return f"{min(float(case['raw_metrics'].get('trade_notional_usdc', '0')) for case in cases):,.0f}"
        except (TypeError, ValueError):
            return None

    def _case_card_payload(self, case: dict) -> dict:
        trade = case["trade"]
        metrics = case["raw_metrics"]
        flags = set(case.get("flags", []))
        entry_probability = self._entry_probability_percent(case)
        side_outcome = self._side_outcome_payload(case)
        timing_raw = metrics.get("hours_to_resolution", "99999")
        try:
            timing_hours = float(timing_raw or 99999)
        except (TypeError, ValueError):
            timing_hours = 99999.0
        try:
            bot_score = float(metrics.get("bot_likeness_score", "0") or 0)
        except (TypeError, ValueError):
            bot_score = 0.0
        try:
            domain_concentration = float(metrics.get("domain_concentration_score", "0") or 0)
        except (TypeError, ValueError):
            domain_concentration = 0.0
        wallet_predictions = self._case_wallet_prediction_count(case)
        return {
            "id": trade["trade_id"],
            "riskKey": self._risk_key(case["severity"]),
            "riskLabel": case["severity"],
            "caseType": case.get("case_type"),
            "market": trade["title"],
            "marketUrl": self._market_url(trade),
            "wallet": trade["wallet"],
            "walletShort": self._short_wallet(trade["wallet"]),
            "profileUrl": self._profile_url(trade["wallet"]),
            "username": self._display_username(trade),
            "side": trade["outcome"],
            "orderSide": trade["side"],
            "position": self._format_money_no_sign(float(metrics.get("trade_notional_usdc", "0"))),
            "entryProbability": entry_probability,
            "entryProbabilityLabel": self._format_entry_probability(entry_probability),
            **side_outcome,
            "walletPredictions": wallet_predictions,
            "walletPredictionsLabel": str(wallet_predictions) if wallet_predictions is not None else "Unavailable",
            "liquidityShare": metrics.get("liquidity_ratio", "Unavailable"),
            "date": self._format_timestamp(trade["timestamp"]),
            "preview": self._quick_analysis(case),
            "topics": case["market"].get("site_categories", []),
            "score": int(case.get("suspicion_score", 0)),
            "timingHours": timing_hours,
            "resolutionGapCase": case.get("case_type") == "Resolution Gap",
            "tradeState": metrics.get("trade_state", "Unavailable"),
            "openingExposure": metrics.get("trade_state") == "increase",
            "yieldLike": "yield_farm_pattern" in flags,
            "thetaDecay": "theta_decay_pattern" in flags,
            "strongRepricing": metrics.get("favorable_repricing_flag") == "Yes",
            "offHours": metrics.get("off_hours_flag") == "Yes",
            "deadlineMarket": metrics.get("deadline_market_flag") == "Yes",
            "botLike": metrics.get("low_analyst_value_flag") == "Yes" or bot_score >= 70,
            "specialist": "domain_specialist_profile" in flags or domain_concentration >= 0.75,
            "zombieDistorted": metrics.get("formal_win_rate_may_be_overstated") == "Yes",
            "tradeDomain": metrics.get("trade_domain", "Other"),
            "localEventTime": metrics.get("local_event_time", ""),
        }

    def _build_case_detail_payload(self, case: dict) -> dict:
        trade = case["trade"]
        wallet_data = self._get_case_detail_data(case)
        technical_lines = self._debug_summary_lines(case) + self._technical_metric_lines(case, wallet_data)
        human_summary = "\n\n".join(
            [
                " ".join(case["explanation"]) or "No summary available.",
                self._interpretation_paragraph(case),
                self._bottom_line(case),
            ]
        ).strip()
        return {
            "id": trade["trade_id"],
            "market": trade["title"],
            "marketUrl": self._market_url(trade),
            "wallet": trade["wallet"],
            "profileUrl": self._profile_url(trade["wallet"]),
            "username": self._display_username(trade),
            "riskKey": self._risk_key(case["severity"]),
            "riskLabel": case["severity"],
            "caseType": case.get("case_type"),
            "entryProbability": self._format_entry_probability(self._entry_probability_percent(case)),
            "rawTokenPriceLabel": self._side_outcome_payload(case)["rawTokenPriceLabel"],
            "economicSideProbabilityLabel": self._side_outcome_payload(case)["economicSideProbabilityLabel"],
            "timeToResolution": self._hours_label(case["raw_metrics"].get("hours_to_resolution", "Unavailable")),
            "keyContext": [value for _label, value in self._key_context_items(case)],
            "humanSummary": human_summary,
            "whatStandsOut": case["explanation"] or ["No standout signals were recorded."],
            "whatReducesConcern": case["reasons_against"] or ["No strong benign pattern clearly reduces concern in the loaded sample."],
            "technicalLines": technical_lines,
            "positions": wallet_data["closed_positions"][:12],
            "lifetime": wallet_data["closed_summary"],
            "open": wallet_data["open_summary"],
            "activitySummary": wallet_data.get("activity_summary", {}),
            "copyText": self._detail_text_payload(case, wallet_data),
        }

    def _selected_categories(self, labels: list[str]) -> tuple[SiteCategory, ...]:
        selected_labels = {label for label in labels if label}
        categories = tuple(category for category in self.site_categories if category.label in selected_labels)
        if not categories:
            raise ValueError("Select at least one category.")
        return categories

    def _parse_amount(self, raw: str) -> Decimal | None:
        text = raw.replace(",", "").replace("$", "").strip()
        if not text:
            return None
        try:
            return Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"Invalid amount: {raw}") from exc

    def _get_case_detail_data(self, case: dict) -> dict:
        trade_id = case["trade"]["trade_id"]
        cached = self.case_detail_cache.get(trade_id)
        if cached is not None:
            return cached
        trade = case["trade"]
        result = dict(self._wallet_detail_data(trade["wallet"]))
        self.case_detail_cache[trade_id] = result
        return result

    def _wallet_detail_data(self, wallet: str) -> dict:
        cached = self.wallet_detail_cache.get(wallet)
        if cached is not None:
            return cached
        try:
            wallet_stats = self.client.fetch_wallet_stats(wallet, trade_limit=500)
            wallet_positions = self.client.fetch_wallet_positions(wallet)
            notionals = [float(item.notional) for item in wallet_stats.trades]
            wallet_median = median(notionals) if notionals else 0.0
            analytics = self._position_analytics(wallet_stats.trades, wallet_positions)
            result = {
                "wallet_median": wallet_median,
                "trade_sample_size": len(wallet_stats.trades),
                "closed_positions": analytics["closed_positions"],
                "closed_summary": analytics["closed_summary"],
                "open_summary": analytics["open_summary"],
                "activity_summary": analytics["activity_summary"],
            }
        except Exception as exc:
            result = {
                "wallet_median": 0.0,
                "trade_sample_size": 0,
                "closed_positions": [],
                "closed_summary": self._empty_closed_summary(),
                "open_summary": self._empty_open_summary(),
                "activity_summary": {
                    "botLikenessScore": 0.0,
                    "microtradeRatio": "0.0%",
                    "medianTradeSize": "$0.00",
                    "tradeBurstRate": "0.0 trades/hour",
                    "medianIntertradeInterval": "0.0 minutes",
                    "marketBreadth": 0,
                    "manualReviewValueScore": 50.0,
                    "lowAnalystValueFlag": False,
                    "activityNote": None,
                },
                "error": str(exc),
            }
        self.wallet_detail_cache[wallet] = result
        return result

    def _apply_wallet_quality_filters(self, cases: list[dict]) -> list[dict]:
        visible: list[dict] = []
        for case in cases:
            if self._case_passes_wallet_quality(case):
                visible.append(case)
        return visible

    def _case_passes_wallet_quality(self, case: dict) -> bool:
        raw = case.get("raw_metrics", {})
        wallet_predictions = self._case_wallet_prediction_count(case)
        if wallet_predictions is not None and wallet_predictions > MAX_VISIBLE_WALLET_PREDICTIONS:
            return False
        if not self._raw_case_passes_minimum_win_rate(raw):
            return False
        if raw.get("low_analyst_value_flag") == "Yes" and case.get("severity") != "Strong Risk":
            return False
        if raw.get("formal_win_rate_may_be_overstated") == "Yes" and case.get("severity") == "Low Risk":
            return False
        if raw.get("economic_win_rate_clears_threshold") in {"Yes", "No"}:
            return True
        wallet = case["trade"]["wallet"]
        wallet_data = self._wallet_detail_data(wallet)
        if wallet_data.get("error"):
            return True
        closed_summary = wallet_data["closed_summary"]
        if wallet_data.get("activity_summary", {}).get("lowAnalystValueFlag"):
            return case.get("severity") == "Strong Risk"
        if closed_summary.get("formalWinRateMayBeOverstated") and case.get("severity") == "Low Risk":
            return False
        return True

    def _raw_case_passes_minimum_win_rate(self, raw: dict) -> bool:
        economic_rate = self._raw_percent(raw.get("wallet_economic_win_rate", ""))
        economic_sample = self._raw_int(raw.get("wallet_economic_sample_size", ""))
        formal_rate = self._raw_percent(raw.get("wallet_closed_win_rate", ""))
        formal_total = self._raw_int(raw.get("wallet_closed_positions", ""))
        if economic_sample > 0 and economic_rate is not None:
            return economic_rate >= 50.0
        if formal_total > 0 and formal_rate is not None:
            return formal_rate >= 50.0
        return True

    def _case_wallet_prediction_count(self, case: dict) -> int | None:
        raw = case.get("raw_metrics", {})
        wallet = case.get("wallet_inspection", {})
        for value in (
            raw.get("wallet_traded_market_count"),
            wallet.get("traded_market_count") if isinstance(wallet, dict) else None,
        ):
            if value in (None, ""):
                continue
            try:
                return int(float(str(value)))
            except (TypeError, ValueError):
                continue
        return None

    def _raw_percent(self, value: object) -> float | None:
        text = str(value or "").strip()
        if not text or text == "Unavailable":
            return None
        try:
            return float(text.rstrip("%"))
        except ValueError:
            return None

    def _raw_int(self, value: object) -> int:
        text = str(value or "").strip()
        if not text:
            return 0
        try:
            return int(float(text))
        except ValueError:
            return 0

    def _position_analytics(self, trades: list[object], wallet_positions: list[WalletPosition]) -> dict:
        performance = compute_wallet_performance(trades, wallet_positions)
        closed_positions = [
            {
                "date": self._format_timestamp(item.timestamp),
                "market": item.market,
                "marketUrl": self._market_url_from_slugs(item.event_slug, item.market_slug),
                "direction": item.direction,
                "stake": self._format_money_no_sign(item.stake),
                "result": item.result,
                "realizedPnl": self._format_money(item.realized_pnl),
                "realizedReturn": self._format_percent(item.realized_return),
                "timestamp": item.timestamp,
            }
            for item in performance.closed_positions
        ]
        closed_summary = performance.closed_summary
        open_summary = performance.open_summary
        activity_summary = performance.activity_summary
        win_rate_visible = closed_summary.win_rate_clears_threshold
        win_rate_note = None if win_rate_visible else self._win_rate_note(closed_summary.total)
        economic_note = economic_history_relevance_note(closed_summary)
        activity_note = bot_activity_note(activity_summary)

        return {
            "closed_positions": closed_positions,
            "closed_summary": {
                "total": closed_summary.total,
                "wins": closed_summary.wins,
                "losses": closed_summary.losses,
                "winRateValue": closed_summary.win_rate_value,
                "winRateThreshold": closed_summary.win_rate_threshold,
                "winRateClearsThreshold": closed_summary.win_rate_clears_threshold,
                "winRate": self._format_percent(closed_summary.win_rate_value, force_sign=False) if win_rate_visible else None,
                "winRateVisible": win_rate_visible,
                "winRateNote": win_rate_note,
                "totalPnl": self._format_money(closed_summary.total_realized_pnl),
                "avgRet": self._format_percent(closed_summary.average_return),
                "economicSampleSize": closed_summary.economic_sample_size,
                "economicWinRateValue": closed_summary.economic_win_rate_value,
                "economicWinRate": self._format_percent(closed_summary.economic_win_rate_value, force_sign=False),
                "economicWinRateThreshold": closed_summary.economic_win_rate_threshold,
                "economicWinRateClearsThreshold": closed_summary.economic_win_rate_clears_threshold,
                "zombieLossCount": closed_summary.zombie_loss_count,
                "zombieLossNotional": self._format_money_no_sign(closed_summary.zombie_loss_notional),
                "redemptionAvoidanceRatio": self._format_percent(
                    closed_summary.redemption_avoidance_ratio * 100,
                    force_sign=False,
                ),
                "formalWinRateMayBeOverstated": closed_summary.formal_win_rate_may_be_overstated,
                "economicNote": economic_note,
            },
            "open_summary": {
                "count": open_summary.count,
                "notional": self._format_money_no_sign(open_summary.notional),
                "unrealizedPnl": self._format_money(open_summary.unrealized_pnl),
                "unrealizedPct": self._format_percent(open_summary.unrealized_pct),
                "zombiePositions": open_summary.zombie_positions,
                "zombieNotional": self._format_money_no_sign(open_summary.zombie_notional),
            },
            "activity_summary": {
                "botLikenessScore": round(activity_summary.bot_likeness_score, 1),
                "microtradeRatio": self._format_percent(activity_summary.microtrade_ratio * 100, force_sign=False),
                "medianTradeSize": self._format_money_no_sign(activity_summary.median_trade_size),
                "tradeBurstRate": f"{activity_summary.trade_burst_rate:.1f} trades/hour",
                "medianIntertradeInterval": f"{activity_summary.median_intertrade_interval_minutes:.1f} minutes",
                "marketBreadth": activity_summary.market_breadth,
                "manualReviewValueScore": round(activity_summary.manual_review_value_score, 1),
                "lowAnalystValueFlag": activity_summary.low_analyst_value_flag,
                "activityNote": activity_note,
            },
        }

    def _empty_closed_summary(self) -> dict:
        return {
            "total": 0,
            "wins": 0,
            "losses": 0,
            "winRateValue": 0.0,
            "winRateThreshold": 50.0,
            "winRateClearsThreshold": False,
            "winRate": None,
            "winRateVisible": False,
            "winRateNote": self._win_rate_note(0),
            "totalPnl": "$0.00",
            "avgRet": "0.0%",
            "economicSampleSize": 0,
            "economicWinRateValue": 0.0,
            "economicWinRate": None,
            "economicWinRateThreshold": 50.0,
            "economicWinRateClearsThreshold": False,
            "zombieLossCount": 0,
            "zombieLossNotional": "$0.00",
            "redemptionAvoidanceRatio": "0.0%",
            "formalWinRateMayBeOverstated": False,
            "economicNote": "The wallet does not yet show a meaningful economic track record in the loaded sample.",
        }

    def _empty_open_summary(self) -> dict:
        return {
            "count": 0,
            "notional": "$0.00",
            "unrealizedPnl": "$0.00",
            "unrealizedPct": "0.0%",
            "zombiePositions": 0,
            "zombieNotional": "$0.00",
        }

    def _detail_text_payload(self, case: dict, wallet_data: dict) -> str:
        lines = [
            f"Market: {case['trade']['title']}",
            f"Wallet: {case['trade']['wallet']}",
            f"Username: {self._display_username(case['trade'])}",
            f"Overall assessment: {case['severity']}",
            f"Case type: {case.get('case_type') or 'Standard risk case'}",
            "",
            "Key context:",
        ]
        lines.extend(f"- {value}" for _label, value in self._key_context_items(case))
        lines.extend(["", "What stands out:"])
        lines.extend(f"- {item}" for item in case["explanation"])
        lines.extend(["", "What reduces concern:"])
        lines.extend(f"- {item}" for item in (case["reasons_against"] or ["No strong benign pattern clearly reduces concern."]))
        lines.extend(["", "Technical detail:"])
        lines.extend(f"- {item}" for item in self._debug_summary_lines(case))
        lines.extend(f"- {item}" for item in self._technical_metric_lines(case, wallet_data))
        return "\n".join(lines)

    def _risk_key(self, severity: str) -> str:
        mapping = {
            "Strong Risk": "strong",
            "Worth a Look": "amber",
            "Low Risk": "low",
        }
        return mapping.get(severity, "low")

    def _quick_analysis(self, case: dict) -> str:
        lines = case["explanation"][:2] or ["No explanation available."]
        return " ".join(lines)

    def _key_context_items(self, case: dict) -> list[tuple[str, str]]:
        raw = case["raw_metrics"]
        trade = case["trade"]
        items = [
            ("Market", trade["title"]),
            ("Wallet", trade["wallet"]),
            ("Username", self._display_username(trade)),
            ("Overall assessment", case["severity"]),
            ("Case type", f"Case type: {case.get('case_type') or 'Standard risk case'}."),
            ("Position size", f"Position size: {self._format_money_no_sign(float(raw.get('trade_notional_usdc', '0')))}."),
            (
                "Position-size meaning",
                "Displayed trade size is executed trade notional from the Polymarket Data API; profile-page position value can be much smaller after reductions, closes, or price moves.",
            ),
            ("Token price", f"Token price at trade: {self._side_outcome_payload(case)['rawTokenPriceLabel']}."),
            (
                "Economic probability",
                f"Economic-side probability at trade: {self._side_outcome_payload(case)['economicSideProbabilityLabel']}.",
            ),
            (
                "Wallet predictions",
                f"Wallet public prediction count: {self._case_wallet_prediction_count(case) if self._case_wallet_prediction_count(case) is not None else 'Unavailable'}.",
            ),
            ("Trade state", f"Trade state: {raw.get('trade_state', 'Unavailable')}."),
            ("Capital at risk", f"Capital at risk added by this trade: {self._format_money_no_sign(float(raw.get('capital_at_risk_usdc', '0')))}."),
            ("Liquidity consumed", f"Consumed {raw.get('liquidity_ratio', 'Unavailable')} of visible liquidity in this market."),
            ("Relative to market", f"Relative size versus this market: percentile {raw.get('market_size_percentile', 'n/a')}."),
            ("Relative to wallet norm", f"Relative size versus this wallet's normal behavior: {raw.get('wallet_size_multiple_vs_median', 'Unavailable')}."),
            ("Trade domain", f"Trade domain: {raw.get('trade_domain', 'Other')}."),
            ("Domain peer percentile", f"Relative size versus peer trades in this domain: percentile {raw.get('domain_peer_percentile', 'Unavailable')}."),
            ("Wallet peer percentile", f"Economic wallet percentile within this domain in the loaded run: {raw.get('wallet_domain_peer_percentile', 'Unavailable')}."),
            ("Entry vs consensus", f"Entry versus local consensus: {raw.get('entry_vs_consensus_15m', 'Unavailable')}."),
            ("Favorable repricing", f"Best favorable repricing after entry in the loaded sample: +{raw.get('favorable_move_1h', '0')} within 1h."),
            ("Local event time", f"Local event time at entry: {raw.get('local_event_time', 'Unavailable')} ({raw.get('event_timezone', 'UTC')})."),
            ("Off-hours", f"Off-hours local entry flag: {raw.get('off_hours_flag', 'No')}."),
            ("Funding source", f"Funding source before entry: {raw.get('funding_source_label', 'Unknown')} ({raw.get('funding_source_category', 'unknown')})."),
            ("Funding velocity", f"Funding-to-trade timing: {raw.get('funding_velocity_label', 'Unavailable')} ({raw.get('minutes_from_funding_to_trade', '')} minutes)."),
            ("Wallet domain", f"Dominant wallet domain in the loaded sample: {raw.get('domain_specialist_label', 'Other')}."),
            ("Domain concentration", f"Domain concentration in the loaded sample: {raw.get('domain_concentration_score', '0.00')}."),
            ("Economic win rate", f"Economic win rate in the loaded sample: {raw.get('wallet_economic_win_rate', 'Unavailable')}."),
            ("Zombie losses", f"Zombie or de facto loss count in the loaded sample: {raw.get('zombie_loss_count', '0')}."),
            ("Bot likeness", f"Bot-likeness score: {raw.get('bot_likeness_score', '0')}."),
            ("Manual review value", f"Manual-review value score: {raw.get('manual_review_value_score', '0')}."),
            ("Timeline evidence", f"Offline timeline matched: {raw.get('offline_timeline_matched', 'No')}."),
            ("Funding linkage", f"Shared funding-source cluster size in this run: {raw.get('shared_funding_source_cluster_size', '0')}."),
            ("Same-side participation", f"Same-side participation in the selected window: {raw.get('cluster_wallets_30m_same_side', '0')} other wallets."),
            ("Same-side dollar volume", f"Same-side dollar volume in that window: {raw.get('same_side_dollar_volume_30m', 'Unavailable')}."),
            ("Same-side share of activity", f"Same-side share of total window activity: {raw.get('same_side_share_30m', 'Unavailable')}."),
            ("Time until resolution", f"Time until resolution: {self._hours_label(raw.get('hours_to_resolution', 'Unavailable'))}."),
        ]
        if raw.get("public_knowledge_at"):
            items.append(
                (
                    "Public knowledge",
                    f"Offline public-knowledge timestamp: {self._format_timestamp(raw.get('public_knowledge_at', ''))}.",
                )
            )
        if raw.get("wallet_closed_positions"):
            items.append(
                (
                    "Closed-position record",
                    "Closed-position record in the scan-time wallet snapshot: "
                    f"{raw.get('wallet_closed_wins', '0')} wins, {raw.get('wallet_closed_losses', '0')} losses, "
                    f"{raw.get('wallet_closed_win_rate', 'Unavailable')}.",
                )
            )
        return items

    def _debug_summary_lines(self, case: dict) -> list[str]:
        lines: list[str] = []
        flags = set(case.get("flags", []))
        raw = case["raw_metrics"]
        if "large_trade_absolute" in flags:
            lines.append("A large absolute trade-size signal was triggered.")
        if "large_trade_relative_to_market" in flags or "liquidity_drain_extreme" in flags:
            lines.append("The trade consumed a meaningfully large share of visible market liquidity.")
        if "wallet_size_anomaly" in flags:
            lines.append("The trade was unusually large relative to this wallet's normal size.")
        if "wallet_recently_activated" in flags:
            lines.append("The wallet-history review found low-history characteristics.")
        if "beat_local_consensus" in flags:
            lines.append("The entry beat the local market consensus at the time it was placed.")
        if "rapid_favorable_repricing" in flags:
            lines.append("The market repriced quickly in the trade's favor after entry.")
        if "crowded_same_side_entry" in flags:
            lines.append("Several wallets entered the same side in a short time window, but this still looks closer to crowding than proven coordination.")
        if "coordinated_new_wallet_cluster" in flags:
            lines.append("The pattern looks stronger than ordinary crowding because several wallets hit the same side quickly in a thin market.")
        if "event_sniper_profile" in flags:
            lines.append("The wallet profile looks unusually narrow for this type of event.")
        if "domain_specialist_profile" in flags:
            lines.append("The wallet appears to be a repeat specialist in this market domain.")
        if "domain_peer_outlier" in flags:
            lines.append("Even against same-domain peers, the trade still looked unusually large or aggressive.")
        if "yield_farm_pattern" in flags:
            lines.append("The trade resembles near-certain capital parking rather than a high-information entry.")
        if "theta_decay_pattern" in flags:
            lines.append("The trade resembles an ordinary deadline or theta-decay position.")
        if "off_hours_local_entry" in flags:
            lines.append("The entry landed in the event's local 2-6 AM window.")
        if "offline_timeline_resolution_gap" in flags:
            lines.append("Offline timeline evidence indicates the event was already publicly knowable before the trade.")
        if case.get("case_type") == "Resolution Gap":
            lines.append("This card is tagged as a resolution-gap/public-lag case rather than an insider-style risk class.")
        if "suspicious_funding_source" in flags:
            lines.append("The wallet appears to have been funded shortly before entry from an unattributed or opaque source.")
        if "shared_funding_source" in flags:
            lines.append("Multiple flagged wallets in this run appear to share the same upstream funding source or intermediary.")
        if "non_opening_trade" in flags:
            lines.append("The trade did not clearly look like fresh opening exposure.")
        if "zombie_position_distortion" in flags:
            lines.append("Zombie-position behavior makes the wallet's headline win rate look better than its economic record.")
        if "bot_like_execution" in flags:
            lines.append("The wallet looks mechanically repetitive rather than especially informative for manual review.")
        if case["subscores"].get("benign_discount", 0) < 0:
            lines.append("A benign-pattern discount reduced the final concern level.")
        if raw.get("pre_win_rate_severity") and raw.get("pre_win_rate_severity") != case["severity"]:
            lines.append("Weak closed-position history downgraded the final risk classification.")
        if not lines:
            lines.append("No additional technical flags were exposed for this case.")
        return lines

    def _technical_metric_lines(self, case: dict, wallet_data: dict) -> list[str]:
        raw = case["raw_metrics"]
        lines = [
            f"Review priority: {case.get('review_priority', 'Unknown')}",
            f"Confidence score: {case.get('confidence_score', 'Unknown')}/100",
            f"Verdict: {case.get('verdict', 'Unknown')}",
            f"Case type: {case.get('case_type') or 'Standard risk case'}",
            f"Window: {self._format_timestamp(case.get('window_start', ''))} to {self._format_timestamp(case.get('window_end', ''))}",
            f"Token price at trade: {self._side_outcome_payload(case)['rawTokenPriceLabel']}",
            f"Economic-side probability at trade: {self._side_outcome_payload(case)['economicSideProbabilityLabel']}",
            f"Trade state: {raw.get('trade_state', 'Unavailable')}",
            f"Capital at risk: {self._format_money_no_sign(float(raw.get('capital_at_risk_usdc', '0')))}",
            f"Uncertainty level: {raw.get('uncertainty_level', 'Unavailable')}",
            f"Entry vs local consensus: {raw.get('entry_vs_consensus_15m', 'Unavailable')}",
            f"Best favorable move after entry: +{raw.get('favorable_move_1h', '0')} in 1h / +{raw.get('favorable_move_4h', '0')} in 4h",
            f"Strong timing proofs: {raw.get('strong_timing_proof_count', raw.get('timing_evidence_count', '0'))}",
            f"Supporting boosters: {raw.get('supporting_booster_count', '0')}",
            f"Related markets in 30m: {raw.get('related_markets_30m', '0')}",
            f"Market liquidity: {self._format_money_no_sign(float(raw.get('market_liquidity_usdc', '0')))}",
            f"Market volume: {self._format_money_no_sign(float(raw.get('market_volume_usdc', '0')))}",
            f"Wallet specialization ratio: {raw.get('wallet_specialization_ratio', 'Unavailable')}",
            f"Wallet conviction ratio in this market: {raw.get('wallet_market_conviction_ratio', 'Unavailable')}",
            f"Trade domain: {raw.get('trade_domain', 'Other')}",
            f"Dominant wallet domain: {raw.get('domain_specialist_label', 'Other')}",
            f"Domain concentration: {raw.get('domain_concentration_score', '0.00')}",
            f"Domain peer percentile: {raw.get('domain_peer_percentile', 'Unavailable')}",
            f"Wallet domain peer percentile: {raw.get('wallet_domain_peer_percentile', 'Unavailable')}",
            f"Domain-adjusted anomaly score: {raw.get('domain_adjusted_anomaly_score', '0.0')}",
            f"Event timezone: {raw.get('event_timezone', 'UTC')}",
            f"Local event time: {raw.get('local_event_time', 'Unavailable')}",
            f"Off-hours flag: {raw.get('off_hours_flag', 'No')}",
            f"Funding source: {raw.get('funding_source_label', 'Unknown')} ({raw.get('funding_source_category', 'unknown')})",
            f"Funding origin: {raw.get('funding_origin_label', 'Unknown')} ({raw.get('funding_origin_category', 'unknown')})",
            f"Funding amount: {raw.get('funding_amount_usdc', '0.00')}",
            f"Funding timestamp: {self._format_timestamp(raw.get('funding_timestamp', ''))}",
            f"Funding velocity: {raw.get('funding_velocity_label', 'Unavailable')}",
            f"Suspicious funding score: {raw.get('suspicious_funding_score', '0.00')}",
            f"Shared funding-source cluster size: {raw.get('shared_funding_source_cluster_size', '0')}",
            f"Formal closed win rate: {raw.get('wallet_closed_win_rate', 'Unavailable')}",
            f"Economic win rate: {raw.get('wallet_economic_win_rate', 'Unavailable')}",
            f"Zombie loss count: {raw.get('zombie_loss_count', '0')}",
            f"Redemption avoidance ratio: {raw.get('redemption_avoidance_ratio', '0.0%')}",
            f"Bot-likeness score: {raw.get('bot_likeness_score', '0')}",
            f"Manual-review value score: {raw.get('manual_review_value_score', '0')}",
            f"Offline timeline matched: {raw.get('offline_timeline_matched', 'No')}",
            f"Visible loaded trade sample: {wallet_data['trade_sample_size']}",
            f"Median loaded trade size: {self._format_money_no_sign(wallet_data['wallet_median'])}",
        ]
        if raw.get("public_knowledge_at"):
            lines.append(f"Public-knowledge timestamp: {self._format_timestamp(raw.get('public_knowledge_at', ''))}")
        if raw.get("official_confirmation_at"):
            lines.append(
                f"Official confirmation timestamp: {self._format_timestamp(raw.get('official_confirmation_at', ''))}"
            )
        if raw.get("public_outcome_at"):
            lines.append(f"Public outcome timestamp: {self._format_timestamp(raw.get('public_outcome_at', ''))}")
        if raw.get("timeline_source"):
            lines.append(f"Offline timeline source: {raw.get('timeline_source', '')}")
        closed_summary = wallet_data.get("closed_summary", {})
        if raw.get("wallet_closed_positions"):
            lines.append(
                "Closed-position record in the scan-time snapshot: "
                f"{raw.get('wallet_closed_positions', '0')} positions, {raw.get('wallet_closed_win_rate', 'Unavailable')} win rate."
            )
        if raw.get("win_rate_adjustment_note"):
            lines.append(str(raw["win_rate_adjustment_note"]))
        elif raw.get("win_rate_relevance_note"):
            lines.append(str(raw["win_rate_relevance_note"]))
        if raw.get("economic_history_note"):
            lines.append(str(raw["economic_history_note"]))
        if raw.get("bot_activity_note"):
            lines.append(str(raw["bot_activity_note"]))
        if closed_summary.get("winRateVisible"):
            lines.append(f"Highlighted wallet win rate: {closed_summary.get('winRate', 'Unavailable')}")
        elif closed_summary.get("winRateNote"):
            lines.append(str(closed_summary["winRateNote"]))
        if closed_summary.get("economicNote"):
            lines.append(str(closed_summary["economicNote"]))
        activity_summary = wallet_data.get("activity_summary", {})
        if activity_summary.get("activityNote"):
            lines.append(str(activity_summary["activityNote"]))
        if wallet_data.get("error"):
            lines.append(f"Wallet enrichment failed: {wallet_data['error']}")
        return lines

    def _interpretation_paragraph(self, case: dict) -> str:
        parts = []
        raw = case["raw_metrics"]
        if case.get("case_type") == "Resolution Gap":
            parts.append("This was tagged as a resolution-gap case, meaning public information likely existed before the trade but market pricing lagged.")
        if case["raw_metrics"].get("trade_state") != "increase":
            parts.append("This did not look like a clean fresh exposure increase, which materially lowers concern.")
        timing_points = int(case["subscores"].get("timing", 0) or 0)
        post_trade_points = int(case["subscores"].get("post_trade", 0) or 0)
        if timing_points > 0:
            parts.append("Timing contributed because the trade landed relatively close to market resolution.")
        elif post_trade_points > 0:
            parts.append("The entry did not look unusually close to formal resolution, but the subsequent repricing still supports a timing edge.")
        else:
            parts.append("Timing did not materially raise concern.")
        if case["subscores"].get("size", 0) > 0:
            parts.append("Size mattered because the trade stood out either in market context, wallet context, or both.")
        if post_trade_points > 0:
            parts.append("The market also moved in the trade's favor after entry, which strengthens the timing interpretation.")
        if case["subscores"].get("cluster", 0) > 0:
            parts.append(
                "Several wallets entered the same side in a short time window. That is still treated as weak crowd evidence unless stronger linkage appears."
            )
        if case["subscores"].get("wallet_novelty", 0) == 0:
            parts.append("The wallet does not look obviously new in the loaded history.")
        if raw.get("specialist_explained_flag") == "Yes":
            parts.append("The pattern may be explained by specialist behavior in this market type.")
        if raw.get("off_hours_flag") == "Yes":
            parts.append("The local event timing was off-hours, which modestly strengthens the timing read when the size is meaningful.")
        if raw.get("public_knowledge_at"):
            parts.append("Offline timeline context suggests the event may already have been publicly knowable by the time of entry.")
        if raw.get("suspicious_funding_flag") == "Yes":
            parts.append("The wallet also shows fresh funding from an opaque source shortly before the trade, which adds structural concern.")
        if raw.get("shared_funding_source_flag") == "Yes":
            parts.append("Other flagged wallets in the same run appear to share the same upstream funding source or intermediary.")
        if raw.get("formal_win_rate_may_be_overstated") == "Yes":
            parts.append("The wallet’s formal win rate may be overstated because several economically dead positions were never redeemed.")
        if raw.get("low_analyst_value_flag") == "Yes":
            parts.append("The wallet looks highly automated and low-value for manual insider-style review.")
        if raw.get("win_rate_adjustment_note"):
            parts.append(str(raw["win_rate_adjustment_note"]))
        elif raw.get("win_rate_relevance_note"):
            parts.append(str(raw["win_rate_relevance_note"]))
        if raw.get("economic_history_note"):
            parts.append(str(raw["economic_history_note"]))
        if raw.get("bot_activity_note"):
            parts.append(str(raw["bot_activity_note"]))
        return " ".join(parts)

    def _bottom_line(self, case: dict) -> str:
        if case.get("case_type") == "Resolution Gap":
            return "This looks more like public information that the market absorbed slowly than like insider-style information."
        if case["severity"] == "Strong Risk":
            return "Several strong factors align here, so this case deserves close manual review."
        if case["severity"] == "Worth a Look":
            return "This case is unusual enough to justify a closer look, but the current evidence still has a meaningful benign explanation."
        return "This case has some unusual elements, but current evidence is weak and may reflect ordinary trading."

    def _display_username(self, trade: dict) -> str:
        trader_name = (trade.get("trader_name") or "").strip()
        pseudonym = (trade.get("trader_pseudonym") or "").strip()
        if trader_name and pseudonym and trader_name != pseudonym:
            return f"{trader_name} ({pseudonym})"
        if trader_name:
            return trader_name
        if pseudonym:
            return pseudonym
        return "Not available"

    def _profile_url(self, wallet: str) -> str:
        return f"https://polymarket.com/profile/{wallet}"

    def _market_url(self, trade: dict) -> str:
        slug = (trade.get("event_slug") or trade.get("slug") or "").strip()
        return f"https://polymarket.com/event/{slug}" if slug else "https://polymarket.com"

    def _market_url_from_slugs(self, event_slug: str, market_slug: str) -> str:
        slug = (event_slug or market_slug or "").strip()
        return f"https://polymarket.com/event/{slug}" if slug else "https://polymarket.com"

    def _market_url_from_trade(self, trade: object) -> str:
        return self._market_url_from_slugs(
            getattr(trade, "event_slug", ""),
            getattr(trade, "slug", ""),
        )

    def _format_timestamp(self, value: str) -> str:
        if not value:
            return "Unknown"
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
        return dt.astimezone().strftime("%b %d, %H:%M")

    def _hours_label(self, value: str) -> str:
        if value == "Unavailable":
            return "Unavailable"
        try:
            hours = float(value)
        except ValueError:
            return value
        if hours >= 24:
            return f"{hours / 24:.1f} days"
        return f"{hours:.1f} hours"

    def _format_money(self, value: float) -> str:
        sign = "+" if value > 0 else ""
        return f"{sign}${value:,.2f}"

    def _format_money_no_sign(self, value: float) -> str:
        return f"${value:,.2f}"

    def _format_percent(self, value: float, *, force_sign: bool = True) -> str:
        sign = "+" if force_sign and value > 0 else ""
        return f"{sign}{value:.1f}%"

    def _coerce_probability_percent(self, value: object) -> float | None:
        if value is None:
            return None
        text = str(value).replace("%", "").strip()
        if not text:
            return None
        try:
            probability = float(text)
        except (TypeError, ValueError):
            return None
        if probability < 0:
            return None
        if probability <= 1:
            probability *= 100.0
        return max(0.0, min(probability, 100.0))

    def _entry_probability_percent(self, case: dict) -> float | None:
        trade = case.get("trade", {})
        raw = case.get("raw_metrics", {})
        from_trade = self._coerce_probability_percent(trade.get("price"))
        if from_trade is not None:
            return from_trade
        return self._coerce_probability_percent(raw.get("price_implied_probability"))

    def _side_outcome_payload(self, case: dict) -> dict[str, object]:
        trade = case.get("trade", {})
        raw = case.get("raw_metrics", {})
        normalized = normalize_side_outcome(
            trade.get("side") or raw.get("raw_order_side"),
            trade.get("outcome") or raw.get("raw_token_outcome"),
            trade.get("price") or raw.get("raw_token_price") or raw.get("price_implied_probability"),
        )
        return normalized.to_payload()

    def _format_entry_probability(self, value: float | None) -> str:
        if value is None:
            return "Unavailable"
        return f"{value:.1f}%"

    def _short_wallet(self, value: str) -> str:
        if len(value) < 12:
            return value
        return f"{value[:6]}...{value[-4:]}"

    def _money_from_label(self, value: str) -> float:
        return float(value.replace("$", "").replace(",", ""))

    def _percent_from_label(self, value: str) -> float:
        return float(value.replace("%", "").replace("+", ""))

    def _should_highlight_win_rate(self, total_closed: int, win_rate: float) -> bool:
        return win_rate_clears_threshold(total_closed, win_rate)

    def _win_rate_note(self, total_closed: int) -> str:
        if total_closed <= 0:
            return "Win rate not emphasized because there are no clearly closed positions in the loaded sample."
        if total_closed < 3:
            return "Win rate not emphasized because the closed-trade sample is still too small."
        if total_closed < 10:
            return "Win rate not emphasized at this sample size because the wallet has not yet reached a high-confidence threshold."
        return "Win rate not emphasized because the closed-trade sample does not clear the stricter high-confidence threshold."


class ArchiveResearchBrowserApp(BrowserDesktopApp):
    def __init__(self) -> None:
        config = AppConfig.load_archive_researcher()
        scanner = ArchiveResearchScanner(PolymarketClient(), Storage(config.db_path), config)
        super().__init__(
            config=config,
            scanner=scanner,
            app_meta={
                "mode": "archive",
                "title": "InsPoly Archive Researcher",
                "hero": "Archive Export and Insider Pattern Research",
                "launchLabel": "InsPoly Archive Researcher UI",
            },
        )

    def _apply_wallet_quality_filters(self, cases: list[dict]) -> list[dict]:
        return super()._apply_wallet_quality_filters(cases)

    def _build_default_filters(self) -> dict[str, object]:
        start_value, end_value = default_archive_range()
        return {
            "startDateTime": start_value,
            "endDateTime": end_value,
            **self._default_case_filters(),
        }

    def start_scan(self, payload: dict) -> dict:
        with self._lock:
            if self.worker and self.worker.is_alive():
                return {"ok": False, "error": "An archive export is already running."}
        try:
            start_at = parse_local_datetime(str(payload.get("startDateTime") or self.default_filters["startDateTime"]))
            end_at = parse_local_datetime(str(payload.get("endDateTime") or self.default_filters["endDateTime"]))
            min_amount = self._parse_amount(str(payload.get("minSize", "")))
            max_amount = self._parse_amount(str(payload.get("maxSize", "")))
            include_related = bool(payload.get("includeRelatedMarkets", True))
            include_blockchain = bool(payload.get("includeBlockchain", True))
            trace_mode = normalize_funding_trace_mode(str(payload.get("fundingTraceMode") or ""), default=funding_trace_mode())
            topic_labels = [str(item) for item in payload.get("topics", []) if str(item).strip()]
            categories = self._selected_categories(topic_labels)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        if min_amount is not None and max_amount is not None and min_amount > max_amount:
            return {"ok": False, "error": "Min size cannot be greater than max size."}
        if end_at <= start_at:
            return {"ok": False, "error": "End datetime must be later than start datetime."}

        with self._lock:
            self.stop_event = threading.Event()
            self.case_detail_cache.clear()
            self.visible_cases = []
            self.scan_status = {
                "running": True,
                "stage": "Starting archive export",
                "detail": "Preparing archive scanner",
                "percent": 0.0,
                "label": "Archive export starting…",
                "error": None,
            }

        worker = threading.Thread(
            target=self._run_archive_worker,
            args=(start_at, end_at, categories, min_amount, max_amount, include_related, include_blockchain, trace_mode),
            daemon=True,
        )
        with self._lock:
            self.worker = worker
        worker.start()
        return {"ok": True}

    def _run_archive_worker(
        self,
        start_at: datetime,
        end_at: datetime,
        categories: tuple[SiteCategory, ...],
        min_amount: Decimal | None,
        max_amount: Decimal | None,
        include_related: bool,
        include_blockchain: bool,
        trace_mode: str,
    ) -> None:
        try:
            report = self.scanner.scan(
                start_at,
                end_at,
                self.config.reports_dir,
                selected_categories=categories,
                min_notional=min_amount,
                max_notional=max_amount,
                include_related_markets=include_related,
                include_blockchain=include_blockchain,
                funding_trace_mode=trace_mode,
                progress_callback=self._on_progress,
                stop_event=self.stop_event,
            )
        except Exception as exc:
            self._log_error("archive worker failed", exc)
            with self._lock:
                self.scan_status = {
                    "running": False,
                    "stage": "Failed",
                    "detail": str(exc),
                    "percent": 0.0,
                    "label": "Archive export failed",
                    "error": str(exc),
                }
                self.worker = None
            return

        normalized = self._normalize_report(report)
        output_path = self._primary_output_path(normalized)
        with self._lock:
            self.current_report = normalized
            self.current_cases = normalized.get("cases", [])
            self.visible_cases = self._apply_wallet_quality_filters(self.current_cases)
            self.current_output_path = output_path if output_path and output_path.exists() else None
            self.case_detail_cache.clear()
            self.scan_status = {
                "running": False,
                "stage": "Archive complete",
                "detail": (
                    f"Archive export completed: {normalized.get('filtered_trade_count', 0)} trades, "
                    f"{len(self.visible_cases)} visible flagged cases"
                ),
                "percent": 100.0,
                "label": f"Completed {normalized.get('filtered_trade_count', 0)} archive trades",
                "error": None,
            }
            self.worker = None

    def _normalize_report(self, report: dict) -> dict:
        normalized = super()._normalize_report(report)
        if "range_start" in normalized and "range_end" in normalized:
            export_files = normalized.get("export_files") or {}
            if "report_txt_path" not in normalized and export_files.get("summary_txt_path"):
                normalized["report_txt_path"] = export_files["summary_txt_path"]
        return normalized

    def _report_payload(self, report: dict | None, visible_cases: list[dict]) -> dict | None:
        if report is None:
            return None
        counts = {"Strong Risk": 0, "Worth a Look": 0, "Low Risk": 0}
        case_type_counts = {"Resolution Gap": 0}
        for case in visible_cases:
            if case.get("case_type") == "Resolution Gap":
                case_type_counts["Resolution Gap"] += 1
                continue
            counts[case["severity"]] = counts.get(case["severity"], 0) + 1
        return {
            "fileName": self.current_output_path.name if self.current_output_path else None,
            "rangeStart": self._format_timestamp(report.get("range_start", "")),
            "rangeEnd": self._format_timestamp(report.get("range_end", "")),
            "rangeLabel": f"{self._format_timestamp(report.get('range_start', ''))} -> {self._format_timestamp(report.get('range_end', ''))}",
            "topics": report.get("topic_scope", "Unknown"),
            "rawTradeCount": report.get("raw_trade_count", 0),
            "candidateTradeCount": report.get("candidate_trade_count", 0),
            "flaggedCaseCount": len(visible_cases),
            "generatedAt": self._format_timestamp(report.get("generated_at", "")),
            "status": report.get("status", "finished"),
            "uniqueWalletCount": report.get("unique_wallet_count", 0),
            "uniqueMarketCount": report.get("unique_market_count", 0),
            "analysisSettings": report.get("analysis_settings", {}),
            "fundingTraceMode": (report.get("funding_resolver_health") or {}).get(
                "fundingTraceMode",
                (report.get("analysis_settings") or {}).get("funding_trace_mode", ""),
            ),
            "fundingEvidenceInterpretation": (report.get("funding_resolver_health") or {}).get(
                "fundingEvidenceInterpretation",
                "",
            ),
            "counts": {
                "flagged": len(visible_cases),
                "strong": counts.get("Strong Risk", 0),
                "worth": counts.get("Worth a Look", 0),
                "low": counts.get("Low Risk", 0),
                "resolutionGap": case_type_counts.get("Resolution Gap", 0),
            },
        }

    def _recent_runs_payload(self) -> list[dict]:
        records: list[dict] = []
        report_files = sorted(self.config.reports_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for json_path in report_files[:20]:
            try:
                report = self._normalize_report(json.loads(json_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
            records.append(
                {
                    "name": json_path.name,
                    "displayTime": self._format_timestamp(report.get("generated_at", "")),
                    "rangeLabel": (
                        f"{self._format_timestamp(report.get('range_start', ''))} -> "
                        f"{self._format_timestamp(report.get('range_end', ''))}"
                    ),
                    "topics": report.get("topic_scope", "Unknown"),
                    "flagged": report.get("flagged_case_count", 0),
                    "minAmount": self._infer_min_amount(report),
                    "tradeCount": report.get("filtered_trade_count", 0),
                    "selected": bool(
                        self.current_report
                        and Path(str(self.current_report.get("report_json_path", ""))).name == json_path.name
                    ),
                }
            )
        return records


def launch_browser_desktop_app() -> None:
    BrowserDesktopApp().launch()


def launch_archive_research_browser_app() -> None:
    ArchiveResearchBrowserApp().launch()
