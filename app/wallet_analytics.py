from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from math import log10
from statistics import median

from app.polymarket import WalletPosition


MICROTRADE_NOTIONAL_USDC = 100.0
ZOMBIE_VALUE_FLOOR_USDC = 1.0


@dataclass(slots=True)
class ClosedPositionRecord:
    timestamp: str
    market: str
    market_slug: str
    event_slug: str
    direction: str
    stake: float
    result: str
    realized_pnl: float
    realized_return: float


@dataclass(slots=True)
class ClosedPositionSummary:
    total: int
    wins: int
    losses: int
    win_rate_value: float
    win_rate_threshold: float
    win_rate_clears_threshold: bool
    total_realized_pnl: float
    average_return: float
    economic_sample_size: int
    economic_win_rate_value: float
    economic_win_rate_threshold: float
    economic_win_rate_clears_threshold: bool
    zombie_loss_count: int
    zombie_loss_notional: float
    redemption_avoidance_ratio: float
    de_facto_loss_count: int
    formal_win_rate_may_be_overstated: bool


@dataclass(slots=True)
class WalletStatisticalPrior:
    p_value: float
    log_score: float
    resolved_sample_size: int
    resolved_win_rate_value: float
    label: str
    note: str

    def to_raw_metrics(self) -> dict[str, str]:
        return {
            "wallet_statistical_p_value": _format_probability(self.p_value),
            "wallet_statistical_log_score": f"{self.log_score:.2f}",
            "wallet_resolved_sample_size": str(self.resolved_sample_size),
            "wallet_resolved_win_rate": f"{self.resolved_win_rate_value:.1f}%",
            "wallet_statistical_prior_label": self.label,
            "wallet_statistical_prior_note": self.note,
        }


@dataclass(slots=True)
class OpenPositionSummary:
    count: int
    notional: float
    unrealized_pnl: float
    unrealized_pct: float
    zombie_positions: int
    zombie_notional: float


@dataclass(slots=True)
class ActivitySummary:
    bot_likeness_score: float
    microtrade_ratio: float
    median_trade_size: float
    trade_burst_rate: float
    median_intertrade_interval_minutes: float
    market_breadth: int
    manual_review_value_score: float
    low_analyst_value_flag: bool


@dataclass(slots=True)
class WalletPerformance:
    closed_positions: list[ClosedPositionRecord]
    closed_summary: ClosedPositionSummary
    open_summary: OpenPositionSummary
    activity_summary: ActivitySummary


def required_win_rate_threshold(total_closed: int) -> float:
    if total_closed < 3:
        return 50.0
    if total_closed < 10:
        return 75.0
    return 90.0


def win_rate_clears_threshold(total_closed: int, win_rate: float) -> bool:
    return win_rate >= required_win_rate_threshold(total_closed)


def win_rate_relevance_note(total_closed: int, clears_threshold: bool) -> str | None:
    if clears_threshold:
        return None
    if total_closed <= 0:
        return "The wallet does not yet show a meaningful closed-position record, so its history does not support a stronger insider-style interpretation."
    if total_closed < 3:
        return "The wallet’s closed-position sample is still very small and not strong enough to support a stronger insider-style interpretation."
    if total_closed < 10:
        return "The wallet’s closed-position hit rate is not strong enough at this sample size to support a stronger risk classification."
    return "The wallet’s broader closed-position record is too weak to support a stronger risk classification."


def economic_history_relevance_note(summary: ClosedPositionSummary) -> str | None:
    if summary.formal_win_rate_may_be_overstated:
        return "The wallet’s formal win rate may be overstated because several economically dead positions were never redeemed."
    if summary.economic_win_rate_clears_threshold:
        return None
    if summary.economic_sample_size <= 0:
        return "The wallet does not yet show a meaningful economic track record in the loaded sample."
    if summary.economic_sample_size < 3:
        return "The wallet’s economic history is still too small to meaningfully strengthen this case."
    if summary.economic_sample_size < 10:
        return "The wallet’s economic hit rate is not strong enough at this sample size to support a stronger risk classification."
    return "The wallet’s broader economic record is too weak to support a stronger risk classification."


def bot_activity_note(summary: ActivitySummary) -> str | None:
    if summary.low_analyst_value_flag:
        return "This wallet is highly active but low-value for manual insider-style review."
    if summary.bot_likeness_score >= 70:
        return "The trading pattern looks automated and mechanically repetitive."
    return None


