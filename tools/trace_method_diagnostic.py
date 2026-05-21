from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config import load_runtime_env, runtime_env_int
from app.funding_context import DEFAULT_RPC_GETLOGS_BLOCK_CHUNK, TRANSFER_EVENT_TOPIC, USDC_ADDRESSES, endpoint_label
from app.polymarket import polygon_rpc_urls
from tools.prewarm_funding_cache import discover_funding_windows

DEFAULT_OUTPUT_DIR = Path("validation_corpus_outputs")
DEFAULT_CORPUS_PATH = Path("validation_corpus/post_v2_validation_corpus.json")
DEFAULT_MAX_ENDPOINTS = 2
DEFAULT_PER_REQUEST_TIMEOUT_SECONDS = 8
DEFAULT_TOTAL_TIMEOUT_SECONDS = 90
DEFAULT_LOG_SPANS = (1, DEFAULT_RPC_GETLOGS_BLOCK_CHUNK)
SYNTHETIC_WALLET = "0x000000000000000000000000000000000000dead"

RpcCaller = Callable[[str, str, list[object], int], dict[str, Any]]


def run_diagnostic(
    *,
    urls: list[str] | None = None,
    corpus_path: Path = DEFAULT_CORPUS_PATH,
    max_endpoints: int = DEFAULT_MAX_ENDPOINTS,
    per_request_timeout_seconds: int = DEFAULT_PER_REQUEST_TIMEOUT_SECONDS,
    total_timeout_seconds: int = DEFAULT_TOTAL_TIMEOUT_SECONDS,
    log_spans: tuple[int, ...] | None = None,
    wallet: str | None = None,
    rpc_caller: RpcCaller | None = None,
    now_func: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    load_runtime_env(REPO_ROOT)
    configured_log_span = _configured_getlogs_block_chunk()
    resolved_log_spans = log_spans if log_spans is not None else _default_log_spans(configured_log_span)
    resolved_urls = urls if urls is not None else polygon_rpc_urls()
    selected_urls = [url for url in resolved_urls if str(url or "").strip()][: max(0, max_endpoints)]
    sample_wallet, sample_source = _sample_wallet(wallet=wallet, corpus_path=corpus_path)
    started = now_func()
    caller = rpc_caller or call_rpc
    endpoint_results: list[dict[str, Any]] = []

    for url in selected_urls:
        if _timed_out(started, total_timeout_seconds, now_func):
            break
        endpoint_results.append(
            _diagnose_endpoint(
                url=url,
                sample_wallet=sample_wallet,
                log_spans=resolved_log_spans,
                per_request_timeout_seconds=per_request_timeout_seconds,
                total_timeout_seconds=total_timeout_seconds,
                started=started,
                rpc_caller=caller,
                now_func=now_func,
            )
        )

    classification = classify_diagnostic(endpoint_results, configured_endpoint_count=len(selected_urls))
    recommended_next_step = _recommended_next_step(classification)
    elapsed = round(max(0.0, now_func() - started), 3)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "purpose": "bounded read-only trace-method diagnostic",
        "classification": classification,
        "recommended_next_step": recommended_next_step,
        "configured_endpoint_count": len(selected_urls),
        "endpoint_labels": [endpoint_label(url) for url in selected_urls],
        "sample_wallet_source": sample_source,
        "sample_wallet_label": _wallet_label(sample_wallet),
        "configured_getlogs_block_chunk": configured_log_span,
        "log_spans_tested": list(resolved_log_spans),
        "per_request_timeout_seconds": per_request_timeout_seconds,
        "total_timeout_seconds": total_timeout_seconds,
        "runtime_seconds": elapsed,
        "read_only": True,
        "production_model_changes": "none",
        "endpoint_results": endpoint_results,
        "method_summary": _method_summary(endpoint_results),
        "invariants_preserved": _invariants_preserved(),
    }


