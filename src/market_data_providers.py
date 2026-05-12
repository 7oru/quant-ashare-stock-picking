"""
Historical market data provider classes.

All providers return the same AkShare-style daily history schema so ranking,
factor calculation, and backtesting can treat data sources uniformly.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

import numpy as np
import pandas as pd


PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "NO_PROXY",
    "no_proxy",
)

HISTORY_COLUMNS = [
    "日期",
    "股票代码",
    "开盘",
    "收盘",
    "最高",
    "最低",
    "成交量",
    "成交额",
    "振幅",
    "涨跌幅",
    "涨跌额",
    "换手率",
    "交易状态",
    "是否ST",
]


class BaseHistoricalDataFetcher(ABC):
    """
    Base class for daily historical data sources.

    Derived classes only need to implement source-specific symbol mapping and
    fetch logic. The public ``fetch`` method must return ``HISTORY_COLUMNS`` and
    attach provider metadata in ``DataFrame.attrs``.
    """

    provider_name: str

    def cache_key(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str,
    ) -> Dict[str, Any]:
        return {
            "api": f"{self.provider_name}_hist",
            "symbol": self.provider_symbol(symbol),
            "period": "daily",
            "start_date": start_date,
            "end_date": end_date,
            "adjust": self.provider_adjustment(adjust),
        }

    @abstractmethod
    def provider_symbol(self, symbol: str) -> str:
        """
        Convert internal A-share symbol to provider-specific symbol.
        """

    def provider_adjustment(self, adjust: str) -> str:
        """
        Provider-specific adjustment label written to metadata/cache.
        """
        return adjust

    @abstractmethod
    def fetch(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str,
    ) -> pd.DataFrame:
        """
        Fetch and normalize daily history.
        """

    def _finalize(
        self,
        frame: pd.DataFrame,
        *,
        symbol: str,
        adjust: str,
    ) -> pd.DataFrame:
        output = frame.copy()
        for column in HISTORY_COLUMNS:
            if column not in output.columns:
                output[column] = np.nan

        output["日期"] = pd.to_datetime(output["日期"], errors="coerce")
        output["股票代码"] = output["股票代码"].fillna(symbol).astype(str)
        numeric_columns = ["开盘", "收盘", "最高", "最低", "成交量", "成交额", "振幅", "涨跌幅", "涨跌额", "换手率"]
        for column in numeric_columns:
            output[column] = pd.to_numeric(output[column], errors="coerce")

        output = output[HISTORY_COLUMNS].dropna(subset=["日期", "收盘"]).sort_values("日期")
        if output.empty:
            raise RuntimeError(f"{self.provider_name} returned no valid close prices for {self.provider_symbol(symbol)}")

        output.attrs["data_provider"] = self.provider_name
        output.attrs["provider_adjustment"] = self.provider_adjustment(adjust)
        output.attrs["provider_symbol"] = self.provider_symbol(symbol)
        return output


class BaoStockHistoricalDataFetcher(BaseHistoricalDataFetcher):
    """
    BaoStock daily A-share history.
    """

    provider_name = "baostock"

    def provider_symbol(self, symbol: str) -> str:
        return baostock_symbol_from_ashare_symbol(symbol)

    def provider_adjustment(self, adjust: str) -> str:
        return {"qfq": "qfq", "hfq": "hfq", "": "raw"}.get(adjust, adjust or "raw")

    def fetch(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str,
    ) -> pd.DataFrame:
        try:
            import baostock as bs
        except ImportError as exc:
            raise RuntimeError("BaoStock is not installed; run: pip install baostock") from exc

        code = self.provider_symbol(symbol)
        adjustflag = {"qfq": "2", "hfq": "1", "": "3"}.get(adjust, "3")
        fields = (
            "date,code,open,high,low,close,preclose,volume,amount,adjustflag,"
            "turn,tradestatus,pctChg,isST"
        )

        login = bs.login()
        try:
            if getattr(login, "error_code", "") != "0":
                raise RuntimeError(f"BaoStock login failed: {login.error_code} {login.error_msg}")
            result = bs.query_history_k_data_plus(
                code,
                fields,
                start_date=_ymd_to_iso(start_date),
                end_date=_ymd_to_iso(end_date),
                frequency="d",
                adjustflag=adjustflag,
            )
            if result.error_code != "0":
                raise RuntimeError(f"BaoStock query failed: {result.error_code} {result.error_msg}")

            rows = []
            while result.next():
                rows.append(result.get_row_data())
        finally:
            bs.logout()

        if not rows:
            raise RuntimeError(f"BaoStock returned no rows for {code}")

        raw = pd.DataFrame(rows, columns=result.fields)
        preclose = pd.to_numeric(raw.get("preclose"), errors="coerce")
        frame = pd.DataFrame(
            {
                "日期": raw["date"],
                "股票代码": symbol,
                "开盘": raw["open"],
                "收盘": raw["close"],
                "最高": raw["high"],
                "最低": raw["low"],
                "成交量": raw["volume"],
                "成交额": raw["amount"],
                "换手率": raw["turn"],
                "涨跌幅": raw["pctChg"],
                "涨跌额": np.nan,
                "振幅": np.nan,
                "交易状态": raw.get("tradestatus", ""),
                "是否ST": raw.get("isST", ""),
            }
        )
        for column in ["最高", "最低"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame["振幅"] = (frame["最高"] - frame["最低"]) / preclose.replace(0, np.nan) * 100
        return self._finalize(frame, symbol=symbol, adjust=adjust)


class YahooFinanceHistoricalDataFetcher(BaseHistoricalDataFetcher):
    """
    Yahoo Finance chart daily history.

    Yahoo is not an official guaranteed API and may rate-limit unauthenticated
    calls. It is kept as a thin OHLCV fallback after BaoStock.
    """

    provider_name = "yahoo"

    def provider_symbol(self, symbol: str) -> str:
        return yahoo_symbol_from_ashare_symbol(symbol)

    def provider_adjustment(self, adjust: str) -> str:
        return "raw_close"

    def fetch(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str,
    ) -> pd.DataFrame:
        yahoo_symbol = self.provider_symbol(symbol)
        params = urlencode(
            {
                "period1": _date_to_unix(start_date),
                "period2": _date_to_unix(end_date, add_days=1),
                "interval": "1d",
                "events": "history",
            }
        )
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?{params}"
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json,text/plain,*/*",
            },
        )
        opener = build_opener(ProxyHandler({}))

        try:
            with opener.open(request, timeout=_yahoo_timeout_seconds()) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"Yahoo Finance HTTP {exc.code} for {yahoo_symbol}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Yahoo Finance fetch failed for {yahoo_symbol}: {exc}") from exc

        result = (payload.get("chart", {}).get("result") or [None])[0]
        if not result:
            error = payload.get("chart", {}).get("error")
            raise RuntimeError(f"Yahoo Finance returned no data for {yahoo_symbol}: {error}")

        timestamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        if not timestamps or not quote:
            raise RuntimeError(f"Yahoo Finance returned empty history for {yahoo_symbol}")

        frame = pd.DataFrame(
            {
                "日期": pd.to_datetime(timestamps, unit="s", utc=True).tz_convert("Asia/Shanghai").date,
                "股票代码": symbol,
                "开盘": quote.get("open", []),
                "收盘": quote.get("close", []),
                "最高": quote.get("high", []),
                "最低": quote.get("low", []),
                "成交量": quote.get("volume", []),
                "成交额": np.nan,
                "换手率": np.nan,
                "涨跌额": np.nan,
                "交易状态": "",
                "是否ST": "",
            }
        )
        for column in ["收盘", "最高", "最低"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        previous_close = frame["收盘"].shift(1)
        frame["涨跌幅"] = frame["收盘"].pct_change() * 100
        frame["振幅"] = (frame["最高"] - frame["最低"]) / previous_close.replace(0, np.nan) * 100
        return self._finalize(frame, symbol=symbol, adjust=adjust)


def default_historical_fetchers() -> List[BaseHistoricalDataFetcher]:
    fetchers: List[BaseHistoricalDataFetcher] = [BaoStockHistoricalDataFetcher()]
    if yahoo_fallback_enabled():
        fetchers.append(YahooFinanceHistoricalDataFetcher())
    return fetchers


def get_hist_dataframe_with_fallback(
    *,
    data_cache,
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str,
    fetchers: Optional[Iterable[BaseHistoricalDataFetcher]] = None,
) -> Tuple[pd.DataFrame, str, bool, Path, str]:
    """
    Fetch daily history through the configured provider chain.

    Returns ``(data, provider_name, cache_hit, cache_path, prior_errors)``.
    ``prior_errors`` is blank when the first provider succeeds.
    """
    errors: List[str] = []
    for fetcher in fetchers or default_historical_fetchers():
        key = fetcher.cache_key(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
        )

        def fetch_current(fetcher=fetcher):
            return fetcher.fetch(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            )

        try:
            data, cache_hit, cache_path = data_cache.get_or_fetch_dataframe(
                "hist",
                key,
                fetch_current,
            )
        except Exception as exc:
            errors.append(f"{fetcher.provider_name}: {exc}")
            continue

        data = data.copy()
        data.attrs["data_provider"] = data.attrs.get("data_provider", fetcher.provider_name)
        data.attrs["provider_adjustment"] = data.attrs.get("provider_adjustment", fetcher.provider_adjustment(adjust))
        data.attrs["provider_symbol"] = data.attrs.get("provider_symbol", fetcher.provider_symbol(symbol))
        return data, fetcher.provider_name, cache_hit, cache_path, "; ".join(errors)

    raise RuntimeError("; ".join(errors) or "No historical data providers configured")


@contextmanager
def maybe_bypass_system_proxy() -> Iterator[None]:
    bypass = os.environ.get("QUANT_BYPASS_SYSTEM_PROXY", "1").strip().lower()
    if bypass in {"0", "false", "no", "off"}:
        yield
        return

    saved = {name: os.environ.get(name) for name in PROXY_ENV_VARS}
    try:
        for name in PROXY_ENV_VARS:
            os.environ.pop(name, None)
        os.environ["NO_PROXY"] = "*"
        os.environ["no_proxy"] = "*"
        yield
    finally:
        for name in PROXY_ENV_VARS:
            if saved[name] is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = saved[name]


def yahoo_fallback_enabled() -> bool:
    value = os.environ.get("QUANT_ENABLE_YAHOO_FALLBACK", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def baostock_symbol_from_ashare_symbol(symbol: str) -> str:
    clean = str(symbol).lower().replace(".sh", "").replace(".sz", "").replace("sh.", "").replace("sz.", "")
    if clean.startswith(("6", "9")):
        return f"sh.{clean}"
    return f"sz.{clean}"


def yahoo_symbol_from_ashare_symbol(symbol: str) -> str:
    clean = str(symbol).upper().replace(".SH", "").replace(".SZ", "").replace(".SS", "")
    if clean.startswith(("6", "9")):
        return f"{clean}.SS"
    return f"{clean}.SZ"


def _date_to_unix(value: str, add_days: int = 0) -> int:
    parsed = datetime.strptime(value, "%Y%m%d").replace(tzinfo=timezone.utc)
    parsed = parsed + timedelta(days=add_days)
    return int(parsed.timestamp())


def _ymd_to_iso(value: str) -> str:
    return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")


def _yahoo_timeout_seconds() -> int:
    try:
        return max(1, int(os.environ.get("QUANT_YAHOO_TIMEOUT_SECONDS", "15")))
    except ValueError:
        return 15
