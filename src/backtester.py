"""
回测管线
Backtest pipeline for the multi-factor stock picker
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .config import POSITION_LIMITS
from .data_cache import TmpDataCache
from .factor_calculator import FactorCalculator
from .market_features import calculate_price_features
from .market_data_providers import get_hist_dataframe_with_fallback
from .results_manager import create_timestamped_result_dir, describe_stock_pool


def log(msg):
    print(msg)
    sys.stdout.flush()


class BacktestPipeline:
    """
    使用同一套因子模型做点时滚动回测。
    """

    POOL_ENTRY_DATE_COLUMNS = ("pool_entry_date", "stock_pool_as_of_date", "as_of_date")
    INDUSTRY_AS_OF_DATE_COLUMNS = ("industry_as_of_date", "classification_as_of_date", "sector_as_of_date")

    def __init__(self):
        self.factor_calculator = FactorCalculator()
        self.position_limits = POSITION_LIMITS
        self.data_cache = TmpDataCache()

    def run(
        self,
        csv_path: str,
        start_date: str,
        end_date: str,
        initial_capital: float = 1_000_000.0,
        rebalance: str = "monthly",
        lookback_days: int = 180,
        top_n: int = 10,
        fee_bps: float = 10.0,
        output_dir: str = "results",
        output_timestamp: str | None = None,
        candidate_visible_dates: Optional[Dict[str, str]] = None,
    ) -> Dict[str, object]:
        """
        运行回测并保存结果。
        """
        stock_info = pd.read_csv(csv_path, index_col="stock_code", encoding="utf-8-sig")
        stock_pool_metadata = describe_stock_pool(csv_path, stock_info)
        stock_codes = stock_info.index.tolist()
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
        candidate_visible_dates = self._normalize_visible_dates(candidate_visible_dates or {})

        histories = self._fetch_histories(stock_codes, start, end, lookback_days)
        if not histories:
            raise RuntimeError("没有获取到任何历史行情，无法回测")

        calendar = self._build_calendar(histories, start, end)
        if len(calendar) < 2:
            raise RuntimeError("回测区间内交易日不足")

        rebalance_dates = self._rebalance_dates(calendar, rebalance)
        if not rebalance_dates:
            raise RuntimeError("回测区间内没有可用调仓日")

        close_panel = self._close_panel(histories, calendar)
        stock_returns = close_panel.pct_change().replace([np.inf, -np.inf], np.nan)

        equity = float(initial_capital)
        benchmark_equity = float(initial_capital)
        previous_weights = pd.Series(dtype="float64")
        equity_records = []
        rebalance_records = []
        point_in_time_records = []

        for i, signal_date in enumerate(rebalance_dates):
            signal_loc = calendar.get_loc(signal_date)
            if signal_loc + 1 >= len(calendar):
                continue

            next_signal_date = rebalance_dates[i + 1] if i + 1 < len(rebalance_dates) else calendar[-1]
            next_signal_loc = calendar.get_loc(next_signal_date)
            trade_dates = calendar[signal_loc + 1 : next_signal_loc + 1]
            if len(trade_dates) == 0:
                continue

            visible_stock_info, point_in_time_record = self._visible_stock_info(
                stock_info,
                signal_date,
                candidate_visible_dates,
            )
            eligible_histories = {
                code: history
                for code, history in histories.items()
                if code in visible_stock_info.index
            }
            provider_counts = self._history_provider_counts(eligible_histories)
            point_in_time_record["history_available_count"] = len(eligible_histories)
            point_in_time_record["history_provider_counts"] = json.dumps(
                provider_counts,
                ensure_ascii=False,
                sort_keys=True,
            )
            point_in_time_records.append(point_in_time_record)

            price_data, financial_data = self._build_signal_data(eligible_histories, signal_date, lookback_days)
            if len(price_data) < max(3, min(top_n, 5)):
                log(f"{signal_date.date()} 可用股票过少，跳过调仓")
                continue

            available_stock_info = visible_stock_info.loc[visible_stock_info.index.intersection(price_data.keys())]
            factors = self.factor_calculator.calculate_all_factors(price_data, financial_data)
            factors = self.factor_calculator.apply_industry_adjustment(factors, available_stock_info)
            composite_score = self.factor_calculator.calculate_composite_score(factors)

            ranking = self._build_ranking(available_stock_info, factors, composite_score)
            weights = self._target_weights(ranking, top_n)
            selected_returns = stock_returns.reindex(columns=weights.index).loc[trade_dates].fillna(0)
            holding_returns = (1 + selected_returns).prod() - 1
            benchmark_period_returns = (
                stock_returns.reindex(columns=visible_stock_info.index)
                .loc[trade_dates]
                .mean(axis=1, skipna=True)
                .fillna(0)
            )
            turnover = self._turnover(previous_weights, weights)
            fee_rate = turnover * fee_bps / 10000
            equity *= max(0, 1 - fee_rate)

            log(
                f"{signal_date.date()} 调仓: {len(weights)} 只, "
                f"换手 {turnover:.2f}, 费用 {fee_rate:.4%}, "
                f"现金 {max(0, 1 - weights.sum()):.1%}"
            )

            for rank, (stock_code, row) in enumerate(ranking.loc[weights.index].iterrows(), 1):
                history = eligible_histories.get(stock_code)
                data_provider = history.attrs.get("data_provider", "unknown") if history is not None else "unknown"
                provider_adjustment = history.attrs.get("provider_adjustment", "") if history is not None else ""
                rebalance_records.append(
                    {
                        "signal_date": signal_date,
                        "trade_start_date": trade_dates[0],
                        "stock_code": stock_code,
                        "stock_name": row.get("stock_name"),
                        "sector": row.get("sector"),
                        "rank": rank,
                        "target_weight": weights.loc[stock_code],
                        "composite_score": row.get("composite_score"),
                        "momentum_score": row.get("momentum_score"),
                        "quality_score": row.get("quality_score"),
                        "liquidity_score": row.get("liquidity_score", 50),
                        "data_provider": data_provider,
                        "provider_adjustment": provider_adjustment,
                        "holding_return": holding_returns.get(stock_code, np.nan),
                        "weighted_contribution": weights.loc[stock_code] * holding_returns.get(stock_code, 0),
                        "eligible_universe_count": point_in_time_record["eligible_universe_count"],
                    }
                )

            for trade_date in trade_dates:
                daily_stock_returns = stock_returns.reindex(columns=weights.index).loc[trade_date].fillna(0)
                strategy_return = float((daily_stock_returns * weights).sum())
                benchmark_return = float(benchmark_period_returns.loc[trade_date])

                equity *= 1 + strategy_return
                benchmark_equity *= 1 + benchmark_return

                equity_records.append(
                    {
                        "date": trade_date,
                        "strategy_return": strategy_return,
                        "benchmark_return": benchmark_return,
                        "equity": equity,
                        "benchmark_equity": benchmark_equity,
                        "cash_weight": max(0.0, 1 - float(weights.sum())),
                        "turnover": turnover if trade_date == trade_dates[0] else 0.0,
                    }
                )

            previous_weights = weights

        if not equity_records:
            raise RuntimeError("没有生成任何回测净值记录")

        equity_curve = pd.DataFrame(equity_records).set_index("date")
        equity_curve["drawdown"] = equity_curve["equity"] / equity_curve["equity"].cummax() - 1
        equity_curve["benchmark_drawdown"] = (
            equity_curve["benchmark_equity"] / equity_curve["benchmark_equity"].cummax() - 1
        )
        rebalances = pd.DataFrame(rebalance_records)
        point_in_time_report = pd.DataFrame(point_in_time_records)
        summary = self._summary(equity_curve, initial_capital, len(rebalance_dates))

        run_config = {
            "csv_path": csv_path,
            "start_date": start_date,
            "end_date": end_date,
            "initial_capital": initial_capital,
            "rebalance": rebalance,
            "lookback_days": lookback_days,
            "top_n": top_n,
            "fee_bps": fee_bps,
            "as_of_date": end_date,
            "point_in_time_stock_pool_policy": (
                "filter stock_pool snapshot by list_date <= signal_date, "
                "candidate_visible_dates <= signal_date, and row-level "
                "pool_entry_date/stock_pool_as_of_date/as_of_date <= signal_date when present"
            ),
            "point_in_time_llm_candidate_policy": "filter LLM candidates by candidate_visible_dates <= signal_date",
            "point_in_time_industry_data_policy": (
                "mask sector/sub_sector/ai_exposure when industry_as_of_date/"
                "classification_as_of_date/sector_as_of_date is after the signal date"
            ),
            "point_in_time_financial_data_policy": (
                "price-only point-in-time proxy in backtest; revised/current "
                "fundamental fields are null at each signal date"
            ),
            "historical_price_provider_policy": (
                "try BaoStock daily history first, then Yahoo chart fallback when enabled"
            ),
            "candidate_visible_dates": self._json_visible_dates(candidate_visible_dates),
            **stock_pool_metadata,
        }
        paths = self._save_outputs(
            summary,
            equity_curve,
            rebalances,
            point_in_time_report,
            output_dir,
            run_config,
            as_of_date=end_date,
            output_timestamp=output_timestamp,
        )
        return {
            "summary": summary,
            "equity_curve": equity_curve,
            "rebalances": rebalances,
            "point_in_time_report": point_in_time_report,
            "paths": paths,
            "output_dir": str(Path(paths["summary"]).parent),
        }

    def _fetch_histories(
        self,
        stock_codes: List[str],
        start: pd.Timestamp,
        end: pd.Timestamp,
        lookback_days: int,
    ) -> Dict[str, pd.DataFrame]:
        fetch_start = start - pd.Timedelta(days=int(lookback_days * 1.8) + 30)
        histories: Dict[str, pd.DataFrame] = {}
        total = len(stock_codes)

        for i, code in enumerate(stock_codes, 1):
            symbol = code.replace(".SZ", "").replace(".SH", "")
            log(f"[{i}/{total}] 获取回测历史: {code}")
            try:
                df = self._get_hist_dataframe(
                    symbol=symbol,
                    start_date=fetch_start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust="qfq",
                )
                if df is None or df.empty:
                    log(f"  无历史数据: {code}")
                    continue
                df = df.copy()
                data_provider = df.attrs.get("data_provider", "unknown")
                provider_adjustment = df.attrs.get("provider_adjustment", "qfq")
                df["日期"] = pd.to_datetime(df["日期"])
                df = df.sort_values("日期").set_index("日期")
                df["收盘"] = pd.to_numeric(df["收盘"], errors="coerce")
                df = df[df["收盘"].notna()]
                if len(df) >= 60:
                    df.attrs["data_provider"] = data_provider
                    df.attrs["provider_adjustment"] = provider_adjustment
                    histories[code] = df
            except Exception as exc:
                log(f"  获取失败: {code} - {exc}")

        log(f"历史行情获取完成: {len(histories)}/{total} 只")
        return histories

    def _get_hist_dataframe(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str,
    ) -> pd.DataFrame:
        hist_df, provider, cache_hit, cache_path, primary_error = get_hist_dataframe_with_fallback(
            data_cache=self.data_cache,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
        )
        if cache_hit:
            log(f"  使用缓存回测日线: {symbol} ({provider}, {cache_path})")
        elif provider == "baostock":
            log(f"  使用BaoStock回测日线: {symbol}")
        elif provider == "yahoo":
            log(f"  BaoStock失败，使用Yahoo回测日线: {symbol} ({primary_error})")
        return hist_df.copy()

    @staticmethod
    def _build_calendar(
        histories: Dict[str, pd.DataFrame],
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> pd.DatetimeIndex:
        all_dates = sorted(set().union(*(history.index for history in histories.values())))
        calendar = pd.DatetimeIndex(all_dates)
        return calendar[(calendar >= start) & (calendar <= end)]

    @staticmethod
    def _rebalance_dates(calendar: pd.DatetimeIndex, rebalance: str) -> List[pd.Timestamp]:
        frequency = rebalance.lower()
        if frequency in {"w", "week", "weekly"}:
            periods = calendar.to_period("W-FRI")
        elif frequency in {"q", "quarter", "quarterly"}:
            periods = calendar.to_period("Q")
        else:
            periods = calendar.to_period("M")

        dates = pd.Series(calendar, index=calendar).groupby(periods).max().tolist()
        return [date for date in dates if calendar.get_loc(date) < len(calendar) - 1]

    @staticmethod
    def _close_panel(histories: Dict[str, pd.DataFrame], calendar: pd.DatetimeIndex) -> pd.DataFrame:
        closes = {
            code: pd.to_numeric(history["收盘"], errors="coerce")
            for code, history in histories.items()
        }
        return pd.DataFrame(closes).reindex(calendar).ffill()

    def _build_signal_data(
        self,
        histories: Dict[str, pd.DataFrame],
        signal_date: pd.Timestamp,
        lookback_days: int,
    ) -> Tuple[Dict[str, Dict], Dict[str, Dict]]:
        price_data = {}
        financial_data = {}
        min_history = min(60, max(30, lookback_days // 3))

        for code, history in histories.items():
            point_in_time = history.loc[history.index <= signal_date].tail(lookback_days)
            if len(point_in_time) < min_history:
                continue
            try:
                features = calculate_price_features(point_in_time.reset_index())
            except Exception:
                continue

            ytd_history = history.loc[
                (history.index <= signal_date) & (history.index.year == signal_date.year)
            ]
            if len(ytd_history) >= 2 and ytd_history["收盘"].iloc[0] != 0:
                returns_ytd = (ytd_history["收盘"].iloc[-1] / ytd_history["收盘"].iloc[0] - 1) * 100
            else:
                returns_ytd = np.nan

            latest = point_in_time.iloc[-1]
            amplitude = self._number(latest.get("振幅"))
            price_data[code] = features
            financial_data[code] = {
                "returns_5d": features.get("returns_5d"),
                "returns_60d": features.get("returns_60d"),
                "returns_ytd": returns_ytd,
                "turnover_rate": features.get("turnover_rate"),
                "volume_ratio": features.get("volume_ratio"),
                "amplitude": amplitude,
                "pe_ttm": None,
                "pb": None,
                "ps": None,
                "pcf": None,
                "market_cap": None,
                "circ_market_cap": None,
                "roe": None,
                "gross_margin": None,
                "revenue_growth_yoy": None,
                "net_profit_growth_yoy": None,
                "net_profit_margin": None,
                "peg": None,
                "cash_flow_to_net_profit": None,
            }

        return price_data, financial_data

    @staticmethod
    def _visible_stock_info(
        stock_info: pd.DataFrame,
        signal_date: pd.Timestamp,
        candidate_visible_dates: Dict[str, pd.Timestamp],
    ) -> Tuple[pd.DataFrame, Dict[str, object]]:
        if "list_date" in stock_info.columns:
            list_dates = pd.to_datetime(stock_info["list_date"], errors="coerce")
        else:
            list_dates = pd.Series(pd.NaT, index=stock_info.index)
        listed_mask = list_dates.isna() | (list_dates <= signal_date)

        pool_entry_column = BacktestPipeline._first_existing_column(
            stock_info,
            BacktestPipeline.POOL_ENTRY_DATE_COLUMNS,
        )
        if pool_entry_column:
            pool_entry_dates = pd.to_datetime(stock_info[pool_entry_column], errors="coerce")
        else:
            pool_entry_dates = pd.Series(pd.NaT, index=stock_info.index)
        pool_entry_mask = pool_entry_dates.isna() | (pool_entry_dates <= signal_date)

        candidate_mask = pd.Series(True, index=stock_info.index)

        for stock_code, visible_date in candidate_visible_dates.items():
            if stock_code in candidate_mask.index and visible_date > signal_date:
                candidate_mask.loc[stock_code] = False

        visible_mask = listed_mask & pool_entry_mask & candidate_mask
        visible_stock_info = stock_info.loc[visible_mask].copy()
        visible_stock_info, classification_record = BacktestPipeline._mask_future_classifications(
            visible_stock_info,
            signal_date,
        )
        return visible_stock_info, {
            "signal_date": signal_date,
            "stock_pool_rows": len(stock_info),
            "eligible_universe_count": int(visible_mask.sum()),
            "excluded_not_listed_count": int((~listed_mask).sum()),
            "excluded_stock_pool_not_visible_count": int((listed_mask & ~pool_entry_mask).sum()),
            "excluded_llm_candidate_not_visible_count": int((listed_mask & pool_entry_mask & ~candidate_mask).sum()),
            "missing_list_date_count": int(list_dates.isna().sum()),
            "pool_entry_date_column": pool_entry_column or "",
            "missing_pool_entry_date_count": int(pool_entry_dates.isna().sum()),
            **classification_record,
        }

    @staticmethod
    def _history_provider_counts(histories: Dict[str, pd.DataFrame]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for history in histories.values():
            provider = str(history.attrs.get("data_provider", "unknown") or "unknown")
            counts[provider] = counts.get(provider, 0) + 1
        return counts

    @staticmethod
    def _mask_future_classifications(
        stock_info: pd.DataFrame,
        signal_date: pd.Timestamp,
    ) -> Tuple[pd.DataFrame, Dict[str, object]]:
        classification_column = BacktestPipeline._first_existing_column(
            stock_info,
            BacktestPipeline.INDUSTRY_AS_OF_DATE_COLUMNS,
        )
        if not classification_column:
            return stock_info, {
                "industry_as_of_date_column": "",
                "future_industry_label_count": 0,
                "missing_industry_as_of_date_count": len(stock_info),
            }

        classification_dates = pd.to_datetime(stock_info[classification_column], errors="coerce")
        future_label_mask = classification_dates.notna() & (classification_dates > signal_date)
        masked = stock_info.copy()
        for column in ["sector", "sub_sector", "ai_exposure"]:
            if column in masked.columns:
                masked.loc[future_label_mask, column] = pd.NA

        return masked, {
            "industry_as_of_date_column": classification_column,
            "future_industry_label_count": int(future_label_mask.sum()),
            "missing_industry_as_of_date_count": int(classification_dates.isna().sum()),
        }

    @staticmethod
    def _first_existing_column(stock_info: pd.DataFrame, columns: Tuple[str, ...]) -> Optional[str]:
        for column in columns:
            if column in stock_info.columns:
                return column
        return None

    @staticmethod
    def _normalize_visible_dates(candidate_visible_dates: Dict[str, str]) -> Dict[str, pd.Timestamp]:
        normalized = {}
        for stock_code, visible_date in candidate_visible_dates.items():
            parsed = pd.to_datetime(visible_date, errors="coerce")
            if pd.notna(parsed):
                normalized[str(stock_code)] = pd.Timestamp(parsed).normalize()
        return normalized

    @staticmethod
    def _json_visible_dates(candidate_visible_dates: Dict[str, pd.Timestamp]) -> str:
        serializable = {
            stock_code: visible_date.strftime("%Y-%m-%d")
            for stock_code, visible_date in sorted(candidate_visible_dates.items())
        }
        return json.dumps(serializable, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _build_ranking(
        stock_info: pd.DataFrame,
        factors: pd.DataFrame,
        composite_score: pd.Series,
    ) -> pd.DataFrame:
        ranking = pd.DataFrame(
            {
                "stock_name": stock_info["stock_name"],
                "sector": stock_info["sector"],
                "sub_sector": stock_info["sub_sector"],
                "ai_exposure": stock_info["ai_exposure"],
                "composite_score": composite_score,
                "momentum_score": factors["momentum_score"],
                "growth_score": factors["growth_score"],
                "valuation_score": factors["valuation_score"],
                "quality_score": factors["quality_score"],
                "volatility_score": factors["volatility_score"],
                "liquidity_score": factors.get("liquidity_score", 50),
            }
        ).sort_values("composite_score", ascending=False)
        ranking["rank"] = range(1, len(ranking) + 1)
        return ranking

    def _target_weights(self, ranking: pd.DataFrame, top_n: int) -> pd.Series:
        selected = ranking.head(top_n).copy()
        if selected.empty:
            return pd.Series(dtype="float64")

        scores = selected["composite_score"].clip(lower=0)
        if scores.sum() <= 0:
            weights = pd.Series(1 / len(selected), index=selected.index)
        else:
            weights = scores / scores.sum()

        weights = self._cap_single_stock(weights, self.position_limits["max_single_stock"])
        weights = self._cap_sector(weights, selected, self.position_limits["max_sector"])
        weights = weights[weights > 0]
        return weights.sort_values(ascending=False)

    @staticmethod
    def _cap_single_stock(weights: pd.Series, cap: float) -> pd.Series:
        weights = weights.copy()
        for _ in range(20):
            over_cap = weights > cap
            if not over_cap.any():
                break
            excess = (weights[over_cap] - cap).sum()
            weights[over_cap] = cap
            under_cap = weights < cap
            if excess <= 0 or weights[under_cap].sum() <= 0:
                break
            weights[under_cap] += excess * weights[under_cap] / weights[under_cap].sum()
        return weights.clip(lower=0)

    @staticmethod
    def _cap_sector(weights: pd.Series, ranking: pd.DataFrame, cap: float) -> pd.Series:
        weights = weights.copy()
        for sector, sector_rows in ranking.loc[weights.index].groupby("sector"):
            sector_weight = weights.reindex(sector_rows.index).sum()
            if sector_weight > cap and sector_weight > 0:
                weights.loc[sector_rows.index] *= cap / sector_weight
        return weights

    @staticmethod
    def _turnover(previous: pd.Series, current: pd.Series) -> float:
        all_index = previous.index.union(current.index)
        return float((current.reindex(all_index).fillna(0) - previous.reindex(all_index).fillna(0)).abs().sum())

    @staticmethod
    def _summary(equity_curve: pd.DataFrame, initial_capital: float, rebalance_count: int) -> pd.DataFrame:
        strategy_metrics = BacktestPipeline._metrics(
            equity_curve["equity"],
            equity_curve["strategy_return"],
            initial_capital,
        )
        benchmark_metrics = BacktestPipeline._metrics(
            equity_curve["benchmark_equity"],
            equity_curve["benchmark_return"],
            initial_capital,
        )
        summary = pd.DataFrame(
            [
                {"name": "strategy", **strategy_metrics},
                {"name": "universe_equal_weight", **benchmark_metrics},
            ]
        )
        summary["rebalance_count"] = rebalance_count
        summary.loc[summary["name"] == "strategy", "avg_turnover"] = equity_curve["turnover"].replace(0, np.nan).mean()
        return summary

    @staticmethod
    def _metrics(equity: pd.Series, returns: pd.Series, initial_capital: float) -> Dict[str, float]:
        n = len(returns)
        total_return = equity.iloc[-1] / initial_capital - 1
        annual_return = (1 + total_return) ** (252 / n) - 1 if n > 0 else np.nan
        annual_volatility = returns.std(ddof=1) * np.sqrt(252) if n > 1 else np.nan
        sharpe = returns.mean() / returns.std(ddof=1) * np.sqrt(252) if n > 1 and returns.std(ddof=1) > 0 else np.nan
        drawdown = equity / equity.cummax() - 1
        return {
            "total_return": total_return,
            "annual_return": annual_return,
            "annual_volatility": annual_volatility,
            "sharpe": sharpe,
            "max_drawdown": drawdown.min(),
            "win_rate": (returns > 0).mean(),
            "final_equity": equity.iloc[-1],
            "trading_days": n,
        }

    @staticmethod
    def _save_outputs(
        summary: pd.DataFrame,
        equity_curve: pd.DataFrame,
        rebalances: pd.DataFrame,
        point_in_time_report: pd.DataFrame,
        output_dir: str,
        run_config: Dict[str, object],
        as_of_date: str,
        output_timestamp: str | None = None,
    ) -> Dict[str, str]:
        run_dir = create_timestamped_result_dir(output_dir, timestamp=output_timestamp)
        paths = {
            "config": str(run_dir / "backtest_config.csv"),
            "summary": str(run_dir / "backtest_summary.csv"),
            "equity": str(run_dir / "backtest_equity.csv"),
            "rebalances": str(run_dir / "backtest_rebalances.csv"),
            "point_in_time": str(run_dir / "backtest_point_in_time.csv"),
        }
        config = pd.DataFrame([run_config])
        summary_output = summary.copy()
        summary_output.insert(0, "as_of_date", as_of_date)

        equity_output = equity_curve.copy()
        equity_output.insert(0, "as_of_date", equity_output.index.strftime("%Y-%m-%d"))

        rebalances_output = rebalances.copy()
        if not rebalances_output.empty and "signal_date" in rebalances_output.columns:
            rebalances_output.insert(0, "as_of_date", pd.to_datetime(rebalances_output["signal_date"]).dt.strftime("%Y-%m-%d"))

        point_in_time_output = point_in_time_report.copy()
        if not point_in_time_output.empty and "signal_date" in point_in_time_output.columns:
            point_in_time_output.insert(0, "as_of_date", pd.to_datetime(point_in_time_output["signal_date"]).dt.strftime("%Y-%m-%d"))

        config.to_csv(paths["config"], index=False)
        summary_output.to_csv(paths["summary"], index=False)
        equity_output.to_csv(paths["equity"])
        rebalances_output.to_csv(paths["rebalances"], index=False)
        point_in_time_output.to_csv(paths["point_in_time"], index=False)
        return paths

    @staticmethod
    def _number(value) -> float:
        if value is None:
            return np.nan
        try:
            number = float(value)
        except (TypeError, ValueError):
            return np.nan
        return number if np.isfinite(number) else np.nan
