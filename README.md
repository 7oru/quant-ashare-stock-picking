# A股 AI 产业链量化选股

这是一个面向 A 股 AI 产业链股票池的多因子选股和回测项目。它从 AkShare 拉取行情数据，计算横截面因子分数，输出股票排名、建议仓位，并提供一个按调仓日滚动的回测入口。

项目仅用于个人研究和流程验证，不构成投资建议。

## 现在能做什么

- 对 `ai_stock_pool.csv` 中的股票做多因子排序。
- 输出推荐评级和目标仓位，默认分为核心配置、卫星配置、观察、不配置。
- 用同一套因子逻辑做周度、月度或季度调仓回测。
- 每次运行写入独立目录：`results/<timestamp>/`。
- 将 AkShare 的实时行情和日线数据缓存到 `/tmp`，24 小时内重复运行会优先读缓存。

## 快速开始

```bash
pip install -r requirements.txt
```

运行选股：

```bash
python ai_stock_ranker.py
```

运行回测：

```bash
python backtest_pipeline.py \
  --csv ai_stock_pool.csv \
  --start 2024-01-01 \
  --end 2025-12-31 \
  --rebalance monthly \
  --lookback-days 180 \
  --top-n 10 \
  --fee-bps 10
```

## 输出目录

默认每次运行都会创建一个时间戳目录：

```text
results/
└── 20260507_213544/
    ├── ranking_result.csv
    ├── ranking_scores.csv
    └── analysis_report.txt
```

回测输出类似：

```text
results/
└── 20260507_213544/
    ├── backtest_config.csv
    ├── backtest_summary.csv
    ├── backtest_equity.csv
    └── backtest_rebalances.csv
```

如果同一秒内多次运行，会自动追加 `_01`、`_02` 之类的后缀，避免覆盖已有结果。

## 选股入口

```bash
python ai_stock_ranker.py \
  --csv ai_stock_pool.csv \
  --capital 100 \
  --lookback-days 240 \
  --report
```

参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--csv` | `ai_stock_pool.csv` | 股票池文件 |
| `--output` | `results/<timestamp>/ranking_result.csv` | 指定后会写到该路径，不自动创建时间戳目录 |
| `--capital` | `100.0` | 组合资金规模，单位沿用项目内的“亿元”口径 |
| `--lookback-days` | `240` | 日线回溯天数 |
| `--report` | `False` | 同时输出并保存文本报告 |

主要输出：

- `ranking_result.csv`: 排名、因子分数、推荐评级、目标仓位和仓位金额。
- `ranking_scores.csv`: 只包含排名和因子分数，不含仓位优化结果。
- `analysis_report.txt`: 使用 `--report` 时生成。

## 回测入口

```bash
python backtest_pipeline.py \
  --csv ai_stock_pool.csv \
  --start 2024-01-01 \
  --end 2025-12-31 \
  --rebalance monthly \
  --lookback-days 180 \
  --top-n 10 \
  --fee-bps 10 \
  --output-dir results
```

参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--csv` | `ai_stock_pool.csv` | 股票池文件 |
| `--start` | 必填 | 回测开始日期 |
| `--end` | 必填 | 回测结束日期 |
| `--capital` | `1000000.0` | 初始资金 |
| `--rebalance` | `monthly` | 调仓频率：`weekly`、`monthly`、`quarterly` |
| `--lookback-days` | `180` | 每个调仓日用于计算信号的历史窗口 |
| `--top-n` | `10` | 每次选择的股票数量 |
| `--fee-bps` | `10.0` | 单边交易成本，单位 bps |
| `--output-dir` | `results` | 基础输出目录，实际会写入其下的时间戳子目录 |

回测使用调仓日收盘前已经可见的历史 K 线计算信号，从下一个交易日开始持有。默认基准是股票池等权组合。

## 数据缓存

AkShare 的部分接口比较慢，项目默认把结果缓存到：

```text
/tmp/quant_ashare_stock_picking_cache
```

缓存有效期为 24 小时。覆盖范围：