def _diagnose_endpoint(
    *,
    url: str,
    sample_wallet: str,
    log_spans: tuple[int, ...],
    per_request_timeout_seconds: int,
    total_timeout_seconds: int,
    started: float,
    rpc_caller: RpcCaller,
    now_func: Callable[[], float],
) -> dict[str, Any]:
    label = endpoint_label(url)
    calls: list[dict[str, Any]] = []
    latest_block: int | None = None

    block_call = _call_bounded(
        url,
        "eth_blockNumber",
        [],
        per_request_timeout_seconds,
        calls,
        started,
        total_timeout_seconds,
        rpc_caller,
        now_func,
    )
    if block_call.get("status") == "available":
        raw_block = block_call.get("result")
        if isinstance(raw_block, str) and raw_block.startswith("0x"):
            latest_block = int(raw_block, 16)
            block_call["latestBlock"] = latest_block
        else:
            block_call["status"] = "malformed_response"
            block_call["detail"] = "eth_blockNumber result was missing a hex block value."

    if latest_block is not None and not _timed_out(started, total_timeout_seconds, now_func):
        _call_bounded(
            url,
            "eth_getBlockByNumber",
            [hex(latest_block), False],
            per_request_timeout_seconds,
            calls,
            started,
            total_timeout_seconds,
            rpc_caller,
            now_func,
        )

    if latest_block is not None:
        padded_wallet = _topic_address(sample_wallet)
        for span in log_spans:
            if _timed_out(started, total_timeout_seconds, now_func):
                break
            normalized_span = max(1, int(span))
            from_block = max(0, latest_block - normalized_span + 1)
            params = [
                {
                    "fromBlock": hex(from_block),
                    "toBlock": hex(latest_block),
                    "address": USDC_ADDRESSES[0],
                    "topics": [TRANSFER_EVENT_TOPIC, None, padded_wallet],
                }
            ]
            call = _call_bounded(
                url,
                "eth_getLogs",
                params,
                per_request_timeout_seconds,
                calls,
                started,
                total_timeout_seconds,
                rpc_caller,
                now_func,
            )
            call["blockSpan"] = normalized_span
            call["tokenAddressLabel"] = _wallet_label(USDC_ADDRESSES[0])

    return {
        "endpoint_label": label,
        "lightweight_status": _first_status(calls, "eth_blockNumber"),
        "block_timestamp_status": _first_status(calls, "eth_getBlockByNumber"),
        "getlogs_statuses": [
            {
                "blockSpan": int(call.get("blockSpan") or 0),
                "status": str(call.get("status") or "unknown"),
                "durationSeconds": call.get("durationSeconds", 0),
                "resultLength": call.get("resultLength"),
                "detail": call.get("detail", ""),
            }
            for call in calls
            if call.get("method") == "eth_getLogs"
        ],
        "calls": calls,
    }


def _call_bounded(
    url: str,
    method: str,
    params: list[object],
    timeout_seconds: int,
    calls: list[dict[str, Any]],
    started: float,
    total_timeout_seconds: int,
    rpc_caller: RpcCaller,
    now_func: Callable[[], float],
) -> dict[str, Any]:
    if _timed_out(started, total_timeout_seconds, now_func):
        call = {
            "method": method,
            "status": "skipped_total_timeout",
            "durationSeconds": 0,
            "detail": "Skipped because diagnostic total timeout was reached.",
        }
        calls.append(call)
        return call
    call = dict(rpc_caller(url, method, params, max(1, int(timeout_seconds))))
    call.setdefault("method", method)
    calls.append(call)
    return call


def call_rpc(url: str, method: str, params: list[object], timeout_seconds: int) -> dict[str, Any]:
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; InsPoly/0.1; +https://polymarket.com)",
        },
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=max(1, int(timeout_seconds))) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        return _rpc_result(method, _status_for_http(exc.code), f"HTTP {exc.code}", started)
    except (TimeoutError, socket.timeout) as exc:
        return _rpc_result(method, "timeout", f"{type(exc).__name__}: {exc}", started)
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        text = f"{type(reason).__name__}: {reason}"
        status = "timeout" if "timed out" in text.lower() else "network_error"
        return _rpc_result(method, status, text, started)
    except Exception as exc:
        text = str(exc)
        lowered = text.lower()
        if any(token in lowered for token in ("401", "403", "unauthorized", "forbidden")):
            status = "auth_error"
        elif "429" in lowered or "rate" in lowered:
            status = "rate_limited"
        elif "timed out" in lowered or "timeout" in lowered:
            status = "timeout"
        else:
            status = "network_error"
        return _rpc_result(method, status, f"{type(exc).__name__}: {text}", started)

    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        return _rpc_result(method, "malformed_response", f"JSONDecodeError: {exc}", started)
    if not isinstance(decoded, Mapping):
        return _rpc_result(method, "malformed_response", "RPC response was not a JSON object.", started)
    if decoded.get("error"):
        detail = str(decoded.get("error"))
        return _rpc_result(method, _status_for_rpc_error(detail), detail, started)
    result = decoded.get("result")
    call = _rpc_result(method, "available", f"{method} returned a result.", started, result=result)
    if isinstance(result, list):
        call["resultLength"] = len(result)
        call.pop("result", None)
    elif method != "eth_blockNumber":
        call.pop("result", None)
    return call


