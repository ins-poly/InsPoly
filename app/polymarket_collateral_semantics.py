"""Static, unknown-safe collateral semantics helpers for sidecar research."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence


UNKNOWN = "unknown"

ACCEPTED_VERIFIED_SOURCE_TYPES = {
    "official_docs",
    "verified_contract",
    "local_chain_artifact",
    "trusted_explorer",
}
FIXTURE_ONLY_SOURCE_TYPES = {"static_fixture", "test_fixture"}
REJECTED_SOURCE_TYPES = {
    "blog",
    "timing_inference",
    "wallet_cluster_heuristic",
    "unverified_note",
}

ROLE_PUSD_TOKEN = "pusd_token"
ROLE_PUSD_TOKEN_IMPL = "pusd_token_impl"
ROLE_CLOB_COLLATERAL = "clob_collateral"
ROLE_EXCHANGE_OR_ONRAMP = "exchange_or_onramp"
ROLE_COLLATERAL_ONRAMP = "collateral_onramp"
ROLE_COLLATERAL_OFFRAMP = "collateral_offramp"
ROLE_PERMISSIONED_RAMP = "permissioned_ramp"
ROLE_CTF_COLLATERAL_ADAPTER = "ctf_collateral_adapter"
ROLE_NEG_RISK_CTF_COLLATERAL_ADAPTER = "neg_risk_ctf_collateral_adapter"
ROLE_CTF_EXCHANGE = "ctf_exchange"
ROLE_NEG_RISK_CTF_EXCHANGE = "neg_risk_ctf_exchange"
KNOWN_ROLES = {
    ROLE_PUSD_TOKEN,
    ROLE_PUSD_TOKEN_IMPL,
    ROLE_CLOB_COLLATERAL,
    ROLE_EXCHANGE_OR_ONRAMP,
    ROLE_COLLATERAL_ONRAMP,
    ROLE_COLLATERAL_OFFRAMP,
    ROLE_PERMISSIONED_RAMP,
    ROLE_CTF_COLLATERAL_ADAPTER,
    ROLE_NEG_RISK_CTF_COLLATERAL_ADAPTER,
    ROLE_CTF_EXCHANGE,
    ROLE_NEG_RISK_CTF_EXCHANGE,
}

ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def classify_collateral_source_fact(fact: Mapping[str, object]) -> dict[str, object]:
    """Classify one static source fact without promoting it to runtime truth."""

    source_type = _text(fact.get("sourceType") or fact.get("source_type"))
    role = _text(fact.get("role"))
    address = _text(fact.get("address") or fact.get("contractAddress") or fact.get("tokenAddress"))
    symbol = _text(fact.get("symbol") or fact.get("tokenSymbol"))
    source_url = _text(fact.get("sourceUrl") or fact.get("source_url"))
    source_name = _text(fact.get("sourceName") or fact.get("source_name"))
    chain_id = _text(fact.get("chainId") or fact.get("chain_id"))
    claim = _text(fact.get("claim"))
    notes: list[str] = []

    source_status = UNKNOWN
    fact_status = UNKNOWN
    production_truth = False

    if not source_type:
        notes.append("missing_source_type")
    elif source_type in REJECTED_SOURCE_TYPES:
        source_status = "rejected_unverified_source"
        notes.append("source_type_not_acceptable_for_collateral_truth")
    elif source_type in FIXTURE_ONLY_SOURCE_TYPES:
        source_status = "static_fixture_only"
        notes.append("fixture_fact_not_production_truth")
    elif source_type in ACCEPTED_VERIFIED_SOURCE_TYPES:
        source_status = "accepted_verified_source_type"
        if not source_url and source_type in {"official_docs", "trusted_explorer"}:
            notes.append("missing_source_url")
    else:
        notes.append("unknown_source_type")

    if role and role not in KNOWN_ROLES:
        notes.append("unknown_collateral_role")
    if not role:
        notes.append("missing_collateral_role")
    if not address:
        notes.append("missing_contract_address")
    elif not ADDRESS_RE.match(address):
        notes.append("invalid_contract_address_shape")

    if source_status == "rejected_unverified_source":
        fact_status = "rejected"
    elif source_status == "static_fixture_only" and role in KNOWN_ROLES and ADDRESS_RE.match(address):
        fact_status = "known_static_fixture"
    elif (
        source_status == "accepted_verified_source_type"
        and role in KNOWN_ROLES
        and ADDRESS_RE.match(address)
        and (source_url or source_type in {"verified_contract", "local_chain_artifact"})
    ):
        fact_status = "verified_static_source"
        production_truth = bool(fact.get("productionTruth") is True)
        if not production_truth:
            notes.append("production_truth_not_explicitly_authorized")
    else:
        fact_status = UNKNOWN

    return {
        "sourceType": source_type or UNKNOWN,
        "sourceName": source_name or UNKNOWN,
        "role": role or UNKNOWN,
        "symbol": symbol or UNKNOWN,
        "chainId": chain_id or UNKNOWN,
        "address": address or UNKNOWN,
        "sourceUrl": source_url,
        "claim": claim or UNKNOWN,
        "sourceStatus": source_status,
        "factStatus": fact_status,
        "fixtureGrade": fact_status in {"known_static_fixture", "verified_static_source"},
        "runtimeGrade": False,
        "productionTruth": production_truth,
        "sidecarOnly": True,
        "runtimeIntegrationAllowed": False,
        "qualityNotes": sorted(set(notes)),
    }


def classify_trade_collateral_semantics(
    trade: Mapping[str, object],
    *,
    source_facts: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Classify static collateral context for one trade without runtime claims."""

    requested_symbol = _text(
        trade.get("collateralTokenSymbol")
        or trade.get("collateral_symbol")
        or trade.get("settlementTokenSymbol")
        or trade.get("assetSymbol")
    )
    requested_address = _text(
        trade.get("collateralTokenAddress")
        or trade.get("collateral_address")
        or trade.get("settlementTokenAddress")
        or trade.get("assetAddress")
    )
    classified = [classify_collateral_source_fact(fact) for fact in source_facts]
    matching = _matching_facts(requested_symbol, requested_address, classified)
    production_matches = [fact for fact in matching if fact["factStatus"] == "verified_static_source" and fact["productionTruth"]]
    fixture_matches = [fact for fact in matching if fact["factStatus"] == "known_static_fixture"]
    notes: list[str] = []

    if production_matches:
        collateral_status = "verified_static_source_no_runtime"
        selected = production_matches[0]
        notes.append("verified_source_still_requires_runtime_approval")
    elif fixture_matches:
        collateral_status = "known_static_fixture_only"
        selected = fixture_matches[0]
        notes.append("fixture_collateral_context_not_production_truth")
    else:
        collateral_status = UNKNOWN
        selected = None
        notes.append("missing_verified_collateral_source")

    if requested_symbol.lower() == "pusd" and selected is None:
        notes.append("pusd_symbol_without_verified_address_remains_unknown")
    if requested_address and not ADDRESS_RE.match(requested_address):
        notes.append("trade_collateral_address_invalid_shape")

    return {
        "collateralStatus": collateral_status,
        "requestedSymbol": requested_symbol or UNKNOWN,
        "requestedAddress": requested_address or UNKNOWN,
        "matchedSourceFact": selected or {},
        "sourceFactCount": len(classified),
        "matchingSourceFactCount": len(matching),
        "fundingRuntimeSafe": False,
        "capitalRuntimeSafe": False,
        "runtimeIntegrationAllowed": False,
        "sidecarOnly": True,
        "qualityNotes": sorted(set(notes)),
    }


def _matching_facts(
    requested_symbol: str,
    requested_address: str,
    facts: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    matches: list[Mapping[str, object]] = []
    for fact in facts:
        fact_symbol = _text(fact.get("symbol"))
        fact_address = _text(fact.get("address"))
        if requested_address and requested_address.lower() == fact_address.lower():
            matches.append(fact)
        elif requested_symbol and requested_symbol.lower() == fact_symbol.lower():
            matches.append(fact)
    return matches


def _text(value: object) -> str:
    return str(value or "").strip()
