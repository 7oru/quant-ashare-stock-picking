"""
多因子选股回测入口

示例:
python backtest_pipeline.py --csv ai_stock_pool.csv --start 2024-01-01 --end 2025-12-31
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.backtester import BacktestPipeline


def main():
    parser = argparse.ArgumentParser(description="AI产业链多因子选股回测")
    parser.add_argument("--csv", type=str, default="ai_stock_pool.csv", help="股票池CSV文件路径")
    parser.add_argument("--start", type=str, required=True, help="回测开始日期, 如 2024-01-01")
    parser.add_argument("--end", type=str, required=True, help="回测结束日期, 如 2025-12-31")
    parser.add_argument("--capital", type=float, default=1_000_000.0, help="初始资金")
    parser.add_argument(
        "--rebalance",
        type=str,
        default="monthly",
        choices=["weekly", "monthly", "quarterly"],
        help="调仓频率",
    )
    parser.add_argument("--lookback-days", type=int, default=180, help="每次调仓使用的历史交易日窗口")
    parser.add_argument("--top-n", type=int, default=10, help="每次持仓股票数量")
    parser.add_argument("--fee-bps", type=float, default=10.0, help="佣金成本, bps；为兼容旧参数名保留")
    parser.add_argument("--stamp-tax-bps", type=float, default=5.0, help="卖出印花税, bps")
    parser.add_argument("--transfer-fee-bps", type=float, default=0.1, help="买卖双边过户费, bps")
    parser.add_argument("--slippage-bps", type=float, default=5.0, help="买卖双边滑点, bps")
    parser.add_argument("--impact-bps", type=float, default=0.0, help="买卖双边冲击成本, bps")
    parser.add_argument("--max-participation-rate", type=float, default=0.10, help="单票单日最大成交额参与率")
    parser.add_argument("--max-drawdown-budget", type=float, default=None, help="组合回撤预算，触发后降低目标总仓位")
    parser.add_argument("--min-listing-days", type=int, default=60, help="上市未满该自然日数的股票不参与调仓买入")
    parser.add_argument("--output-dir", type=str, default="results", help="基础输出目录，每次运行会创建 <timestamp> 子目录")
    parser.add_argument(
        "--candidate-visible-dates-json",
        type=str,
        default=None,
        help="可选 JSON 文件，内容为 {stock_code: YYYY-MM-DD}，用于限制 LLM 新候选的历史可见日期",
    )
    args = parser.parse_args()

    candidate_visible_dates = None
    if args.candidate_visible_dates_json:
        with open(args.candidate_visible_dates_json, "r", encoding="utf-8") as handle:
            candidate_visible_dates = json.load(handle)

    pipeline = BacktestPipeline()
    result = pipeline.run(
        csv_path=args.csv,
        start_date=args.start,
        end_date=args.end,
        initial_capital=args.capital,
        rebalance=args.rebalance,
        lookback_days=args.lookback_days,
        top_n=args.top_n,
        fee_bps=args.fee_bps,
        stamp_tax_bps=args.stamp_tax_bps,
        transfer_fee_bps=args.transfer_fee_bps,
        slippage_bps=args.slippage_bps,
        impact_bps=args.impact_bps,
        max_participation_rate=args.max_participation_rate,
        max_drawdown_budget=args.max_drawdown_budget,
        output_dir=args.output_dir,
        candidate_visible_dates=candidate_visible_dates,
        min_listing_days=args.min_listing_days,
    )

    print("\n回测完成")
    print(result["summary"].to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    print(f"\n输出目录: {result['output_dir']}")
    print("\n输出文件:")
    for name, path in result["paths"].items():
        print(f"- {name}: {path}")


if __name__ == "__main__":
    main()
