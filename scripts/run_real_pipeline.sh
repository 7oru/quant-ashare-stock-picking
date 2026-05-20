#!/usr/bin/env bash
set -euo pipefail

CSV="${CSV:-ai_stock_pool.csv}"
START="${START:-2026-03-01}"
END="${END:-2026-05-08}"
REBALANCE="${REBALANCE:-monthly}"
LOOKBACK_DAYS="${LOOKBACK_DAYS:-60}"
TOP_N="${TOP_N:-10}"
FEE_BPS="${FEE_BPS:-10}"
SPOT_TIMEOUT_SECONDS="${SPOT_TIMEOUT_SECONDS:-30}"
BACKTEST_CAPITAL="${BACKTEST_CAPITAL:-1000000}"

export NO_PROXY="${NO_PROXY:-*}"
export no_proxy="${no_proxy:-*}"
export QUANT_ENABLE_YAHOO_FALLBACK="${QUANT_ENABLE_YAHOO_FALLBACK:-0}"

python3 scripts/run_full_pipeline.py \
  --csv "${CSV}" \
  --start "${START}" \
  --end "${END}" \
  --rebalance "${REBALANCE}" \
  --lookback-days "${LOOKBACK_DAYS}" \
  --top-n "${TOP_N}" \
  --fee-bps "${FEE_BPS}" \
  --backtest-capital "${BACKTEST_CAPITAL}" \
  --spot-timeout-seconds "${SPOT_TIMEOUT_SECONDS}" \
  "$@"
