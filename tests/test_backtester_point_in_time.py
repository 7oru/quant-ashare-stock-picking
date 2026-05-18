import unittest
from pathlib import Path
import sys
import tempfile

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtester import BacktestPipeline


class BacktesterPointInTimeTests(unittest.TestCase):
    def test_visible_stock_info_filters_future_pool_entries_and_candidates(self):
        stock_info = pd.DataFrame(
            [
                {
                    "stock_code": "000001.SZ",
                    "stock_name": "A",
                    "sector": "old sector",
                    "sub_sector": "old sub",
                    "ai_exposure": "high",
                    "list_date": "2000-01-01",
                    "pool_entry_date": "2024-01-01",
                    "industry_as_of_date": "2024-01-01",
                },
                {
                    "stock_code": "000002.SZ",
                    "stock_name": "B",
                    "sector": "future pool",
                    "sub_sector": "future pool",
                    "ai_exposure": "high",
                    "list_date": "2000-01-01",
                    "pool_entry_date": "2024-06-01",
                    "industry_as_of_date": "2024-01-01",
                },
                {
                    "stock_code": "000003.SZ",
                    "stock_name": "C",
                    "sector": "candidate",
                    "sub_sector": "candidate",
                    "ai_exposure": "medium",
                    "list_date": "2000-01-01",
                    "pool_entry_date": "2024-01-01",
                    "industry_as_of_date": "2024-01-01",
                },
                {
                    "stock_code": "000004.SZ",
                    "stock_name": "D",
                    "sector": "not listed",
                    "sub_sector": "not listed",
                    "ai_exposure": "low",
                    "list_date": "2024-06-01",
                    "pool_entry_date": "2024-01-01",
                    "industry_as_of_date": "2024-01-01",
                },
            ]
        ).set_index("stock_code")

        visible, record = BacktestPipeline._visible_stock_info(
            stock_info,
            pd.Timestamp("2024-03-01"),
            {"000003.SZ": pd.Timestamp("2024-04-01")},
        )

        self.assertEqual(visible.index.tolist(), ["000001.SZ"])
        self.assertEqual(record["eligible_universe_count"], 1)
        self.assertEqual(record["excluded_stock_pool_not_visible_count"], 1)
        self.assertEqual(record["excluded_llm_candidate_not_visible_count"], 1)
        self.assertEqual(record["excluded_not_listed_count"], 1)

    def test_visible_stock_info_masks_future_industry_labels(self):
        stock_info = pd.DataFrame(
            [
                {
                    "stock_code": "000001.SZ",
                    "stock_name": "A",
                    "sector": "visible sector",
                    "sub_sector": "visible sub",
                    "ai_exposure": "high",
                    "list_date": "2000-01-01",
                    "industry_as_of_date": "2024-01-01",
                },
                {
                    "stock_code": "000002.SZ",
                    "stock_name": "B",
                    "sector": "future sector",
                    "sub_sector": "future sub",
                    "ai_exposure": "medium",
                    "list_date": "2000-01-01",
                    "industry_as_of_date": "2024-06-01",
                },
            ]
        ).set_index("stock_code")

        visible, record = BacktestPipeline._visible_stock_info(
            stock_info,
            pd.Timestamp("2024-03-01"),
            {},
        )

        self.assertEqual(visible.loc["000001.SZ", "sector"], "visible sector")
        self.assertTrue(pd.isna(visible.loc["000002.SZ", "sector"]))
        self.assertTrue(pd.isna(visible.loc["000002.SZ", "sub_sector"]))
        self.assertTrue(pd.isna(visible.loc["000002.SZ", "ai_exposure"]))
        self.assertEqual(record["future_industry_label_count"], 1)

    def test_save_outputs_adds_as_of_date_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = BacktestPipeline._save_outputs(
                summary=pd.DataFrame([{"name": "strategy", "total_return": 0.1}]),
                equity_curve=pd.DataFrame(
                    [{"strategy_return": 0.01, "equity": 101.0}],
                    index=pd.DatetimeIndex([pd.Timestamp("2024-03-04")], name="date"),
                ),
                rebalances=pd.DataFrame(
                    [{"signal_date": pd.Timestamp("2024-03-01"), "stock_code": "000001.SZ"}]
                ),
                point_in_time_report=pd.DataFrame(
                    [{"signal_date": pd.Timestamp("2024-03-01"), "eligible_universe_count": 1}]
                ),
                factor_diagnostics=pd.DataFrame(
                    [{"metric": "rank_ic_mean", "factor": "momentum_score", "value": 0.1, "observations": 1, "periods": 1, "notes": ""}]
                ),
                factor_diagnostics_summary="# Factor Diagnostics\n",
                output_dir=tmpdir,
                run_config={"as_of_date": "2024-03-31"},
                as_of_date="2024-03-31",
                output_timestamp="run",
            )

            summary = pd.read_csv(paths["summary"])
            equity = pd.read_csv(paths["equity"])
            rebalances = pd.read_csv(paths["rebalances"])
            point_in_time = pd.read_csv(paths["point_in_time"])
            factor_lineage = pd.read_csv(paths["factor_lineage"])
            factor_lineage_notes = Path(paths["factor_lineage_notes"]).read_text(encoding="utf-8")
            factor_diagnostics = pd.read_csv(paths["factor_diagnostics"])
            factor_diagnostics_summary = Path(paths["factor_diagnostics_summary"]).read_text(encoding="utf-8")

        self.assertEqual(summary.loc[0, "as_of_date"], "2024-03-31")
        self.assertEqual(equity.loc[0, "as_of_date"], "2024-03-04")
        self.assertEqual(rebalances.loc[0, "as_of_date"], "2024-03-01")
        self.assertEqual(point_in_time.loc[0, "as_of_date"], "2024-03-01")
        self.assertIn("momentum_score", factor_lineage["item"].tolist())
        self.assertIn("proxy_point_in_time", factor_lineage["point_in_time_status"].tolist())
        self.assertIn("Backtest Factor Lineage", factor_lineage_notes)
        self.assertEqual(factor_diagnostics.loc[0, "as_of_date"], "2024-03-31")
        self.assertEqual(factor_diagnostics.loc[0, "metric"], "rank_ic_mean")
        self.assertIn("Factor Diagnostics", factor_diagnostics_summary)

    def test_factor_lineage_marks_strict_and_proxy_factors(self):
        lineage = BacktestPipeline._factor_lineage("2024-03-31")
        statuses = dict(zip(lineage["item"], lineage["point_in_time_status"]))

        self.assertEqual(statuses["momentum_score"], "strict_point_in_time")
        self.assertEqual(statuses["volatility_score"], "strict_point_in_time")
        self.assertEqual(statuses["growth_score"], "proxy_point_in_time")
        self.assertEqual(statuses["quality_score"], "proxy_point_in_time")
        self.assertEqual(statuses["valuation_score"], "current_fundamental_data_disabled")

    def test_factor_diagnostics_calculates_rank_ic_and_turnover(self):
        factor_signals = pd.DataFrame(
            [
                {"signal_date": "2024-03-31", "stock_code": "A", "sector": "compute", "market_cap": "large", "ai_exposure": "high", "composite_score": 90, "momentum_score": 90, "growth_score": 50, "valuation_score": 50, "quality_score": 50, "volatility_score": 50, "liquidity_score": 50, "forward_return": 0.10, "selected": True, "target_weight": 0.6},
                {"signal_date": "2024-03-31", "stock_code": "B", "sector": "compute", "market_cap": "mid", "ai_exposure": "medium", "composite_score": 70, "momentum_score": 70, "growth_score": 50, "valuation_score": 50, "quality_score": 50, "volatility_score": 50, "liquidity_score": 50, "forward_return": 0.05, "selected": True, "target_weight": 0.4},
                {"signal_date": "2024-03-31", "stock_code": "C", "sector": "power", "market_cap": "small", "ai_exposure": "low", "composite_score": 30, "momentum_score": 30, "growth_score": 50, "valuation_score": 50, "quality_score": 50, "volatility_score": 50, "liquidity_score": 50, "forward_return": -0.02, "selected": False, "target_weight": 0.0},
                {"signal_date": "2024-04-30", "stock_code": "A", "sector": "compute", "market_cap": "large", "ai_exposure": "high", "composite_score": 20, "momentum_score": 20, "growth_score": 50, "valuation_score": 50, "quality_score": 50, "volatility_score": 50, "liquidity_score": 50, "forward_return": -0.03, "selected": False, "target_weight": 0.0},
                {"signal_date": "2024-04-30", "stock_code": "B", "sector": "compute", "market_cap": "mid", "ai_exposure": "medium", "composite_score": 60, "momentum_score": 60, "growth_score": 50, "valuation_score": 50, "quality_score": 50, "volatility_score": 50, "liquidity_score": 50, "forward_return": 0.02, "selected": True, "target_weight": 0.5},
                {"signal_date": "2024-04-30", "stock_code": "C", "sector": "power", "market_cap": "small", "ai_exposure": "low", "composite_score": 80, "momentum_score": 80, "growth_score": 50, "valuation_score": 50, "quality_score": 50, "volatility_score": 50, "liquidity_score": 50, "forward_return": 0.08, "selected": True, "target_weight": 0.5},
            ]
        )
        rebalances = factor_signals.loc[factor_signals["selected"], ["signal_date", "stock_code", "target_weight"]]

        diagnostics, summary = BacktestPipeline._factor_diagnostics(factor_signals, rebalances)
        composite_rank_ic = diagnostics.loc[
            (diagnostics["metric"] == "rank_ic_mean") & (diagnostics["factor"] == "composite_score"),
            "value",
        ].iloc[0]
        avg_turnover = diagnostics.loc[
            (diagnostics["metric"] == "avg_turnover") & (diagnostics["factor"] == "portfolio")
        ]

        self.assertGreater(composite_rank_ic, 0)
        self.assertFalse(avg_turnover.empty)
        group_rows = diagnostics.loc[diagnostics["metric"] == "group_avg_forward_return"]
        self.assertIn("sector", group_rows["group_type"].tolist())
        self.assertIn("market_cap", group_rows["group_type"].tolist())
        self.assertIn("ai_exposure", group_rows["group_type"].tolist())
        self.assertIn("sector=compute", summary)
        self.assertIn("Factor Diagnostics", summary)

    def test_factor_diagnostics_reports_sector_market_cap_neutralized_ic(self):
        factor_signals = pd.DataFrame(
            [
                {"signal_date": "2024-03-31", "stock_code": "A", "sector": "compute", "market_cap": "large", "ai_exposure": "high", "composite_score": 90, "momentum_score": 90, "growth_score": 50, "valuation_score": 50, "quality_score": 50, "volatility_score": 50, "liquidity_score": 50, "forward_return": 0.10, "selected": True, "target_weight": 0.5},
                {"signal_date": "2024-03-31", "stock_code": "B", "sector": "compute", "market_cap": "large", "ai_exposure": "high", "composite_score": 80, "momentum_score": 80, "growth_score": 50, "valuation_score": 50, "quality_score": 50, "volatility_score": 50, "liquidity_score": 50, "forward_return": 0.08, "selected": True, "target_weight": 0.5},
                {"signal_date": "2024-03-31", "stock_code": "C", "sector": "power", "market_cap": "small", "ai_exposure": "low", "composite_score": 40, "momentum_score": 40, "growth_score": 50, "valuation_score": 50, "quality_score": 50, "volatility_score": 50, "liquidity_score": 50, "forward_return": 0.02, "selected": False, "target_weight": 0.0},
                {"signal_date": "2024-03-31", "stock_code": "D", "sector": "power", "market_cap": "small", "ai_exposure": "low", "composite_score": 30, "momentum_score": 30, "growth_score": 50, "valuation_score": 50, "quality_score": 50, "volatility_score": 50, "liquidity_score": 50, "forward_return": 0.01, "selected": False, "target_weight": 0.0},
                {"signal_date": "2024-04-30", "stock_code": "A", "sector": "compute", "market_cap": "large", "ai_exposure": "high", "composite_score": 92, "momentum_score": 92, "growth_score": 50, "valuation_score": 50, "quality_score": 50, "volatility_score": 50, "liquidity_score": 50, "forward_return": 0.11, "selected": True, "target_weight": 0.5},
                {"signal_date": "2024-04-30", "stock_code": "B", "sector": "compute", "market_cap": "large", "ai_exposure": "high", "composite_score": 82, "momentum_score": 82, "growth_score": 50, "valuation_score": 50, "quality_score": 50, "volatility_score": 50, "liquidity_score": 50, "forward_return": 0.09, "selected": True, "target_weight": 0.5},
                {"signal_date": "2024-04-30", "stock_code": "C", "sector": "power", "market_cap": "small", "ai_exposure": "low", "composite_score": 42, "momentum_score": 42, "growth_score": 50, "valuation_score": 50, "quality_score": 50, "volatility_score": 50, "liquidity_score": 50, "forward_return": 0.03, "selected": False, "target_weight": 0.0},
                {"signal_date": "2024-04-30", "stock_code": "D", "sector": "power", "market_cap": "small", "ai_exposure": "low", "composite_score": 32, "momentum_score": 32, "growth_score": 50, "valuation_score": 50, "quality_score": 50, "volatility_score": 50, "liquidity_score": 50, "forward_return": 0.02, "selected": False, "target_weight": 0.0},
            ]
        )
        rebalances = factor_signals.loc[factor_signals["selected"], ["signal_date", "stock_code", "target_weight"]]

        diagnostics, summary = BacktestPipeline._factor_diagnostics(factor_signals, rebalances)
        neutralized = diagnostics.loc[
            (diagnostics["metric"] == "neutralized_rank_ic_mean")
            & (diagnostics["factor"] == "composite_score")
        ].iloc[0]

        self.assertEqual(neutralized["group_type"], "sector_market_cap")
        self.assertEqual(neutralized["group_value"], "residual")
        self.assertEqual(neutralized["observations"], 2)
        self.assertGreater(neutralized["value"], 0)
        self.assertIn("neutralized_rank_ic_mean", summary)


if __name__ == "__main__":
    unittest.main()