def clears_minimum_visible_win_rate(
    summary: ClosedPositionSummary,
    *,
    minimum_win_rate: float = 50.0,
) -> bool:
    if summary.economic_sample_size > 0:
        return summary.economic_win_rate_value >= minimum_win_rate
    if summary.total > 0:
        return summary.win_rate_value >= minimum_win_rate
    return True


def compute_wallet_statistical_prior(summary: ClosedPositionSummary) -> WalletStatisticalPrior:
    sample_size = summary.economic_sample_size if summary.economic_sample_size > 0 else summary.total
    wins = max(0, min(summary.wins, sample_size))
    win_rate = (wins / sample_size * 100.0) if sample_size else 0.0
    p_value = _binomial_upper_tail(wins, sample_size) if sample_size else 1.0
    log_score = -log10(max(p_value, 1e-300)) if sample_size >= 5 else 0.0

    if sample_size < 5:
        label = "insufficient_sample"
        note = (
            f"Only {sample_size} resolved/economic position(s) are available; "
            "the sample is too small for a wallet-level resolved-win-history prior."
        )
    elif p_value < 0.0001 and sample_size >= 10:
        label = "strong_statistical_prior"
        note = (
            "Unusual resolved win history, context only: "
            f"{wins} wins in {sample_size} resolved/economic positions is highly unusual under a simple "
            "50/50 null. It is not event-specific proof."
        )
    elif p_value < 0.001 and sample_size >= 8:
        label = "meaningful_statistical_prior"
        note = (
            "Unusual resolved win history, context only: "
            f"{wins} wins in {sample_size} resolved/economic positions is unusual under a simple "
            "50/50 null. It is not event-specific proof."
        )
    elif p_value < 0.01 and sample_size >= 5:
        label = "weak_statistical_prior"
        note = (
            "Mildly unusual resolved win history, context only: "
            f"{wins} wins in {sample_size} resolved/economic positions is unusual under a simple "
            "50/50 null. Do not treat it as decisive without trade-specific evidence."
        )
    else:
        label = "no_statistical_prior"
        note = "The resolved/economic history does not create an unusual win-history context signal on its own."

    return WalletStatisticalPrior(
        p_value=p_value,
        log_score=log_score,
        resolved_sample_size=sample_size,
        resolved_win_rate_value=win_rate,
        label=label,
        note=note,
    )


