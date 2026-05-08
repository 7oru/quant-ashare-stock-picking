#!/usr/bin/env python3
"""
Run the full stock-picking loop and persist all run artifacts.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.backtester import BacktestPipeline
from src.pipeline_artifacts import (
    create_run_id,
    write_reconciliation_data,
    write_run_manifest,
    write_training_data,
)
from src.research_ledger import candidates_from_stock_pool, create_research_ledger, load_candidates_json
from src.stock_ranker import StockRanker


def main() -> None:
    today = date.today()
    default_end = today.strftime("%Y-%m-%d")
    default_start = (today - timedelta(days=120)).strftime("%Y-%m-%d")
    default_news_start = (today - timedelta(days=6)).strftime("%Y-%m-%d")

    parser = argparse.ArgumentParser(description="Run LLM research ledger, ranking, training, reconciliation, and backtest artifacts")
    parser.add_argument("--csv", default="ai_stock_pool.csv", help="Stock pool CSV path")
    parser.add_argument("--run-id", default=None, help="Optional run id. Defaults to current timestamp")
    parser.add_argument("--news-window-start", default=default_news_start, help="News window start date")
    parser.add_argument("--news-window-end", default=default_end, help="News window end date")
    parser.add_argument("--candidates-json", default=None, help="Optional JSON evidence payload for the research ledger")
    parser.add_argument("--title", default="AI upstream full pipeline", help="Research ledger title")
    parser.add_argument("--notes", default="", help="Research ledger notes")
    parser.add_argument("--capital", type=float, default=100.0, help="Ranking capital")
    parser.add_argument("--backtest-capital", type=float, default=1_000_000.0, help="Backtest initial capital")
    parser.add_argument("--start", default=default_start, help="Backtest start date")
    parser.add_argument("--end", default=default_end, help="Backtest end date")
    parser.add_argument("--rebalance", default="monthly", choices=["weekly", "monthly", "quarterly"], help="Backtest rebalance frequency")
    parser.add_argument("--lookback-days", type=int, default=60, help="Ranking and backtest lookback window")
    parser.add_argument("--top-n", type=int, default=10, help="Backtest holdings count")
    parser.add_argument("--fee-bps", type=float, default=10.0, help="Backtest one-way fee in bps")
    parser.add_argument("--spot-timeout-seconds", type=int, default=30, help="Ranking spot-data timeout")
    args = parser.parse_args()

    os.environ["QUANT_SPOT_TIMEOUT_SECONDS"] = str(args.spot_timeout_seconds)

    roots = ["research_ledgers", "results", "training_data", "reconciliation"]
    run_id = create_run_id(roots, timestamp=args.run_id)
    results_root = Path("results") / run_id
    ranking_dir = results_root / "ranking"
    backtest_root = results_root
    training_dir = Path("training_data") / run_id
    reconciliation_dir = Path("reconciliation") / run_id

    if args.candidates_json:
        payload = load_candidates_json(args.candidates_json)
    else:
        payload = {
            "candidates": candidates_from_stock_pool(args.csv),
            "notes": (
                "No candidates JSON was provided. This ledger was generated from "
                "the current stock pool snapshot; source rows are stock-pool "
                "provenance, not external news evidence."
            ),
        }
    research_paths = create_research_ledger(
        news_window_start=args.news_window_start,
        news_window_end=args.news_window_end,
        stock_pool_path=args.csv,
        output_root="research_ledgers",
        title=args.title or payload.get("title", ""),
        notes=args.notes or payload.get("notes", ""),
        candidates=payload.get("candidates", []),
        timestamp=run_id,
    )

    ranker = StockRanker()
    ranking, allocation = ranker.rank_stocks(
        csv_path=args.csv,
        total_capital=args.capital,
        output_path=str(ranking_dir / "ranking_result.csv"),
        lookback_days=args.lookback_days,
    )
    stock_info = pd.read_csv(args.csv, index_col="stock_code", encoding="utf-8-sig")
    report = ranker.generate_report(ranking, allocation, stock_info.loc[ranking.index.intersection(stock_info.index)])
    (ranking_dir / "analysis_report.txt").write_text(report, encoding="utf-8")

    backtest_result = BacktestPipeline().run(
        csv_path=args.csv,
        start_date=args.start,
        end_date=args.end,
        initial_capital=args.backtest_capital,
        rebalance=args.rebalance,
        lookback_days=args.lookback_days,
        top_n=args.top_n,
        fee_bps=args.fee_bps,
        output_dir=str(backtest_root),
        output_timestamp="backtest",
    )

    training_paths = write_training_data(
        output_dir=training_dir,
        csv_path=args.csv,
        ranking=ranking,
        allocation=allocation,
        backtest_result=backtest_result,
        run_id=run_id,
    )
    reconciliation_paths = write_reconciliation_data(
        output_dir=reconciliation_dir,
        csv_path=args.csv,
        run_id=run_id,
        research_paths=research_paths,
        ranking_dir=ranking_dir,
        backtest_paths=backtest_result["paths"],
        training_paths=training_paths,
        ranking=ranking,
        allocation=allocation,
        backtest_result=backtest_result,
    )
    manifest_path = write_run_manifest(
        output_path=results_root / "run_manifest.json",
        run_id=run_id,
        csv_path=args.csv,
        research_paths=research_paths,
        ranking_dir=ranking_dir,
        backtest_paths=backtest_result["paths"],
        training_paths=training_paths,
        reconciliation_paths=reconciliation_paths,
    )

    print("\nFull pipeline complete")
    print(f"run_id: {run_id}")
    print(f"research ledger: {research_paths['ledger_dir']}")
    print(f"ranking: {ranking_dir}")
    print(f"backtest: {backtest_result['output_dir']}")
    print(f"training data: {training_dir}")
    print(f"reconciliation: {reconciliation_dir}")
    print(f"manifest: {manifest_path}")


if __name__ == "__main__":
    main()
