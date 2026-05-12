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
                output_dir=tmpdir,
                run_config={"as_of_date": "2024-03-31"},
                as_of_date="2024-03-31",
                output_timestamp="run",
            )

            summary = pd.read_csv(paths["summary"])
            equity = pd.read_csv(paths["equity"])
            rebalances = pd.read_csv(paths["rebalances"])
            point_in_time = pd.read_csv(paths["point_in_time"])

        self.assertEqual(summary.loc[0, "as_of_date"], "2024-03-31")
        self.assertEqual(equity.loc[0, "as_of_date"], "2024-03-04")
        self.assertEqual(rebalances.loc[0, "as_of_date"], "2024-03-01")
        self.assertEqual(point_in_time.loc[0, "as_of_date"], "2024-03-01")


if __name__ == "__main__":
    unittest.main()
