#!/usr/bin/env python3
"""
Create a folder-based LLM stock-pool research evidence ledger.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.research_ledger import candidates_from_stock_pool, create_research_ledger, load_candidates_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an AI upstream stock research ledger")
    parser.add_argument("--news-window-start", required=True, help="News window start date, YYYY-MM-DD")
    parser.add_argument("--news-window-end", required=True, help="News window end date, YYYY-MM-DD")
    parser.add_argument("--stock-pool", default="ai_stock_pool.csv", help="Stock pool CSV path")
    parser.add_argument("--output-root", default="research_ledgers", help="Base folder for ledger runs")
    parser.add_argument("--timestamp", default=None, help="Optional folder timestamp override")
    parser.add_argument("--title", default="", help="Ledger title")
    parser.add_argument("--notes", default="", help="Free-form notes")
    parser.add_argument(
        "--candidates-json",
        default=None,
        help="Optional JSON file containing candidates or an object with a candidates list",
    )
    parser.add_argument(
        "--empty",
        action="store_true",
        help="Create an empty scaffold ledger instead of defaulting to a stock-pool snapshot",
    )
    args = parser.parse_args()

    if args.candidates_json:
        payload = load_candidates_json(args.candidates_json)
    elif args.empty:
        payload = {"candidates": []}
    else:
        payload = {
            "candidates": candidates_from_stock_pool(args.stock_pool),
            "notes": (
                "No candidates JSON was provided. This ledger was generated from "
                "the current stock pool snapshot; source rows are stock-pool "
                "provenance, not external news evidence."
            ),
        }
    title = args.title or payload.get("title", "")
    notes = args.notes or payload.get("notes", "")

    paths = create_research_ledger(
        news_window_start=args.news_window_start,
        news_window_end=args.news_window_end,
        stock_pool_path=args.stock_pool,
        output_root=args.output_root,
        title=title,
        notes=notes,
        candidates=payload.get("candidates", []),
        timestamp=args.timestamp,
    )

    print("Research ledger created")
    for name, path in paths.items():
        print(f"- {name}: {path}")


if __name__ == "__main__":
    main()
