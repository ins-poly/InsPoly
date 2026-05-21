from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS_PATH = Path("validation_corpus/post_v2_validation_corpus.json")
DEFAULT_OUTPUT_DIR = Path("validation_corpus_outputs")


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _slug_from_url(value: str) -> str:
    text = value.strip().rstrip("/")
    if not text:
        return ""
    return text.rsplit("/", 1)[-1]


def _safe_label(text: str, fallback: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    return (base or fallback)[:80]


def _category_tags(text: str) -> set[str]:
    lower = text.lower()
    tags: set[str] = set()
    if any(token in lower for token in ("gta", "grand theft auto")):
        tags.add("gta_or_known_cluster")
    else:
        tags.add("non_gta")
    if any(token in lower for token in ("bitcoin", "crypto", "btc", "ethereum", "stanley", "hockey", "nhl", "nba", "nfl", "sports")):
        tags.add("sports_crypto")
    if any(
        token in lower
        for token in (
            "iran",
            "ukraine",
            "russia",
            "trump",
            "mayor",
            "election",
            "maduro",
            "nato",
            "pope",
            "israel",
            "middle east",
            "world",
        )
    ):
        tags.add("politics_world")
    if any(token in lower for token in ("candidate", "funding", "wallet", "usdc")):
        tags.add("funding_candidate")
    if any(token in lower for token in ("high volume", "candidate_trade_count", "raw_trade_count")):
        tags.add("high_volume")
    return tags


def _target_family(mode: str, tags: Iterable[str]) -> str:
    tag_set = {str(tag) for tag in tags}
    if "gta_or_known_cluster" in tag_set:
        return "gta_or_known_cluster"
    if "sports_crypto" in tag_set:
        return "sports_crypto"
    if mode == "archive":
        return "archive_politics_world" if "politics_world" in tag_set else "archive"
    if "politics_world" in tag_set:
        return "politics_world_event_forensic"
    if "funding_candidate" in tag_set:
        return "funding_candidate_other"
    return "non_gta_other" if "non_gta" in tag_set else "unknown"


def _with_required_fields(target: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(target)
    tags = {str(tag).strip() for tag in normalized.get("tags") or [] if str(tag).strip()}
    mode = str(normalized.get("mode") or "")
    input_type = str(normalized.get("inputType") or "")
    if mode == "event_forensic":
        tags.add("event_forensic")
    if mode == "archive":
        tags.add("archive")
    if input_type == "saved_output_replay":
        tags.add("audit_only_saved_output")
        tags.add("cached_only")
    else:
        tags.add("fresh_rerunnable")
    normalized["tags"] = sorted(tags)
    normalized["freshRerunnable"] = bool("fresh_rerunnable" in tags and input_type != "saved_output_replay")
    normalized["auditOnly"] = bool("audit_only_saved_output" in tags or input_type == "saved_output_replay")
    normalized["cacheOnlyOk"] = bool("cache_only_ok" in tags or normalized.get("cacheOnlyOk"))
    normalized["networkAllowed"] = bool("network_allowed" in tags or normalized.get("networkAllowed"))
    normalized["targetFamily"] = str(normalized.get("targetFamily") or _target_family(mode, tags))
    return normalized


def _resolution_tags(payload: Mapping[str, Any], text: str) -> set[str]:
    tags: set[str] = set()
    lower = text.lower()
    target = payload.get("target_resolution")
    eligibility = payload.get("eligibility")
    summary = payload.get("summary")
    resolved_markets = 0
    unresolved_markets = 0
    if isinstance(summary, Mapping):
        resolved_markets = int(summary.get("resolved_market_count") or 0)
        unresolved_markets = int(summary.get("unresolved_market_count") or 0)
    if isinstance(target, Mapping):
        if target.get("outcome") or target.get("resolved") or target.get("winner"):
            tags.add("resolved_or_partial")
    if isinstance(eligibility, Mapping) and str(eligibility.get("mode") or "").lower() in {
        "resolved",
        "partial",
        "partial_resolution",
    }:
        tags.add("resolved_or_partial")
    if resolved_markets > 0:
        tags.add("resolved_or_partial")
    if unresolved_markets > 0 or any(token in lower for token in ("live", "unresolved", "open")):
        tags.add("live_or_unresolved")
    if not tags & {"resolved_or_partial", "live_or_unresolved"}:
        tags.add("live_or_unresolved")
    return tags


def _event_target_from_report(path: Path) -> dict[str, Any] | None:
    payload = _load_json(path)
    if not payload:
        return None
    input_url = str(payload.get("input_url") or "").strip()
    bundle_dir = path.parent
    selected_market_slug = str(payload.get("selected_market_slug") or "").strip()
    parent_event_slug = str(payload.get("parent_event_slug") or "").strip()
    selected_title = str(payload.get("selected_market_title") or "").strip()
    event = payload.get("event")
    event_title = ""
    if isinstance(event, Mapping):
        event_title = str(event.get("title") or event.get("slug") or "").strip()
    slug = selected_market_slug or parent_event_slug or _slug_from_url(input_url) or bundle_dir.name
    if input_url:
        input_type = "market_url" if "/market/" in input_url else "event_url"
        confidence = "high"
        tags = {"event_forensic", "fresh_rerunnable", "cache_only_ok", "network_allowed"}
    else:
        input_type = "saved_output_replay"
        input_url = str(bundle_dir)
        confidence = "medium"
        tags = {"event_forensic", "audit_only_saved_output", "cache_only_ok", "cached_only"}
    text = " ".join(
        str(item)
        for item in (
            input_url,
            slug,
            selected_title,
            event_title,
            payload.get("status"),
            payload.get("analysis_scope"),
        )
        if item
    )
    tags.update(_category_tags(text))
    tags.update(_resolution_tags(payload, text))
    summary = payload.get("summary")
    if isinstance(summary, Mapping) and int(summary.get("candidate_trade_count") or 0) >= 100:
        tags.add("high_volume")
    if isinstance(payload.get("funding_resolver_health"), Mapping):
        tags.add("funding_candidate")
    analysis_scope = str(payload.get("analysis_scope") or "market")
    if input_type == "event_url" and not selected_market_slug and not str(payload.get("selected_condition_id") or "").strip():
        analysis_scope = "event"
    return _with_required_fields({
        "label": _safe_label(slug or selected_title, bundle_dir.name),
        "mode": "event_forensic",
        "inputType": input_type,
        "inputValue": input_url,
        "savedOutputPath": str(bundle_dir),
        "eventOrMarketSlug": slug,
        "scopeSettings": {
            "analysisScope": analysis_scope,
            "selectedConditionId": str(payload.get("selected_condition_id") or ""),
            "selectedMarketSlug": selected_market_slug,
            "includeRelatedMarkets": False,
            "includeBlockchain": True,
        },
        "minNotional": "10000",
        "expectedCategory": "resolved_or_partial" if "resolved_or_partial" in tags else "live_or_unresolved",
        "tags": sorted(tags),
        "confidence": confidence,
        "source": "event_forensic_output_metadata",
    })


def _archive_target_from_report(path: Path) -> dict[str, Any] | None:
    payload = _load_json(path)
    if not payload:
        return None
    start = str(payload.get("range_start") or payload.get("start_at") or "").strip()
    end = str(payload.get("range_end") or payload.get("end_at") or "").strip()
    topic = str(payload.get("topic_scope") or "").strip()
    export_files = payload.get("export_files")
    saved_path = str(path)
    if isinstance(export_files, Mapping):
        saved_path = str(export_files.get("report_json_path") or saved_path)
    if start and end:
        input_type = "archive_window"
        input_value = f"{start}/{end}"
        confidence = "high"
        tags = {"archive", "fresh_rerunnable", "cache_only_ok", "network_allowed"}
    else:
        input_type = "saved_output_replay"
        input_value = saved_path
        confidence = "medium"
        tags = {"archive", "audit_only_saved_output", "cache_only_ok", "cached_only"}
    text = " ".join(str(item) for item in (topic, path.name, payload.get("status")) if item)
    tags.update(_category_tags(text))
    tags.add("resolved_or_partial")
    if int(payload.get("candidate_trade_count") or 0) >= 100:
        tags.add("high_volume")
    if isinstance(payload.get("funding_resolver_health"), Mapping):
        tags.add("funding_candidate")
    label = _safe_label(f"archive_{topic}_{start}_{end}", path.stem)
    categories = [item.strip() for item in topic.split(",") if item.strip()]
    return _with_required_fields({
        "label": label,
        "mode": "archive",
        "inputType": input_type,
        "inputValue": input_value,
        "savedOutputPath": saved_path,
        "eventOrMarketSlug": "",
        "scopeSettings": {"categories": categories},
        "minNotional": "10000",
        "expectedCategory": "resolved_or_partial",
        "tags": sorted(tags),
        "confidence": confidence,
        "source": "archive_output_metadata",
    })


def _current_corpus_targets(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = _load_json(path)
    targets = payload.get("targets")
    return [dict(item) for item in targets if isinstance(item, Mapping)] if isinstance(targets, list) else []


def _target_key(target: Mapping[str, Any]) -> tuple[str, str, str]:
    mode = str(target.get("mode") or "")
    input_type = str(target.get("inputType") or "")
    input_value = str(target.get("inputValue") or target.get("savedOutputPath") or "")
    return mode, input_type, input_value


def discover_validation_targets(
    *,
    repo_root: Path = REPO_ROOT,
    corpus_path: Path = REPO_ROOT / DEFAULT_CORPUS_PATH,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for target in _current_corpus_targets(corpus_path):
        candidate = _with_required_fields(target)
        candidate.setdefault("confidence", "high" if candidate.get("inputType") != "saved_output_replay" else "medium")
        candidate.setdefault("source", "current_corpus")
        candidate.setdefault("savedOutputPath", "")
        candidate.setdefault("eventOrMarketSlug", _slug_from_url(str(candidate.get("inputValue") or "")))
        candidates.append(candidate)

    for path in sorted((repo_root / "event_forensic_outputs").glob("event_forensic_*/event_analysis.json")):
        target = _event_target_from_report(path)
        if target:
            candidates.append(target)
    for path in sorted((repo_root / ".inspoly_archive_researcher" / "reports").glob("archive_research_*.json")):
        target = _archive_target_from_report(path)
        if target:
            candidates.append(target)

    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    confidence_rank = {"high": 3, "medium": 2, "low": 1}
    for candidate in candidates:
        key = _target_key(candidate)
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = candidate
            continue
        old_rank = confidence_rank.get(str(existing.get("confidence") or "low"), 1)
        new_rank = confidence_rank.get(str(candidate.get("confidence") or "low"), 1)
        if new_rank > old_rank:
            merged = dict(candidate)
            prior_paths = set(existing.get("priorOutputPaths") or [])
            saved = existing.get("savedOutputPath")
            if saved:
                prior_paths.add(str(saved))
            if prior_paths:
                merged["priorOutputPaths"] = sorted(prior_paths)
            deduped[key] = merged
        else:
            prior_paths = set(existing.get("priorOutputPaths") or [])
            saved = candidate.get("savedOutputPath")
            if saved:
                prior_paths.add(str(saved))
            if prior_paths:
                existing["priorOutputPaths"] = sorted(prior_paths)

    discovered = sorted(
        deduped.values(),
        key=lambda item: (
            {"high": 0, "medium": 1, "low": 2}.get(str(item.get("confidence") or "low"), 2),
            str(item.get("mode") or ""),
            str(item.get("label") or ""),
        ),
    )
    confidence_counts = Counter(str(item.get("confidence") or "unknown") for item in discovered)
    tag_counts: Counter[str] = Counter()
    for item in discovered:
        tag_counts.update(str(tag) for tag in item.get("tags") or [])
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "total_candidates": len(discovered),
        "confidence_counts": dict(sorted(confidence_counts.items())),
        "tag_counts": dict(sorted(tag_counts.items())),
        "targets": discovered,
    }


def render_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Discovered Validation Targets",
        "",
        f"- Generated at: {summary.get('generated_at', '')}",
        f"- Total candidates: {summary.get('total_candidates', 0)}",
        f"- Confidence counts: {summary.get('confidence_counts', {})}",
        f"- Tag counts: {summary.get('tag_counts', {})}",
        "",
        "## Targets",
    ]
    for target in summary.get("targets", []):
        if not isinstance(target, Mapping):
            continue
        lines.append(
            f"- {target.get('label', '')}: mode={target.get('mode', '')}, "
            f"inputType={target.get('inputType', '')}, confidence={target.get('confidence', '')}, "
            f"tags={target.get('tags', [])}"
        )
        if target.get("inputValue"):
            lines.append(f"  - input: {target.get('inputValue')}")
        if target.get("savedOutputPath"):
            lines.append(f"  - saved: {target.get('savedOutputPath')}")
    return "\n".join(lines) + "\n"


def write_outputs(summary: Mapping[str, Any], output_dir: Path = REPO_ROOT / DEFAULT_OUTPUT_DIR) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"discovered_validation_targets_{stamp}.json"
    markdown_path = output_dir / f"discovered_validation_targets_{stamp}.md"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
        handle.write("\n")
    markdown_path.write_text(render_markdown(summary), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover local InsPoly validation targets from saved metadata.")
    parser.add_argument("--corpus", type=Path, default=REPO_ROOT / DEFAULT_CORPUS_PATH)
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    summary = discover_validation_targets(corpus_path=args.corpus)
    outputs = write_outputs(summary, args.output_dir)
    print(f"Discovered validation targets: {summary['total_candidates']}")
    print(f"JSON: {outputs['json_path']}")
    print(f"Markdown: {outputs['markdown_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
