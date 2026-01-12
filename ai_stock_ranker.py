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
版本：1.0
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
import argparse
import logging
from typing import Tuple, Dict, List
import os
import sys

warnings.filterwarnings('ignore')

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 因子权重配置
FACTOR_WEIGHTS = {
    'momentum': 0.25,      # 动量因子权重
    'growth': 0.25,        # 成长因子权重
    'valuation': 0.18,     # 估值因子权重
    'quality': 0.18,       # 质量因子权重
    'volatility': 0.14     # 波动率因子权重
}

# 行业调整系数（不同行业的因子需要调整）
INDUSTRY_ADJUSTMENT = {
    '上游-算力基础设施': {'valuation': 1.0, 'growth': 1.0, 'quality': 1.0},
    '上游-液冷技术': {'valuation': 1.0, 'growth': 1.1, 'quality': 1.0},
    '上游-电力设备': {'valuation': 0.9, 'growth': 0.9, 'quality': 1.1},
    '中游-芯片': {'valuation': 1.2, 'growth': 1.2, 'quality': 0.9},
    '中游-光模块': {'valuation': 1.0, 'growth': 1.1, 'quality': 1.0},
    '中游-数据平台': {'valuation': 0.9, 'growth': 1.0, 'quality': 1.0},
    '中游-大模型': {'valuation': 1.3, 'growth': 1.3, 'quality': 0.8},
    '下游-智能驾驶': {'valuation': 1.0, 'growth': 1.1, 'quality': 1.0},
    '下游-AI办公': {'valuation': 1.0, 'growth': 1.1, 'quality': 1.0},
    '下游-AI金融': {'valuation': 0.9, 'growth': 1.0, 'quality': 1.1},
    '数据中心基础设施': {'valuation': 0.85, 'growth': 0.9, 'quality': 1.1},
    '电力设备': {'valuation': 0.85, 'growth': 0.85, 'quality': 1.1},
    '液冷技术': {'valuation': 1.0, 'growth': 1.1, 'quality': 1.0},
    '智能机器人': {'valuation': 1.1, 'growth': 1.2, 'quality': 0.95},
    'AI应用软件': {'valuation': 1.0, 'growth': 1.0, 'quality': 1.0}
}

# 单票和行业配置限制
POSITION_LIMITS = {
    'max_single_stock': 0.15,      # 单票最大仓位15%
    'max_sector': 0.30,            # 单行业最大仓位30%
    'max_sub_sector': 0.25,        # 单一子行业最大仓位25%
    'min_stock_weight': 0.02,      # 最小入选仓位2%
    'min_rank_for_position': 40    # 排名40名以后不配置
}


