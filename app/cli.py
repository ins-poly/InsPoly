from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import AppConfig
from app.polymarket import PolymarketClient
from app.scanner import Scanner, inspect_wallet
from app.site_categories import SiteCategory
from app.storage import Storage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app", description="InsPoly batch-first scanner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Scan recent Polymarket categories")
    scan_parser.add_argument("--lookback", default="4h", help="Example: 4h, 12h, 1d")
    scan_parser.add_argument(
        "--categories",
        default="Politics,World,Ukraine,Middle East",
        help="Comma-separated Polymarket site categories",
    )

    wallet_parser = subparsers.add_parser("inspect-wallet", help="Inspect a wallet")
    wallet_parser.add_argument("--address", required=True, help="Wallet address")

    subparsers.add_parser("desktop", help="Launch the local desktop app")
    subparsers.add_parser("archive-desktop", help="Launch InsPoly Archive Researcher")
    subparsers.add_parser("event-desktop", help="Launch InsPoly Event Forensic Analyzer")
    subparsers.add_parser("macos-app", help="Launch the native macOS wrapper")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    config = AppConfig.load()
    config.ensure_dirs()

    storage = Storage(config.db_path)
    storage.init()
    client = PolymarketClient()

    if args.command == "scan":
        categories = _resolve_categories(client, args.categories)
        return _run_scan(args.lookback, categories, client, storage, config.reports_dir)
    if args.command == "inspect-wallet":
        return _run_inspect_wallet(args.address, client)
    if args.command == "desktop":
        from app.browser_desktop import launch_browser_desktop_app

        launch_browser_desktop_app()
        return 0
    if args.command == "archive-desktop":
        from app.browser_desktop import launch_archive_research_browser_app

        launch_archive_research_browser_app()
        return 0
    if args.command == "event-desktop":
        from app.event_forensic_desktop import launch_event_forensic_browser_app

        launch_event_forensic_browser_app()
        return 0
    if args.command == "macos-app":
        from app.macos_launcher import launch_native_macos_app

        launch_native_macos_app()
        return 0

    parser.error("Unknown command")
    return 2


def _resolve_categories(client: PolymarketClient, raw: str) -> tuple[SiteCategory, ...]:
    available = client.fetch_site_categories()
    by_label = {item.label: item for item in available}
    selected = tuple(by_label[item.strip()] for item in raw.split(",") if item.strip() in by_label)
    if not selected:
        raise SystemExit("Не вдалося зіставити жодну категорію Polymarket.")
    return selected


def _run_scan(
    lookback: str,
    categories: tuple[SiteCategory, ...],
    client: PolymarketClient,
    storage: Storage,
    reports_dir: Path,
) -> int:
    config = AppConfig.load()
    scanner = Scanner(client, storage, config)
    report = scanner.scan(lookback, reports_dir, selected_categories=categories)

    print(f"Scan run id: {report['scan_run_id']}")
    print(f"Lookback: {report['lookback']}")
    print(f"Categories: {report['topic_scope']}")
    print(f"Recent trades checked: {report['raw_trade_count']}")
    print(f"Focus-category trades after filter: {report['filtered_trade_count']}")
    print(f"Candidate trades after size pre-filter: {report['candidate_trade_count']}")
    print(f"Flagged cases: {report['flagged_case_count']}")
    print(f"JSON report: {report['report_json_path']}")
    print(f"Markdown report: {report['report_md_path']}")
    print(f"Text output: {report['report_txt_path']}")
    print()

    cases = report["cases"]
    if not cases:
        print("Підозрілих кейсів у цьому вікні не знайдено.")
        return 0

    for case in cases[:20]:
        trade = case["trade"]
        print(f"[{case['severity']}] {trade['wallet']} flagged on \"{trade['title']}\"")
        print(f"Time: {trade['timestamp']}")
        print(f"Side: {trade['side']} {trade['outcome']}")
        print(f"Trade size: ${case['raw_metrics']['trade_notional_usdc']}")
        print(f"Score: {case['suspicion_score']}/100")
        print("Reasons:")
        for reason in case["explanation"]:
            print(f"- {reason}")
        print(f"Verdict: {case['verdict']}")
        print()
    return 0


def _run_inspect_wallet(address: str, client: PolymarketClient) -> int:
    categories = tuple(client.fetch_site_categories()[:4])
    focus_markets = client.fetch_focus_markets(selected_categories=categories)
    inspection = inspect_wallet(client, address, focus_markets)
    print(json.dumps(inspection.to_dict(), ensure_ascii=False, indent=2))
    return 0
