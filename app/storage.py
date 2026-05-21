from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.models import FlaggedCase, WalletInspection


SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    lookback TEXT NOT NULL,
    topic_scope TEXT NOT NULL,
    raw_trade_count INTEGER NOT NULL,
    filtered_trade_count INTEGER NOT NULL,
    flagged_case_count INTEGER NOT NULL,
    report_json_path TEXT NOT NULL,
    report_md_path TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS flagged_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_run_id INTEGER NOT NULL,
    trade_id TEXT NOT NULL,
    market_slug TEXT NOT NULL,
    market_title TEXT NOT NULL,
    wallet_address TEXT NOT NULL,
    side TEXT NOT NULL,
    outcome TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    trade_notional TEXT NOT NULL,
    score INTEGER NOT NULL,
    level TEXT NOT NULL,
    verdict TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    wallet_summary_json TEXT NOT NULL,
    FOREIGN KEY(scan_run_id) REFERENCES scan_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_flagged_cases_scan_run_id ON flagged_cases(scan_run_id);
CREATE INDEX IF NOT EXISTS idx_flagged_cases_wallet ON flagged_cases(wallet_address);
"""


class Storage:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def init(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript(SCHEMA)

    def create_scan_run(
        self,
        *,
        started_at: str,
        lookback: str,
        topic_scope: str,
        raw_trade_count: int,
        filtered_trade_count: int,
        flagged_case_count: int,
        report_json_path: str,
        report_md_path: str,
    ) -> int:
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO scan_runs (
                    started_at, lookback, topic_scope, raw_trade_count,
                    filtered_trade_count, flagged_case_count,
                    report_json_path, report_md_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    started_at,
                    lookback,
                    topic_scope,
                    raw_trade_count,
                    filtered_trade_count,
                    flagged_case_count,
                    report_json_path,
                    report_md_path,
                ),
            )
            return int(cursor.lastrowid)

    def save_flagged_cases(self, scan_run_id: int, cases: list[FlaggedCase]) -> None:
        rows = []
        for case in cases:
            wallet_summary: WalletInspection = case.wallet_inspection
            rows.append(
                (
                    scan_run_id,
                    case.trade.trade_id,
                    case.market.slug,
                    case.market.question,
                    case.trade.wallet,
                    case.trade.side,
                    case.trade.outcome,
                    case.trade.timestamp.isoformat(),
                    str(case.trade.notional),
                    case.suspicion_score,
                    case.severity,
                    case.verdict,
                    json.dumps(case.explanation, ensure_ascii=False),
                    json.dumps(case.raw_metrics, ensure_ascii=False),
                    json.dumps(wallet_summary.to_dict(), ensure_ascii=False),
                )
            )
        with sqlite3.connect(self._db_path) as conn:
            conn.executemany(
                """
                INSERT INTO flagged_cases (
                    scan_run_id, trade_id, market_slug, market_title, wallet_address,
                    side, outcome, timestamp, trade_notional, score, level, verdict,
                    reasons_json, metrics_json, wallet_summary_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
