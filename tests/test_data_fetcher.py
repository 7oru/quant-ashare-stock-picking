import unittest
from pathlib import Path

from src.data_fetcher import StockDataFetcher


class DataFetcherTests(unittest.TestCase):
    def test_calendar_lookback_days_adds_trading_day_slack(self):
        self.assertEqual(StockDataFetcher._calendar_lookback_days(60), 138)
        self.assertEqual(StockDataFetcher._calendar_lookback_days(180), 354)

    def test_real_run_default_lookback_covers_long_momentum_factors(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "run_real_pipeline.sh"
        self.assertIn('LOOKBACK_DAYS="${LOOKBACK_DAYS:-180}"', script.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
