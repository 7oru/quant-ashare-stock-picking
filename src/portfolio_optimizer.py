"""
组合优化模块
Portfolio Optimization Module

基于因子得分和限制条件进行组合优化
"""

import pandas as pd

from .config import POSITION_LIMITS


class PortfolioOptimizer:
    """
    组合优化器
    基于因子得分和限制条件进行组合优化
    """
    
    def __init__(self):
        self.position_limits = POSITION_LIMITS
        
    def optimize_allocation(self, 
                           ranking: pd.DataFrame,
                           stock_info: pd.DataFrame,
                           total_capital: float = 100.0) -> pd.DataFrame:
        """
        优化资产配置
        
        Args:
            ranking: 排名结果DataFrame
            stock_info: 股票信息
            total_capital: 总资金
            
        Returns:
            包含配置结果的DataFrame
        """
        # 初始化配置结果
        allocation = ranking.copy()
        allocation['target_weight'] = 0.0
        allocation['position_value'] = 0.0
        allocation['shares'] = 0
        
        # 分类配置
        top_stocks = allocation.head(10).copy()  # 第一梯队
        mid_stocks = allocation.iloc[10:25].copy()  # 第二梯队
        other_stocks = allocation.iloc[25:40].copy()  # 第三梯队
        
        # 第一梯队配置（60%），排名越高权重越大，但梯队合计严格归一。
        self._assign_tier_weights(
            allocation,
            top_stocks.index,
            total_weight=0.60,
            rank_tilt=True,
            max_weight=self.position_limits['max_single_stock'],
        )

        # 第二梯队配置（30%），等权卫星配置。
        self._assign_tier_weights(
            allocation,
            mid_stocks.index,
            total_weight=0.30,
            rank_tilt=False,
            max_weight=self.position_limits['max_single_stock'] * 0.5,
        )

        # 第三梯队观察（10%），只配置分数仍高于中性线的股票。
        eligible_other = other_stocks[other_stocks['composite_score'] >= 50].index
        self._assign_tier_weights(
            allocation,
            eligible_other,
            total_weight=0.10,
            rank_tilt=False,
            max_weight=self.position_limits['max_single_stock'] * 0.35,
        )
        
        # 行业集中度检查和调整
        allocation = self._check_sector_limits(allocation, stock_info)
        
        # 计算实际配置金额
        allocation['position_value'] = allocation['target_weight'] * total_capital
        
        # 添加推荐评级
        allocation['recommendation'] = '观察'
        allocation.loc[allocation.index[:10], 'recommendation'] = '核心配置'
        allocation.loc[allocation.index[10:25], 'recommendation'] = '卫星配置'
        allocation.loc[allocation.index[25:40], 'recommendation'] = '观察'
        allocation.loc[allocation.index[40:], 'recommendation'] = '不配置'
        
        return allocation

    def _assign_tier_weights(self,
                             allocation: pd.DataFrame,
                             indexes: pd.Index,
                             total_weight: float,
                             rank_tilt: bool,
                             max_weight: float) -> None:
        """
        给一个梯队分配权重，并确保梯队初始权重合计不超过目标值。
        """
        if len(indexes) == 0 or total_weight <= 0:
            return

        if rank_tilt:
            raw_weights = pd.Series(
                [1 + (len(indexes) - rank - 1) * 0.05 for rank in range(len(indexes))],
                index=indexes,
                dtype='float64',
            )
        else:
            raw_weights = pd.Series(1.0, index=indexes, dtype='float64')

        weights = raw_weights / raw_weights.sum() * total_weight
        allocation.loc[indexes, 'target_weight'] = weights.clip(upper=max_weight)
    
    def _check_sector_limits(self, 
                            allocation: pd.DataFrame,
                            stock_info: pd.DataFrame) -> pd.DataFrame:
        """
        检查并调整行业集中度限制
        
        Args:
            allocation: 配置结果
            stock_info: 股票信息
            
        Returns:
            调整后的配置结果
        """
        # 计算行业权重
        sectors = allocation['sector'].unique()
        
        for sector in sectors:
            sector_stocks = allocation[allocation['sector'] == sector]
            sector_weight = sector_stocks['target_weight'].sum()
            
            if sector_weight > self.position_limits['max_sector']:
                # 需要调整
                excess = sector_weight - self.position_limits['max_sector']
                adjustable = sector_stocks[
                    sector_stocks['target_weight'] > self.position_limits['min_stock_weight']
                ]
                if adjustable.empty:
                    continue

                excess_per_stock = excess / len(adjustable)

                for idx in adjustable.index:
                    if allocation.loc[idx, 'target_weight'] > self.position_limits['min_stock_weight']:
                        allocation.loc[idx, 'target_weight'] = max(
                            allocation.loc[idx, 'target_weight'] - excess_per_stock,
                            self.position_limits['min_stock_weight']
                        )
        
        return allocation
