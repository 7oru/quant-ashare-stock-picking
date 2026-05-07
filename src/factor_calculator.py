"""
因子计算模块
Factor Calculation Module

计算六个维度的因子得分：动量、成长、估值、质量、波动率、流动性。
"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from .config import INDUSTRY_ADJUSTMENT


class FactorCalculator:
    """
    因子计算器

    使用稳健的横截面百分位得分，避免极端值把一整批股票的分数拉偏。
    """

    SCORE_COLUMNS = [
        "momentum_score",
        "growth_score",
        "valuation_score",
        "quality_score",
        "volatility_score",
        "liquidity_score",
    ]

    def __init__(self):
        self.factors = {}

    def calculate_all_factors(
        self,
        price_data: Dict[str, Dict],
        financial_data: Dict[str, Dict],
    ) -> pd.DataFrame:
        """
        计算所有因子得分。

        Args:
            price_data: 点时价格/技术特征
            financial_data: 估值、成交、财务特征

        Returns:
            包含原始因子和因子得分的 DataFrame
        """
        stocks = list(price_data.keys())
        financial_data = financial_data or {}
        factors = pd.DataFrame(index=stocks)

        # ========== 1. 动量因子 ==========
        factors["momentum_5d"] = self._series(
            [self._coalesce(stock, price_data, financial_data, "returns_5d") for stock in stocks],
            stocks,
        )
        factors["momentum_20d"] = self._series(
            [self._coalesce(stock, price_data, financial_data, "returns_20d") for stock in stocks],
            stocks,
        )
        missing_20d = factors["momentum_20d"].isna() & factors["momentum_5d"].notna()
        factors.loc[missing_20d, "momentum_20d"] = factors.loc[missing_20d, "momentum_5d"] * 4

        factors["momentum_60d"] = self._series(
            [self._coalesce(stock, price_data, financial_data, "returns_60d") for stock in stocks],
            stocks,
        )
        factors["momentum_120d"] = self._series(
            [self._coalesce(stock, price_data, financial_data, "returns_120d") for stock in stocks],
            stocks,
        )
        factors["returns_ytd"] = self._series(
            [self._coalesce(stock, price_data, financial_data, "returns_ytd") for stock in stocks],
            stocks,
        )

        factors["current_price"] = self._series(
            [self._number(price_data.get(stock, {}).get("current_price")) for stock in stocks],
            stocks,
        )
        factors["ma20_distance"] = self._series(
            [
                self._first_number(
                    price_data.get(stock, {}).get("ma20_distance"),
                    self._pct_distance(
                        price_data.get(stock, {}).get("current_price"),
                        price_data.get(stock, {}).get("ma20"),
                    ),
                )
                for stock in stocks
            ],
            stocks,
        )
        factors["ma60_distance"] = self._series(
            [
                self._first_number(
                    price_data.get(stock, {}).get("ma60_distance"),
                    self._pct_distance(
                        price_data.get(stock, {}).get("current_price"),
                        price_data.get(stock, {}).get("ma60"),
                    ),
                )
                for stock in stocks
            ],
            stocks,
        )
        factors["return_acceleration"] = self._series(
            [
                self._first_number(
                    price_data.get(stock, {}).get("return_acceleration"),
                    self._number(price_data.get(stock, {}).get("returns_20d"))
                    - self._number(price_data.get(stock, {}).get("returns_60d")) / 3,
                )
                for stock in stocks
            ],
            stocks,
        )

        factors["rsi"] = self._series([self._coalesce(stock, price_data, financial_data, "rsi", default=50) for stock in stocks], stocks)
        factors["stoch"] = self._series(
            [
                np.nanmean(
                    [
                        self._coalesce(stock, price_data, financial_data, "stoch_k", default=50),
                        self._coalesce(stock, price_data, financial_data, "stoch_d", default=50),
                    ]
                )
                for stock in stocks
            ],
            stocks,
        )
        factors["macd_signal"] = self._series(
            [
                self._pct_distance(
                    price_data.get(stock, {}).get("macd_histogram"),
                    price_data.get(stock, {}).get("current_price"),
                )
                for stock in stocks
            ],
            stocks,
        )
        factors["trend_strength"] = self._series(
            [self._coalesce(stock, price_data, financial_data, "trend_strength", default=0) for stock in stocks],
            stocks,
        )
        factors["price_position"] = self._series(
            [self._coalesce(stock, price_data, financial_data, "price_position", default=50) for stock in stocks],
            stocks,
        )

        # 原始风险指标先放入，给风险调整动量使用。
        factors["volatility"] = self._series(
            [self._coalesce(stock, price_data, financial_data, "volatility") for stock in stocks],
            stocks,
        )
        factors["risk_adjusted_momentum"] = (
            factors["momentum_60d"] / factors["volatility"].replace(0, np.nan)
        )

        factors["rsi_health"] = self._score_target(factors["rsi"], target=58, tolerance=24)
        factors["stoch_health"] = self._score_target(factors["stoch"], target=60, tolerance=30)
        momentum_components: List[Tuple[float, pd.Series]] = []
        self._add_component(momentum_components, 0.24, factors["momentum_20d"], self._score_high(factors["momentum_20d"]))
        self._add_component(momentum_components, 0.22, factors["momentum_60d"], self._score_high(factors["momentum_60d"]))
        self._add_component(momentum_components, 0.14, factors["return_acceleration"], self._score_high(factors["return_acceleration"]))
        self._add_component(momentum_components, 0.12, factors["ma20_distance"], self._score_high(factors["ma20_distance"]))
        self._add_component(momentum_components, 0.10, factors["macd_signal"], self._score_high(factors["macd_signal"]))
        self._add_component(momentum_components, 0.08, factors["trend_strength"], self._score_high(factors["trend_strength"]))
        self._add_component(momentum_components, 0.05, factors["rsi"], factors["rsi_health"])
        self._add_component(momentum_components, 0.05, factors["stoch"], factors["stoch_health"])
        factors["momentum_score"] = self._weighted_score(momentum_components, factors.index)

        # ========== 2. 成长因子 ==========
        factors["revenue_growth"] = self._series(
            [self._number(financial_data.get(stock, {}).get("revenue_growth_yoy")) for stock in stocks],
            stocks,
        )
        factors["profit_growth"] = self._series(
            [self._number(financial_data.get(stock, {}).get("net_profit_growth_yoy")) for stock in stocks],
            stocks,
        )
        factors["net_profit_margin"] = self._series(
            [self._number(financial_data.get(stock, {}).get("net_profit_margin")) for stock in stocks],
            stocks,
        )
        factors["growth_data_coverage"] = (
            factors[["revenue_growth", "profit_growth"]].notna().sum(axis=1) / 2
        )

        growth_proxy = self._weighted_score(
            [
                (0.40, self._score_high(factors["returns_ytd"])),
                (0.30, self._score_high(factors["momentum_120d"])),
                (0.30, self._score_high(factors["risk_adjusted_momentum"])),
            ],
            factors.index,
        )

        fundamental_growth_components: List[Tuple[float, pd.Series]] = []
        self._add_component(fundamental_growth_components, 0.45, factors["revenue_growth"], self._score_high(factors["revenue_growth"]))
        self._add_component(fundamental_growth_components, 0.45, factors["profit_growth"], self._score_high(factors["profit_growth"]))
        self._add_component(fundamental_growth_components, 0.10, factors["net_profit_margin"], self._score_high(factors["net_profit_margin"]))
        if fundamental_growth_components:
            fundamental_growth = self._weighted_score(fundamental_growth_components, factors.index)
            factors["growth_score"] = 0.75 * fundamental_growth + 0.25 * growth_proxy
        else:
            factors["growth_score"] = growth_proxy

        # ========== 3. 估值因子（越低越好） ==========
        factors["pe"] = self._positive_series(
            [financial_data.get(stock, {}).get("pe_ttm") for stock in stocks],
            stocks,
        )
        factors["pb"] = self._positive_series(
            [financial_data.get(stock, {}).get("pb") for stock in stocks],
            stocks,
        )
        factors["ps"] = self._positive_series(
            [financial_data.get(stock, {}).get("ps") for stock in stocks],
            stocks,
        )
        factors["pcf"] = self._positive_series(
            [financial_data.get(stock, {}).get("pcf") for stock in stocks],
            stocks,
        )
        factors["peg"] = self._series(
            [self._estimate_peg(stock, financial_data, factors) for stock in stocks],
            stocks,
        )

        valuation_components: List[Tuple[float, pd.Series]] = []
        self._add_component(valuation_components, 0.28, factors["pe"], self._score_low(factors["pe"]))
        self._add_component(valuation_components, 0.24, factors["pb"], self._score_low(factors["pb"]))
        self._add_component(valuation_components, 0.18, factors["ps"], self._score_low(factors["ps"]))
        self._add_component(valuation_components, 0.15, factors["pcf"], self._score_low(factors["pcf"]))
        self._add_component(valuation_components, 0.15, factors["peg"], self._score_low(factors["peg"]))
        factors["valuation_score"] = self._weighted_score(valuation_components, factors.index)

        # ========== 4. 波动率/风险因子（越低越好） ==========
        factors["downside_volatility"] = self._series(
            [self._coalesce(stock, price_data, financial_data, "downside_volatility") for stock in stocks],
            stocks,
        )
        factors["max_dd"] = self._series(
            [self._coalesce(stock, price_data, financial_data, "max_drawdown") for stock in stocks],
            stocks,
        )
        factors["atr_percent"] = self._series(
            [self._coalesce(stock, price_data, financial_data, "atr_percent") for stock in stocks],
            stocks,
        )
        factors["bb_width"] = self._series(
            [self._coalesce(stock, price_data, financial_data, "bb_width") for stock in stocks],
            stocks,
        )
        factors["amplitude"] = self._series(
            [self._number(financial_data.get(stock, {}).get("amplitude")) for stock in stocks],
            stocks,
        )

        volatility_components: List[Tuple[float, pd.Series]] = []
        self._add_component(volatility_components, 0.28, factors["volatility"], self._score_low(factors["volatility"]))
        self._add_component(volatility_components, 0.22, factors["downside_volatility"], self._score_low(factors["downside_volatility"]))
        self._add_component(volatility_components, 0.22, factors["max_dd"], self._score_low(factors["max_dd"]))
        self._add_component(volatility_components, 0.16, factors["atr_percent"], self._score_low(factors["atr_percent"]))
        self._add_component(volatility_components, 0.08, factors["bb_width"], self._score_low(factors["bb_width"]))
        self._add_component(volatility_components, 0.04, factors["amplitude"], self._score_low(factors["amplitude"]))
        factors["volatility_score"] = self._weighted_score(volatility_components, factors.index)

        # ========== 5. 流动性因子 ==========
        factors["turnover_rate"] = self._series(
            [
                self._first_number(
                    financial_data.get(stock, {}).get("turnover_rate_f"),
                    financial_data.get(stock, {}).get("turnover_rate"),
                    price_data.get(stock, {}).get("turnover_rate"),
                )
                for stock in stocks
            ],
            stocks,
        )
        factors["volume_ratio"] = self._series(
            [self._coalesce(stock, price_data, financial_data, "volume_ratio") for stock in stocks],
            stocks,
        )
        factors["volume_momentum"] = self._series(
            [self._coalesce(stock, price_data, financial_data, "volume_momentum") for stock in stocks],
            stocks,
        )
        factors["market_cap"] = self._positive_series(
            [
                self._first_number(
                    financial_data.get(stock, {}).get("circ_market_cap"),
                    financial_data.get(stock, {}).get("market_cap"),
                )
                for stock in stocks
            ],
            stocks,
        )
        factors["amount"] = self._positive_series(
            [price_data.get(stock, {}).get("amount") for stock in stocks],
            stocks,
        )

        liquidity_components: List[Tuple[float, pd.Series]] = []
        self._add_component(
            liquidity_components,
            0.30,
            factors["turnover_rate"],
            self._score_high(np.log1p(factors["turnover_rate"].clip(lower=0))),
        )
        self._add_component(
            liquidity_components,
            0.20,
            factors["volume_ratio"],
            self._score_target(factors["volume_ratio"], target=1.5, tolerance=1.2),
        )
        self._add_component(
            liquidity_components,
            0.15,
            factors["volume_momentum"],
            self._score_target(factors["volume_momentum"], target=1.2, tolerance=0.8),
        )
        self._add_component(
            liquidity_components,
            0.20,
            factors["market_cap"],
            self._score_high(np.log1p(factors["market_cap"].clip(lower=0))),
        )
        self._add_component(
            liquidity_components,
            0.15,
            factors["amount"],
            self._score_high(np.log1p(factors["amount"].clip(lower=0))),
        )
        factors["liquidity_score"] = self._weighted_score(liquidity_components, factors.index)

        # ========== 6. 质量因子 ==========
        factors["roe"] = self._series(
            [self._number(financial_data.get(stock, {}).get("roe")) for stock in stocks],
            stocks,
        )
        factors["gross_margin"] = self._series(
            [self._number(financial_data.get(stock, {}).get("gross_margin")) for stock in stocks],
            stocks,
        )
        factors["cash_quality"] = self._series(
            [self._number(financial_data.get(stock, {}).get("cash_flow_to_net_profit")) for stock in stocks],
            stocks,
        )
        factors["quality_data_coverage"] = (
            factors[["roe", "gross_margin", "net_profit_margin", "cash_quality"]].notna().sum(axis=1) / 4
        )

        quality_components: List[Tuple[float, pd.Series]] = []
        self._add_component(quality_components, 0.35, factors["roe"], self._score_high(factors["roe"]))
        self._add_component(quality_components, 0.25, factors["gross_margin"], self._score_high(factors["gross_margin"]))
        self._add_component(quality_components, 0.20, factors["net_profit_margin"], self._score_high(factors["net_profit_margin"]))
        self._add_component(quality_components, 0.20, factors["cash_quality"], self._score_high(factors["cash_quality"]))
        if quality_components:
            fundamental_quality = self._weighted_score(quality_components, factors.index)
            factors["quality_score"] = (
                0.75 * fundamental_quality
                + 0.15 * factors["volatility_score"]
                + 0.10 * factors["liquidity_score"]
            )
        else:
            factors["quality_score"] = (
                0.45 * factors["valuation_score"]
                + 0.35 * factors["volatility_score"]
                + 0.20 * factors["liquidity_score"]
            )

        for column in self.SCORE_COLUMNS:
            if column in factors.columns:
                factors[column] = factors[column].fillna(50).clip(0, 100)

        self.factors = factors
        return factors

    def _normalize(self, series: pd.Series) -> pd.Series:
        """
        兼容旧接口：高值高分的稳健横截面百分位得分。
        """
        return self._score_high(series)

    def apply_industry_adjustment(
        self,
        factors: pd.DataFrame,
        stock_info: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        应用行业调整系数。
        """
        adjusted = factors.copy()

        for idx in adjusted.index:
            sector = stock_info.loc[idx, "sector"] if idx in stock_info.index else None

            if sector in INDUSTRY_ADJUSTMENT:
                adj = INDUSTRY_ADJUSTMENT[sector]
                for factor in ["valuation", "growth", "quality"]:
                    column = factor + "_score"
                    if column in adjusted.columns:
                        adjusted.loc[idx, column] *= adj.get(factor, 1.0)

        for column in self.SCORE_COLUMNS:
            if column in adjusted.columns:
                adjusted[column] = adjusted[column].clip(0, 100)

        return adjusted

    def calculate_composite_score(self, factors: pd.DataFrame) -> pd.Series:
        """
        计算综合得分。
        """
        from .config import FACTOR_WEIGHTS

        weighted_columns = [
            (factor_name, weight, f"{factor_name}_score")
            for factor_name, weight in FACTOR_WEIGHTS.items()
            if f"{factor_name}_score" in factors.columns and weight > 0
        ]
        if not weighted_columns:
            return pd.Series(50.0, index=factors.index)

        total_weight = sum(weight for _, weight, _ in weighted_columns)
        composite = pd.Series(0.0, index=factors.index)
        for _, weight, column in weighted_columns:
            composite += (weight / total_weight) * factors[column].fillna(50)

        return composite.clip(0, 100)

    def _coalesce(
        self,
        stock: str,
        price_data: Dict[str, Dict],
        financial_data: Dict[str, Dict],
        key: str,
        default: float = np.nan,
    ) -> float:
        return self._first_number(
            financial_data.get(stock, {}).get(key),
            price_data.get(stock, {}).get(key),
            default=default,
        )

    @staticmethod
    def _first_number(*values, default: float = np.nan) -> float:
        for value in values:
            number = FactorCalculator._number(value)
            if pd.notna(number):
                return number
        return default

    @staticmethod
    def _number(value) -> float:
        if value is None:
            return np.nan
        try:
            number = float(value)
        except (TypeError, ValueError):
            return np.nan
        return number if np.isfinite(number) else np.nan

    @staticmethod
    def _series(values, index) -> pd.Series:
        return pd.Series(values, index=index, dtype="float64").replace([np.inf, -np.inf], np.nan)

    def _positive_series(self, values, index) -> pd.Series:
        series = self._series(values, index)
        return series.where(series > 0)

    @staticmethod
    def _pct_distance(value, base) -> float:
        value = FactorCalculator._number(value)
        base = FactorCalculator._number(base)
        if pd.isna(value) or pd.isna(base) or base == 0:
            return np.nan
        return (value / base - 1) * 100

    def _estimate_peg(self, stock: str, financial_data: Dict[str, Dict], factors: pd.DataFrame) -> float:
        peg = self._number(financial_data.get(stock, {}).get("peg"))
        if pd.isna(peg):
            pe = factors.loc[stock, "pe"] if "pe" in factors.columns else np.nan
            profit_growth = factors.loc[stock, "profit_growth"] if "profit_growth" in factors.columns else np.nan
            if pd.notna(pe) and pd.notna(profit_growth) and profit_growth > 0:
                peg = pe / profit_growth
        if pd.isna(peg) or peg <= 0 or peg > 10:
            return np.nan
        return float(peg)

    def _add_component(
        self,
        components: List[Tuple[float, pd.Series]],
        weight: float,
        raw: pd.Series,
        score: pd.Series,
    ) -> None:
        if self._has_signal(raw):
            components.append((weight, score))

    @staticmethod
    def _has_signal(series: pd.Series) -> bool:
        cleaned = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        return len(cleaned) >= 2 and cleaned.nunique() > 1

    @staticmethod
    def _neutral(index) -> pd.Series:
        return pd.Series(50.0, index=index)

    def _score_high(self, series: pd.Series) -> pd.Series:
        values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
        score = self._neutral(values.index)
        valid = values.dropna()
        if len(valid) < 2 or valid.nunique() <= 1:
            return score
        score.loc[valid.index] = valid.rank(pct=True, method="average") * 100
        return score.clip(0, 100)

    def _score_low(self, series: pd.Series) -> pd.Series:
        return (100 - self._score_high(series)).clip(0, 100)

    def _score_target(self, series: pd.Series, target: float, tolerance: float) -> pd.Series:
        values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
        score = self._neutral(values.index)
        if tolerance <= 0:
            return score
        valid = values.dropna()
        distance = (valid - target).abs() / tolerance
        score.loc[valid.index] = (100 - distance * 50).clip(0, 100)
        return score

    def _weighted_score(
        self,
        components: List[Tuple[float, pd.Series]],
        index,
    ) -> pd.Series:
        if not components:
            return self._neutral(index)

        total_weight = sum(weight for weight, _ in components)
        if total_weight <= 0:
            return self._neutral(index)

        score = pd.Series(0.0, index=index)
        for weight, component in components:
            score += (weight / total_weight) * component.reindex(index).fillna(50)
        return score.clip(0, 100)
