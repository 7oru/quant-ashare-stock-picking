import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.pipeline_artifacts import write_merged_scores, write_run_manifest, write_training_data


class PipelineArtifactTests(unittest.TestCase):
    def test_merged_scores_preserve_ranking_as_of_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ranking = self._ranking()
            allocation = self._allocation()
            result = write_merged_scores(
                output_dir=tmpdir,
                ranking=ranking,
                allocation=allocation,
                backtest_result=self._backtest_result(),
            )

            merged = pd.read_csv(result["merged_scores"])

        self.assertEqual(merged.loc[0, "as_of_date"], "2026-05-19")
        self.assertEqual(merged.loc[0, "backtest_as_of_date"], "2026-05-08")

    def test_training_data_preserves_feature_and_label_as_of_dates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            stock_pool_path = tmp_path / "pool.csv"
            pd.DataFrame(
                [
                    {"stock_code": "A", "stock_name": "Alpha"},
                    {"stock_code": "B", "stock_name": "Beta"},
                ]
            ).to_csv(stock_pool_path, index=False)

            result = write_training_data(
                output_dir=tmp_path / "training",
                csv_path=stock_pool_path,
                ranking=self._ranking(),
                allocation=self._allocation(),
                backtest_result=self._backtest_result(),
                run_id="run",
            )

            stock_pool = pd.read_csv(result["stock_pool_snapshot"])
            ranking_features = pd.read_csv(result["ranking_features"])
            allocation_labels = pd.read_csv(result["allocation_labels"])
            rebalance_labels = pd.read_csv(result["rebalance_labels"])
            equity_labels = pd.read_csv(result["equity_labels"])
            metadata = json.loads(Path(result["metadata"]).read_text(encoding="utf-8"))

        self.assertEqual(stock_pool.loc[0, "as_of_date"], "2026-05-19")
        self.assertEqual(ranking_features.loc[0, "as_of_date"], "2026-05-19")
        self.assertEqual(allocation_labels.loc[0, "as_of_date"], "2026-05-19")
        self.assertEqual(rebalance_labels.loc[0, "as_of_date"], "2026-05-01")
        self.assertEqual(equity_labels.loc[0, "as_of_date"], "2026-05-08")
        self.assertEqual(metadata["ranking_as_of_date"], "2026-05-19")
        self.assertEqual(metadata["backtest_as_of_date"], "2026-05-08")

    def test_run_manifest_uses_primary_result_as_of_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            stock_pool_path = tmp_path / "pool.csv"
            pd.DataFrame([{"stock_code": "A", "stock_name": "Alpha"}]).to_csv(stock_pool_path, index=False)
            primary_paths = write_merged_scores(
                output_dir=tmp_path / "results",
                ranking=self._ranking(),
                allocation=self._allocation(),
                backtest_result=self._backtest_result(),
            )
            backtest_summary = tmp_path / "backtest_summary.csv"
            pd.DataFrame([{"as_of_date": "2026-05-08", "name": "strategy"}]).to_csv(backtest_summary, index=False)

            manifest_path = write_run_manifest(
                output_path=tmp_path / "results" / "run_manifest.json",
                run_id="run",
                csv_path=stock_pool_path,
                research_paths={"ledger_dir": str(tmp_path / "audits" / "llm_research")},
                raw_output_dir=tmp_path / "audits" / "raw_outputs",
                primary_result_paths=primary_paths,
                backtest_paths={"summary": str(backtest_summary)},
                training_paths={"metadata": str(tmp_path / "results" / "training_data" / "metadata.json")},
                reconciliation_paths={"summary": str(tmp_path / "audits" / "summary.json")},
            )

            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))

        self.assertEqual(manifest["as_of_date"], "2026-05-19")
        self.assertEqual(manifest["ranking_as_of_date"], "2026-05-19")
        self.assertEqual(manifest["backtest_as_of_date"], "2026-05-08")

    @staticmethod
    def _ranking():
        ranking = pd.DataFrame(
            [
                {"stock_code": "A", "stock_name": "Alpha", "rank": 1, "composite_score": 80.0},
                {"stock_code": "B", "stock_name": "Beta", "rank": 2, "composite_score": 70.0},
            ]
        ).set_index("stock_code")
        ranking.attrs["as_of_date"] = "2026-05-19"
        return ranking

    @staticmethod
    def _allocation():
        allocation = pd.DataFrame(
            [
                {"stock_code": "A", "target_weight": 0.6, "position_value": 60.0, "recommendation": "核心配置"},
                {"stock_code": "B", "target_weight": 0.4, "position_value": 40.0, "recommendation": "卫星配置"},
            ]
        ).set_index("stock_code")
        allocation.attrs["as_of_date"] = "2026-05-19"
        return allocation

    @staticmethod
    def _backtest_result():
        return {
            "rebalances": pd.DataFrame(
                [
                    {
                        "signal_date": pd.Timestamp("2026-05-01"),
                        "stock_code": "A",
                        "rank": 1,
                        "target_weight": 0.6,
                        "composite_score": 80.0,
                    }
                ]
            ),
            "equity_curve": pd.DataFrame(
                [{"equity": 1.0}],
                index=pd.DatetimeIndex([pd.Timestamp("2026-05-08")], name="date"),
            ),
        }


if __name__ == "__main__":
    unittest.main()
