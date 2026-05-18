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
    DEFAULT_MIN_LISTING_DAYS = 60

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
        stamp_tax_bps: float = 5.0,
        transfer_fee_bps: float = 0.1,
        slippage_bps: float = 5.0,
        impact_bps: float = 0.0,
        max_participation_rate: float = 0.10,
        max_drawdown_budget: float | None = None,
        output_dir: str = "results",
        output_timestamp: str | None = None,
        candidate_visible_dates: Optional[Dict[str, str]] = None,
        min_listing_days: int = DEFAULT_MIN_LISTING_DAYS,
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
        peak_equity = float(initial_capital)
        max_drawdown_budget = (
            self.position_limits.get("max_drawdown_budget", 0.20)
            if max_drawdown_budget is None
            else max_drawdown_budget
        )
        previous_weights = pd.Series(dtype="float64")
        equity_records = []
        rebalance_records = []
        point_in_time_records = []
        factor_signal_records = []
        portfolio_risk_records = []

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

            price_data, financial_data = self._build_signal_data(eligible_histories, signal_date, lookback_days)
            if len(price_data) < max(3, min(top_n, 5)):
                point_in_time_records.append(point_in_time_record)
                log(f"{signal_date.date()} 可用股票过少，跳过调仓")
                continue

            available_stock_info = visible_stock_info.loc[visible_stock_info.index.intersection(price_data.keys())]
            factors = self.factor_calculator.calculate_all_factors(price_data, financial_data)
            factors = self.factor_calculator.apply_industry_adjustment(factors, available_stock_info)
            composite_score = self.factor_calculator.calculate_composite_score(factors)

            ranking = self._build_ranking(available_stock_info, factors, composite_score)
            unconstrained_desired_weights = self._target_weights(ranking, top_n)
            trading_constraints = self._trading_constraint_report(
                stock_info=available_stock_info,
                histories=eligible_histories,
                ranking=ranking,
                signal_date=signal_date,
                trade_start_date=trade_dates[0],
                min_listing_days=min_listing_days,
            )
            tradable_index = trading_constraints.loc[trading_constraints["tradable"]].index
            tradable_ranking = ranking.loc[ranking.index.intersection(tradable_index)]
            point_in_time_record.update(self._trading_constraint_counts(trading_constraints))
            point_in_time_records.append(point_in_time_record)

            desired_weights = self._target_weights(tradable_ranking, top_n)
            current_drawdown = equity / peak_equity - 1 if peak_equity > 0 else 0.0
            drawdown_budget_active = current_drawdown <= -abs(max_drawdown_budget)
            if drawdown_budget_active:
                desired_weights = desired_weights * 0.5
            blocked_buy_records = self._blocked_buy_records(
                signal_date=signal_date,
                trade_start_date=trade_dates[0],
                ranking=ranking,
                unconstrained_desired=unconstrained_desired_weights,
                trading_constraints=trading_constraints,
                eligible_universe_count=point_in_time_record["eligible_universe_count"],
            )
            weights, capacity_report = self._apply_capacity_limits(
                desired=desired_weights,
                previous=previous_weights,
                histories=eligible_histories,
                trading_constraints=trading_constraints,
                trade_start_date=trade_dates[0],
                capital=equity,
                max_participation_rate=max_participation_rate,
            )
            portfolio_risk_records.extend(
                self._portfolio_risk_rows(
                    signal_date=signal_date,
                    weights=weights,
                    ranking=ranking,
                )
            )
            selected_returns = stock_returns.reindex(columns=weights.index).loc[trade_dates].fillna(0)
            holding_returns = (1 + selected_returns).prod() - 1
            universe_returns = (1 + stock_returns.reindex(columns=ranking.index).loc[trade_dates].fillna(0)).prod() - 1
            factor_signal_records.extend(
                self._factor_signal_records(
                    signal_date=signal_date,
                    ranking=ranking,
                    factors=factors,
                    forward_returns=universe_returns,
                    selected_weights=weights,
                )
            )
            benchmark_period_returns = (
                stock_returns.reindex(columns=visible_stock_info.index)
                .loc[trade_dates]
                .mean(axis=1, skipna=True)
                .fillna(0)
            )
            cost = self._transaction_cost(
                previous=previous_weights,
                current=weights,
                commission_bps=fee_bps,
                stamp_tax_bps=stamp_tax_bps,
                transfer_fee_bps=transfer_fee_bps,
                slippage_bps=slippage_bps,
                impact_bps=impact_bps,
            )
            turnover = cost["turnover"]
            fee_rate = cost["cost_rate"]
            equity *= max(0, 1 - fee_rate)

            log(
                f"{signal_date.date()} 调仓: {len(weights)} 只, "
                f"可交易 {len(tradable_ranking)}/{len(ranking)} 只, "
                f"换手 {turnover:.2f}, 成本 {fee_rate:.4%}, "
                f"现金 {max(0, 1 - weights.sum()):.1%}"
            )

            rebalance_records.extend(blocked_buy_records)
            for rank, (stock_code, row) in enumerate(ranking.reindex(weights.index).iterrows(), 1):
                history = eligible_histories.get(stock_code)
                data_provider = history.attrs.get("data_provider", "unknown") if history is not None else "unknown"
                provider_adjustment = history.attrs.get("provider_adjustment", "") if history is not None else ""
                execution_status = self._execution_status(stock_code, capacity_report)
                rebalance_records.append(
                    {
                        "signal_date": signal_date,
                        "trade_start_date": trade_dates[0],
                        "stock_code": stock_code,
                        "stock_name": row.get("stock_name"),
                        "sector": row.get("sector"),
                        "rank": rank,
                        "desired_weight": desired_weights.get(stock_code, 0.0),
                        "target_weight": weights.loc[stock_code],
                        "capacity_limited": bool(capacity_report.get(stock_code, {}).get("capacity_limited", False)),
                        "capacity_reason": capacity_report.get(stock_code, {}).get("capacity_reason", ""),
                        "trade_action": execution_status["trade_action"],
                        "execution_status": execution_status["execution_status"],
                        "trade_constraint_reason": execution_status["trade_constraint_reason"],
                        "capacity_weight": capacity_report.get(stock_code, {}).get("capacity_weight", np.nan),
                        "estimated_trade_amount": capacity_report.get(stock_code, {}).get("estimated_trade_amount", np.nan),
                        "drawdown_budget_active": drawdown_budget_active,
                        "drawdown_at_signal": current_drawdown,
                        "buy_turnover": cost["buy_turnover"],
                        "sell_turnover": cost["sell_turnover"],
                        "transaction_cost_rate": fee_rate,
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
                peak_equity = max(peak_equity, equity)

                equity_records.append(
                    {
                        "date": trade_date,
                        "strategy_return": strategy_return,
                        "benchmark_return": benchmark_return,
                        "equity": equity,
                        "benchmark_equity": benchmark_equity,
                        "cash_weight": max(0.0, 1 - float(weights.sum())),
                        "turnover": turnover if trade_date == trade_dates[0] else 0.0,
                        "buy_turnover": cost["buy_turnover"] if trade_date == trade_dates[0] else 0.0,
                        "sell_turnover": cost["sell_turnover"] if trade_date == trade_dates[0] else 0.0,
                        "transaction_cost_rate": fee_rate if trade_date == trade_dates[0] else 0.0,
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
        factor_signals = pd.DataFrame(factor_signal_records)
        factor_diagnostics, factor_diagnostics_summary = self._factor_diagnostics(factor_signals, rebalances)
        portfolio_risk = pd.DataFrame(portfolio_risk_records)
        summary = self._summary(equity_curve, initial_capital, len(rebalance_dates))

        run_config = {
            "csv_path": csv_path,
            "start_date": start_date,
            "end_date": end_date,
            "initial_capital": initial_capital,
            "rebalance": rebalance,
            "lookback_days": lookback_days,
            "top_n": top_n,
            "commission_bps": fee_bps,
            "stamp_tax_bps": stamp_tax_bps,
            "transfer_fee_bps": transfer_fee_bps,
            "slippage_bps": slippage_bps,
            "impact_bps": impact_bps,
            "max_participation_rate": max_participation_rate,
            "max_drawdown_budget": max_drawdown_budget,
            "min_listing_days": min_listing_days,
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
            "trading_constraint_policy": (
                "exclude suspended, ST, newly listed, and limit-locked names from rebalance buys"
            ),
            "transaction_cost_policy": (
                "rebalance at next trading day to model T+1 signal execution; "
                "charge commission/transfer/slippage/impact on buys and sells, plus stamp tax on sells"
            ),
            "capacity_policy": (
                "cap each buy and sell by trade-start daily amount times max_participation_rate divided by equity"
            ),
            "risk_budget_policy": (
                "constrain single stock, sector, sub-sector, AI exposure, and approximate single-name risk contribution; "
                "halve desired gross exposure when current drawdown breaches max_drawdown_budget"
            ),
            "candidate_visible_dates": self._json_visible_dates(candidate_visible_dates),
            **stock_pool_metadata,
        }
        paths = self._save_outputs(
            summary,
            equity_curve,
            rebalances,
            point_in_time_report,
            factor_diagnostics,
            factor_diagnostics_summary,
            portfolio_risk,
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
            "factor_diagnostics": factor_diagnostics,
            "factor_diagnostics_summary": factor_diagnostics_summary,
            "portfolio_risk": portfolio_risk,
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
    def _trading_constraint_report(
        *,
        stock_info: pd.DataFrame,
        histories: Dict[str, pd.DataFrame],
        ranking: pd.DataFrame,
        signal_date: pd.Timestamp,
        trade_start_date: pd.Timestamp,
        min_listing_days: int,
    ) -> pd.DataFrame:
        rows = []
        list_dates = (
            pd.to_datetime(stock_info["list_date"], errors="coerce")
            if "list_date" in stock_info.columns
            else pd.Series(pd.NaT, index=stock_info.index)
        )
        for stock_code in ranking.index:
            reasons = []
            list_date = list_dates.get(stock_code, pd.NaT)
            if pd.notna(list_date):
                listing_age_days = int((signal_date.normalize() - pd.Timestamp(list_date).normalize()).days)
                if listing_age_days < min_listing_days:
                    reasons.append(f"listing_age_lt_{min_listing_days}d")
            else:
                listing_age_days = np.nan

            history = histories.get(stock_code)
            signal_row = BacktestPipeline._history_row_at_or_before(history, signal_date)
            trade_row = BacktestPipeline._history_row_on_or_after(history, trade_start_date)

            if signal_row is not None and BacktestPipeline._is_st(signal_row):
                reasons.append("st_at_signal")
            if trade_row is None or pd.Timestamp(trade_row.name).normalize() != trade_start_date.normalize():
                reasons.append("suspended_or_no_trade_row")
                trade_status = ""
                pct_change = np.nan
                volume = np.nan
            else:
                trade_status = str(trade_row.get("交易状态", "")).strip()
                pct_change = BacktestPipeline._number(trade_row.get("涨跌幅"))
                volume = BacktestPipeline._number(trade_row.get("成交量"))
                if trade_status and not BacktestPipeline._is_active_trade_status(trade_status):
                    reasons.append("suspended")
                if pd.notna(volume) and volume <= 0:
                    reasons.append("zero_volume")
                if BacktestPipeline._is_st(trade_row):
                    reasons.append("st_at_trade")
                if BacktestPipeline._is_limit_locked(stock_code, trade_row):
                    reasons.append("limit_locked")

            rows.append(
                {
                    "stock_code": stock_code,
                    "signal_date": signal_date,
                    "trade_start_date": trade_start_date,
                    "tradable": len(reasons) == 0,
                    "constraint_reason": "|".join(reasons),
                    "listing_age_days": listing_age_days,
                    "trade_status": trade_status,
                    "trade_pct_change": pct_change,
                    "trade_volume": volume,
                }
            )

        return pd.DataFrame(rows).set_index("stock_code") if rows else pd.DataFrame()

    @staticmethod
    def _trading_constraint_counts(trading_constraints: pd.DataFrame) -> Dict[str, int]:
        if trading_constraints.empty:
            return {
                "tradable_universe_count": 0,
                "excluded_trading_constraint_count": 0,
            }

        counts = {
            "tradable_universe_count": int(trading_constraints["tradable"].sum()),
            "excluded_trading_constraint_count": int((~trading_constraints["tradable"]).sum()),
        }
        reason_counts: Dict[str, int] = {}
        for reason_text in trading_constraints.loc[~trading_constraints["tradable"], "constraint_reason"].dropna():
            for reason in str(reason_text).split("|"):
                if reason:
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
        counts["trading_constraint_reason_counts"] = json.dumps(
            reason_counts,
            ensure_ascii=False,
            sort_keys=True,
        )
        return counts

    @staticmethod
    def _history_row_at_or_before(history: Optional[pd.DataFrame], date: pd.Timestamp) -> Optional[pd.Series]:
        if history is None or history.empty:
            return None
        rows = history.loc[history.index <= date]
        return rows.iloc[-1] if not rows.empty else None

    @staticmethod
    def _history_row_on_or_after(history: Optional[pd.DataFrame], date: pd.Timestamp) -> Optional[pd.Series]:
        if history is None or history.empty:
            return None
        rows = history.loc[history.index >= date]
        return rows.iloc[0] if not rows.empty else None

    @staticmethod
    def _is_st(row: pd.Series) -> bool:
        value = str(row.get("是否ST", "")).strip().lower()
        if value in {"1", "true", "yes", "y", "st"}:
            return True
        try:
            return float(value) == 1.0
        except ValueError:
            return False

    @staticmethod
    def _is_active_trade_status(value: object) -> bool:
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "normal"}:
            return True
        try:
            return float(text) == 1.0
        except ValueError:
            return False

    @staticmethod
    def _is_limit_locked(stock_code: str, row: pd.Series) -> bool:
        pct_change = BacktestPipeline._number(row.get("涨跌幅"))
        if pd.isna(pct_change):
            return False
        threshold = 19.8 if stock_code.startswith(("300", "301", "688")) else 9.8
        return abs(pct_change) >= threshold

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
                "market_cap": stock_info.get("market_cap", pd.Series(pd.NA, index=stock_info.index)),
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

    @staticmethod
    def _factor_signal_records(
        *,
        signal_date: pd.Timestamp,
        ranking: pd.DataFrame,
        factors: pd.DataFrame,
        forward_returns: pd.Series,
        selected_weights: pd.Series,
    ) -> List[Dict[str, object]]:
        factor_columns = [
            "composite_score",
            "momentum_score",
            "growth_score",
            "valuation_score",
            "quality_score",
            "volatility_score",
            "liquidity_score",
        ]
        records = []
        selected_set = set(selected_weights.index)
        for stock_code, row in ranking.iterrows():
            record = {
                "signal_date": signal_date,
                "stock_code": stock_code,
                "forward_return": forward_returns.get(stock_code, np.nan),
                "rank": row.get("rank"),
                "selected": stock_code in selected_set,
                "target_weight": selected_weights.get(stock_code, 0.0),
                "sector": row.get("sector"),
                "sub_sector": row.get("sub_sector"),
                "market_cap": row.get("market_cap"),
                "ai_exposure": row.get("ai_exposure"),
            }
            for column in factor_columns:
                if column == "composite_score":
                    record[column] = row.get(column)
                else:
                    record[column] = factors.get(column, pd.Series(dtype="float64")).get(stock_code, np.nan)
            records.append(record)
        return records

    @staticmethod
    def _factor_diagnostics(
        factor_signals: pd.DataFrame,
        rebalances: pd.DataFrame,
    ) -> Tuple[pd.DataFrame, str]:
        factor_columns = [
            "composite_score",
            "momentum_score",
            "growth_score",
            "valuation_score",
            "quality_score",
            "volatility_score",
            "liquidity_score",
        ]
        rows = []
        if factor_signals.empty:
            diagnostics = pd.DataFrame(
                columns=["metric", "factor", "group_type", "group_value", "value", "observations", "periods", "notes"]
            )
            return diagnostics, BacktestPipeline._factor_diagnostics_markdown(diagnostics)

        for factor in factor_columns:
            ic_values = []
            monotonic_flags = []
            spread_values = []
            for signal_date, group in factor_signals.groupby("signal_date"):
                valid = group[[factor, "forward_return"]].dropna()
                if len(valid) < 3 or valid[factor].nunique() < 2 or valid["forward_return"].nunique() < 2:
                    continue
                ic = valid[factor].rank().corr(valid["forward_return"].rank())
                if pd.notna(ic):
                    ic_values.append(float(ic))

                quantiles = BacktestPipeline._quantile_returns(valid[factor], valid["forward_return"], buckets=5)
                if len(quantiles) >= 2:
                    first = quantiles.iloc[0]
                    last = quantiles.iloc[-1]
                    spread_values.append(float(last - first))
                    monotonic_flags.append(bool(quantiles.is_monotonic_increasing or quantiles.is_monotonic_decreasing))

            rows.append(
                {
                    "metric": "rank_ic_mean",
                    "factor": factor,
                    "group_type": "",
                    "group_value": "",
                    "value": float(np.mean(ic_values)) if ic_values else np.nan,
                    "observations": len(ic_values),
                    "periods": factor_signals["signal_date"].nunique(),
                    "notes": "Spearman rank correlation between factor score and next holding-period return.",
                }
            )
            rows.append(
                {
                    "metric": "icir",
                    "factor": factor,
                    "group_type": "",
                    "group_value": "",
                    "value": BacktestPipeline._icir(ic_values),
                    "observations": len(ic_values),
                    "periods": factor_signals["signal_date"].nunique(),
                    "notes": "Mean Rank IC divided by Rank IC standard deviation.",
                }
            )
            rows.append(
                {
                    "metric": "quantile_spread_top_minus_bottom",
                    "factor": factor,
                    "group_type": "",
                    "group_value": "",
                    "value": float(np.mean(spread_values)) if spread_values else np.nan,
                    "observations": len(spread_values),
                    "periods": factor_signals["signal_date"].nunique(),
                    "notes": "Average top-minus-bottom factor quantile forward return spread.",
                }
            )
            rows.append(
                {
                    "metric": "monotonicity_rate",
                    "factor": factor,
                    "group_type": "",
                    "group_value": "",
                    "value": float(np.mean(monotonic_flags)) if monotonic_flags else np.nan,
                    "observations": len(monotonic_flags),
                    "periods": factor_signals["signal_date"].nunique(),
                    "notes": "Share of periods where factor quantile returns are monotonic.",
                }
            )

        rows.extend(BacktestPipeline._portfolio_diagnostic_rows(factor_signals, rebalances))
        rows.extend(BacktestPipeline._group_stability_rows(factor_signals))
        rows.extend(BacktestPipeline._neutralized_factor_rows(factor_signals, factor_columns))
        diagnostics = pd.DataFrame(rows)
        return diagnostics, BacktestPipeline._factor_diagnostics_markdown(diagnostics)

    @staticmethod
    def _quantile_returns(scores: pd.Series, returns: pd.Series, buckets: int = 5) -> pd.Series:
        frame = pd.DataFrame({"score": scores, "return": returns}).dropna()
        if len(frame) < buckets or frame["score"].nunique() < 2:
            return pd.Series(dtype="float64")
        bucket_count = min(buckets, frame["score"].nunique(), len(frame))
        try:
            frame["bucket"] = pd.qcut(frame["score"].rank(method="first"), bucket_count, labels=False, duplicates="drop")
        except ValueError:
            return pd.Series(dtype="float64")
        return frame.groupby("bucket")["return"].mean().sort_index()

    @staticmethod
    def _icir(ic_values: List[float]) -> float:
        if len(ic_values) < 2:
            return np.nan
        std = np.std(ic_values, ddof=1)
        if std <= 0 or pd.isna(std):
            return np.nan
        return float(np.mean(ic_values) / std)

    @staticmethod
    def _portfolio_diagnostic_rows(factor_signals: pd.DataFrame, rebalances: pd.DataFrame) -> List[Dict[str, object]]:
        rows = []
        periods = factor_signals["signal_date"].nunique() if not factor_signals.empty else 0
        if "selected" in factor_signals.columns:
            selected_returns = factor_signals.loc[factor_signals["selected"], "forward_return"].dropna()
            rows.append(
                {
                    "metric": "selected_avg_forward_return",
                    "factor": "portfolio",
                    "group_type": "",
                    "group_value": "",
                    "value": float(selected_returns.mean()) if len(selected_returns) else np.nan,
                    "observations": int(len(selected_returns)),
                    "periods": periods,
                    "notes": "Average holding-period return for selected names.",
                }
            )

        turnover_values = []
        if rebalances is not None and not rebalances.empty and {"signal_date", "stock_code", "target_weight"}.issubset(rebalances.columns):
            previous = pd.Series(dtype="float64")
            for _, group in rebalances.groupby("signal_date", sort=True):
                current = group.set_index("stock_code")["target_weight"].astype(float)
                turnover_values.append(BacktestPipeline._turnover(previous, current))
                previous = current
        rows.append(
            {
                "metric": "avg_turnover",
                "factor": "portfolio",
                "group_type": "",
                "group_value": "",
                "value": float(np.mean(turnover_values)) if turnover_values else np.nan,
                "observations": len(turnover_values),
                "periods": periods,
                "notes": "Average one-way absolute target-weight change across rebalance dates.",
            }
        )

        decay_rows = BacktestPipeline._holding_decay_rows(factor_signals)
        rows.extend(decay_rows)
        return rows

    @staticmethod
    def _holding_decay_rows(factor_signals: pd.DataFrame) -> List[Dict[str, object]]:
        rows = []
        selected = factor_signals.loc[factor_signals.get("selected", False) == True] if not factor_signals.empty else pd.DataFrame()
        if selected.empty:
            return rows
        periods = sorted(pd.to_datetime(selected["signal_date"]).dropna().unique())
        period_returns = (
            selected.groupby("signal_date")["forward_return"].mean().sort_index().reset_index(drop=True)
        )
        for lag in [1, 2, 3]:
            if len(period_returns) <= lag + 1:
                value = np.nan
                observations = 0
            else:
                value = period_returns.autocorr(lag=lag)
                observations = int(len(period_returns) - lag)
            rows.append(
                {
                    "metric": f"holding_return_autocorr_lag_{lag}",
                    "factor": "portfolio",
                    "group_type": "",
                    "group_value": "",
                    "value": float(value) if pd.notna(value) else np.nan,
                    "observations": observations,
                    "periods": len(periods),
                    "notes": "Autocorrelation of selected basket average forward returns; lower values suggest faster signal decay.",
                }
            )
        return rows

    @staticmethod
    def _group_stability_rows(factor_signals: pd.DataFrame) -> List[Dict[str, object]]:
        rows = []
        if factor_signals.empty:
            return rows

        periods = factor_signals["signal_date"].nunique()
        group_columns = [
            ("sector", "行业"),
            ("market_cap", "市值"),
            ("ai_exposure", "AI 暴露"),
        ]
        for column, label in group_columns:
            if column not in factor_signals.columns:
                continue
            group_values = factor_signals[column].fillna("unknown").replace("", "unknown")
            for group_value, group in factor_signals.assign(_group_value=group_values).groupby("_group_value"):
                valid_returns = group["forward_return"].dropna()
                rows.append(
                    {
                        "metric": "group_avg_forward_return",
                        "factor": "portfolio",
                        "group_type": column,
                        "group_value": group_value,
                        "value": float(valid_returns.mean()) if len(valid_returns) else np.nan,
                        "observations": int(len(valid_returns)),
                        "periods": int(group["signal_date"].nunique()),
                        "notes": f"Average next holding-period return by {label} group.",
                    }
                )
                selected = group["selected"].dropna() if "selected" in group.columns else pd.Series(dtype="bool")
                rows.append(
                    {
                        "metric": "group_selected_rate",
                        "factor": "portfolio",
                        "group_type": column,
                        "group_value": group_value,
                        "value": float(selected.astype(bool).mean()) if len(selected) else np.nan,
                        "observations": int(len(selected)),
                        "periods": int(group["signal_date"].nunique()),
                        "notes": f"Share of observations selected within {label} group.",
                    }
                )
        return rows

    @staticmethod
    def _neutralized_factor_rows(factor_signals: pd.DataFrame, factor_columns: List[str]) -> List[Dict[str, object]]:
        rows = []
        neutralizers = ["sector", "market_cap"]
        if factor_signals.empty or not set(neutralizers).issubset(factor_signals.columns):
            return rows

        periods = factor_signals["signal_date"].nunique()
        for factor in factor_columns:
            ic_values = []
            for _, group in factor_signals.groupby("signal_date"):
                required = [factor, "forward_return", *neutralizers]
                valid = group[required].dropna(subset=[factor, "forward_return"]).copy()
                if len(valid) < 4:
                    continue

                factor_residual = BacktestPipeline._neutralize_series_by_groups(
                    valid[factor],
                    valid[neutralizers],
                )
                return_residual = BacktestPipeline._neutralize_series_by_groups(
                    valid["forward_return"],
                    valid[neutralizers],
                )
                residuals = pd.DataFrame(
                    {
                        "factor_residual": factor_residual,
                        "return_residual": return_residual,
                    }
                ).dropna()
                if (
                    len(residuals) < 3
                    or residuals["factor_residual"].nunique() < 2
                    or residuals["return_residual"].nunique() < 2
                ):
                    continue
                ic = residuals["factor_residual"].rank().corr(residuals["return_residual"].rank())
                if pd.notna(ic):
                    ic_values.append(float(ic))

            rows.append(
                {
                    "metric": "neutralized_rank_ic_mean",
                    "factor": factor,
                    "group_type": "sector_market_cap",
                    "group_value": "residual",
                    "value": float(np.mean(ic_values)) if ic_values else np.nan,
                    "observations": len(ic_values),
                    "periods": periods,
                    "notes": "Rank IC after residualizing factor score and forward return by sector and market-cap groups.",
                }
            )
            rows.append(
                {
                    "metric": "neutralized_icir",
                    "factor": factor,
                    "group_type": "sector_market_cap",
                    "group_value": "residual",
                    "value": BacktestPipeline._icir(ic_values),
                    "observations": len(ic_values),
                    "periods": periods,
                    "notes": "Neutralized Rank IC mean divided by neutralized Rank IC standard deviation.",
                }
            )
        return rows

    @staticmethod
    def _neutralize_series_by_groups(values: pd.Series, groups: pd.DataFrame) -> pd.Series:
        frame = pd.concat(
            [
                pd.to_numeric(values, errors="coerce").rename("_value"),
                groups.fillna("unknown").astype(str),
            ],
            axis=1,
        ).dropna(subset=["_value"])
        if frame.empty:
            return pd.Series(dtype="float64")

        design_parts = [pd.Series(1.0, index=frame.index, name="_intercept")]
        for column in groups.columns:
            dummies = pd.get_dummies(frame[column], prefix=column, dtype=float)
            if dummies.shape[1] > 1:
                dummies = dummies.iloc[:, 1:]
            design_parts.append(dummies)

        design = pd.concat(design_parts, axis=1)
        y = frame["_value"].astype(float)
        try:
            beta, *_ = np.linalg.lstsq(design.to_numpy(dtype=float), y.to_numpy(dtype=float), rcond=None)
        except np.linalg.LinAlgError:
            return y - y.mean()

        fitted = pd.Series(design.to_numpy(dtype=float).dot(beta), index=design.index)
        return y - fitted

    @staticmethod
    def _factor_diagnostics_markdown(diagnostics: pd.DataFrame) -> str:
        lines = [
            "# Factor Diagnostics",
            "",
            "Diagnostics are calculated from each rebalance signal date and the next holding-period return.",
            "",
            "| Metric | Factor | Group | Value | Observations | Notes |",
            "| --- | --- | --- | ---: | ---: | --- |",
        ]
        for _, row in diagnostics.iterrows():
            value = row.get("value")
            value_text = "" if pd.isna(value) else f"{float(value):.6f}"
            group_type = row.get("group_type", "")
            group_value = row.get("group_value", "")
            group_text = "" if not group_type else f"{group_type}={group_value}"
            lines.append(
                f"| {row.get('metric')} | {row.get('factor')} | {group_text} | {value_text} | {int(row.get('observations', 0))} | {row.get('notes')} |"
            )
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _portfolio_risk_rows(
        *,
        signal_date: pd.Timestamp,
        weights: pd.Series,
        ranking: pd.DataFrame,
    ) -> List[Dict[str, object]]:
        rows = []
        if weights.empty:
            return rows
        held = ranking.reindex(weights.index).copy()
        held["target_weight"] = weights

        group_columns = [
            ("sector", "industry_exposure"),
            ("sub_sector", "sub_industry_exposure"),
            ("market_cap", "market_cap_exposure"),
            ("ai_exposure", "ai_exposure"),
        ]
        for column, metric in group_columns:
            if column not in held.columns:
                continue
            group_values = held[column].fillna("unknown").replace("", "unknown")
            for group_value, group in held.assign(_group_value=group_values).groupby("_group_value"):
                rows.append(
                    {
                        "signal_date": signal_date,
                        "metric": metric,
                        "group_type": column,
                        "group_value": group_value,
                        "value": float(group["target_weight"].sum()),
                        "weight": float(group["target_weight"].sum()),
                        "notes": "Portfolio target-weight exposure by group.",
                    }
                )

        weighted_metrics = [
            ("volatility_score", "weighted_avg_volatility_score"),
            ("momentum_score", "weighted_avg_momentum_score"),
            ("composite_score", "weighted_avg_composite_score"),
        ]
        for column, metric in weighted_metrics:
            if column in held.columns and held[column].notna().any():
                rows.append(
                    {
                        "signal_date": signal_date,
                        "metric": metric,
                        "group_type": "portfolio",
                        "group_value": "",
                        "value": float((held[column].fillna(0) * held["target_weight"]).sum()),
                        "weight": float(held["target_weight"].sum()),
                        "notes": "Target-weighted average score.",
                    }
                )

        if "momentum_score" in held.columns:
            crowded = held.loc[pd.to_numeric(held["momentum_score"], errors="coerce") >= 75]
            rows.append(
                {
                    "signal_date": signal_date,
                    "metric": "momentum_crowding_weight",
                    "group_type": "portfolio",
                    "group_value": "momentum_score_gte_75",
                    "value": float(crowded["target_weight"].sum()),
                    "weight": float(crowded["target_weight"].sum()),
                    "notes": "Portfolio weight in high-momentum names.",
                }
            )
        if "volatility_score" in held.columns:
            risk_proxy = (100 - pd.to_numeric(held["volatility_score"], errors="coerce")).clip(lower=1).fillna(50)
            risk_value = held["target_weight"] * risk_proxy
            total_risk = risk_value.sum()
            if total_risk > 0:
                for stock_code, contribution in (risk_value / total_risk).items():
                    rows.append(
                        {
                            "signal_date": signal_date,
                            "metric": "single_name_risk_contribution",
                            "group_type": "stock_code",
                            "group_value": stock_code,
                            "value": float(contribution),
                            "weight": float(held.loc[stock_code, "target_weight"]),
                            "notes": "Approximate risk contribution using target weight times inverse volatility score.",
                        }
                    )
        return rows

    def _target_weights(self, ranking: pd.DataFrame, top_n: int) -> pd.Series:
        selected = ranking.head(top_n).copy()
        if selected.empty:
            return pd.Series(dtype="float64")

        scores = selected["composite_score"].clip(lower=0)
        if scores.sum() <= 0:
            weights = pd.Series(1 / len(selected), index=selected.index)
        else:
            weights = scores / scores.sum()

        weights = self._constrained_weight_optimization(weights, selected)
        weights = weights[weights > 0]
        return weights.sort_values(ascending=False)

    def _constrained_weight_optimization(self, initial_weights: pd.Series, ranking: pd.DataFrame) -> pd.Series:
        weights = initial_weights.clip(lower=0).astype(float)
        constraints = [
            ("single", None, self.position_limits["max_single_stock"]),
            ("group", "sector", self.position_limits["max_sector"]),
            ("group", "sub_sector", self.position_limits.get("max_sub_sector", 1.0)),
            ("group", "ai_exposure", self.position_limits.get("max_ai_exposure", 1.0)),
        ]
        for _ in range(100):
            before = weights.copy()
            for constraint_type, column, cap in constraints:
                if constraint_type == "single":
                    weights = weights.clip(upper=cap)
                elif column in ranking.columns:
                    weights = self._cap_group_weight(weights, ranking, column, cap)
            weights = self._cap_single_risk_contribution(
                weights,
                ranking,
                self.position_limits.get("max_single_risk_contribution", 1.0),
            )
            weights = self._redistribute_available_weight(weights, initial_weights, ranking, constraints)
            if weights.sub(before, fill_value=0).abs().sum() < 1e-8:
                break
        for constraint_type, column, cap in constraints:
            if constraint_type == "single":
                weights = weights.clip(upper=cap)
            elif column in ranking.columns:
                weights = self._cap_group_weight(weights, ranking, column, cap)
        weights = self._cap_single_risk_contribution(
            weights,
            ranking,
            self.position_limits.get("max_single_risk_contribution", 1.0),
        )
        return weights.clip(lower=0)

    @staticmethod
    def _cap_group_weight(weights: pd.Series, ranking: pd.DataFrame, column: str, cap: float) -> pd.Series:
        weights = weights.copy()
        for _, group_rows in ranking.loc[weights.index].groupby(column):
            group_weight = weights.reindex(group_rows.index).sum()
            if group_weight > cap and group_weight > 0:
                weights.loc[group_rows.index] *= cap / group_weight
        return weights

    def _redistribute_available_weight(
        self,
        weights: pd.Series,
        preferred_weights: pd.Series,
        ranking: pd.DataFrame,
        constraints: List[Tuple[str, Optional[str], float]],
    ) -> pd.Series:
        available = max(0.0, min(1.0, float(preferred_weights.sum())) - float(weights.sum()))
        if available <= 1e-10:
            return weights

        room = (self.position_limits["max_single_stock"] - weights).astype(float)
        for constraint_type, column, cap in constraints:
            if constraint_type != "group" or column not in ranking.columns:
                continue
            for _, group_rows in ranking.loc[weights.index].groupby(column):
                group_room = cap - weights.reindex(group_rows.index).sum()
                room.loc[group_rows.index] = room.loc[group_rows.index].clip(upper=group_room)
        room = room.clip(lower=0)
        candidates = room[room > 1e-10].index
        if len(candidates) == 0:
            return weights

        tilt = preferred_weights.reindex(candidates).fillna(0).clip(lower=0)
        if tilt.sum() <= 0:
            tilt = pd.Series(1.0, index=candidates)
        additions = tilt / tilt.sum() * available
        additions = pd.Series(np.minimum(additions, room.reindex(candidates)), index=candidates)
        weights = weights.copy()
        weights.loc[candidates] += additions
        return weights

    @staticmethod
    def _cap_single_risk_contribution(weights: pd.Series, ranking: pd.DataFrame, cap: float) -> pd.Series:
        if cap >= 1 or weights.empty or "volatility_score" not in ranking.columns:
            return weights
        effective_cap = cap * 0.995
        weights = weights.copy()
        for _ in range(100):
            risk_proxy = (100 - pd.to_numeric(ranking.reindex(weights.index)["volatility_score"], errors="coerce"))
            risk_proxy = risk_proxy.clip(lower=1).fillna(50)
            risk_value = weights * risk_proxy
            total_risk = risk_value.sum()
            if total_risk <= 0:
                break
            contributions = risk_value / total_risk
            over = contributions > effective_cap
            if not over.any():
                break
            for stock_code in contributions[over].index:
                other_risk = total_risk - risk_value.loc[stock_code]
                if other_risk <= 0:
                    max_weight = 0.0
                else:
                    max_weight = effective_cap * other_risk / (
                        risk_proxy.loc[stock_code] * (1 - effective_cap)
                    )
                weights.loc[stock_code] = min(weights.loc[stock_code], max_weight)
        return weights.clip(lower=0)

    @staticmethod
    def _turnover(previous: pd.Series, current: pd.Series) -> float:
        all_index = previous.index.union(current.index)
        return float((current.reindex(all_index).fillna(0) - previous.reindex(all_index).fillna(0)).abs().sum())

    @staticmethod
    def _transaction_cost(
        *,
        previous: pd.Series,
        current: pd.Series,
        commission_bps: float,
        stamp_tax_bps: float,
        transfer_fee_bps: float,
        slippage_bps: float,
        impact_bps: float,
    ) -> Dict[str, float]:
        all_index = previous.index.union(current.index)
        delta = current.reindex(all_index).fillna(0) - previous.reindex(all_index).fillna(0)
        buy_turnover = float(delta.clip(lower=0).sum())
        sell_turnover = float((-delta.clip(upper=0)).sum())
        buy_cost_bps = commission_bps + transfer_fee_bps + slippage_bps + impact_bps
        sell_cost_bps = commission_bps + transfer_fee_bps + slippage_bps + impact_bps + stamp_tax_bps
        cost_rate = (buy_turnover * buy_cost_bps + sell_turnover * sell_cost_bps) / 10000
        return {
            "turnover": float(buy_turnover + sell_turnover),
            "buy_turnover": buy_turnover,
            "sell_turnover": sell_turnover,
            "cost_rate": float(cost_rate),
        }

    @staticmethod
    def _apply_capacity_limits(
        *,
        desired: pd.Series,
        previous: pd.Series,
        histories: Dict[str, pd.DataFrame],
        trading_constraints: pd.DataFrame,
        trade_start_date: pd.Timestamp,
        capital: float,
        max_participation_rate: float,
    ) -> Tuple[pd.Series, Dict[str, Dict[str, object]]]:
        if capital <= 0 or max_participation_rate <= 0:
            return desired.copy(), {}

        adjusted = {}
        report: Dict[str, Dict[str, object]] = {}
        all_index = previous.index.union(desired.index)
        for stock_code in all_index:
            previous_weight = float(previous.get(stock_code, 0.0))
            desired_weight = float(desired.get(stock_code, 0.0))
            delta = desired_weight - previous_weight
            amount = BacktestPipeline._trade_start_amount(histories.get(stock_code), trade_start_date)
            capacity_weight = np.inf if pd.isna(amount) else float(amount * max_participation_rate / capital)
            limited_delta = delta
            reason = ""
            trade_constraint_reason = ""
            if stock_code in trading_constraints.index:
                trade_constraint_reason = str(trading_constraints.loc[stock_code].get("constraint_reason", "") or "")
            if delta < 0 and trade_constraint_reason:
                limited_delta = 0.0
                reason = "sell_trading_constraint_blocked"
            elif np.isfinite(capacity_weight) and abs(delta) > capacity_weight:
                limited_delta = np.sign(delta) * capacity_weight
                reason = "buy_capacity_limited" if delta > 0 else "sell_capacity_limited"

            final_weight = max(0.0, previous_weight + limited_delta)
            if final_weight > 0:
                adjusted[stock_code] = final_weight
            report[stock_code] = {
                "capacity_limited": bool(reason),
                "capacity_reason": reason,
                "trade_constraint_reason": trade_constraint_reason,
                "capacity_weight": capacity_weight if np.isfinite(capacity_weight) else np.nan,
                "estimated_trade_amount": abs(limited_delta) * capital,
                "desired_weight": desired_weight,
                "previous_weight": previous_weight,
                "final_weight": final_weight,
            }

        return pd.Series(adjusted, dtype="float64").sort_values(ascending=False), report

    @staticmethod
    def _blocked_buy_records(
        *,
        signal_date: pd.Timestamp,
        trade_start_date: pd.Timestamp,
        ranking: pd.DataFrame,
        unconstrained_desired: pd.Series,
        trading_constraints: pd.DataFrame,
        eligible_universe_count: int,
    ) -> List[Dict[str, object]]:
        records = []
        if unconstrained_desired.empty or trading_constraints.empty:
            return records
        blocked_codes = [
            stock_code
            for stock_code in unconstrained_desired.index
            if stock_code in trading_constraints.index and not bool(trading_constraints.loc[stock_code, "tradable"])
        ]
        for stock_code in blocked_codes:
            row = ranking.loc[stock_code]
            constraint_reason = trading_constraints.loc[stock_code, "constraint_reason"]
            records.append(
                {
                    "signal_date": signal_date,
                    "trade_start_date": trade_start_date,
                    "stock_code": stock_code,
                    "stock_name": row.get("stock_name"),
                    "sector": row.get("sector"),
                    "rank": row.get("rank"),
                    "desired_weight": unconstrained_desired.get(stock_code, 0.0),
                    "target_weight": 0.0,
                    "capacity_limited": False,
                    "capacity_reason": "",
                    "trade_action": "buy",
                    "execution_status": "blocked_buy",
                    "trade_constraint_reason": constraint_reason,
                    "capacity_weight": np.nan,
                    "estimated_trade_amount": 0.0,
                    "buy_turnover": 0.0,
                    "sell_turnover": 0.0,
                    "transaction_cost_rate": 0.0,
                    "composite_score": row.get("composite_score"),
                    "momentum_score": row.get("momentum_score"),
                    "quality_score": row.get("quality_score"),
                    "liquidity_score": row.get("liquidity_score", 50),
                    "data_provider": "",
                    "provider_adjustment": "",
                    "holding_return": np.nan,
                    "weighted_contribution": 0.0,
                    "eligible_universe_count": eligible_universe_count,
                }
            )
        return records

    @staticmethod
    def _execution_status(stock_code: str, capacity_report: Dict[str, Dict[str, object]]) -> Dict[str, str]:
        report = capacity_report.get(stock_code, {})
        previous_weight = float(report.get("previous_weight", 0.0) or 0.0)
        desired_weight = float(report.get("desired_weight", 0.0) or 0.0)
        final_weight = float(report.get("final_weight", 0.0) or 0.0)
        if desired_weight > previous_weight:
            trade_action = "buy"
        elif desired_weight < previous_weight:
            trade_action = "sell"
        else:
            trade_action = "hold"

        capacity_reason = str(report.get("capacity_reason", "") or "")
        trade_constraint_reason = str(report.get("trade_constraint_reason", "") or "")
        if capacity_reason == "sell_trading_constraint_blocked":
            execution_status = "blocked_sell"
        elif capacity_reason in {"buy_capacity_limited", "sell_capacity_limited"}:
            execution_status = "partial_buy" if trade_action == "buy" else "partial_sell"
        elif final_weight == desired_weight:
            execution_status = "filled"
        else:
            execution_status = "partial"
        return {
            "trade_action": trade_action,
            "execution_status": execution_status,
            "trade_constraint_reason": trade_constraint_reason,
        }

    @staticmethod
    def _trade_start_amount(history: Optional[pd.DataFrame], trade_start_date: pd.Timestamp) -> float:
        row = BacktestPipeline._history_row_on_or_after(history, trade_start_date)
        if row is None or pd.Timestamp(row.name).normalize() != trade_start_date.normalize():
            return np.nan
        return BacktestPipeline._number(row.get("成交额"))

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
        factor_diagnostics: pd.DataFrame,
        factor_diagnostics_summary: str,
        portfolio_risk: pd.DataFrame,
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
            "factor_lineage": str(run_dir / "backtest_factor_lineage.csv"),
            "factor_lineage_notes": str(run_dir / "backtest_factor_lineage.md"),
            "factor_diagnostics": str(run_dir / "factor_diagnostics.csv"),
            "factor_diagnostics_summary": str(run_dir / "factor_diagnostics.md"),
            "portfolio_risk": str(run_dir / "portfolio_risk.csv"),
        }
        config = pd.DataFrame([run_config])
        summary_output = summary.copy()
        summary_output.insert(0, "as_of_date", as_of_date)
        factor_lineage = BacktestPipeline._factor_lineage(as_of_date)

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
        factor_lineage.to_csv(paths["factor_lineage"], index=False)
        Path(paths["factor_lineage_notes"]).write_text(
            BacktestPipeline._factor_lineage_markdown(factor_lineage),
            encoding="utf-8",
        )
        factor_diagnostics_output = factor_diagnostics.copy()
        if "as_of_date" not in factor_diagnostics_output.columns:
            factor_diagnostics_output.insert(0, "as_of_date", as_of_date)
        factor_diagnostics_output.to_csv(paths["factor_diagnostics"], index=False)
        Path(paths["factor_diagnostics_summary"]).write_text(
            factor_diagnostics_summary,
            encoding="utf-8",
        )
        portfolio_risk_output = portfolio_risk.copy()
        if "as_of_date" not in portfolio_risk_output.columns:
            if not portfolio_risk_output.empty and "signal_date" in portfolio_risk_output.columns:
                portfolio_risk_output.insert(
                    0,
                    "as_of_date",
                    pd.to_datetime(portfolio_risk_output["signal_date"]).dt.strftime("%Y-%m-%d"),
                )
            else:
                portfolio_risk_output.insert(0, "as_of_date", as_of_date)
        portfolio_risk_output.to_csv(paths["portfolio_risk"], index=False)
        return paths

    @staticmethod
    def _factor_lineage(as_of_date: str) -> pd.DataFrame:
        rows = [
            {
                "as_of_date": as_of_date,
                "item": "momentum_score",
                "point_in_time_status": "strict_point_in_time",
                "source": "daily history sliced to signal_date",
                "inputs": "returns_5d|returns_20d|returns_60d|return_acceleration|ma20_distance|macd_signal|trend_strength|rsi|stoch",
                "notes": "Only price rows at or before each signal_date are used.",
            },
            {
                "as_of_date": as_of_date,
                "item": "volatility_score",
                "point_in_time_status": "strict_point_in_time",
                "source": "daily history sliced to signal_date",
                "inputs": "volatility|downside_volatility|max_drawdown|atr_percent|bb_width|amplitude",
                "notes": "Risk features are calculated from the rolling historical window visible at signal_date.",
            },
            {
                "as_of_date": as_of_date,
                "item": "liquidity_score",
                "point_in_time_status": "strict_point_in_time_with_missing_current_fields",
                "source": "daily history sliced to signal_date",
                "inputs": "turnover_rate|volume_ratio|volume_momentum|amount|market_cap",
                "notes": "Turnover, volume, and amount are point-in-time daily fields; current market-cap fields are null in backtest and do not use revised/current snapshots.",
            },
            {
                "as_of_date": as_of_date,
                "item": "growth_score",
                "point_in_time_status": "proxy_point_in_time",
                "source": "price-derived proxy",
                "inputs": "returns_ytd|momentum_120d|risk_adjusted_momentum|revenue_growth|profit_growth|net_profit_margin",
                "notes": "Fundamental growth inputs are null in backtest; score falls back to price-derived point-in-time proxies.",
            },
            {
                "as_of_date": as_of_date,
                "item": "valuation_score",
                "point_in_time_status": "current_fundamental_data_disabled",
                "source": "neutral fallback",
                "inputs": "pe|pb|ps|pcf|peg",
                "notes": "Current/revised valuation fields are intentionally null in backtest, so this score is neutral unless a true point-in-time fundamental source is added later.",
            },
            {
                "as_of_date": as_of_date,
                "item": "quality_score",
                "point_in_time_status": "proxy_point_in_time",
                "source": "risk/liquidity fallback",
                "inputs": "roe|gross_margin|net_profit_margin|cash_quality|valuation_score|volatility_score|liquidity_score",
                "notes": "Fundamental quality inputs are null in backtest; score uses the model's proxy fallback from valuation/risk/liquidity scores.",
            },
            {
                "as_of_date": as_of_date,
                "item": "industry_adjustment",
                "point_in_time_status": "conditional_point_in_time",
                "source": "stock pool classification metadata",
                "inputs": "sector|industry_as_of_date|classification_as_of_date|sector_as_of_date",
                "notes": "Industry labels are masked when their as-of date is after signal_date. If the stock pool has no label as-of column, labels are current snapshot proxies and this is reported in backtest_point_in_time.csv.",
            },
            {
                "as_of_date": as_of_date,
                "item": "composite_score",
                "point_in_time_status": "mixed",
                "source": "weighted factor scores",
                "inputs": "momentum_score|quality_score|growth_score|valuation_score|volatility_score|liquidity_score",
                "notes": "Composite score mixes strict point-in-time price/risk/liquidity signals with explicit proxy or neutral fundamental components.",
            },
        ]
        return pd.DataFrame(rows)

    @staticmethod
    def _factor_lineage_markdown(factor_lineage: pd.DataFrame) -> str:
        lines = [
            "# Backtest Factor Lineage",
            "",
            "This report marks whether each backtest signal is strict point-in-time data, a point-in-time proxy, or a disabled/current-data placeholder.",
            "",
            "| Item | Status | Source | Notes |",
            "| --- | --- | --- | --- |",
        ]
        for _, row in factor_lineage.iterrows():
            lines.append(
                f"| {row['item']} | {row['point_in_time_status']} | {row['source']} | {row['notes']} |"
            )
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _number(value) -> float:
        if value is None:
            return np.nan
        try:
            number = float(value)
        except (TypeError, ValueError):
            return np.nan
        return number if np.isfinite(number) else np.nan
