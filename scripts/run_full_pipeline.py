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
    write_merged_scores,
    write_reconciliation_data,
    write_run_manifest,
    write_training_data,
)
from src.research_ledger import candidates_from_stock_pool, create_research_ledger, load_candidates_json
from src.stock_ranker import StockRanker


def candidate_visible_dates_from_payload(payload: dict, default_visible_date: str) -> dict:
    """
    Treat accepted/watchlist LLM candidates as visible from the research window end.
    Pool snapshot rows are baseline universe members and do not get gated.
    """
    visible_dates = {}
    for candidate in payload.get("candidates", []):
        decision = str(candidate.get("decision", "")).lower()
        if decision in {"", "pool_member", "rejected"}:
            continue
        stock_code = candidate.get("stock_code")
        if not stock_code:
            continue
        visible_dates[str(stock_code)] = (
            candidate.get("as_of_date")
            or candidate.get("visible_date")
            or candidate.get("decision_date")
            or default_visible_date
        )
    return visible_dates


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

    roots = ["results", "audits"]
    run_id = create_run_id(roots, timestamp=args.run_id)
    results_root = Path("results") / run_id
    audits_root = Path("audits") / run_id
    reconciliation_dir = audits_root / "pipeline_reconcilliation"
    raw_output_dir = reconciliation_dir / "raw_outputs"
    training_dir = results_root / "training_data"

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
    candidate_visible_dates = candidate_visible_dates_from_payload(payload, args.news_window_end)
    research_paths = create_research_ledger(
        news_window_start=args.news_window_start,
        news_window_end=args.news_window_end,
        stock_pool_path=args.csv,
        output_root=str(audits_root),
        title=args.title or payload.get("title", ""),
        notes=args.notes or payload.get("notes", ""),
        candidates=payload.get("candidates", []),
        timestamp="llm_research",
    )

    ranker = StockRanker()
    ranking, allocation = ranker.rank_stocks(
        csv_path=args.csv,
        total_capital=args.capital,
        output_path=str(raw_output_dir / "ranking_result.csv"),
        lookback_days=args.lookback_days,
    )
    stock_info = pd.read_csv(args.csv, index_col="stock_code", encoding="utf-8-sig")
    report = ranker.generate_report(ranking, allocation, stock_info.loc[ranking.index.intersection(stock_info.index)])
    (raw_output_dir / "analysis_report.txt").write_text(report, encoding="utf-8")

    backtest_result = BacktestPipeline().run(
        csv_path=args.csv,
        start_date=args.start,
        end_date=args.end,
        initial_capital=args.backtest_capital,
        rebalance=args.rebalance,
        lookback_days=args.lookback_days,
        top_n=args.top_n,
        fee_bps=args.fee_bps,
        output_dir=str(raw_output_dir),
        output_timestamp="backtest",
        candidate_visible_dates=candidate_visible_dates,
    )

    primary_result_paths = write_merged_scores(
        output_dir=results_root,
        ranking=ranking,
        allocation=allocation,
        backtest_result=backtest_result,
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
        raw_output_dir=raw_output_dir,
        primary_result_paths=primary_result_paths,
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
        raw_output_dir=raw_output_dir,
        primary_result_paths=primary_result_paths,
        backtest_paths=backtest_result["paths"],
        training_paths=training_paths,
        reconciliation_paths=reconciliation_paths,
    )

    print("\nFull pipeline complete")
    print(f"run_id: {run_id}")
    print(f"primary result: {primary_result_paths['merged_scores']}")
    print(f"llm research audit: {research_paths['ledger_dir']}")
    print(f"raw outputs: {raw_output_dir}")
    print(f"training data: {training_dir}")
    print(f"pipeline reconciliation: {reconciliation_dir}")
    print(f"manifest: {manifest_path}")


if __name__ == "__main__":
    main()
