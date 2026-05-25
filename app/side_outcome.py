from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SideOutcomeNormalization:
    raw_token_outcome: str
    raw_order_side: str
    raw_token_price: Decimal | None
    economic_side: str
    economic_side_probability: Decimal | None
    economic_direction_normalized: str
    normalization_status: str
    fallback_reason: str

    @property
    def model_probability_basis(self) -> str:
        if self.economic_side_probability is not None and self.economic_side != UNKNOWN:
            return "economic_side_probability"
        return "unknown"

    @property
    def model_economic_direction(self) -> str:
        return self.economic_direction_normalized

    @property
    def raw_token_price_label(self) -> str:
        if self.raw_token_price is None or self.raw_token_outcome == UNKNOWN:
            return "Raw token: unknown"
        return f"Raw token: {_display_side(self.raw_token_outcome)} @ {_percent_label(self.raw_token_price)}"

    @property
    def economic_side_probability_label(self) -> str:
        if self.economic_side_probability is None or self.economic_side == UNKNOWN:
            return "Economic side: unknown"
        return f"Economic side: {_display_side(self.economic_side)} @ {_percent_label(self.economic_side_probability)}"

    def to_raw_metrics(self) -> dict[str, str]:
        return {
            "raw_token_outcome": self.raw_token_outcome,
            "raw_order_side": self.raw_order_side,
            "raw_token_price": _decimal_text(self.raw_token_price),
            "raw_token_price_label": self.raw_token_price_label,
            "economic_side": self.economic_side,
            "economic_side_probability": _decimal_text(self.economic_side_probability),
            "economic_side_probability_label": self.economic_side_probability_label,
            "economic_direction_normalized": self.economic_direction_normalized,
            "model_probability_basis": self.model_probability_basis,
            "model_economic_direction": self.model_economic_direction,
            "side_outcome_normalization_status": self.normalization_status,
            "side_outcome_fallback_reason": self.fallback_reason,
        }

    def to_payload(self) -> dict[str, object]:
        return {
            "rawTokenOutcome": self.raw_token_outcome,
            "rawOrderSide": self.raw_order_side,
            "rawTokenPrice": _decimal_payload(self.raw_token_price),
            "rawTokenPriceLabel": self.raw_token_price_label,
            "economicSide": self.economic_side,
            "economicSideProbability": _decimal_payload(self.economic_side_probability),
            "economicSideProbabilityLabel": self.economic_side_probability_label,
            "economicDirectionNormalized": self.economic_direction_normalized,
            "modelProbabilityBasis": self.model_probability_basis,
            "modelEconomicDirection": self.model_economic_direction,
            "sideOutcomeNormalizationStatus": self.normalization_status,
            "sideOutcomeFallbackReason": self.fallback_reason,
        }


@dataclass(frozen=True, slots=True)
class ClusterDirectionNormalization:
    cluster_direction: str
    cluster_direction_basis: str
    cluster_normalization_status: str
    cluster_direction_fallback_reason: str

    def to_raw_metrics(self) -> dict[str, str]:
        return {
            "cluster_direction": self.cluster_direction,
            "cluster_direction_basis": self.cluster_direction_basis,
            "cluster_normalization_status": self.cluster_normalization_status,
            "cluster_direction_fallback_reason": self.cluster_direction_fallback_reason,
        }

    def to_payload(self) -> dict[str, object]:
        return {
            "clusterDirection": self.cluster_direction,
            "clusterDirectionBasis": self.cluster_direction_basis,
            "clusterNormalizationStatus": self.cluster_normalization_status,
            "clusterDirectionFallbackReason": self.cluster_direction_fallback_reason,
        }


def normalize_side_outcome(side: object, outcome: object, price: object) -> SideOutcomeNormalization:
    raw_order_side = _normalize_side(side)
    raw_token_outcome = _normalize_outcome(outcome)
    raw_token_price = _coerce_probability(price)
    if raw_order_side == UNKNOWN or raw_token_outcome == UNKNOWN or raw_token_price is None:
        return SideOutcomeNormalization(
            raw_token_outcome=raw_token_outcome,
            raw_order_side=raw_order_side,
            raw_token_price=raw_token_price,
            economic_side=UNKNOWN,
            economic_side_probability=None,
            economic_direction_normalized=UNKNOWN,
            normalization_status="unknown",
            fallback_reason=_fallback_reason(raw_order_side, raw_token_outcome, raw_token_price),
        )

    if raw_order_side == "BUY":
        economic_side = raw_token_outcome
        economic_probability = raw_token_price
    else:
        economic_side = "NO" if raw_token_outcome == "YES" else "YES"
        economic_probability = Decimal("1") - raw_token_price
    return SideOutcomeNormalization(
        raw_token_outcome=raw_token_outcome,
        raw_order_side=raw_order_side,
        raw_token_price=raw_token_price,
        economic_side=economic_side,
        economic_side_probability=economic_probability,
        economic_direction_normalized=f"long_{economic_side.lower()}",
        normalization_status="normalized",
        fallback_reason="",
    )


def normalize_cluster_direction(side: object, outcome: object, price: object) -> ClusterDirectionNormalization:
    normalized = normalize_side_outcome(side, outcome, price)
    if normalized.normalization_status == "normalized" and normalized.economic_direction_normalized != UNKNOWN:
        return ClusterDirectionNormalization(
            cluster_direction=normalized.economic_direction_normalized,
            cluster_direction_basis="economic_direction_normalized",
            cluster_normalization_status="normalized",
            cluster_direction_fallback_reason="",
        )
    return ClusterDirectionNormalization(
        cluster_direction=UNKNOWN,
        cluster_direction_basis="unknown",
        cluster_normalization_status="unknown",
        cluster_direction_fallback_reason=normalized.fallback_reason,
    )


def _normalize_side(value: object) -> str:
    text = str(value or "").strip().upper()
    return text if text in {"BUY", "SELL"} else UNKNOWN


def _normalize_outcome(value: object) -> str:
    text = str(value or "").strip().upper()
    if text in {"YES", "Y"}:
        return "YES"
    if text in {"NO", "N"}:
        return "NO"
    return UNKNOWN


def _coerce_probability(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        probability = Decimal(str(value).replace("%", "").strip())
    except (InvalidOperation, ValueError):
        return None
    if not probability.is_finite():
        return None
    if probability > Decimal("1") and probability <= Decimal("100"):
        probability = probability / Decimal("100")
    if probability < Decimal("0") or probability > Decimal("1"):
        return None
    return probability


def _percent_label(value: Decimal) -> str:
    return f"{(value * Decimal('100')):.1f}%"


def _display_side(value: str) -> str:
    if value == UNKNOWN:
        return UNKNOWN
    return value.title()


def _decimal_text(value: Decimal | None) -> str:
    return str(value) if value is not None else UNKNOWN


def _decimal_payload(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def _fallback_reason(side: str, outcome: str, price: Decimal | None) -> str:
    missing: list[str] = []
    if side == UNKNOWN:
        missing.append("raw_order_side")
    if outcome == UNKNOWN:
        missing.append("raw_token_outcome")
    if price is None:
        missing.append("raw_token_price")
    return "missing_or_malformed_" + "_".join(missing) if missing else "unknown"