def classify_diagnostic(
    endpoint_results: list[Mapping[str, Any]],
    *,
    configured_endpoint_count: int | None = None,
) -> str:
    if (configured_endpoint_count if configured_endpoint_count is not None else len(endpoint_results)) <= 0:
        return "operator_rpc_configuration_required"
    calls = [call for endpoint in endpoint_results for call in endpoint.get("calls", []) if isinstance(call, Mapping)]
    if not calls:
        return "trace_method_diagnostic_no_calls"
    block_statuses = [str(call.get("status") or "unknown") for call in calls if call.get("method") == "eth_blockNumber"]
    if not any(status == "available" for status in block_statuses):
        if any(status == "auth_error" for status in block_statuses):
            return "operator_rpc_auth_or_configuration_required"
        if any(status == "rate_limited" for status in block_statuses):
            return "public_rpc_rate_limited"
        if any(status == "timeout" for status in block_statuses):
            return "public_rpc_lightweight_timeout"
        return "public_rpc_lightweight_unavailable"
    getlogs_calls = [call for call in calls if call.get("method") == "eth_getLogs"]
    if not getlogs_calls:
        return "public_rpc_lightweight_only"
    non_available_getlogs = [
        call for call in getlogs_calls if str(call.get("status") or "") not in {"available", "skipped_total_timeout"}
    ]
    widest_span = max(int(call.get("blockSpan") or 0) for call in getlogs_calls)
    widest_statuses = [
        str(call.get("status") or "")
        for call in getlogs_calls
        if int(call.get("blockSpan") or 0) == widest_span and widest_span > 0
    ]
    widest_path_available = any(status == "available" for status in widest_statuses)
    if widest_path_available:
        if non_available_getlogs:
            return "trace_method_path_available_with_endpoint_errors"
        return "trace_method_path_available"
    if any(str(call.get("status") or "") in {"timeout", "skipped_total_timeout"} for call in getlogs_calls):
        return "public_rpc_trace_timeout"
    if any(str(call.get("status") or "") == "rate_limited" for call in getlogs_calls):
        return "public_rpc_trace_rate_limited"
    if not any(str(call.get("status") or "") == "available" for call in getlogs_calls):
        return "public_rpc_trace_unavailable"
    if widest_statuses:
        return "public_rpc_trace_chunk_bottleneck"
    if non_available_getlogs:
        return "trace_method_path_available_with_endpoint_errors"
    return "trace_method_path_available"


