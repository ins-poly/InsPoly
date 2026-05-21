from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config import load_runtime_env
from app.funding_context import TRANSFER_EVENT_TOPIC, USDC_ADDRESSES, endpoint_label
from app.polymarket import _post_json, polygon_rpc_urls

DEFAULT_OUTPUT_DIR = Path("funding_health_outputs")


def classify_rpc_health(url: str) -> dict[str, object]:
    if not str(url or "").strip():
        return _result(
            url,
            "not_configured",
            "No Polygon RPC URL configured.",
            lightweight_status="not_configured",
            funding_trace_status="not_configured",
        )
    block_result = _call_rpc(url, "eth_blockNumber", [])
    if block_result["status"] != "available":
        return _result(
            url,
            str(block_result["status"]),
            str(block_result["detail"]),
            lightweight_status=str(block_result["status"]),
            funding_trace_status="not_assessed",
        )
    latest_raw = block_result["result"]
    if not isinstance(latest_raw, str) or not latest_raw.startswith("0x"):
        return _result(
            url,
            "malformed_response",
            "eth_blockNumber result was missing or malformed.",
            lightweight_status="malformed_response",
            funding_trace_status="not_assessed",
        )
    latest_block = int(latest_raw, 16)
    from_block = max(0, latest_block - 1)
    logs_result = _call_rpc(
        url,
        "eth_getLogs",
        [
            {
                "fromBlock": hex(from_block),
                "toBlock": hex(latest_block),
                "address": USDC_ADDRESSES[0],
                "topics": [TRANSFER_EVENT_TOPIC],
            }
        ],
    )
    if logs_result["status"] == "available" and isinstance(logs_result.get("result"), list):
        return _result(
            url,
            "funding_trace_available",
            "eth_blockNumber and narrow eth_getLogs both succeeded.",
            lightweight_status="lightweight_available",
            funding_trace_status="funding_trace_available",
        )
    funding_status = str(logs_result["status"])
    if funding_status == "available":
        funding_status = "malformed_response"
    return _result(
        url,
        funding_status,
        str(logs_result["detail"]),
        lightweight_status="lightweight_available",
        funding_trace_status=funding_status,
    )


def _call_rpc(url: str, method: str, params: list[object]) -> dict[str, object]:
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    try:
        response = _post_json(url, payload, timeout=10)
    except HTTPError as exc:
        if exc.code in {401, 403}:
            return {"status": "auth_error", "detail": f"HTTP {exc.code}", "result": None}
        if exc.code == 429:
            return {"status": "rate_limited", "detail": "HTTP 429", "result": None}
        return {"status": "network_error", "detail": f"HTTP {exc.code}", "result": None}
    except URLError as exc:
        return {"status": "network_error", "detail": f"{type(exc.reason).__name__}: {exc.reason}", "result": None}
    except Exception as exc:
        text = str(exc)
        lowered = text.lower()
        if any(token in lowered for token in ("401", "403", "unauthorized", "forbidden")):
            return {"status": "auth_error", "detail": f"{type(exc).__name__}: {text}", "result": None}
        if "429" in lowered or "rate" in lowered:
            return {"status": "rate_limited", "detail": f"{type(exc).__name__}: {text}", "result": None}
        return {"status": "network_error", "detail": f"{type(exc).__name__}: {text}", "result": None}

    if not isinstance(response, Mapping):
        return {"status": "malformed_response", "detail": "RPC response was not a JSON object.", "result": None}
    error = response.get("error")
    if error:
        text = str(error)
        lowered = text.lower()
        if any(token in lowered for token in ("401", "403", "unauthorized", "forbidden", "auth")):
            return {"status": "auth_error", "detail": text, "result": None}
        if "429" in lowered or "rate" in lowered:
            return {"status": "rate_limited", "detail": text, "result": None}
        return {"status": "network_error", "detail": text, "result": None}
    result = response.get("result")
    return {"status": "available", "detail": f"{method} returned a result.", "result": result}


