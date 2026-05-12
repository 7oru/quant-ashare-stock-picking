import unittest
from unittest.mock import patch

import pandas as pd

from src.market_data_providers import (
    BaoStockHistoricalDataFetcher,
    BaseHistoricalDataFetcher,
    YahooFinanceHistoricalDataFetcher,
    baostock_symbol_from_ashare_symbol,
    default_historical_fetchers,
    get_hist_dataframe_with_fallback,
    yahoo_symbol_from_ashare_symbol,
)


class FakeDataCache:
    def get_or_fetch_dataframe(self, namespace, key, fetcher):
        return fetcher(), False, f"/tmp/{namespace}/{key['api']}.pkl"


class FakeFetcher(BaseHistoricalDataFetcher):
    def __init__(self, provider_name, frame=None, error=None):
        self.provider_name = provider_name
        self.frame = frame
        self.error = error

    def provider_symbol(self, symbol: str) -> str:
        return f"{self.provider_name}:{symbol}"

    def fetch(self, *, symbol: str, start_date: str, end_date: str, adjust: str) -> pd.DataFrame:
        if self.error:
            raise RuntimeError(self.error)
        output = self.frame.copy()
        output.attrs["data_provider"] = self.provider_name
        output.attrs["provider_adjustment"] = adjust
        return output


def sample_history():
    return pd.DataFrame(
        {
            "日期": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "股票代码": ["603019", "603019"],
            "开盘": [10.0, 10.2],
            "收盘": [10.2, 10.4],
            "最高": [10.3, 10.5],
            "最低": [9.9, 10.1],
            "成交量": [1000, 1200],
            "成交额": [10000, 12000],
            "振幅": [4.0, 3.9],
            "涨跌幅": [1.0, 2.0],
            "涨跌额": [0.1, 0.2],
            "换手率": [1.1, 1.2],
            "交易状态": ["1", "1"],
            "是否ST": ["0", "0"],
        }
    )


class MarketDataProviderTests(unittest.TestCase):
    def test_yahoo_symbol_from_ashare_symbol(self):
        self.assertEqual(yahoo_symbol_from_ashare_symbol("603019"), "603019.SS")
        self.assertEqual(yahoo_symbol_from_ashare_symbol("603019.SH"), "603019.SS")
        self.assertEqual(yahoo_symbol_from_ashare_symbol("000063"), "000063.SZ")
        self.assertEqual(yahoo_symbol_from_ashare_symbol("300750.SZ"), "300750.SZ")

    def test_baostock_symbol_from_ashare_symbol(self):
        self.assertEqual(baostock_symbol_from_ashare_symbol("603019"), "sh.603019")
        self.assertEqual(baostock_symbol_from_ashare_symbol("603019.SH"), "sh.603019")
        self.assertEqual(baostock_symbol_from_ashare_symbol("000063"), "sz.000063")
        self.assertEqual(baostock_symbol_from_ashare_symbol("sz.300750"), "sz.300750")

    def test_default_fetchers_are_baostock_then_yahoo(self):
        fetchers = default_historical_fetchers()
        self.assertIsInstance(fetchers[0], BaoStockHistoricalDataFetcher)
        self.assertIsInstance(fetchers[1], YahooFinanceHistoricalDataFetcher)

    def test_can_disable_yahoo_default_fetcher(self):
        with patch.dict("os.environ", {"QUANT_ENABLE_YAHOO_FALLBACK": "0"}):
            fetchers = default_historical_fetchers()

        self.assertEqual(len(fetchers), 1)
        self.assertIsInstance(fetchers[0], BaoStockHistoricalDataFetcher)

    def test_provider_chain_uses_first_success(self):
        data, provider, cache_hit, _, prior_errors = get_hist_dataframe_with_fallback(
            data_cache=FakeDataCache(),
            symbol="603019",
            start_date="20240101",
            end_date="20240131",
            adjust="qfq",
            fetchers=[
                FakeFetcher("baostock", sample_history()),
                FakeFetcher("yahoo", sample_history()),
            ],
        )

        self.assertFalse(cache_hit)
        self.assertEqual(provider, "baostock")
        self.assertEqual(data.attrs["data_provider"], "baostock")
        self.assertEqual(prior_errors, "")

    def test_provider_chain_falls_back_to_yahoo(self):
        data, provider, cache_hit, _, prior_errors = get_hist_dataframe_with_fallback(
            data_cache=FakeDataCache(),
            symbol="603019",
            start_date="20240101",
            end_date="20240131",
            adjust="qfq",
            fetchers=[
                FakeFetcher("baostock", error="baostock down"),
                FakeFetcher("yahoo", sample_history()),
            ],
        )

        self.assertFalse(cache_hit)
        self.assertEqual(provider, "yahoo")
        self.assertEqual(data.attrs["data_provider"], "yahoo")
        self.assertIn("baostock down", prior_errors)

    def test_provider_chain_reports_all_errors(self):
        with self.assertRaises(RuntimeError) as ctx:
            get_hist_dataframe_with_fallback(
                data_cache=FakeDataCache(),
                symbol="603019",
                start_date="20240101",
                end_date="20240131",
                adjust="qfq",
                fetchers=[
                    FakeFetcher("baostock", error="baostock down"),
                    FakeFetcher("yahoo", error="yahoo down"),
                ],
            )

        self.assertIn("baostock down", str(ctx.exception))
        self.assertIn("yahoo down", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
