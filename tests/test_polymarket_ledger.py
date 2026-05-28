from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import unittest

from app.polymarket_ledger import (
    CASH_SOURCE_SIZE_PRICE,
    CASH_SOURCE_UNKNOWN,
    CASH_SOURCE_USDC_SIZE,
    QUALITY_CURRENT_PRICE_UNAVAILABLE,
    QUALITY_MISSING_CASH_FIELD,
    QUALITY_POSITION_RECONCILIATION_MISMATCH,
    QUALITY_SELL_EXCEEDS_TRACKED_HOLDINGS,
    QUALITY_SOURCE_CASH_DISAGREEMENT,
    QUALITY_UNKNOWN_CASH_SOURCE,
    build_position_ledgers,
)


ROOT = Path(__file__).resolve().parents[1]


def trade(
    *,
    wallet: str = "wallet-a",
    condition_id: str = "cond-a",
    token_id: str = "yes-token",
    outcome: str = "YES",
    side: str,
    size: str,
    price: str | None = None,
    usdc_size: str | None = None,
    timestamp: int = 1,
) -> dict[str, object]:
    row: dict[str, object] = {
        "wallet": wallet,
        "condition_id": condition_id,
        "token_id": token_id,
        "outcome": outcome,
        "side": side,
        "size": size,
        "timestamp": timestamp,
    }
    if price is not None:
        row["price"] = price
    if usdc_size is not None:
        row["usdcSize"] = usdc_size
    return row


