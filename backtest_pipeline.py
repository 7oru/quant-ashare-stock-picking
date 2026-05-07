"""
多因子选股回测入口

示例:
python backtest_pipeline.py --csv ai_stock_pool.csv --start 2024-01-01 --end 2025-12-31
"""

import argparse
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
    parser.add_argument("--fee-bps", type=float, default=10.0, help="单边交易成本, bps")
    parser.add_argument("--output-dir", type=str, default="results", help="结果输出目录")
    args = parser.parse_args()

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
        output_dir=args.output_dir,
    )

    print("\n回测完成")
    print(result["summary"].to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    print("\n输出文件:")
    for name, path in result["paths"].items():
        print(f"- {name}: {path}")


if __name__ == "__main__":
    main()