def compute_wallet_performance(trades: list[object], wallet_positions: list[WalletPosition]) -> WalletPerformance:
    open_map = {position.asset_id: position for position in wallet_positions if position.size > 0}
    grouped: dict[str, list[object]] = defaultdict(list)
    for trade in trades:
        grouped[trade.asset_id].append(trade)

    closed_positions: list[ClosedPositionRecord] = []
    open_notional = 0.0
    aggregate_unrealized_pnl = 0.0
    aggregate_cost_basis = 0.0
    zombie_loss_count = 0
    zombie_loss_notional = 0.0
    now = datetime.now(UTC)

    for asset_id, asset_trades in grouped.items():
        ordered = sorted(asset_trades, key=lambda item: item.timestamp)
        buy_notional = sum(float(item.notional) for item in ordered if item.side == "BUY")
        sell_notional = sum(float(item.notional) for item in ordered if item.side == "SELL")
        quantity = 0.0
        cost_basis = 0.0
        for item in ordered:
            size = float(item.size)
            price = float(item.price)
            if item.side == "BUY":
                quantity += size
                cost_basis += size * price
            elif quantity > 0:
                average_cost = cost_basis / quantity
                close_size = min(quantity, size)
                quantity -= close_size
                cost_basis -= average_cost * close_size

        latest = ordered[-1]
        if asset_id not in open_map:
            realized_pnl = sell_notional - buy_notional
            realized_return = (realized_pnl / buy_notional * 100.0) if buy_notional > 0 else 0.0
            closed_positions.append(
                ClosedPositionRecord(
                    timestamp=latest.timestamp.isoformat(),
                    market=latest.title,
                    market_slug=getattr(latest, "slug", ""),
                    event_slug=getattr(latest, "event_slug", ""),
                    direction=latest.outcome,
                    stake=buy_notional,
                    result="Won" if realized_pnl > 0 else "Lost" if realized_pnl < 0 else "Closed early",
                    realized_pnl=realized_pnl,
                    realized_return=realized_return,
                )
            )
            continue

        current_value = float(open_map[asset_id].current_value)
        open_notional += current_value
        remaining_cost_basis = max(cost_basis, 0.0)
        aggregate_cost_basis += remaining_cost_basis
        aggregate_unrealized_pnl += current_value - remaining_cost_basis

        if _is_zombie_position(
            current_value=current_value,
            cost_basis=remaining_cost_basis,
            redeemable=bool(open_map[asset_id].redeemable),
            latest_trade_at=latest.timestamp,
            now=now,
        ):
            zombie_loss_count += 1
            zombie_loss_notional += remaining_cost_basis

    closed_positions.sort(key=lambda item: item.timestamp, reverse=True)
    wins = sum(1 for item in closed_positions if item.result == "Won")
    losses = sum(1 for item in closed_positions if item.result == "Lost")
    total_realized = sum(item.realized_pnl for item in closed_positions)
    average_return = (
        sum(item.realized_return for item in closed_positions) / len(closed_positions)
        if closed_positions
        else 0.0
    )
    win_rate_value = (wins / len(closed_positions) * 100.0) if closed_positions else 0.0
    threshold = required_win_rate_threshold(len(closed_positions))
    economic_sample_size = len(closed_positions) + zombie_loss_count
    economic_win_rate = (wins / economic_sample_size * 100.0) if economic_sample_size else 0.0
    economic_threshold = required_win_rate_threshold(economic_sample_size)
    open_return = (aggregate_unrealized_pnl / aggregate_cost_basis * 100.0) if aggregate_cost_basis > 0 else 0.0
    redemption_avoidance_ratio = (
        zombie_loss_count / max(1, losses + zombie_loss_count)
        if zombie_loss_count or losses
        else 0.0
    )
    formal_overstated = bool(
        zombie_loss_count > 0
        and (win_rate_value - economic_win_rate >= 10.0 or redemption_avoidance_ratio >= 0.25)
    )
    activity_summary = _activity_summary(trades)

    return WalletPerformance(
        closed_positions=closed_positions,
        closed_summary=ClosedPositionSummary(
            total=len(closed_positions),
            wins=wins,
            losses=losses,
            win_rate_value=win_rate_value,
            win_rate_threshold=threshold,
            win_rate_clears_threshold=win_rate_clears_threshold(len(closed_positions), win_rate_value),
            total_realized_pnl=total_realized,
            average_return=average_return,
            economic_sample_size=economic_sample_size,
            economic_win_rate_value=economic_win_rate,
            economic_win_rate_threshold=economic_threshold,
            economic_win_rate_clears_threshold=win_rate_clears_threshold(economic_sample_size, economic_win_rate),
            zombie_loss_count=zombie_loss_count,
            zombie_loss_notional=zombie_loss_notional,
            redemption_avoidance_ratio=redemption_avoidance_ratio,
            de_facto_loss_count=zombie_loss_count,
            formal_win_rate_may_be_overstated=formal_overstated,
        ),
        open_summary=OpenPositionSummary(
            count=len(open_map),
            notional=open_notional,
            unrealized_pnl=aggregate_unrealized_pnl,
            unrealized_pct=open_return,
            zombie_positions=zombie_loss_count,
            zombie_notional=zombie_loss_notional,
        ),
        activity_summary=activity_summary,
    )


def _is_zombie_position(
    *,
    current_value: float,
    cost_basis: float,
    redeemable: bool,
    latest_trade_at: datetime,
    now: datetime,
) -> bool:
    if cost_basis <= 0:
        return False

    held_hours = max((now - latest_trade_at).total_seconds() / 3600.0, 0.0)
    value_floor = max(ZOMBIE_VALUE_FLOOR_USDC, cost_basis * 0.05)
    value_ratio = current_value / cost_basis if cost_basis > 0 else 1.0

    if redeemable and current_value <= value_floor:
        return True
    if value_ratio <= 0.03 and held_hours >= 24:
        return True
    if value_ratio <= 0.08 and held_hours >= 72:
        return True
    return False