def run_healthcheck(
    urls: list[str] | None = None,
    *,
    runtime_env_root: Path | None = None,
) -> dict[str, object]:
    load_runtime_env(runtime_env_root or REPO_ROOT)
    resolved_urls = urls if urls is not None else polygon_rpc_urls()
    if not resolved_urls:
        resolved_urls = [""]
    endpoint_results = [classify_rpc_health(url) for url in resolved_urls]
    overall = _overall_status(endpoint_results)
    selected_endpoint_label = next(
        (
            str(item.get("endpoint_label") or "")
            for item in endpoint_results
            if item.get("lightweight_status") == "lightweight_available" or item.get("status") == "available"
        ),
        "",
    )
    selected_funding_trace_endpoint_label = next(
        (
            str(item.get("endpoint_label") or "")
            for item in endpoint_results
            if item.get("funding_trace_status") == "funding_trace_available"
            or item.get("status") in {"available", "funding_trace_available"}
        ),
        "",
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_status": overall,
        "auth_error": any(item.get("status") == "auth_error" for item in endpoint_results),
        "lightweight_available": any(item.get("lightweight_status") == "lightweight_available" for item in endpoint_results),
        "funding_trace_available": any(item.get("funding_trace_status") == "funding_trace_available" for item in endpoint_results),
        "endpoint_count": len(endpoint_results),
        "selected_endpoint_label": selected_endpoint_label,
        "selected_funding_trace_endpoint_label": selected_funding_trace_endpoint_label,
        "endpoints": endpoint_results,
    }


def write_health_outputs(
    report: Mapping[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    timestamp: str | None = None,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"funding_resolver_healthcheck_{stamp}.json"
    markdown_path = output_dir / f"funding_resolver_healthcheck_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Funding Resolver Healthcheck",
        "",
        f"- Generated at: {report.get('generated_at', '')}",
        f"- Overall status: {report.get('overall_status', 'unknown')}",
        f"- Auth error present: {report.get('auth_error', False)}",
        f"- Lightweight RPC available: {report.get('lightweight_available', False)}",
        f"- Funding trace available: {report.get('funding_trace_available', False)}",
        f"- Endpoint count: {report.get('endpoint_count', 0)}",
        f"- Selected endpoint: {report.get('selected_endpoint_label') or 'none'}",
        f"- Selected funding trace endpoint: {report.get('selected_funding_trace_endpoint_label') or 'none'}",
        "",
        "## Endpoints",
    ]
    endpoints = report.get("endpoints", [])
    if isinstance(endpoints, list) and endpoints:
        for item in endpoints:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                f"- {item.get('endpoint_label', 'unknown')}: {item.get('status', 'unknown')} "
                f"(lightweight={item.get('lightweight_status', 'unknown')}, "
                f"funding_trace={item.get('funding_trace_status', 'unknown')}) "
                f"({item.get('detail', '')})"
            )
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def _result(
    url: str,
    status: str,
    detail: str,
    *,
    lightweight_status: str,
    funding_trace_status: str,
) -> dict[str, object]:
    return {
        "endpoint_label": mask_rpc_url(url),
        "status": status,
        "lightweight_status": lightweight_status,
        "funding_trace_status": funding_trace_status,
        "lightweight_available": lightweight_status == "lightweight_available",
        "funding_trace_available": funding_trace_status == "funding_trace_available",
        "detail": detail,
    }


def mask_rpc_url(url: str) -> str:
    return endpoint_label(url)


def _overall_status(results: list[Mapping[str, object]]) -> str:
    statuses = [str(item.get("status") or "unknown") for item in results]
    funding_statuses = [str(item.get("funding_trace_status") or "unknown") for item in results]
    lightweight_statuses = [str(item.get("lightweight_status") or "unknown") for item in results]
    if any(status == "funding_trace_available" for status in funding_statuses) or any(
        status in {"available", "funding_trace_available"} for status in statuses
    ):
        return "available_for_funding_trace"
    if any(status == "auth_error" for status in statuses):
        return "auth_error"
    if any(status == "lightweight_available" for status in lightweight_statuses) and any(
        status == "rate_limited" for status in funding_statuses
    ):
        return "rate_limited_for_funding_trace"
    if any(status == "lightweight_available" for status in lightweight_statuses):
        return "available_lightweight_only"
    for status in ("rate_limited", "network_error", "malformed_response", "not_configured"):
        if status in statuses:
            return status
    return "malformed_response"


def main() -> None:
    parser = argparse.ArgumentParser(description="Check configured Polygon RPC health for InsPoly funding traces.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    report = run_healthcheck()
    outputs = write_health_outputs(report, args.output_dir)
    print(f"Funding resolver health: {report.get('overall_status', 'unknown')}")
    print(f"Auth error present: {report.get('auth_error', False)}")
    print(f"Lightweight RPC available: {report.get('lightweight_available', False)}")
    print(f"Funding trace available: {report.get('funding_trace_available', False)}")
    print(f"Selected endpoint: {report.get('selected_endpoint_label') or 'none'}")
    print(f"Selected funding trace endpoint: {report.get('selected_funding_trace_endpoint_label') or 'none'}")
    print(f"Markdown: {outputs['markdown_path']}")
    print(f"JSON: {outputs['json_path']}")


if __name__ == "__main__":
    main()