class StockDataFetcher:
    """
    股票数据获取器
    从akshare获取真实股票数据
    """

    def __init__(self):
        """
        初始化数据获取器
        使用akshare获取真实市场数据
        """
        self.cache = {}
        
    def get_price_data(self, stock_codes: List[str],
                       lookback_days: int = 90) -> Dict[str, Dict]:
        """
        获取股票价格数据

        Args:
            stock_codes: 股票代码列表
            lookback_days: 回溯天数

        Returns:
            字典格式的股票价格数据
        """
        return self._get_real_price_data(stock_codes, lookback_days)
    
    
    def _get_real_price_data(self, stock_codes: List[str], 
                             lookback_days: int) -> Dict[str, Dict]:
        """
        从AkShare获取真实价格数据
        
        AkShare是完全开源免费的财经数据接口
        """
        try:
            import akshare as ak
            import pandas as pd
            import numpy as np
            from datetime import datetime, timedelta
            
            price_data = {}
            
            for code in stock_codes:
                # 转换股票代码格式 (000977.SZ -> 000977)
                ts_code = code.replace('.SZ', '').replace('.SH', '')
                market = 'sz' if code.endswith('.SZ') else 'sh'
                
                try:
                    # 获取日线数据
                    df = ak.stock_zh_a_hist(
                        symbol=ts_code,
                        period="daily",
                        start_date=(datetime.now() - timedelta(days=lookback_days)).strftime('%Y%m%d'),
                        end_date=datetime.now().strftime('%Y%m%d'),
                        adjust="qfq"
                    )
                    
                    if df is not None and len(df) > 0:
                        df = df.sort_values('日期')
                        prices = df['收盘'].values
                        dates = df['日期'].values
                        
                        # 计算技术指标
                        ma20 = pd.Series(prices[-20:]).mean() if len(prices) >= 20 else prices[-1]
                        ma60 = pd.Series(prices[-60:]).mean() if len(prices) >= 60 else ma20
                        
                        # 计算RSI (14日)
                        delta = np.diff(prices)
                        gain = np.where(delta > 0, delta, 0)
                        loss = np.where(delta < 0, -delta, 0)
                        avg_gain = np.mean(gain[-14:]) if len(gain) >= 14 else np.mean(gain)
                        avg_loss = np.mean(loss[-14:]) if len(loss) >= 14 else np.mean(loss)
                        rsi = 100 * (avg_gain / (avg_gain + avg_loss)) if (avg_gain + avg_loss) > 0 else 50
                        
                        # 计算最大回撤
                        peak = np.maximum.accumulate(prices)
                        drawdown = (prices - peak) / peak
                        max_drawdown = abs(np.min(drawdown)) * 100
                        
                        # 计算波动率
                        volatility = np.std(prices[-90:]) / np.mean(prices[-90:]) * np.sqrt(252) if len(prices) >= 90 else 0.3
                        
                        price_data[code] = {
                            'current_price': prices[-1],
                            'prices_90d': prices,
                            'ma20': ma20,
                            'ma60': ma60,
                            'rsi': min(rsi, 100),
                            'volatility': volatility,
                            'max_drawdown': max_drawdown,
                            'returns_20d': (prices[-1] - prices[-20]) / prices[-20] * 100 if len(prices) >= 20 else 0,
                            'returns_60d': (prices[-1] - prices[-60]) / prices[-60] * 100 if len(prices) >= 60 else 0,
                            'turnover_rate': df['换手率'].iloc[-20:].mean() if '换手率' in df.columns else 3.0
                        }
                    else:
                        logger.warning(f"无法获取{code}的价格数据，使用默认值")
                        price_data[code] = self._get_default_price_data(code)
                        
                except Exception as e:
                    logger.warning(f"获取{code}价格数据失败: {str(e)}，使用默认值")
                    price_data[code] = self._get_default_price_data(code)
                    
            return price_data
            
        except ImportError:
            logger.error("未安装akshare，请运行: pip install akshare")
            raise ImportError("akshare未安装，请先安装: pip install akshare")
    
    def _calculate_max_drawdown(self, prices: np.ndarray) -> float:
        """计算最大回撤"""
        peak = np.maximum.accumulate(prices)
        drawdown = (prices - peak) / peak
        return abs(np.min(drawdown)) * 100
    
    def _get_default_price_data(self, code: str) -> Dict:
        """获取默认价格数据（当API失败时使用）"""
        return {
            'current_price': 50.0,
            'prices_90d': np.array([50.0] * 90),
            'ma20': 50.0,
            'ma60': 50.0,
            'rsi': 50.0,
            'volatility': 0.3,
            'max_drawdown': 15.0,
            'returns_20d': 0.0,
            'returns_60d': 0.0,
            'turnover_rate': 3.0
        }
    
    def get_financial_data(self, stock_codes: List[str]) -> Dict[str, Dict]:
        """
        获取财务数据

        Returns:
            字典格式的财务数据
        """
        return self._get_real_financial_data(stock_codes)
    
    
    def _get_real_financial_data(self, stock_codes: List[str]) -> Dict[str, Dict]:
        """从AkShare获取真实财务数据"""
        try:
            import akshare as ak
            import pandas as pd

            financial_data = {}

            try:
                spot_df = ak.stock_zh_a_spot_em()
                spot_df = spot_df.set_index('代码')

                for code in stock_codes:
                    try:
                        ts_code = code.replace('.SZ', '').replace('.SH', '')

                        default_data = self._get_default_financial_data()

                        spot_row = spot_df.loc[ts_code] if ts_code in spot_df.index else None

                        if spot_row is not None:
                            try:
                                pe = float(spot_row.get('市盈率-动态', 50.0))
                                if pe <= 0 or pe > 1000:
                                    pe = 50.0
                            except:
                                pe = 50.0

                            try:
                                pb = float(spot_row.get('市净率', 3.0))
                                if pb <= 0 or pb > 100:
                                    pb = 3.0
                            except:
                                pb = 3.0

                            try:
                                market_cap = float(spot_row.get('总市值', 500.0))
                            except:
                                market_cap = 500.0

                            default_data['pe_ttm'] = pe
                            default_data['pb'] = pb
                            default_data['market_cap'] = market_cap / 1e8
                        else:
                            logger.warning(f"无法获取{code}的实时行情数据")

                        try:
                            finance_df = ak.stock_financial_abstract_ths(symbol=ts_code)
                            if finance_df is not None and len(finance_df) > 0:
                                latest = finance_df.iloc[0]

                                def safe_float(val, default):
                                    try:
                                        v = float(val)
                                        return v if pd.notna(v) and abs(v) < 10000 else default
                                    except:
                                        return default

                                default_data['roe'] = safe_float(latest.get('净资产收益率'), default_data['roe'])
                                default_data['gross_margin'] = safe_float(latest.get('销售毛利率'), default_data['gross_margin'])
                                default_data['revenue_growth_yoy'] = safe_float(latest.get('营业总收入同比增长率'), default_data['revenue_growth_yoy'])
                                default_data['net_profit_growth_yoy'] = safe_float(latest.get('净利润同比增长率'), default_data['net_profit_growth_yoy'])
                                default_data['net_profit_margin'] = safe_float(latest.get('销售净利率'), default_data['net_profit_margin'])

                                if default_data['pe_ttm'] > 0 and default_data['roe'] > 0:
                                    default_data['peg'] = default_data['pe_ttm'] / (default_data['roe'] * 100)
                                    if default_data['peg'] <= 0 or default_data['peg'] > 10:
                                        default_data['peg'] = 1.0
                        except Exception as e:
                            logger.warning(f"获取{code}详细财务数据失败: {str(e)}")

                        financial_data[code] = default_data

                    except Exception as e:
                        logger.warning(f"处理{code}财务数据时出错: {str(e)}，使用默认值")
                        financial_data[code] = self._get_default_financial_data()

            except Exception as e:
                logger.error(f"获取实时行情数据失败: {str(e)}，所有股票使用默认财务数据")
                for code in stock_codes:
                    financial_data[code] = self._get_default_financial_data()

            return financial_data

        except ImportError:
            logger.error("未安装akshare，请运行: pip install akshare")
            raise ImportError("akshare未安装，请先安装: pip install akshare")
    
    def _get_default_financial_data(self) -> Dict:
        """获取默认财务数据（当API失败时使用）"""
        return {
            'roe': 10.0,
            'gross_margin': 30.0,
            'revenue_growth_yoy': 15.0,
            'net_profit_growth_yoy': 15.0,
            'net_profit_margin': 10.0,
            'pe_ttm': 50.0,
            'peg': 1.0,
            'pb': 3.0,
            'ps': 5.0,
            'market_cap': 500.0,
            'cash_flow_to_net_profit': 0.9,
            'debt_to_asset': 40.0
        }
    


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
        factors['momentum_20d'] = [price_data[s]['returns_20d'] for s in stocks]
        factors['momentum_60d'] = [price_data[s]['returns_60d'] for s in stocks]
        factors['ma_distance'] = [(price_data[s]['current_price'] / price_data[s]['ma60'] - 1) * 100 
                                   for s in stocks]
        factors['momentum_score'] = (
            0.4 * self._normalize(factors['momentum_20d']) +
            0.4 * self._normalize(factors['momentum_60d']) +
            0.2 * self._normalize(factors['ma_distance'])
        )
        
        # 2. 成长因子得分
        factors['revenue_growth'] = [financial_data[s]['revenue_growth_yoy'] for s in stocks]
        factors['profit_growth'] = [financial_data[s]['net_profit_growth_yoy'] for s in stocks]
        factors['growth_score'] = (
            0.5 * self._normalize(factors['revenue_growth']) +
            0.5 * self._normalize(factors['profit_growth'])
        )
        
        # 3. 估值因子得分（估值越低得分越高）
        factors['pe'] = [financial_data[s]['pe_ttm'] for s in stocks]
        factors['peg'] = [financial_data[s]['peg'] for s in stocks]
        factors['valuation_score'] = (
            0.4 * (1 - self._normalize(factors['pe'])) +
            0.6 * (1 - self._normalize(factors['peg']))
        )
        
        # 4. 质量因子得分
        factors['roe'] = [financial_data[s]['roe'] for s in stocks]
        factors['cash_quality'] = [financial_data[s]['cash_flow_to_net_profit'] for s in stocks]
        factors['gross_margin'] = [financial_data[s]['gross_margin'] for s in stocks]
        factors['quality_score'] = (
            0.4 * self._normalize(factors['roe']) +
            0.3 * self._normalize(factors['cash_quality']) +
            0.3 * self._normalize(factors['gross_margin'])
        )
        
        # 5. 波动率因子得分（波动率越低得分越高）
        factors['volatility'] = [price_data[s]['volatility'] for s in stocks]
        factors['max_dd'] = [price_data[s]['max_drawdown'] for s in stocks]
        factors['volatility_score'] = (
            0.5 * (1 - self._normalize(factors['volatility'])) +
            0.5 * (1 - self._normalize(factors['max_dd']))
        )
        
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
        composite = (
            FACTOR_WEIGHTS['momentum'] * factors['momentum_score'] +
            FACTOR_WEIGHTS['growth'] * factors['growth_score'] +
            FACTOR_WEIGHTS['valuation'] * factors['valuation_score'] +
            FACTOR_WEIGHTS['quality'] * factors['quality_score'] +
            FACTOR_WEIGHTS['volatility'] * factors['volatility_score']
        )
        
        return composite.clip(0, 100)


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
        
        # 第一梯队配置（60%）
        top_weight = 0.60
        for idx in top_stocks.index:
            # 根据排名分配权重
            rank = list(top_stocks.index).index(idx)
            base_weight = top_weight / len(top_stocks)
            
            # 排名越高权重越大
            weight = base_weight * (1 + (10 - rank) * 0.05)
            allocation.loc[idx, 'target_weight'] = min(weight, self.position_limits['max_single_stock'])
        
        # 第二梯队配置（30%）
        mid_weight = 0.30
        for idx in mid_stocks.index:
            base_weight = mid_weight / len(mid_stocks)
            allocation.loc[idx, 'target_weight'] = min(base_weight * 0.8, self.position_limits['max_single_stock'] * 0.5)
        
        # 第三梯队观察（10%）
        other_weight = 0.10
        for idx in other_stocks.index:
            if allocation.loc[idx, 'composite_score'] >= 50:
                base_weight = other_weight / len(other_stocks[other_stocks['composite_score'] >= 50])
                allocation.loc[idx, 'target_weight'] = min(base_weight, self.position_limits['min_stock_weight'])
        
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
                excess_per_stock = excess / len(sector_stocks[sector_stocks['target_weight'] > self.position_limits['min_stock_weight']])
                
                for idx in sector_stocks.index:
                    if allocation.loc[idx, 'target_weight'] > self.position_limits['min_stock_weight']:
                        allocation.loc[idx, 'target_weight'] = max(
                            allocation.loc[idx, 'target_weight'] - excess_per_stock,
                            self.position_limits['min_stock_weight']
                        )
        
        return allocation


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
                   output_path: str = None,
                   results_dir: str = "results") -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        对股票池进行排序和配置
        
        Args:
            csv_path: 股票池CSV文件路径
            total_capital: 总资金
            output_path: 输出文件路径
            
        Returns:
            (排名结果, 配置结果)
        """
        logger.info(f"开始股票排序分析: {csv_path}")
        
        # 1. 加载股票池
        stock_info = pd.read_csv(csv_path, index_col='stock_code')
        stock_codes = stock_info.index.tolist()
        logger.info(f"加载股票数量: {len(stock_codes)}")
        
        # 2. 获取数据
        logger.info("获取股票数据...")
        price_data = self.data_fetcher.get_price_data(stock_codes)
        financial_data = self.data_fetcher.get_financial_data(stock_codes)
        
        # 3. 计算因子得分
        logger.info("计算因子得分...")
        factors = self.factor_calculator.calculate_all_factors(
            price_data, financial_data
        )
        
        # 4. 应用行业调整
        factors = self.factor_calculator.apply_industry_adjustment(factors, stock_info)
        
        # 5. 计算综合得分
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
        logger.info("优化资产配置...")
        allocation = self.portfolio_optimizer.optimize_allocation(
            ranking, stock_info, total_capital
        )
        
        # 8. 输出结果
        if output_path:
            # 创建带时间戳的结果文件夹
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            results_folder = f"{results_dir}/{timestamp}"
            os.makedirs(results_folder, exist_ok=True)

            # 保存完整排名结果
            ranking_output = ranking.copy()
            ranking_file = f"{results_folder}/ranking_result_ranking.csv"
            ranking_output.to_csv(ranking_file)
            logger.info(f"排名结果已保存到: {ranking_file}")

            # 保存配置结果
            allocation_output = allocation.copy()
            allocation_file = f"{results_folder}/ranking_result.csv"
            allocation_output.to_csv(allocation_file)
            logger.info(f"配置结果已保存到: {allocation_file}")

            # 保存运行参数和配置信息
            config_file = f"{results_folder}/run_config.txt"
            
            # 计算数据获取时间段
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
            
            with open(config_file, 'w', encoding='utf-8') as f:
                f.write(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"数据获取时间段: {start_date} 至 {end_date}\n")
                f.write(f"股票池文件: {csv_path}\n")
                f.write(f"总资金: {total_capital}亿元\n")
                f.write(f"分析股票数量: {len(ranking)}\n")
                f.write(f"Top 5股票: {', '.join(ranking.head(5).index.tolist())}\n")
            
            logger.info(f"运行配置已保存到: {config_file}")
            logger.info(f"数据获取时间段: {start_date} 至 {end_date}")

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


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='AI产业链股票量化选股系统')
    parser.add_argument('--csv', type=str, default='ai_stock_pool.csv',
                       help='股票池CSV文件路径')
    parser.add_argument('--output', type=str, default='ranking_result.csv',
                       help='输出文件路径（会自动创建时间戳文件夹）')
    parser.add_argument('--capital', type=float, default=100.0,
                       help='总资金（亿元）')
    parser.add_argument('--results-dir', type=str, default='results',
                       help='结果文件夹名称')
    parser.add_argument('--report', action='store_true',
                       help='生成详细分析报告')

    args = parser.parse_args()

    # 初始化排序器（使用真实数据）
    ranker = StockRanker()
    
    # 执行排序
    ranking, allocation = ranker.rank_stocks(
        csv_path=args.csv,
        total_capital=args.capital,
        output_path=args.output,
        results_dir=args.results_dir
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
