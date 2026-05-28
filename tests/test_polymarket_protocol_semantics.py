from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import unittest

from app.polymarket_protocol import (
    CLOB_END_CURSOR,
    CLOB_INITIAL_CURSOR,
    LedgerPosition,
    apply_ledger_fill,
    build_market_socket_subscription,
    build_token_condition_map,
    build_user_socket_subscription_shape,
    collect_clob_cursor_pages,
    interpret_order_filled,
    pnl_display,
    stable_order_fill_trade_id,
    token_mapping_for_token_id,
)


ROOT = Path(__file__).resolve().parents[1]


class ClobPaginationSemanticsTests(unittest.TestCase):
    def test_clob_next_cursor_collects_from_initial_cursor_until_end_and_preserves_raw_rows(self) -> None:
        calls: list[str] = []
        raw_row = {"market": "cond-1", "tokens": ["yes-token", "no-token"], "unexpectedField": {"keep": True}}
        pages = {
            CLOB_INITIAL_CURSOR: {"data": [raw_row], "next_cursor": "cursor-2"},
            "cursor-2": {"data": [{"market": "cond-2", "raw": "kept"}], "next_cursor": CLOB_END_CURSOR},
        }

        def fetch_page(cursor: str):
            calls.append(cursor)
            return pages[cursor]

        result = collect_clob_cursor_pages(fetch_page, max_pages=5)

        self.assertEqual(calls, [CLOB_INITIAL_CURSOR, "cursor-2"])
        self.assertEqual(result.stopped_reason, "end_cursor")
        self.assertEqual(result.next_cursor, CLOB_END_CURSOR)
        self.assertEqual(result.rows[0], raw_row)
        self.assertEqual(result.rows[0]["unexpectedField"], {"keep": True})

    def test_clob_pagination_is_bounded_when_endpoint_never_reaches_end_cursor(self) -> None:
        calls: list[str] = []

        def fetch_page(cursor: str):
            calls.append(cursor)
            return {"data": [{"cursor": cursor}], "next_cursor": f"{cursor}-next"}

        result = collect_clob_cursor_pages(fetch_page, max_pages=2)

        self.assertEqual(calls, [CLOB_INITIAL_CURSOR, f"{CLOB_INITIAL_CURSOR}-next"])
        self.assertEqual(result.page_count, 2)
        self.assertEqual(result.stopped_reason, "max_pages_reached")
        self.assertEqual(len(result.rows), 2)

    def test_clob_pagination_stops_on_repeated_cursor_to_avoid_infinite_loop(self) -> None:
        calls: list[str] = []

        def fetch_page(cursor: str):
            calls.append(cursor)
            return {"data": [{"cursor": cursor}], "next_cursor": cursor}

        result = collect_clob_cursor_pages(fetch_page, max_pages=10)

        self.assertEqual(calls, [CLOB_INITIAL_CURSOR])
        self.assertEqual(result.stopped_reason, "repeated_cursor")
        self.assertEqual(result.next_cursor, CLOB_INITIAL_CURSOR)


class SocketPayloadSemanticsTests(unittest.TestCase):
    def test_market_socket_subscription_shape_uses_asset_ids_and_initial_dump_without_auth(self) -> None:
        payload = build_market_socket_subscription(["yes-token", "no-token"])

        self.assertEqual(payload["type"], "market")
        self.assertEqual(payload["assets_ids"], ["yes-token", "no-token"])
        self.assertEqual(payload["initial_dump"], True)
        self.assertEqual(payload["custom_feature_enabled"], True)
        self.assertNotIn("auth", payload)

    def test_user_socket_subscription_shape_is_documented_with_placeholders_not_secrets(self) -> None:
        payload = build_user_socket_subscription_shape(["cond-1", "cond-2"])

        self.assertEqual(payload["type"], "user")
        self.assertEqual(payload["markets"], ["cond-1", "cond-2"])
        self.assertEqual(
            payload["auth"],
            {
                "apiKey": "<api-key>",
                "secret": "<api-secret>",
                "passphrase": "<api-passphrase>",
            },
        )
        self.assertNotIn("assets_ids", payload)


