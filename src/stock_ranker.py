"""
股票排序模块
Stock Ranking Module

整合数据获取、因子计算和组合优化
"""

import pandas as pd
import logging
import os
import sys
from typing import Tuple
from datetime import datetime

# Use print for progress updates
def log(msg):
    print(msg)
    sys.stdout.flush()

from .data_fetcher import StockDataFetcher
from .factor_calculator import FactorCalculator
from .portfolio_optimizer import PortfolioOptimizer


class StockRanker:
    """
    股票排序器
    整合数据获取、因子计算和组合优化
    """

    def __init__(self):
        self.data_fetcher = StockDataFetcher()
        self.factor_calculator = FactorCalculator()
        self.portfolio_optimizer = PortfolioOptimizer()
        
    def rank_stocks(self,
                   csv_path: str,
                   total_capital: float = 100.0,
                   output_path: str = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        对股票池进行排序和配置
        
        Args:
            csv_path: 股票池CSV文件路径
            total_capital: 总资金
            output_path: 输出文件路径 (默认: results/ranking_result_yyyymmdd_hhmmss.csv)
            
        Returns:
            (排名结果, 配置结果)
        """
        log(f"开始股票排序分析: {csv_path}")
        
        # 生成带时间戳的默认输出路径
        if output_path is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            os.makedirs('results', exist_ok=True)
            output_path = f"results/ranking_result_{timestamp}.csv"
        
        # 1. 加载股票池
        stock_info = pd.read_csv(csv_path, index_col='stock_code')
        stock_codes = stock_info.index.tolist()
        log(f"加载股票数量: {len(stock_codes)}")
        
        # 2. 获取数据
        log("获取股票数据...")
        price_data = self.data_fetcher.get_price_data(stock_codes)
        financial_data = self.data_fetcher.get_financial_data(stock_codes)
        
        # 3. 计算因子得分
        log("计算因子得分...")
        factors = self.factor_calculator.calculate_all_factors(
            price_data, financial_data
        )
        log(f"因子得分计算完成: {len(factors)} 只股票")
        
        # 4. 应用行业调整
        log("应用行业调整系数...")
        factors = self.factor_calculator.apply_industry_adjustment(factors, stock_info)
        
        # 5. 计算综合得分
        log("计算综合得分...")
        composite_score = self.factor_calculator.calculate_composite_score(factors)
        
        # 6. 生成排名结果
        ranking = pd.DataFrame({
            'stock_name': stock_info['stock_name'],
            'sector': stock_info['sector'],
            'sub_sector': stock_info['sub_sector'],
            'ai_exposure': stock_info['ai_exposure'],
            'composite_score': composite_score,
            'momentum_score': factors['momentum_score'],
            'growth_score': factors['growth_score'],
            'valuation_score': factors['valuation_score'],
            'quality_score': factors['quality_score'],
            'volatility_score': factors['volatility_score']
        })
        
        ranking = ranking.sort_values('composite_score', ascending=False)
        ranking['rank'] = range(1, len(ranking) + 1)
        
        # 7. 优化配置
        log("优化资产配置...")
        allocation = self.portfolio_optimizer.optimize_allocation(
            ranking, stock_info, total_capital
        )
        
        # 8. 输出结果
        log(f"保存结果到: {output_path}")
        allocation.to_csv(output_path)
        
        # 汇总信息
        top_stock = ranking.iloc[0]
        log(f"完成! Top 1: {top_stock['stock_name']} ({ranking.index[0]}) - 综合得分: {top_stock['composite_score']:.1f}")
        
        return ranking, allocation
    
    def generate_report(self, 
                       ranking: pd.DataFrame,
                       allocation: pd.DataFrame,
                       stock_info: pd.DataFrame) -> str:
        """
        生成分析报告
        
        Args:
            ranking: 排名结果
            allocation: 配置结果
            stock_info: 股票信息
            
        Returns:
            格式化的报告字符串
        """
        report = []
        report.append("=" * 80)
        report.append("AI产业链股票量化选股报告")
        report.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("=" * 80)
        report.append("")
        
        # 1. 摘要
        report.append("【执行摘要】")
        report.append(f"分析股票数量: {len(ranking)}")
        report.append(f"平均综合得分: {ranking['composite_score'].mean():.2f}")
        report.append(f"得分标准差: {ranking['composite_score'].std():.2f}")
        report.append("")
        
        # 2. 第一梯队
        report.append("【第一梯队 - 核心配置】(Top 10)")
        top10 = ranking.head(10)
        for idx, row in top10.iterrows():
            report.append(f"  {row['rank']:2d}. {row['stock_name']:10s} ({idx}) "
                         f"- 综合得分: {row['composite_score']:.1f} "
                         f"- 动量: {row['momentum_score']:.1f} "
                         f"- 成长: {row['growth_score']:.1f}")
        report.append("")
        
        # 3. 配置建议
        report.append("【配置建议】")
        core_allocation = allocation[allocation['recommendation'] == '核心配置']
        satellite_allocation = allocation[allocation['recommendation'] == '卫星配置']
        
        report.append(f"核心配置 ({len(core_allocation)}支): 建议权重合计 {core_allocation['target_weight'].sum()*100:.1f}%")
        report.append(f"卫星配置 ({len(satellite_allocation)}支): 建议权重合计 {satellite_allocation['target_weight'].sum()*100:.1f}%")
        report.append("")
        
        # 4. 行业分布
        report.append("【行业分布】")
        sector_weights = allocation.groupby('sector')['target_weight'].sum().sort_values(ascending=False)
        for sector, weight in sector_weights.items():
            if weight > 0:
                report.append(f"  {sector}: {weight*100:.1f}%")
        report.append("")
        
        # 5. 风险提示
        report.append("【风险提示】")
        report.append("1. 本报告基于量化模型，存在模型风险")
        report.append("2. AI行业波动较大，需注意仓位控制")
        report.append("3. 建议配合基本面研究进行投资决策")
        report.append("")
        report.append("=" * 80)
        
        return "\n".join(report)
