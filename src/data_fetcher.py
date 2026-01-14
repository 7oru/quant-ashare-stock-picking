"""
数据获取模块
Data Fetching Module

从akshare获取真实股票数据
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List
import sys

# Use print for progress updates
def log(msg):
    print(msg)
    sys.stdout.flush()


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

        Raises:
            RuntimeError: 当无法获取股票数据时
        """
        return self._get_real_price_data(stock_codes, lookback_days)
    
    def get_spot_data(self, stock_codes: List[str]) -> Dict[str, Dict]:
        """
        获取实时行情数据（用于补充收益率等因子）
        
        Args:
            stock_codes: 股票代码列表
            
        Returns:
            实时行情数据字典
        """
        try:
            import akshare as ak
            
            log(f"获取实时行情数据...")
            spot_df = ak.stock_zh_a_spot_em()
            spot_df = spot_df.set_index('代码')
            
            spot_data = {}
            for code in stock_codes:
                ts_code = code.replace('.SZ', '').replace('.SH', '')
                if ts_code in spot_df.index:
                    spot_row = spot_df.loc[ts_code]
                    spot_data[code] = {
                        'current_price': float(spot_row.get('最新价', 0)),
                        'returns_5d': float(spot_row.get('5日涨跌幅', 0)) if '5日涨跌幅' in spot_row else 0,
                        'returns_60d': float(spot_row.get('60日涨跌幅', 0)) if '60日涨跌幅' in spot_row else 0,
                        'returns_ytd': float(spot_row.get('年初至今涨跌幅', 0)) if '年初至今涨跌幅' in spot_row else 0,
                    }
            
            return spot_data
        except Exception as e:
            log(f"获取实时行情数据失败: {e}")
            return {}
    
    
    def _get_real_price_data(self, stock_codes: List[str], 
                             lookback_days: int) -> Dict[str, Dict]:
        """
        从AkShare获取真实价格数据
        
        AkShare是完全开源免费的财经数据接口
        
        Raises:
            RuntimeError: 当无法获取股票数据时
        """
        try:
            import akshare as ak
            
            price_data = {}
            failed_stocks = []
            total = len(stock_codes)
            
            for i, code in enumerate(stock_codes, 1):
                log(f"[{i}/{total}] 获取价格数据: {code}")
                
                # 转换股票代码格式 (000977.SZ -> 000977)
                ts_code = code.replace('.SZ', '').replace('.SH', '')
                
                try:
                    # 获取日线数据
                    df = ak.stock_zh_a_hist(
                        symbol=ts_code,
                        period="daily",
                        start_date=(datetime.now() - timedelta(days=lookback_days)).strftime('%Y%m%d'),
                        end_date=datetime.now().strftime('%Y%m%d'),
                        adjust="qfq"
                    )
                    
                    if df is None or len(df) == 0:
                        log(f"  [{i}/{total}] 无数据: {code}")
                        failed_stocks.append(code)
                        continue
                        
                    df = df.sort_values('日期')
                    prices = df['收盘'].values
                    highs = df['最高'].values if '最高' in df.columns else prices
                    lows = df['最低'].values if '最低' in df.columns else prices
                    volumes = df['成交量'].values if '成交量' in df.columns else np.ones(len(prices))
                    
                    # ========== 基础移动平均线 ==========
                    ma20 = pd.Series(prices[-20:]).mean() if len(prices) >= 20 else prices[-1]
                    ma60 = pd.Series(prices[-60:]).mean() if len(prices) >= 60 else ma20
                    ma5 = pd.Series(prices[-5:]).mean() if len(prices) >= 5 else prices[-1]
                    
                    # ========== RSI (14日) ==========
                    delta = np.diff(prices)
                    gain = np.where(delta > 0, delta, 0)
                    loss = np.where(delta < 0, -delta, 0)
                    avg_gain = np.mean(gain[-14:]) if len(gain) >= 14 else np.mean(gain) if len(gain) > 0 else 0.01
                    avg_loss = np.mean(loss[-14:]) if len(loss) >= 14 else np.mean(loss) if len(loss) > 0 else 0.01
                    rsi = 100 * (avg_gain / (avg_gain + avg_loss)) if (avg_gain + avg_loss) > 0 else 50
                    
                    # ========== MACD ==========
                    ema12 = pd.Series(prices).ewm(span=12, adjust=False).mean().iloc[-1] if len(prices) >= 12 else prices[-1]
                    ema26 = pd.Series(prices).ewm(span=26, adjust=False).mean().iloc[-1] if len(prices) >= 26 else prices[-1]
                    macd_line = ema12 - ema26
                    signal_line = pd.Series([macd_line] * len(prices[-9:])).ewm(span=9, adjust=False).mean().iloc[-1] if len(prices) >= 9 else macd_line
                    macd_histogram = macd_line - signal_line
                    
                    # ========== Bollinger Bands ==========
                    bb_period = 20
                    if len(prices) >= bb_period:
                        bb_ma = np.mean(prices[-bb_period:])
                        bb_std = np.std(prices[-bb_period:])
                        bb_upper = bb_ma + 2 * bb_std
                        bb_lower = bb_ma - 2 * bb_std
                        bb_percent = ((prices[-1] - bb_lower) / (bb_upper - bb_lower)) * 100 if (bb_upper - bb_lower) > 0 else 50
                        bb_width = ((bb_upper - bb_lower) / bb_ma) * 100 if bb_ma > 0 else 0
                    else:
                        bb_upper = bb_lower = bb_percent = bb_width = None
                    
                    # ========== Stochastic Oscillator (%K, %D) ==========
                    stoch_period = 14
                    if len(prices) >= stoch_period:
                        highest_high = np.max(highs[-stoch_period:])
                        lowest_low = np.min(lows[-stoch_period:])
                        stoch_k = 100 * ((prices[-1] - lowest_low) / (highest_high - lowest_low)) if (highest_high - lowest_low) > 0 else 50
                        # %D is 3-period SMA of %K
                        stoch_d = np.mean([stoch_k] * min(3, len(prices))) if len(prices) >= 3 else stoch_k
                    else:
                        stoch_k = stoch_d = None
                    
                    # ========== ATR (Average True Range) ==========
                    atr_period = 14
                    if len(prices) >= atr_period and len(highs) == len(prices) and len(lows) == len(prices):
                        true_ranges = []
                        for i in range(1, len(prices)):
                            tr1 = highs[i] - lows[i]
                            tr2 = abs(highs[i] - prices[i-1])
                            tr3 = abs(lows[i] - prices[i-1])
                            true_ranges.append(max(tr1, tr2, tr3))
                        atr = np.mean(true_ranges[-atr_period:]) if len(true_ranges) >= atr_period else np.mean(true_ranges) if true_ranges else 0
                        atr_percent = (atr / prices[-1]) * 100 if prices[-1] > 0 else 0
                    else:
                        atr = atr_percent = None
                    
                    # ========== Williams %R ==========
                    wr_period = 14
                    if len(prices) >= wr_period:
                        highest_high_wr = np.max(highs[-wr_period:])
                        lowest_low_wr = np.min(lows[-wr_period:])
                        williams_r = -100 * ((highest_high_wr - prices[-1]) / (highest_high_wr - lowest_low_wr)) if (highest_high_wr - lowest_low_wr) > 0 else -50
                    else:
                        williams_r = None
                    
                    # ========== CCI (Commodity Channel Index) ==========
                    cci_period = 20
                    if len(prices) >= cci_period:
                        typical_price = (highs[-cci_period:] + lows[-cci_period:] + prices[-cci_period:]) / 3
                        sma_tp = np.mean(typical_price)
                        mean_deviation = np.mean(np.abs(typical_price - sma_tp))
                        cci = (typical_price[-1] - sma_tp) / (0.015 * mean_deviation) if mean_deviation > 0 else 0
                    else:
                        cci = None
                    
                    # ========== Volume Indicators ==========
                    # OBV (On-Balance Volume)
                    if len(volumes) == len(prices) and len(prices) > 1:
                        obv = 0
                        for i in range(1, len(prices)):
                            if prices[i] > prices[i-1]:
                                obv += volumes[i]
                            elif prices[i] < prices[i-1]:
                                obv -= volumes[i]
                        obv_change = obv - (obv - volumes[-1] if prices[-1] > prices[-2] else obv + volumes[-1]) if len(prices) >= 2 else 0
                    else:
                        obv = obv_change = None
                    
                    # Volume MA
                    volume_ma20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else np.mean(volumes) if len(volumes) > 0 else 0
                    volume_ratio_current = volumes[-1] / volume_ma20 if volume_ma20 > 0 else 1.0
                    
                    # ========== Price Position Indicators ==========
                    # Price position relative to recent range
                    if len(prices) >= 20:
                        recent_high = np.max(prices[-20:])
                        recent_low = np.min(prices[-20:])
                        price_position = ((prices[-1] - recent_low) / (recent_high - recent_low)) * 100 if (recent_high - recent_low) > 0 else 50
                    else:
                        price_position = 50
                    
                    # ========== Trend Strength ==========
                    # ADX-like calculation (simplified)
                    if len(prices) >= 14:
                        up_moves = np.where(np.diff(prices) > 0, np.diff(prices), 0)
                        down_moves = np.where(np.diff(prices) < 0, -np.diff(prices), 0)
                        avg_up = np.mean(up_moves[-14:]) if len(up_moves) >= 14 else np.mean(up_moves) if len(up_moves) > 0 else 0.01
                        avg_down = np.mean(down_moves[-14:]) if len(down_moves) >= 14 else np.mean(down_moves) if len(down_moves) > 0 else 0.01
                        trend_strength = 100 * abs(avg_up - avg_down) / (avg_up + avg_down) if (avg_up + avg_down) > 0 else 0
                    else:
                        trend_strength = 0
                    
                    # ========== 最大回撤 ==========
                    peak = np.maximum.accumulate(prices)
                    drawdown = (prices - peak) / peak
                    max_drawdown = abs(np.min(drawdown)) * 100
                    
                    # ========== 波动率 ==========
                    volatility = np.std(prices[-90:]) / np.mean(prices[-90:]) * np.sqrt(252) if len(prices) >= 90 else 0.3
                    
                    price_data[code] = {
                        'current_price': prices[-1],
                        'prices_90d': prices,
                        
                        # 移动平均线
                        'ma5': ma5,
                        'ma20': ma20,
                        'ma60': ma60,
                        
                        # 动量指标
                        'rsi': min(max(rsi, 0), 100),
                        'macd': macd_line,
                        'macd_signal': signal_line,
                        'macd_histogram': macd_histogram,
                        'stoch_k': stoch_k if stoch_k is not None else 50,
                        'stoch_d': stoch_d if stoch_d is not None else 50,
                        'williams_r': williams_r if williams_r is not None else -50,
                        'cci': cci if cci is not None else 0,
                        
                        # 波动率指标
                        'volatility': volatility,
                        'atr': atr if atr is not None else 0,
                        'atr_percent': atr_percent if atr_percent is not None else 0,
                        'max_drawdown': max_drawdown,
                        
                        # 布林带
                        'bb_upper': bb_upper if bb_upper is not None else prices[-1],
                        'bb_lower': bb_lower if bb_lower is not None else prices[-1],
                        'bb_percent': bb_percent if bb_percent is not None else 50,
                        'bb_width': bb_width if bb_width is not None else 0,
                        
                        # 成交量指标
                        'volume_ma20': volume_ma20,
                        'volume_ratio': volume_ratio_current,
                        'obv': obv if obv is not None else 0,
                        'obv_change': obv_change if obv_change is not None else 0,
                        
                        # 价格位置
                        'price_position': price_position,
                        'trend_strength': trend_strength,
                        
                        # 收益率
                        'returns_20d': (prices[-1] - prices[-20]) / prices[-20] * 100 if len(prices) >= 20 else 0,
                        'returns_60d': (prices[-1] - prices[-60]) / prices[-60] * 100 if len(prices) >= 60 else 0,
                        
                        # 换手率
                        'turnover_rate': df['换手率'].iloc[-20:].mean() if '换手率' in df.columns else 3.0,
                    }
                    
                    log(f"  [{i}/{total}] 完成: {code} (价格: {prices[-1]:.2f})")
                        
                except Exception as e:
                    log(f"  [{i}/{total}] 失败: {code} - {str(e)}")
                    failed_stocks.append(code)
                    
            if failed_stocks:
                raise RuntimeError(f"无法获取以下股票的价格数据: {', '.join(failed_stocks)}")
                    
            return price_data
            
        except ImportError:
            log("错误: 未安装akshare，请运行: pip install akshare")
            raise ImportError("akshare未安装，请先安装: pip install akshare")
    
    
    def get_financial_data(self, stock_codes: List[str]) -> Dict[str, Dict]:
        """
        获取财务数据

        Returns:
            字典格式的财务数据

        Raises:
            RuntimeError: 当无法获取财务数据时
        """
        return self._get_real_financial_data(stock_codes)
    
    
    def _get_real_financial_data(self, stock_codes: List[str]) -> Dict[str, Dict]:
        """
        从AkShare获取财务数据
        
        使用实时行情API获取PE/PB/市值/收益率等因子
        
        Raises:
            RuntimeError: 当无法获取财务数据时
        """
        try:
            import akshare as ak

            log(f"获取实时行情数据...")
            spot_df = ak.stock_zh_a_spot_em()
            spot_df = spot_df.set_index('代码')
            log(f"实时行情数据获取完成，共 {len(spot_df)} 只股票")

            financial_data = {}
            failed_stocks = []
            total = len(stock_codes)

            for i, code in enumerate(stock_codes, 1):
                log(f"[{i}/{total}] 获取财务数据: {code}")
                
                ts_code = code.replace('.SZ', '').replace('.SH', '')
                spot_row = spot_df.loc[ts_code] if ts_code in spot_df.index else None

                if spot_row is None:
                    log(f"  [{i}/{total}] 实时行情无数据: {code}")
                    failed_stocks.append(code)
                    continue

                # 提取估值指标 - 使用实际数据，只过滤明显无效值
                try:
                    pe_val = spot_row.get('市盈率-动态', None)
                    if pe_val is not None and pd.notna(pe_val):
                        pe = float(pe_val)
                        # 只过滤明显无效值（负值或极端异常值），允许高PE（成长股常见）
                        if pe <= 0 or pe > 10000:  # 允许到10000，只过滤极端异常
                            pe = None
                    else:
                        pe = None
                except:
                    pe = None

                try:
                    pb_val = spot_row.get('市净率', None)
                    if pb_val is not None and pd.notna(pb_val):
                        pb = float(pb_val)
                        if pb <= 0 or pb > 1000:  # 允许高PB（科技股常见）
                            pb = None
                    else:
                        pb = None
                except:
                    pb = None

                try:
                    market_cap_val = spot_row.get('总市值', None)
                    if market_cap_val is not None and pd.notna(market_cap_val):
                        market_cap = float(market_cap_val)
                        if market_cap <= 0:
                            market_cap = None
                    else:
                        market_cap = None
                except:
                    market_cap = None

                # 提取其他可用指标 - 使用实际数据
                try:
                    ps_val = spot_row.get('市销率', None) if '市销率' in spot_row else None
                    if ps_val is not None and pd.notna(ps_val):
                        ps = float(ps_val)
                        if ps <= 0 or ps > 1000:  # 允许高PS
                            ps = None
                    else:
                        ps = None
                except:
                    ps = None

                try:
                    pcf_val = spot_row.get('市现率', None) if '市现率' in spot_row else None
                    if pcf_val is not None and pd.notna(pcf_val):
                        pcf = float(pcf_val)
                        if pcf <= 0 or pcf > 1000:
                            pcf = None
                    else:
                        pcf = None
                except:
                    pcf = None

                # 提取收益率数据（从实时行情直接获取）- 使用实际数据
                try:
                    returns_5d_val = spot_row.get('5日涨跌幅', None) if '5日涨跌幅' in spot_row else None
                    returns_5d = float(returns_5d_val) if returns_5d_val is not None and pd.notna(returns_5d_val) else None
                except:
                    returns_5d = None

                try:
                    returns_60d_val = spot_row.get('60日涨跌幅', None) if '60日涨跌幅' in spot_row else None
                    returns_60d = float(returns_60d_val) if returns_60d_val is not None and pd.notna(returns_60d_val) else None
                except:
                    returns_60d = None

                try:
                    returns_ytd_val = spot_row.get('年初至今涨跌幅', None) if '年初至今涨跌幅' in spot_row else None
                    returns_ytd = float(returns_ytd_val) if returns_ytd_val is not None and pd.notna(returns_ytd_val) else None
                except:
                    returns_ytd = None

                # 提取换手率 - 使用实际数据
                try:
                    turnover_val = spot_row.get('换手率', None)
                    if turnover_val is not None and pd.notna(turnover_val):
                        turnover_rate = float(turnover_val)
                        if turnover_rate < 0 or turnover_rate > 200:  # 允许高换手率
                            turnover_rate = None
                    else:
                        turnover_rate = None
                except:
                    turnover_rate = None

                try:
                    turnover_f_val = spot_row.get('换手率(自由流通股)', None) if '换手率(自由流通股)' in spot_row else None
                    if turnover_f_val is not None and pd.notna(turnover_f_val):
                        turnover_rate_f = float(turnover_f_val)
                        if turnover_rate_f < 0 or turnover_rate_f > 200:
                            turnover_rate_f = turnover_rate  # 回退到普通换手率
                    else:
                        turnover_rate_f = turnover_rate
                except:
                    turnover_rate_f = turnover_rate

                # 提取量比 - 使用实际数据
                try:
                    vol_ratio_val = spot_row.get('量比', None) if '量比' in spot_row else None
                    if vol_ratio_val is not None and pd.notna(vol_ratio_val):
                        volume_ratio = float(vol_ratio_val)
                        if volume_ratio <= 0 or volume_ratio > 50:  # 允许高量比
                            volume_ratio = None
                    else:
                        volume_ratio = None
                except:
                    volume_ratio = None

                # 提取振幅 - 使用实际数据
                try:
                    amp_val = spot_row.get('振幅', None) if '振幅' in spot_row else None
                    if amp_val is not None and pd.notna(amp_val):
                        amplitude = float(amp_val)
                        if amplitude < 0 or amplitude > 100:  # 振幅通常在0-100%之间
                            amplitude = None
                    else:
                        amplitude = None
                except:
                    amplitude = None

                # 处理流通市值
                try:
                    circ_cap_val = spot_row.get('流通市值', None)
                    if circ_cap_val is not None and pd.notna(circ_cap_val):
                        circ_market_cap = float(circ_cap_val) / 1e8
                    elif market_cap is not None:
                        circ_market_cap = market_cap / 1e8
                    else:
                        circ_market_cap = None
                except:
                    circ_market_cap = market_cap / 1e8 if market_cap is not None else None
                
                financial_data[code] = {
                    # 估值因子 - 使用实际数据或None
                    'pe_ttm': pe,
                    'pb': pb,
                    'ps': ps,
                    'pcf': pcf,
                    'market_cap': market_cap / 1e8 if market_cap is not None else None,  # 转换为亿元
                    'circ_market_cap': circ_market_cap,
                    
                    # 动量因子（从实时行情获取）- 使用实际数据
                    'returns_5d': returns_5d,
                    'returns_60d': returns_60d,
                    'returns_ytd': returns_ytd,
                    
                    # 技术因子 - 使用实际数据
                    'turnover_rate': turnover_rate,
                    'turnover_rate_f': turnover_rate_f,
                    'volume_ratio': volume_ratio,
                    'amplitude': amplitude,
                    
                    # 财务质量因子（暂无数据源，设为None）
                    'roe': None,
                    'gross_margin': None,
                    'revenue_growth_yoy': None,
                    'net_profit_growth_yoy': None,
                    'net_profit_margin': None,
                    'peg': None,
                    'cash_flow_to_net_profit': None,
                }
                
                # 格式化日志输出
                pe_str = f"{pe:.1f}" if pe is not None else "N/A"
                pb_str = f"{pb:.1f}" if pb is not None else "N/A"
                cap_str = f"{market_cap/1e8:.1f}亿" if market_cap is not None else "N/A"
                ret_str = f"{returns_60d:.1f}%" if returns_60d is not None else "N/A"
                log(f"  [{i}/{total}] 完成: {code} (PE: {pe_str}, PB: {pb_str}, 市值: {cap_str}, 60日收益: {ret_str})")

            if failed_stocks:
                log(f"警告: {len(failed_stocks)} 只股票无法获取财务数据: {', '.join(failed_stocks[:5])}...")
                if len(failed_stocks) == len(stock_codes):
                    raise RuntimeError(f"无法获取任何股票的财务数据")

            log(f"财务数据获取完成: {len(financial_data)}/{total} 只股票")
            return financial_data

        except ImportError:
            log("错误: 未安装akshare，请运行: pip install akshare")
            raise ImportError("akshare未安装，请先安装: pip install akshare")
        except ValueError as e:
            log(f"错误: {str(e)}")
            raise RuntimeError(str(e))
