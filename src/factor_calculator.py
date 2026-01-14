"""
因子计算模块
Factor Calculation Module

计算六个维度的因子得分
"""

import pandas as pd
from typing import Dict

from .config import INDUSTRY_ADJUSTMENT


class FactorCalculator:
    """
    因子计算器
    计算六个维度的因子得分
    """
    
    def __init__(self):
        self.factors = {}
        
    def calculate_all_factors(self, 
                             price_data: Dict[str, Dict],
                             financial_data: Dict[str, Dict]) -> pd.DataFrame:
        """
        计算所有因子得分
        
        Args:
            price_data: 价格数据
            financial_data: 财务数据
            
        Returns:
            包含所有因子得分的DataFrame
        """
        stocks = list(price_data.keys())
        
        # 初始化因子DataFrame
        factors = pd.DataFrame(index=stocks)
        
        # 1. 动量因子得分
        # 优先使用实时行情的收益率数据，否则使用历史数据计算
        momentum_20d = []
        momentum_60d = []
        macd_signals = []
        rsi_values = []
        stoch_values = []
        
        for s in stocks:
            # 优先使用financial_data中的实时收益率
            ret_60d = financial_data[s].get('returns_60d') if s in financial_data else None
            ret_5d = financial_data[s].get('returns_5d') if s in financial_data else None
            
            if ret_60d is not None:
                momentum_60d.append(ret_60d)
                # 如果没有20日数据，使用5日数据推算或60日数据估算
                if ret_5d is not None:
                    momentum_20d.append(ret_5d * 4)  # 近似20日收益
                else:
                    momentum_20d.append(ret_60d * 0.33)  # 使用60日的1/3作为近似
            else:
                # 使用历史数据计算
                momentum_20d.append(price_data[s].get('returns_20d', 0))
                momentum_60d.append(price_data[s].get('returns_60d', 0))
            
            # 提取技术指标
            macd_hist = price_data[s].get('macd_histogram', 0)
            macd_signals.append(macd_hist)
            rsi_values.append(price_data[s].get('rsi', 50))
            stoch_k = price_data[s].get('stoch_k', 50)
            stoch_d = price_data[s].get('stoch_d', 50)
            stoch_values.append((stoch_k + stoch_d) / 2)
        
        factors['momentum_20d'] = momentum_20d
        factors['momentum_60d'] = momentum_60d
        factors['ma_distance'] = [(price_data[s]['current_price'] / price_data[s]['ma60'] - 1) * 100 
                                   for s in stocks]
        factors['macd_signal'] = macd_signals
        factors['rsi'] = rsi_values
        factors['stoch'] = stoch_values
        
        # 增强动量得分：结合收益率、MACD、RSI、Stochastic
        factors['momentum_score'] = (
            0.3 * self._normalize(factors['momentum_20d']) +
            0.3 * self._normalize(factors['momentum_60d']) +
            0.15 * self._normalize(factors['ma_distance']) +
            0.15 * self._normalize(factors['macd_signal']) +
            0.1 * self._normalize(factors['rsi'])
        )
        
        # 2. 成长因子得分
        # 如果财务数据中没有成长数据，使用收益率作为代理
        revenue_growth = []
        profit_growth = []
        for s in stocks:
            rev_growth = financial_data[s].get('revenue_growth_yoy')
            prof_growth = financial_data[s].get('net_profit_growth_yoy')
            
            # 如果没有财务成长数据，使用YTD收益率作为代理
            if rev_growth is None and s in financial_data:
                ytd_return = financial_data[s].get('returns_ytd')
                if ytd_return is not None:
                    rev_growth = ytd_return * 0.8  # 假设营收增长约为股价增长的80%
                    prof_growth = ytd_return * 1.2  # 假设利润增长约为股价增长的120%
                else:
                    rev_growth = 0
                    prof_growth = 0
            elif rev_growth is None:
                rev_growth = 0
            if prof_growth is None:
                prof_growth = 0
            
            revenue_growth.append(rev_growth)
            profit_growth.append(prof_growth)
        
        factors['revenue_growth'] = revenue_growth
        factors['profit_growth'] = profit_growth
        
        # 如果所有成长数据都为0，则使用动量因子作为代理
        if all(x == 0 for x in revenue_growth) and all(x == 0 for x in profit_growth):
            factors['growth_score'] = factors['momentum_score'] * 0.8
        else:
            factors['growth_score'] = (
                0.5 * self._normalize(factors['revenue_growth']) +
                0.5 * self._normalize(factors['profit_growth'])
            )
        
        # 3. 估值因子得分（估值越低得分越高）
        # 使用实际数据，缺失时使用中位数填充
        pe_values = [financial_data[s].get('pe_ttm') for s in stocks]
        pb_values = [financial_data[s].get('pb') for s in stocks]
        ps_values = [financial_data[s].get('ps') for s in stocks]
        
        # 计算有效值的中位数作为默认值
        pe_valid = [v for v in pe_values if v is not None]
        pb_valid = [v for v in pb_values if v is not None]
        ps_valid = [v for v in ps_values if v is not None]
        
        pe_default = pd.Series(pe_valid).median() if pe_valid else 50.0
        pb_default = pd.Series(pb_valid).median() if pb_valid else 3.0
        ps_default = pd.Series(ps_valid).median() if ps_valid else 0.0
        
        factors['pe'] = [v if v is not None else pe_default for v in pe_values]
        factors['pb'] = [v if v is not None else pb_default for v in pb_values]
        factors['ps'] = [v if v is not None else ps_default for v in ps_values]
        
        # 计算PEG（如果可用），否则使用PE/PB组合
        peg_values = []
        for s in stocks:
            peg = financial_data[s].get('peg')
            if peg is None and factors.loc[s, 'profit_growth'] != 0:
                # 估算PEG = PE / 利润增长率
                pe_val = factors.loc[s, 'pe']
                prof_growth = abs(factors.loc[s, 'profit_growth'])
                if prof_growth > 0:
                    peg = pe_val / prof_growth
                else:
                    peg = None
            if peg is not None and (peg <= 0 or peg > 10):
                peg = None
            peg_values.append(peg if peg is not None else 0)
        factors['peg'] = peg_values
        
        # 估值得分：使用PE和PB，如果有PS也加入
        if any(factors['ps'] > 0):
            factors['valuation_score'] = (
                0.3 * (1 - self._normalize(factors['pe'])) +
                0.3 * (1 - self._normalize(factors['pb'])) +
                0.2 * (1 - self._normalize(factors['ps'])) +
                0.2 * (1 - self._normalize(factors['peg']))
            )
        else:
            factors['valuation_score'] = (
                0.4 * (1 - self._normalize(factors['pe'])) +
                0.4 * (1 - self._normalize(factors['pb'])) +
                0.2 * (1 - self._normalize(factors['peg']))
            )
        
        # 4. 波动率因子得分（波动率越低得分越高）- 先计算，因为质量因子可能需要用到
        factors['volatility'] = [price_data[s].get('volatility', 0.3) for s in stocks]
        factors['max_dd'] = [price_data[s].get('max_drawdown', 20) for s in stocks]
        factors['atr_percent'] = [price_data[s].get('atr_percent', 0) for s in stocks]
        factors['bb_width'] = [price_data[s].get('bb_width', 0) for s in stocks]
        
        # 如果有振幅数据，也加入波动率计算
        amplitude_values = [financial_data[s].get('amplitude') if financial_data[s].get('amplitude') is not None else 0 for s in stocks]
        
        # 增强波动率得分：结合波动率、最大回撤、ATR、布林带宽度、振幅
        volatility_components = []
        weights = []
        
        volatility_components.append(1 - self._normalize(factors['volatility']))
        weights.append(0.25)
        
        volatility_components.append(1 - self._normalize(factors['max_dd']))
        weights.append(0.25)
        
        if any(x > 0 for x in factors['atr_percent']):
            volatility_components.append(1 - self._normalize(factors['atr_percent']))
            weights.append(0.15)
        
        if any(x > 0 for x in factors['bb_width']):
            volatility_components.append(1 - self._normalize(factors['bb_width']))
            weights.append(0.15)
        
        if any(x > 0 for x in amplitude_values):
            factors['amplitude'] = amplitude_values
            volatility_components.append(1 - self._normalize(factors['amplitude']))
            weights.append(0.2)
        else:
            weights = [w * (1.0 / sum(weights)) for w in weights]  # 归一化权重
        
        factors['volatility_score'] = sum(w * comp for w, comp in zip(weights, volatility_components))
        
        # 5. 质量因子得分
        # 如果财务质量数据不可用，使用技术指标作为代理
        roe_values = [financial_data[s].get('roe') for s in stocks]
        gross_margin_values = [financial_data[s].get('gross_margin') for s in stocks]
        cash_quality_values = [financial_data[s].get('cash_flow_to_net_profit') for s in stocks]
        
        factors['roe'] = roe_values
        factors['gross_margin'] = gross_margin_values
        factors['cash_quality'] = cash_quality_values
        
        # 如果质量数据都不可用，使用估值和波动率的组合作为代理
        if all(x is None or x == 0 for x in roe_values) and all(x is None or x == 0 for x in gross_margin_values):
            # 使用低估值和低波动率作为质量代理
            factors['quality_score'] = (
                0.6 * factors['valuation_score'] +
                0.4 * factors['volatility_score']
            )
        else:
            # 只使用有数据的因子
            quality_components = []
            weights = []
            if any(x is not None and x != 0 for x in roe_values):
                # 将None值替换为0用于计算
                roe_series = pd.Series([x if x is not None else 0 for x in roe_values], index=stocks)
                factors['roe'] = roe_series
                quality_components.append(self._normalize(roe_series))
                weights.append(0.4)
            if any(x is not None and x != 0 for x in gross_margin_values):
                gross_margin_series = pd.Series([x if x is not None else 0 for x in gross_margin_values], index=stocks)
                factors['gross_margin'] = gross_margin_series
                quality_components.append(self._normalize(gross_margin_series))
                weights.append(0.3)
            if any(x is not None and x != 0 for x in cash_quality_values):
                cash_quality_series = pd.Series([x if x is not None else 0 for x in cash_quality_values], index=stocks)
                factors['cash_quality'] = cash_quality_series
                quality_components.append(self._normalize(cash_quality_series))
                weights.append(0.3)
            
            if quality_components:
                # 归一化权重
                total_weight = sum(weights)
                weights = [w / total_weight for w in weights]
                factors['quality_score'] = sum(w * comp for w, comp in zip(weights, quality_components))
            else:
                factors['quality_score'] = pd.Series([50] * len(stocks), index=stocks)
        
        self.factors = factors
        return factors
    
    def _normalize(self, series: pd.Series) -> pd.Series:
        """
        Z-score标准化
        
        Args:
            series: 待标准化的Series
            
        Returns:
            标准化后的Series，范围0-100
        """
        mean = series.mean()
        std = series.std()
        
        if std == 0:
            return pd.Series([50] * len(series), index=series.index)
        
        normalized = (series - mean) / std * 10 + 50
        return normalized.clip(0, 100)
    
    def apply_industry_adjustment(self, 
                                  factors: pd.DataFrame,
                                  stock_info: pd.DataFrame) -> pd.DataFrame:
        """
        应用行业调整系数
        
        Args:
            factors: 因子得分DataFrame
            stock_info: 股票信息DataFrame
            
        Returns:
            调整后的因子得分
        """
        adjusted = factors.copy()
        
        for idx in adjusted.index:
            sector = stock_info.loc[idx, 'sector'] if idx in stock_info.index else None
            
            if sector in INDUSTRY_ADJUSTMENT:
                adj = INDUSTRY_ADJUSTMENT[sector]
                for factor in ['valuation', 'growth', 'quality']:
                    if factor + '_score' in adjusted.columns:
                        adjusted.loc[idx, factor + '_score'] *= adj.get(factor, 1.0)
        
        # 重新标准化
        for col in ['valuation_score', 'growth_score', 'quality_score']:
            if col in adjusted.columns:
                adjusted[col] = self._normalize(adjusted[col])
        
        return adjusted
    
    def calculate_composite_score(self, factors: pd.DataFrame) -> pd.Series:
        """
        计算综合得分
        
        Args:
            factors: 因子得分DataFrame
            
        Returns:
            综合得分Series
        """
        from .config import FACTOR_WEIGHTS
        
        composite = (
            FACTOR_WEIGHTS['momentum'] * factors['momentum_score'] +
            FACTOR_WEIGHTS['growth'] * factors['growth_score'] +
            FACTOR_WEIGHTS['valuation'] * factors['valuation_score'] +
            FACTOR_WEIGHTS['quality'] * factors['quality_score'] +
            FACTOR_WEIGHTS['volatility'] * factors['volatility_score']
        )
        
        return composite.clip(0, 100)