class PolymarketLedgerTests(unittest.TestCase):
    def test_empty_ledger_has_no_positions_or_notes(self) -> None:
        book = build_position_ledgers([])

        self.assertEqual(book.positions, ())
        self.assertEqual(book.quality_notes, ())

    def test_single_buy_tracks_shares_cash_and_average_entry(self) -> None:
        book = build_position_ledgers(
            [trade(side="BUY", size="100", price="0.40", usdc_size="40")]
        )
        position = book.get(wallet="wallet-a", condition_id="cond-a", token_id="yes-token", outcome="YES")

        self.assertIsNotNone(position)
        assert position is not None
        self.assertEqual(position.total_bought_shares, Decimal("100"))
        self.assertEqual(position.remaining_shares, Decimal("100"))
        self.assertEqual(position.total_buy_cash, Decimal("40"))
        self.assertEqual(position.weighted_average_entry, Decimal("0.4"))
        self.assertEqual(position.realized_pnl, Decimal("0"))
        self.assertIn(QUALITY_CURRENT_PRICE_UNAVAILABLE, position.quality_notes)

    def test_multiple_buys_use_weighted_average_entry(self) -> None:
        book = build_position_ledgers(
            [
                trade(side="BUY", size="100", price="0.40", usdc_size="40", timestamp=1),
                trade(side="BUY", size="50", price="0.70", usdc_size="35", timestamp=2),
            ]
        )
        position = book.get(wallet="wallet-a", condition_id="cond-a", token_id="yes-token", outcome="YES")

        assert position is not None
        self.assertEqual(position.total_bought_shares, Decimal("150"))
        self.assertEqual(position.total_buy_cash, Decimal("75"))
        self.assertEqual(position.remaining_shares, Decimal("150"))
        self.assertEqual(position.weighted_average_entry, Decimal("0.5"))

    def test_partial_sell_realizes_pnl_and_preserves_remaining_shares(self) -> None:
        book = build_position_ledgers(
            [
                trade(side="BUY", size="100", price="0.40", usdc_size="40", timestamp=1),
                trade(side="SELL", size="25", price="0.55", usdc_size="13.75", timestamp=2),
            ]
        )
        position = book.get(wallet="wallet-a", condition_id="cond-a", token_id="yes-token", outcome="YES")

        assert position is not None
        self.assertEqual(position.requested_sold_shares, Decimal("25"))
        self.assertEqual(position.total_sold_shares, Decimal("25"))
        self.assertEqual(position.remaining_shares, Decimal("75"))
        self.assertEqual(position.total_sell_cash, Decimal("13.75"))
        self.assertEqual(position.realized_pnl, Decimal("3.75"))
        self.assertEqual(position.weighted_average_entry, Decimal("0.4"))

    def test_sold_out_position_keeps_realized_pnl_and_zero_remaining_amount(self) -> None:
        book = build_position_ledgers(
            [
                trade(side="BUY", size="100", price="0.40", usdc_size="40", timestamp=1),
                trade(side="SELL", size="100", price="0.50", usdc_size="50", timestamp=2),
            ]
        )
        position = book.get(wallet="wallet-a", condition_id="cond-a", token_id="yes-token", outcome="YES")

        assert position is not None
        self.assertEqual(position.remaining_shares, Decimal("0"))
        self.assertEqual(position.weighted_average_entry, Decimal("0"))
        self.assertEqual(position.realized_pnl, Decimal("10.00"))
        self.assertEqual(position.unrealized_pnl, Decimal("0"))
        self.assertEqual(position.total_pnl, Decimal("10.00"))

    def test_sell_greater_than_tracked_holdings_caps_amount_without_fake_pnl(self) -> None:
        book = build_position_ledgers(
            [
                trade(side="BUY", size="100", price="0.40", usdc_size="40", timestamp=1),
                trade(side="SELL", size="150", price="0.55", usdc_size="82.50", timestamp=2),
            ]
        )
        position = book.get(wallet="wallet-a", condition_id="cond-a", token_id="yes-token", outcome="YES")

        assert position is not None
        self.assertEqual(position.requested_sold_shares, Decimal("150"))
        self.assertEqual(position.total_sold_shares, Decimal("100"))
        self.assertEqual(position.ignored_sell_shares, Decimal("50"))
        self.assertEqual(position.total_sell_cash, Decimal("55.00"))
        self.assertEqual(position.realized_pnl, Decimal("15.00"))
        self.assertIn(QUALITY_SELL_EXCEEDS_TRACKED_HOLDINGS, position.quality_notes)

    def test_current_price_absent_keeps_unrealized_pnl_unknown_for_open_position(self) -> None:
        book = build_position_ledgers(
            [trade(side="BUY", size="100", price="0.40", usdc_size="40")]
        )
        position = book.get(wallet="wallet-a", condition_id="cond-a", token_id="yes-token", outcome="YES")

        assert position is not None
        self.assertIsNone(position.current_price)
        self.assertIsNone(position.unrealized_pnl)
        self.assertIsNone(position.total_pnl)
        self.assertIn(QUALITY_CURRENT_PRICE_UNAVAILABLE, position.quality_notes)

    def test_current_price_present_calculates_unrealized_and_total_pnl(self) -> None:
        book = build_position_ledgers(
            [trade(side="BUY", size="100", price="0.40", usdc_size="40")],
            current_prices={("wallet-a", "cond-a", "yes-token", "YES"): Decimal("0.55")},
        )
        position = book.get(wallet="wallet-a", condition_id="cond-a", token_id="yes-token", outcome="YES")

        assert position is not None
        self.assertEqual(position.current_price, Decimal("0.55"))
        self.assertEqual(position.unrealized_pnl, Decimal("15.00"))
        self.assertEqual(position.total_pnl, Decimal("15.00"))

    def test_usdc_size_is_preferred_over_size_times_price_when_explicitly_present(self) -> None:
        book = build_position_ledgers(
            [trade(side="BUY", size="100", price="0.40", usdc_size="41")]
        )
        position = book.get(wallet="wallet-a", condition_id="cond-a", token_id="yes-token", outcome="YES")

        assert position is not None
        self.assertEqual(position.total_buy_cash, Decimal("41"))
        self.assertEqual(position.weighted_average_entry, Decimal("0.41"))
        self.assertIn(CASH_SOURCE_USDC_SIZE, position.cash_sources)
        self.assertIn(QUALITY_SOURCE_CASH_DISAGREEMENT, position.quality_notes)

    def test_source_cash_disagreement_is_reported_not_hidden(self) -> None:
        book = build_position_ledgers(
            [trade(side="BUY", size="10", price="0.50", usdc_size="5.25")]
        )
        position = book.get(wallet="wallet-a", condition_id="cond-a", token_id="yes-token", outcome="YES")

        assert position is not None
        self.assertEqual(position.source_cash_disagreement_count, 1)
        self.assertIn(QUALITY_SOURCE_CASH_DISAGREEMENT, position.quality_notes)
        self.assertEqual(position.total_buy_cash, Decimal("5.25"))

    def test_missing_cash_source_is_unknown_not_zero_when_price_is_absent(self) -> None:
        book = build_position_ledgers(
            [trade(side="BUY", size="100", price=None, usdc_size=None)]
        )
        position = book.get(wallet="wallet-a", condition_id="cond-a", token_id="yes-token", outcome="YES")

        assert position is not None
        self.assertIsNone(position.total_buy_cash)
        self.assertIsNone(position.weighted_average_entry)
        self.assertIsNone(position.realized_pnl)
        self.assertIn(CASH_SOURCE_UNKNOWN, position.cash_sources)
        self.assertIn(QUALITY_MISSING_CASH_FIELD, position.quality_notes)
        self.assertIn(QUALITY_UNKNOWN_CASH_SOURCE, position.quality_notes)

    def test_size_times_price_fallback_is_distinct_from_usdc_size_source(self) -> None:
        book = build_position_ledgers(
            [trade(side="BUY", size="20", price="0.25", usdc_size=None)]
        )
        position = book.get(wallet="wallet-a", condition_id="cond-a", token_id="yes-token", outcome="YES")

        assert position is not None
        self.assertEqual(position.total_buy_cash, Decimal("5.00"))
        self.assertEqual(position.weighted_average_entry, Decimal("0.25"))
        self.assertIn(CASH_SOURCE_SIZE_PRICE, position.cash_sources)
        self.assertIn(QUALITY_MISSING_CASH_FIELD, position.quality_notes)

    def test_multi_market_wallet_grouping_keeps_condition_ledgers_separate(self) -> None:
        book = build_position_ledgers(
            [
                trade(side="BUY", size="10", price="0.50", usdc_size="5", condition_id="cond-a", token_id="yes-a"),
                trade(side="BUY", size="20", price="0.25", usdc_size="5", condition_id="cond-b", token_id="yes-b"),
            ]
        )

        self.assertEqual(len(book.positions), 2)
        self.assertIsNotNone(book.get(wallet="wallet-a", condition_id="cond-a", token_id="yes-a", outcome="YES"))
        self.assertIsNotNone(book.get(wallet="wallet-a", condition_id="cond-b", token_id="yes-b", outcome="YES"))

    def test_multi_outcome_token_grouping_keeps_yes_no_positions_separate(self) -> None:
        book = build_position_ledgers(
            [
                trade(side="BUY", size="10", price="0.40", usdc_size="4", token_id="yes-token", outcome="YES"),
                trade(side="BUY", size="15", price="0.60", usdc_size="9", token_id="no-token", outcome="NO"),
            ]
        )
        yes = book.get(wallet="wallet-a", condition_id="cond-a", token_id="yes-token", outcome="YES")
        no = book.get(wallet="wallet-a", condition_id="cond-a", token_id="no-token", outcome="NO")

        assert yes is not None
        assert no is not None
        self.assertEqual(yes.remaining_shares, Decimal("10"))
        self.assertEqual(no.remaining_shares, Decimal("15"))
        self.assertNotEqual(yes.key, no.key)

    def test_reconciliation_against_expected_remaining_shares_respects_tolerance(self) -> None:
        rows = [
            trade(side="BUY", size="100", price="0.40", usdc_size="40", timestamp=1),
            trade(side="SELL", size="25", price="0.50", usdc_size="12.50", timestamp=2),
        ]
        within_tolerance = build_position_ledgers(
            rows,
            expected_positions={("wallet-a", "cond-a", "yes-token", "YES"): Decimal("75.0000004")},
        ).get(wallet="wallet-a", condition_id="cond-a", token_id="yes-token", outcome="YES")
        mismatch = build_position_ledgers(
            rows,
            expected_positions={("wallet-a", "cond-a", "yes-token", "YES"): Decimal("74.9")},
        ).get(wallet="wallet-a", condition_id="cond-a", token_id="yes-token", outcome="YES")

        assert within_tolerance is not None
        assert mismatch is not None
        self.assertNotIn(QUALITY_POSITION_RECONCILIATION_MISMATCH, within_tolerance.quality_notes)
        self.assertIn(QUALITY_POSITION_RECONCILIATION_MISMATCH, mismatch.quality_notes)


class ProductionIsolationTests(unittest.TestCase):
    def test_ledger_helper_is_not_imported_by_current_runtime_paths(self) -> None:
        for relative_path in (
            "app/scanner.py",
            "app/archive_scanner.py",
            "app/event_forensic.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("polymarket_ledger", source)


if __name__ == "__main__":
    unittest.main()