def write_outputs(
    report: Mapping[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    timestamp: str | None = None,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"trace_method_diagnostic_{stamp}.json"
    markdown_path = output_dir / f"trace_method_diagnostic_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Trace Method Diagnostic",
        "",
        f"- Generated at: {report.get('generated_at', '')}",
        f"- Classification: `{report.get('classification', 'unknown')}`",
        f"- Recommended next step: `{report.get('recommended_next_step', 'unknown')}`",
        f"- Read-only: `{report.get('read_only', True)}`",
        f"- Production model changes: `{report.get('production_model_changes', 'none')}`",
        f"- Endpoint count tested: `{report.get('configured_endpoint_count', 0)}`",
        f"- Endpoint labels: `{', '.join(report.get('endpoint_labels', []) or []) or 'none'}`",
        f"- Sample wallet source: `{report.get('sample_wallet_source', 'unknown')}`",
        f"- Sample wallet label: `{report.get('sample_wallet_label', '')}`",
        f"- Configured getLogs block chunk: `{report.get('configured_getlogs_block_chunk', '')}`",
        f"- Log spans tested: `{report.get('log_spans_tested', [])}`",
        f"- Per-request timeout seconds: `{report.get('per_request_timeout_seconds', 0)}`",
        f"- Total timeout seconds: `{report.get('total_timeout_seconds', 0)}`",
        f"- Runtime seconds: `{report.get('runtime_seconds', 0)}`",
        "",
        "## Method Summary",
    ]
    summary = report.get("method_summary", {})
    if isinstance(summary, Mapping):
        for method, values in sorted(summary.items()):
            if isinstance(values, Mapping):
                lines.append(
                    f"- `{method}`: available `{values.get('available', 0)}`, "
                    f"timeouts `{values.get('timeout', 0)}`, rate-limited `{values.get('rate_limited', 0)}`, "
                    f"errors `{values.get('errors', 0)}`"
                )
    lines.extend(["", "## Endpoints"])
    endpoints = report.get("endpoint_results", [])
    if isinstance(endpoints, list) and endpoints:
        for endpoint in endpoints:
            if not isinstance(endpoint, Mapping):
                continue
            lines.append(f"- `{endpoint.get('endpoint_label', 'unknown')}`")
            lines.append(f"  - lightweight: `{endpoint.get('lightweight_status', 'unknown')}`")
            lines.append(f"  - block timestamp: `{endpoint.get('block_timestamp_status', 'unknown')}`")
            statuses = endpoint.get("getlogs_statuses", [])
            if isinstance(statuses, list) and statuses:
                for status in statuses:
                    if isinstance(status, Mapping):
                        lines.append(
                            f"  - eth_getLogs span `{status.get('blockSpan', 0)}`: "
                            f"`{status.get('status', 'unknown')}` in `{status.get('durationSeconds', 0)}`s, "
                            f"logs `{status.get('resultLength', '')}`"
                        )
            else:
                lines.append("  - eth_getLogs: `not_assessed`")
    else:
        lines.append("- none")
    lines.extend(["", "## Invariants Preserved"])
    for invariant in report.get("invariants_preserved", []) or []:
        lines.append(f"- {invariant}")
    lines.append("")
    return "\n".join(lines)


def _sample_wallet(*, wallet: str | None, corpus_path: Path) -> tuple[str, str]:
    if wallet and _looks_like_wallet(wallet):
        return wallet.lower(), "cli_wallet"
    try:
        corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return SYNTHETIC_WALLET, "synthetic_wallet_no_corpus_sample"
    targets = corpus.get("targets", []) if isinstance(corpus, Mapping) else []
    if isinstance(targets, list):
        for target in targets:
            if not isinstance(target, Mapping):
                continue
            windows = discover_funding_windows(target, max_windows=1, repo_root=REPO_ROOT)
            if windows:
                return windows[0].wallet.lower(), "local_corpus_funding_window"
    return SYNTHETIC_WALLET, "synthetic_wallet_no_funding_window"


def _method_summary(endpoint_results: list[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for endpoint in endpoint_results:
        calls = endpoint.get("calls", [])
        if not isinstance(calls, list):
            continue
        for call in calls:
            if not isinstance(call, Mapping):
                continue
            method = str(call.get("method") or "unknown")
            status = str(call.get("status") or "unknown")
            bucket = summary.setdefault(method, {"available": 0, "timeout": 0, "rate_limited": 0, "errors": 0})
            if status == "available":
                bucket["available"] += 1
            elif status in {"timeout", "skipped_total_timeout"}:
                bucket["timeout"] += 1
            elif status == "rate_limited":
                bucket["rate_limited"] += 1
            else:
                bucket["errors"] += 1
    return summary


def _recommended_next_step(classification: str) -> str:
    if classification == "trace_method_path_available":
        return "run_bounded_12_target_validation_smoke"
    if classification == "trace_method_path_available_with_endpoint_errors":
        return "run_bounded_12_target_validation_smoke_with_endpoint_quarantine"
    if classification in {
        "operator_rpc_configuration_required",
        "operator_rpc_auth_or_configuration_required",
        "public_rpc_lightweight_unavailable",
        "public_rpc_lightweight_timeout",
        "public_rpc_rate_limited",
        "public_rpc_lightweight_only",
        "public_rpc_trace_timeout",
        "public_rpc_trace_rate_limited",
        "public_rpc_trace_unavailable",
        "public_rpc_trace_chunk_bottleneck",
    }:
        return "operator_rpc_configuration_or_capacity_decision"
    return "inspect_trace_method_diagnostic_before_running_larger_corpus"


def _status_for_http(code: int) -> str:
    if code in {401, 403}:
        return "auth_error"
    if code == 429:
        return "rate_limited"
    return "network_error"


def _status_for_rpc_error(detail: str) -> str:
    lowered = detail.lower()
    if any(token in lowered for token in ("401", "403", "unauthorized", "forbidden", "auth")):
        return "auth_error"
    if "429" in lowered or "rate" in lowered or "limit" in lowered:
        return "rate_limited"
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout"
    return "network_error"


def _rpc_result(
    method: str,
    status: str,
    detail: str,
    started: float,
    *,
    result: object | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "method": method,
        "status": status,
        "durationSeconds": round(max(0.0, time.monotonic() - started), 3),
        "detail": detail,
    }
    if result is not None:
        payload["result"] = result
    return payload


def _topic_address(address: str) -> str:
    return "0x" + address.lower().replace("0x", "").zfill(64)


def _looks_like_wallet(value: str) -> bool:
    raw = value.lower().strip()
    return raw.startswith("0x") and len(raw) == 42 and all(ch in "0123456789abcdef" for ch in raw[2:])


def _wallet_label(wallet: str) -> str:
    normalized = wallet.lower()
    if not _looks_like_wallet(normalized):
        return "invalid"
    return f"{normalized[:6]}...{normalized[-4:]}"


def _first_status(calls: list[Mapping[str, Any]], method: str) -> str:
    for call in calls:
        if call.get("method") == method:
            return str(call.get("status") or "unknown")
    return "not_assessed"


def _timed_out(started: float, timeout_seconds: int, now_func: Callable[[], float]) -> bool:
    return max(0, int(timeout_seconds)) > 0 and now_func() - started >= max(1, int(timeout_seconds))


def _parse_log_spans(value: str) -> tuple[int, ...]:
    spans = []
    for part in str(value or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            spans.append(max(1, int(part)))
        except ValueError:
            raise argparse.ArgumentTypeError(f"Invalid log span: {part}") from None
    return tuple(spans or _default_log_spans())


def _configured_getlogs_block_chunk() -> int:
    return runtime_env_int(
        "INSPOLY_POLYGON_RPC_GETLOGS_BLOCK_CHUNK",
        DEFAULT_RPC_GETLOGS_BLOCK_CHUNK,
        minimum=1,
    )


def _default_log_spans(configured_log_span: int | None = None) -> tuple[int, ...]:
    configured = max(1, int(configured_log_span or _configured_getlogs_block_chunk()))
    spans = [1, configured]
    return tuple(dict.fromkeys(spans))


def _invariants_preserved() -> list[str]:
    return [
        "_score_trade() unchanged",
        "Strong Risk gates unchanged",
        "Scoring weights unchanged",
        "Production severity labels unchanged",
        "Structural pre-admission unchanged",
        "Suspicious funding v2 unchanged",
        "Hard Evidence Review routing unchanged",
        "No LLM scoring",
        "No external signal ingestion",
        "No private credentials or hardcoded endpoint URLs",
        "No old saved-output mutation",
        "Dedupe remains reporting-only",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a bounded read-only Polygon RPC trace-method diagnostic.")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-endpoints", type=int, default=DEFAULT_MAX_ENDPOINTS)
    parser.add_argument("--per-request-timeout-seconds", type=int, default=DEFAULT_PER_REQUEST_TIMEOUT_SECONDS)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TOTAL_TIMEOUT_SECONDS)
    parser.add_argument("--log-spans", type=_parse_log_spans, default=None)
    parser.add_argument("--wallet", default="")
    args = parser.parse_args()

    report = run_diagnostic(
        corpus_path=args.corpus,
        max_endpoints=args.max_endpoints,
        per_request_timeout_seconds=max(1, args.per_request_timeout_seconds),
        total_timeout_seconds=max(1, args.timeout_seconds),
        log_spans=args.log_spans,
        wallet=args.wallet or None,
    )
    paths = write_outputs(report, args.output_dir)
    print(f"Trace method diagnostic: {report.get('classification', 'unknown')}")
    print(f"Recommended next step: {report.get('recommended_next_step', 'unknown')}")
    print(f"JSON: {paths['json_path']}")
    print(f"Markdown: {paths['markdown_path']}")


if __name__ == "__main__":
    main()
