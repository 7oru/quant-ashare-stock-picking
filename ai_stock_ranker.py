"""
AI产业链股票量化选股系统
Multi-Factor Quantitative Stock Selection System for AI Industry Chain

功能：
1. 自动从CSV加载股票池
2. 获取股票实时行情和财务数据
3. 计算六维度因子得分
4. 应用Z-score标准化
5. 输出综合排名和推荐权重
6. 支持每周自动重排序

使用方法：
python ai_stock_ranker.py --csv ai_stock_pool.csv --output ranking_result.csv --date 2026-01-11

作者：MiniMax Agent
版本：2.0 (Refactored)
"""

import argparse
import sys
import os
import pandas as pd
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)

# Add src to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.stock_ranker import StockRanker


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='AI产业链股票量化选股系统')
    parser.add_argument('--csv', type=str, default='ai_stock_pool.csv',
                       help='股票池CSV文件路径')
    parser.add_argument('--output', type=str, default=None,
                       help='输出文件路径 (默认: results/ranking_result_yyyymmdd_hhmmss.csv)')
    parser.add_argument('--capital', type=float, default=100.0,
                       help='总资金（亿元）')
    parser.add_argument('--report', action='store_true',
                       help='生成详细分析报告')

    args = parser.parse_args()

    # 初始化排序器
    ranker = StockRanker()
    
    # 执行排序
    ranking, allocation = ranker.rank_stocks(
        csv_path=args.csv,
        total_capital=args.capital,
        output_path=args.output
    )
    
    # 生成报告
    if args.report:
        stock_info = pd.read_csv(args.csv, index_col='stock_code')
        report = ranker.generate_report(ranking, allocation, stock_info)
        print(report)
    
    print(f"\n排序完成！")
    print(f"Top 5 股票: {list(ranking.head(5).index)}")
    print(f"建议核心配置权重: {allocation[allocation['recommendation']=='核心配置']['target_weight'].sum()*100:.1f}%")


if __name__ == "__main__":
    main()