class TokenConditionMappingSemanticsTests(unittest.TestCase):
    def test_token_id_maps_to_condition_id_and_yes_no_tokens_remain_distinct(self) -> None:
        mapping = build_token_condition_map(
            condition_id="cond-123",
            yes_token_id="yes-token",
            no_token_id="no-token",
        )

        yes_mapping = token_mapping_for_token_id("yes-token", mapping)
        no_mapping = token_mapping_for_token_id("no-token", mapping)

        self.assertEqual(yes_mapping.condition_id, "cond-123")
        self.assertEqual(no_mapping.condition_id, "cond-123")
        self.assertEqual(yes_mapping.outcome, "YES")
        self.assertEqual(no_mapping.outcome, "NO")
        self.assertNotEqual(yes_mapping, no_mapping)

    def test_unknown_token_mapping_remains_unknown_instead_of_guessing(self) -> None:
        mapping = build_token_condition_map(
            condition_id="cond-123",
            yes_token_id="yes-token",
            no_token_id="no-token",
        )

        unknown = token_mapping_for_token_id("missing-token", mapping)

        self.assertEqual(unknown.condition_id, "unknown")
        self.assertEqual(unknown.outcome, "unknown")


class OrderFilledInterpretationSemanticsTests(unittest.TestCase):
    def test_maker_asset_zero_interprets_as_buy_with_quote_given_for_base_tokens(self) -> None:
        fill = interpret_order_filled(
            {
                "transactionHash": "0xtx",
                "logIndex": 7,
                "orderHash": "0xorder",
                "makerAssetId": "0",
                "takerAssetId": "yes-token",
                "makerAmountFilled": "40",
                "takerAmountFilled": "100",
                "rawField": "preserved",
            }
        )

        self.assertEqual(fill.side, "BUY")
        self.assertEqual(fill.token_id, "yes-token")
        self.assertEqual(fill.quote_amount, Decimal("40"))
        self.assertEqual(fill.base_amount, Decimal("100"))
        self.assertEqual(fill.price, Decimal("0.4"))
        self.assertEqual(fill.stable_trade_id, "0xtx:7")
        self.assertEqual(fill.raw["rawField"], "preserved")

    def test_nonzero_maker_asset_interprets_as_sell_with_base_given_for_quote(self) -> None:
        fill = interpret_order_filled(
            {
                "transactionHash": "0xtx",
                "orderHash": "0xorder",
                "makerAssetId": "no-token",
                "takerAssetId": "0",
                "makerAmountFilled": "50",
                "takerAmountFilled": "35",
            }
        )

        self.assertEqual(fill.side, "SELL")
        self.assertEqual(fill.token_id, "no-token")
        self.assertEqual(fill.base_amount, Decimal("50"))
        self.assertEqual(fill.quote_amount, Decimal("35"))
        self.assertEqual(fill.price, Decimal("0.7"))
        self.assertEqual(fill.stable_trade_id, "0xtx:0xorder")

    def test_stable_order_fill_trade_id_falls_back_without_guessing_missing_fields(self) -> None:
        self.assertEqual(stable_order_fill_trade_id({"orderHash": "0xorder"}), "0xorder")
        self.assertEqual(stable_order_fill_trade_id({}), "unknown")


