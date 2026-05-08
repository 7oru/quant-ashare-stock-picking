"""
数据获取模块
Data Fetching Module

从akshare获取真实股票数据
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List
import multiprocessing
import os
import sys
import tempfile
import time

from .data_cache import TmpDataCache
from .market_features import calculate_price_features

# Use print for progress updates
def log(msg):
    print(msg)
    sys.stdout.flush()


class DataFetchTimeout(TimeoutError):
    pass


def fetch_spot_dataframe_worker(result_path: str, conn) -> None:
    try:
        import akshare as ak

        data = ak.stock_zh_a_spot_em()
        if data is None or data.empty:
            conn.send(("error", "实时行情数据为空"))
            return
        data.to_pickle(result_path)
        conn.send(("ok", result_path))
    except Exception as e:
        conn.send(("error", repr(e)))
    finally:
        conn.close()


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
        self.data_cache = TmpDataCache()
        self.spot_disabled_reason = None
        
    def get_price_data(self, stock_codes: List[str],
                       lookback_days: int = 240) -> Dict[str, Dict]:
        """
        获取股票价格数据

        Args:
            stock_codes: 股票代码列表
            lookback_days: 回溯天数

        Returns:
            字典格式的股票价格数据

        Raises:
            RuntimeError: 当无法获取任何股票数据时
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
            spot_df = self._get_spot_dataframe(ak)
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
            RuntimeError: 当无法获取任何股票数据时
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
                    start_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y%m%d')
                    end_date = datetime.now().strftime('%Y%m%d')
                    df = self._get_hist_dataframe(
                        ak,
                        symbol=ts_code,
                        start_date=start_date,
                        end_date=end_date,
                        adjust="qfq",
                    )
                    
                    if df is None or len(df) == 0:
                        log(f"  [{i}/{total}] 无数据: {code}")
                        failed_stocks.append(code)
                        continue
                        
                    features = calculate_price_features(df)
                    price_data[code] = features

                    log(f"  [{i}/{total}] 完成: {code} (价格: {features['current_price']:.2f})")
                        
                except Exception as e:
                    log(f"  [{i}/{total}] 失败: {code} - {str(e)}")
                    failed_stocks.append(code)
                    
            if failed_stocks:
                log(f"警告: {len(failed_stocks)} 只股票无法获取价格数据: {', '.join(failed_stocks[:5])}...")
                if len(failed_stocks) == len(stock_codes):
                    raise RuntimeError("无法获取任何股票的价格数据")
                    
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

            if self.spot_disabled_reason:
                log(f"跳过实时行情数据: {self.spot_disabled_reason}")
                return {}

            log(f"获取实时行情数据...")
            try:
                spot_df = self._get_spot_dataframe(ak)
            except Exception as e:
                message = str(e) or repr(e)
                self.spot_disabled_reason = message
                log(f"警告: 获取实时行情数据失败，将使用价格数据代理因子继续运行: {message}")
                return {}
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

    def _get_spot_dataframe(self, ak) -> pd.DataFrame:
        key = {"api": "stock_zh_a_spot_em"}
        cached = self.data_cache.get_dataframe("spot", key)
        cache_path = self.data_cache.path_for("spot", key)
        if cached is not None:
            log(f"使用缓存实时行情数据: {cache_path}")
            return cached.copy()

        spot_timeout = int(os.environ.get("QUANT_SPOT_TIMEOUT_SECONDS", "120"))
        if spot_timeout <= 0:
            spot_df = ak.stock_zh_a_spot_em()
            self.data_cache.set_dataframe("spot", key, spot_df)
            return spot_df.copy()

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=f"{cache_path.stem}.",
            suffix=".tmp",
            dir=cache_path.parent,
        )
        os.close(fd)

        ctx = multiprocessing.get_context("spawn")
        parent_conn, child_conn = ctx.Pipe(duplex=False)
        process = ctx.Process(
            target=fetch_spot_dataframe_worker,
            args=(tmp_path, child_conn),
        )
        process.start()
        child_conn.close()

        deadline = time.monotonic() + spot_timeout
        try:
            while time.monotonic() < deadline:
                if parent_conn.poll(0.25):
                    try:
                        status, payload = parent_conn.recv()
                    except EOFError:
                        process.join(timeout=1)
                        raise RuntimeError(f"实时行情子进程没有返回数据: exitcode={process.exitcode}")
                    process.join(timeout=1)
                    if status == "ok":
                        spot_df = pd.read_pickle(payload)
                        self.data_cache.set_dataframe("spot", key, spot_df)
                        return spot_df.copy()
                    raise RuntimeError(payload)

                if not process.is_alive():
                    process.join(timeout=1)
                    raise RuntimeError(f"实时行情子进程异常退出: exitcode={process.exitcode}")

            process.terminate()
            process.join(timeout=3)
            raise DataFetchTimeout(f"实时行情接口超时超过 {spot_timeout} 秒")
        finally:
            parent_conn.close()
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    def _get_hist_dataframe(
        self,
        ak,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str,
    ) -> pd.DataFrame:
        key = {
            "api": "stock_zh_a_hist",
            "symbol": symbol,
            "period": "daily",
            "start_date": start_date,
            "end_date": end_date,
            "adjust": adjust,
        }

        def fetch():
            return ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            )

        hist_df, cache_hit, cache_path = self.data_cache.get_or_fetch_dataframe(
            "hist",
            key,
            fetch,
        )
        if cache_hit:
            log(f"  使用缓存日线: {symbol} ({cache_path})")
        return hist_df.copy()
