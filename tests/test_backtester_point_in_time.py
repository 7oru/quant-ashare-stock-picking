import unittest
from pathlib import Path
import sys
import tempfile
import json

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
                portfolio_risk=pd.DataFrame(
                    [{"signal_date": pd.Timestamp("2024-03-01"), "metric": "industry_exposure", "value": 0.3}]
                ),
                history_fetch_log=pd.DataFrame(
                    [{"stock_code": "000001.SZ", "provider": "baostock", "cache_hit": True, "cache_path": "/tmp/cache.pkl", "rows": 60}]
                ),
                exception_log=[{"stage": "fetch_history", "stock_code": "000002.SZ", "error": "network"}],
                output_dir=tmpdir,
                run_config={
                    "as_of_date": "2024-03-31",
                    "git_commit": "abc123",
                    "stock_pool_path": "pool.csv",
                    "stock_pool_sha256": "hash",
                    "stock_pool_rows": 2,
                    "stock_pool_columns": "stock_code",
                },
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
            portfolio_risk = pd.read_csv(paths["portfolio_risk"])
            history_fetch_log = pd.read_csv(paths["history_fetch_log"])
            exception_log = json.loads(Path(paths["exception_log"]).read_text(encoding="utf-8"))
            run_metadata = json.loads(Path(paths["run_metadata"]).read_text(encoding="utf-8"))

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
        self.assertEqual(portfolio_risk.loc[0, "as_of_date"], "2024-03-01")
        self.assertEqual(portfolio_risk.loc[0, "metric"], "industry_exposure")
        self.assertEqual(history_fetch_log.loc[0, "provider"], "baostock")
        self.assertEqual(exception_log[0]["error"], "network")
        self.assertEqual(run_metadata["git_commit"], "abc123")
        self.assertEqual(run_metadata["stock_pool"]["sha256"], "hash")
        self.assertEqual(run_metadata["data_fetch"]["cache_hits"], 1)
        self.assertIn("summary", run_metadata["outputs"])

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

    def test_trading_constraint_report_excludes_untradable_names(self):
        stock_info = pd.DataFrame(
            [
                {"stock_code": "000001.SZ", "stock_name": "A", "list_date": "2020-01-01"},
                {"stock_code": "000002.SZ", "stock_name": "B", "list_date": "2024-02-15"},
                {"stock_code": "000003.SZ", "stock_name": "C", "list_date": "2020-01-01"},
                {"stock_code": "000004.SZ", "stock_name": "D", "list_date": "2020-01-01"},
                {"stock_code": "000005.SZ", "stock_name": "E", "list_date": "2020-01-01"},
            ]
        ).set_index("stock_code")
        ranking = pd.DataFrame(index=stock_info.index)
        histories = {
            "000001.SZ": self._history(["2024-03-29", "2024-04-01"], [0, 0], [1, 1], [1.0, 1.0]),
            "000002.SZ": self._history(["2024-03-29", "2024-04-01"], [0, 0], [1, 1], [1.0, 1.0]),
            "000003.SZ": self._history(["2024-03-29", "2024-04-01"], [1, 1], [1, 1], [1.0, 1.0]),
            "000004.SZ": self._history(["2024-03-29", "2024-04-01"], [0, 0], [0, 0], [1.0, 1.0]),
            "000005.SZ": self._history(["2024-03-29", "2024-04-01"], [0, 0], [1, 1], [1.0, 9.9]),
        }

        report = BacktestPipeline._trading_constraint_report(
            stock_info=stock_info,
            histories=histories,
            ranking=ranking,
            signal_date=pd.Timestamp("2024-03-29"),
            trade_start_date=pd.Timestamp("2024-04-01"),
            min_listing_days=60,
        )

        self.assertTrue(report.loc["000001.SZ", "tradable"])
        self.assertIn("listing_age_lt_60d", report.loc["000002.SZ", "constraint_reason"])
        self.assertIn("st_at_signal", report.loc["000003.SZ", "constraint_reason"])
        self.assertIn("suspended", report.loc["000004.SZ", "constraint_reason"])
        self.assertIn("limit_locked", report.loc["000005.SZ", "constraint_reason"])
        counts = BacktestPipeline._trading_constraint_counts(report)
        self.assertEqual(counts["tradable_universe_count"], 1)
        self.assertEqual(counts["excluded_trading_constraint_count"], 4)

    def test_transaction_cost_charges_sell_side_stamp_tax(self):
        previous = pd.Series({"A": 0.6, "B": 0.4})
        current = pd.Series({"A": 0.3, "C": 0.5})

        cost = BacktestPipeline._transaction_cost(
            previous=previous,
            current=current,
            commission_bps=10.0,
            stamp_tax_bps=5.0,
            transfer_fee_bps=0.1,
            slippage_bps=5.0,
            impact_bps=2.0,
        )

        self.assertAlmostEqual(cost["buy_turnover"], 0.5)
        self.assertAlmostEqual(cost["sell_turnover"], 0.7)
        self.assertAlmostEqual(cost["turnover"], 1.2)
        expected_cost = (0.5 * 17.1 + 0.7 * 22.1) / 10000
        self.assertAlmostEqual(cost["cost_rate"], expected_cost)

    def test_apply_capacity_limits_caps_buy_and_sell_turnover(self):
        previous = pd.Series({"A": 0.5})
        desired = pd.Series({"A": 0.0, "B": 0.6})
        histories = {
            "A": pd.DataFrame({"成交额": [1000.0]}, index=pd.DatetimeIndex([pd.Timestamp("2024-04-01")])),
            "B": pd.DataFrame({"成交额": [2000.0]}, index=pd.DatetimeIndex([pd.Timestamp("2024-04-01")])),
        }

        adjusted, report = BacktestPipeline._apply_capacity_limits(
            desired=desired,
            previous=previous,
            histories=histories,
            trading_constraints=pd.DataFrame(index=["A", "B"]),
            trade_start_date=pd.Timestamp("2024-04-01"),
            capital=10000.0,
            max_participation_rate=0.1,
        )

        self.assertAlmostEqual(adjusted.loc["A"], 0.49)
        self.assertAlmostEqual(adjusted.loc["B"], 0.02)
        self.assertEqual(report["A"]["capacity_reason"], "sell_capacity_limited")
        self.assertEqual(report["B"]["capacity_reason"], "buy_capacity_limited")

    def test_blocked_buy_records_and_sell_constraints_are_marked(self):
        ranking = pd.DataFrame(
            [
                {"stock_code": "A", "stock_name": "Alpha", "sector": "compute", "rank": 1, "composite_score": 90, "momentum_score": 80, "quality_score": 70, "liquidity_score": 60},
                {"stock_code": "B", "stock_name": "Beta", "sector": "power", "rank": 2, "composite_score": 80, "momentum_score": 70, "quality_score": 60, "liquidity_score": 50},
            ]
        ).set_index("stock_code")
        constraints = pd.DataFrame(
            [
                {"stock_code": "A", "tradable": False, "constraint_reason": "limit_locked"},
                {"stock_code": "B", "tradable": False, "constraint_reason": "suspended"},
            ]
        ).set_index("stock_code")

        blocked = BacktestPipeline._blocked_buy_records(
            signal_date=pd.Timestamp("2024-03-31"),
            trade_start_date=pd.Timestamp("2024-04-01"),
            ranking=ranking,
            unconstrained_desired=pd.Series({"A": 0.6}),
            trading_constraints=constraints,
            eligible_universe_count=2,
        )
        self.assertEqual(blocked[0]["execution_status"], "blocked_buy")
        self.assertEqual(blocked[0]["trade_constraint_reason"], "limit_locked")

        adjusted, report = BacktestPipeline._apply_capacity_limits(
            desired=pd.Series(dtype="float64"),
            previous=pd.Series({"B": 0.4}),
            histories={"B": pd.DataFrame({"成交额": [10000.0]}, index=pd.DatetimeIndex([pd.Timestamp("2024-04-01")]))},
            trading_constraints=constraints,
            trade_start_date=pd.Timestamp("2024-04-01"),
            capital=10000.0,
            max_participation_rate=0.1,
        )
        status = BacktestPipeline._execution_status("B", report)
        self.assertAlmostEqual(adjusted.loc["B"], 0.4)
        self.assertEqual(report["B"]["capacity_reason"], "sell_trading_constraint_blocked")
        self.assertEqual(status["execution_status"], "blocked_sell")

    def test_portfolio_risk_rows_report_exposures_and_crowding(self):
        ranking = pd.DataFrame(
            [
                {"stock_code": "A", "sector": "compute", "sub_sector": "server", "market_cap": "large", "ai_exposure": "high", "momentum_score": 80, "volatility_score": 40, "composite_score": 70},
                {"stock_code": "B", "sector": "power", "sub_sector": "grid", "market_cap": "mid", "ai_exposure": "medium", "momentum_score": 60, "volatility_score": 50, "composite_score": 65},
            ]
        ).set_index("stock_code")

        rows = BacktestPipeline._portfolio_risk_rows(
            signal_date=pd.Timestamp("2024-03-31"),
            weights=pd.Series({"A": 0.6, "B": 0.3}),
            ranking=ranking,
        )
        risk = pd.DataFrame(rows)
        sector_weights = risk.loc[risk["metric"] == "industry_exposure"].set_index("group_value")["value"]
        crowding = risk.loc[risk["metric"] == "momentum_crowding_weight", "value"].iloc[0]

        self.assertAlmostEqual(sector_weights.loc["compute"], 0.6)
        self.assertAlmostEqual(sector_weights.loc["power"], 0.3)
        self.assertAlmostEqual(crowding, 0.6)

    def test_target_weights_respect_single_sector_and_sub_sector_constraints(self):
        pipeline = BacktestPipeline()
        ranking = pd.DataFrame(
            [
                {"stock_code": "A", "sector": "compute", "sub_sector": "server", "composite_score": 100},
                {"stock_code": "B", "sector": "compute", "sub_sector": "server", "composite_score": 95},
                {"stock_code": "C", "sector": "compute", "sub_sector": "chip", "composite_score": 90},
                {"stock_code": "D", "sector": "power", "sub_sector": "grid", "composite_score": 85},
                {"stock_code": "E", "sector": "power", "sub_sector": "grid", "composite_score": 80},
            ]
        ).set_index("stock_code")

        weights = pipeline._target_weights(ranking, top_n=5)
        sector_weights = weights.groupby(ranking.loc[weights.index, "sector"]).sum()
        sub_sector_weights = weights.groupby(ranking.loc[weights.index, "sub_sector"]).sum()

        self.assertLessEqual(weights.max(), pipeline.position_limits["max_single_stock"] + 1e-8)
        self.assertLessEqual(sector_weights.max(), pipeline.position_limits["max_sector"] + 1e-8)
        self.assertLessEqual(sub_sector_weights.max(), pipeline.position_limits["max_sub_sector"] + 1e-8)

    def test_target_weights_respect_theme_and_risk_contribution_constraints(self):
        pipeline = BacktestPipeline()
        ranking = pd.DataFrame(
            [
                {"stock_code": "A", "sector": "s1", "sub_sector": "ss1", "ai_exposure": "high", "composite_score": 100, "volatility_score": 10},
                {"stock_code": "B", "sector": "s2", "sub_sector": "ss2", "ai_exposure": "high", "composite_score": 95, "volatility_score": 20},
                {"stock_code": "C", "sector": "s3", "sub_sector": "ss3", "ai_exposure": "medium", "composite_score": 90, "volatility_score": 90},
                {"stock_code": "D", "sector": "s4", "sub_sector": "ss4", "ai_exposure": "low", "composite_score": 85, "volatility_score": 80},
                {"stock_code": "E", "sector": "s5", "sub_sector": "ss5", "ai_exposure": "low", "composite_score": 80, "volatility_score": 70},
            ]
        ).set_index("stock_code")

        weights = pipeline._target_weights(ranking, top_n=5)
        ai_weights = weights.groupby(ranking.loc[weights.index, "ai_exposure"]).sum()
        risk_rows = pd.DataFrame(
            BacktestPipeline._portfolio_risk_rows(
                signal_date=pd.Timestamp("2024-03-31"),
                weights=weights,
                ranking=ranking,
            )
        )
        max_contribution = risk_rows.loc[
            risk_rows["metric"] == "single_name_risk_contribution",
            "value",
        ].max()

        self.assertLessEqual(ai_weights.max(), pipeline.position_limits["max_ai_exposure"] + 1e-8)
        self.assertLessEqual(max_contribution, pipeline.position_limits["max_single_risk_contribution"] + 1e-8)

    @staticmethod
    def _history(dates, is_st, trade_status, pct_change):
        return pd.DataFrame(
            {
                "收盘": [10.0] * len(dates),
                "成交量": [1000.0] * len(dates),
                "交易状态": trade_status,
                "是否ST": is_st,
                "涨跌幅": pct_change,
            },
            index=pd.DatetimeIndex(pd.to_datetime(dates)),
        )


if __name__ == "__main__":
    unittest.main()