class LedgerPrimitiveSemanticsTests(unittest.TestCase):
    def test_weighted_average_entry_updates_on_buy(self) -> None:
        first = apply_ledger_fill(
            LedgerPosition(),
            side="BUY",
            amount=Decimal("100"),
            price=Decimal("0.40"),
        ).position
        second_update = apply_ledger_fill(
            first,
            side="BUY",
            amount=Decimal("50"),
            price=Decimal("0.70"),
        )

        self.assertEqual(second_update.position.amount, Decimal("150"))
        self.assertEqual(second_update.position.avg_price, Decimal("0.50"))
        self.assertEqual(second_update.position.total_bought, Decimal("75.00"))
        self.assertEqual(second_update.realized_pnl_delta, Decimal("0"))

    def test_realized_pnl_updates_on_partial_sell_and_preserves_remaining_amount(self) -> None:
        position = apply_ledger_fill(
            LedgerPosition(),
            side="BUY",
            amount=Decimal("100"),
            price=Decimal("0.40"),
        ).position
        sell = apply_ledger_fill(
            position,
            side="SELL",
            amount=Decimal("25"),
            price=Decimal("0.55"),
        )

        self.assertEqual(sell.adjusted_amount, Decimal("25"))
        self.assertEqual(sell.ignored_amount, Decimal("0"))
        self.assertEqual(sell.realized_pnl_delta, Decimal("3.75"))
        self.assertEqual(sell.position.amount, Decimal("75"))
        self.assertEqual(sell.position.avg_price, Decimal("0.40"))
        self.assertEqual(sell.position.realized_pnl, Decimal("3.75"))

    def test_oversell_caps_adjusted_amount_and_does_not_create_fake_pnl(self) -> None:
        position = apply_ledger_fill(
            LedgerPosition(),
            side="BUY",
            amount=Decimal("100"),
            price=Decimal("0.40"),
        ).position
        sell = apply_ledger_fill(
            position,
            side="SELL",
            amount=Decimal("150"),
            price=Decimal("0.55"),
        )

        self.assertEqual(sell.adjusted_amount, Decimal("100"))
        self.assertEqual(sell.ignored_amount, Decimal("50"))
        self.assertEqual(sell.realized_pnl_delta, Decimal("15.00"))
        self.assertEqual(sell.position.amount, Decimal("0"))
        self.assertEqual(sell.position.avg_price, Decimal("0"))

    def test_sold_out_position_has_zero_remaining_amount(self) -> None:
        position = apply_ledger_fill(
            LedgerPosition(),
            side="BUY",
            amount=Decimal("100"),
            price=Decimal("0.40"),
        ).position
        sell = apply_ledger_fill(
            position,
            side="SELL",
            amount=Decimal("100"),
            price=Decimal("0.50"),
        )

        self.assertEqual(sell.position.amount, Decimal("0"))
        self.assertEqual(sell.position.realized_pnl, Decimal("10.00"))


class PnlDisplaySemanticsTests(unittest.TestCase):
    def test_open_position_uses_unrealized_pnl_when_current_price_and_entry_price_exist(self) -> None:
        position = apply_ledger_fill(
            LedgerPosition(),
            side="BUY",
            amount=Decimal("100"),
            price=Decimal("0.40"),
        ).position

        display = pnl_display(position, current_price=Decimal("0.55"))

        self.assertEqual(display.position_status, "open")
        self.assertEqual(display.source, "unrealized")
        self.assertEqual(display.pnl, Decimal("15.00"))
        self.assertEqual(display.pnl_percent, Decimal("37.500"))

    def test_closed_position_uses_realized_pnl(self) -> None:
        position = apply_ledger_fill(
            LedgerPosition(),
            side="BUY",
            amount=Decimal("100"),
            price=Decimal("0.40"),
        ).position
        closed = apply_ledger_fill(
            position,
            side="SELL",
            amount=Decimal("100"),
            price=Decimal("0.50"),
        ).position

        display = pnl_display(closed, current_price=Decimal("0.20"))

        self.assertEqual(display.position_status, "closed")
        self.assertEqual(display.source, "realized")
        self.assertEqual(display.pnl, Decimal("10.00"))
        self.assertEqual(display.pnl_percent, Decimal("25.00"))

    def test_loss_percent_display_is_capped_at_minus_100_percent(self) -> None:
        display = pnl_display(
            LedgerPosition(
                amount=Decimal("0"),
                avg_price=Decimal("0"),
                realized_pnl=Decimal("-150"),
                total_bought=Decimal("100"),
            )
        )

        self.assertEqual(display.position_status, "closed")
        self.assertEqual(display.source, "realized")
        self.assertEqual(display.pnl_percent, Decimal("-100"))


class ProductionIsolationTests(unittest.TestCase):
    def test_protocol_helper_is_not_imported_by_current_runtime_paths(self) -> None:
        for relative_path in ("app/polymarket.py", "app/scanner.py", "app/event_forensic.py"):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("polymarket_protocol", source)


if __name__ == "__main__":
    unittest.main()