def _activity_summary(trades: list[object]) -> ActivitySummary:
    if not trades:
        return ActivitySummary(
            bot_likeness_score=0.0,
            microtrade_ratio=0.0,
            median_trade_size=0.0,
            trade_burst_rate=0.0,
            median_intertrade_interval_minutes=0.0,
            market_breadth=0,
            manual_review_value_score=50.0,
            low_analyst_value_flag=False,
        )

    ordered = sorted(trades, key=lambda item: item.timestamp)
    notionals = [float(item.notional) for item in ordered if float(item.notional) >= 0]
    trade_count = len(ordered)
    median_trade_size = median(notionals) if notionals else 0.0
    microtrade_ratio = (
        sum(1 for value in notionals if value <= MICROTRADE_NOTIONAL_USDC) / trade_count
        if trade_count
        else 0.0
    )
    intervals = [
        max((current.timestamp - previous.timestamp).total_seconds() / 60.0, 0.0)
        for previous, current in zip(ordered, ordered[1:])
    ]
    median_interval = median(intervals) if intervals else 9999.0
    market_breadth = len({item.condition_id for item in ordered})
    burst_rate = _trade_burst_rate(ordered)

    bot_score = 0.0
    if trade_count >= 300:
        bot_score += 25
    elif trade_count >= 150:
        bot_score += 15
    elif trade_count >= 75:
        bot_score += 8

    if microtrade_ratio >= 0.8:
        bot_score += 25
    elif microtrade_ratio >= 0.6:
        bot_score += 18
    elif microtrade_ratio >= 0.4:
        bot_score += 10

    if median_trade_size <= 50:
        bot_score += 20
    elif median_trade_size <= 100:
        bot_score += 12
    elif median_trade_size <= 250:
        bot_score += 6

    if median_interval <= 1:
        bot_score += 15
    elif median_interval <= 5:
        bot_score += 8

    if burst_rate >= 40:
        bot_score += 15
    elif burst_rate >= 20:
        bot_score += 10
    elif burst_rate >= 10:
        bot_score += 6

    if market_breadth >= 80:
        bot_score += 10
    elif market_breadth >= 40:
        bot_score += 6

    if median_trade_size >= 500:
        bot_score -= 10
    elif median_trade_size >= 250:
        bot_score -= 4

    bot_score = max(0.0, min(100.0, bot_score))

    manual_review_value = 70.0
    if median_trade_size >= 500:
        manual_review_value += 15
    elif median_trade_size >= 250:
        manual_review_value += 8
    if 2 <= market_breadth <= 30:
        manual_review_value += 10
    if microtrade_ratio <= 0.2:
        manual_review_value += 5
    if trade_count >= 300 and median_trade_size < 100:
        manual_review_value -= 15
    manual_review_value -= bot_score * 0.7
    manual_review_value = max(0.0, min(100.0, manual_review_value))

    return ActivitySummary(
        bot_likeness_score=bot_score,
        microtrade_ratio=microtrade_ratio,
        median_trade_size=median_trade_size,
        trade_burst_rate=burst_rate,
        median_intertrade_interval_minutes=median_interval if median_interval != 9999.0 else 0.0,
        market_breadth=market_breadth,
        manual_review_value_score=manual_review_value,
        low_analyst_value_flag=bool(bot_score >= 70 and manual_review_value <= 30),
    )


def _trade_burst_rate(trades: list[object]) -> float:
    if not trades:
        return 0.0

    max_count = 1
    left = 0
    for right, trade in enumerate(trades):
        while left < right and (trade.timestamp - trades[left].timestamp).total_seconds() > 15 * 60:
            left += 1
        max_count = max(max_count, right - left + 1)
    return max_count * 4.0


def _binomial_upper_tail(wins: int, total: int, probability: float = 0.5) -> float:
    if total <= 0:
        return 1.0
    wins = max(0, min(wins, total))
    if probability <= 0.0:
        return 1.0 if wins <= 0 else 0.0
    if probability >= 1.0:
        return 1.0

    term = (1.0 - probability) ** total
    tail = 0.0
    odds = probability / (1.0 - probability)
    for observed_wins in range(0, total + 1):
        if observed_wins >= wins:
            tail += term
        if observed_wins < total:
            term *= ((total - observed_wins) / (observed_wins + 1)) * odds
    return min(max(tail, 0.0), 1.0)


def _format_probability(value: float) -> str:
    if value < 0.000001:
        return f"{value:.3e}"
    return f"{value:.6f}"