- `stock_zh_a_spot_em`: A 股实时行情全表。
- `stock_zh_a_hist`: 单只股票日线数据，选股和回测共用。

可以通过环境变量修改缓存目录：

```bash
export QUANT_ASHARE_CACHE_DIR=/tmp/my_quant_cache
```

删除缓存目录即可强制重新拉取数据。

## 因子模型

当前综合分使用 6 个维度，分数均为横截面打分后映射到 0-100。

| 因子 | 权重 | 主要信息 |
| --- | ---: | --- |
| 动量 | 30% | 20/60/120 日收益、动量加速度、均线距离、MACD、RSI、趋势强度 |
| 质量 | 20% | ROE、毛利率、净利率、现金流质量；缺失时用估值、风险和流动性代理 |
| 成长 | 15% | 营收增长、利润增长、YTD 收益、风险调整动量 |
| 估值 | 15% | PE、PB、PS、PCF、PEG，低估值高分 |
| 波动率 | 10% | 年化波动、下行波动、最大回撤、ATR、布林带宽度、振幅，低风险高分 |
| 流动性 | 10% | 换手率、量比、成交额、流通市值、量能确认 |

权重配置在 `src/config.py`。

需要注意：当前财务质量和成长数据并不总是有稳定的点时数据源。缺失时模型会降级使用代理因子，因此回测更适合作为流程和相对排序验证，不应被理解为严格的财务点时回测。

## 仓位规则

组合优化逻辑在 `src/portfolio_optimizer.py`。

默认分层：

| 分层 | 排名 | 目标权重 |
| --- | --- | ---: |
| 核心配置 | Top 10 | 60% |
| 卫星配置 | 11-25 | 30% |
| 观察 | 26-40 且分数不低于中性线 | 10% |
| 不配置 | 40 以后 | 0% |

主要限制：

- 单票最高 15%。
- 单行业最高 30%。
- 单一子行业最高 25%。

## 项目结构

```text
.
├── ai_stock_ranker.py           # 选股 CLI
├── backtest_pipeline.py         # 回测 CLI
├── ai_stock_pool.csv            # 当前股票池
├── scripts/                     # 数据源探索脚本
├── src/
│   ├── backtester.py            # 回测流程
│   ├── config.py                # 因子权重、行业调整、仓位限制
│   ├── data_cache.py            # /tmp 数据缓存
│   ├── data_fetcher.py          # AkShare 数据获取
│   ├── factor_calculator.py     # 因子计算
│   ├── market_features.py       # 技术、风险、流动性特征
│   ├── portfolio_optimizer.py   # 仓位分配
│   ├── results_manager.py       # 时间戳输出目录
│   └── stock_ranker.py          # 选股流程协调
├── docs/legacy/                 # 历史分析文档
└── results/                     # 运行结果
```

辅助脚本：

- `scripts/explore_akshare_data.py`: 探索 AkShare 可用数据源。
- `scripts/explore_akshare_financial.py`: 探索财务相关接口。

## 数据来源

核心依赖是 AkShare：

- `stock_zh_a_spot_em`: 实时行情、估值、换手率、量比、市值等。
- `stock_zh_a_hist`: 前复权日线行情，用于技术指标、波动率和回测。

AkShare 接口偶尔会慢或失败。项目会尽量缓存成功结果，但如果接口字段变更或网络不可用，仍然可能需要重跑。

## 开发和检查

基础语法检查：

```bash
python -m compileall src ai_stock_ranker.py backtest_pipeline.py
```

查看 CLI 参数：

```bash
python ai_stock_ranker.py --help
python backtest_pipeline.py --help
```

## 重要限制

- 这不是交易系统，没有下单、风控执行或实时监控能力。
- 回测没有处理停牌、涨跌停无法成交、真实滑点、分红税费等交易细节。
- 股票池本身带有主观筛选，回测结果受股票池选择影响很大。
- 财务因子缺少完整点时数据时会使用代理变量。
- 所有结果只适合研究和决策辅助，不构成投资建议。
