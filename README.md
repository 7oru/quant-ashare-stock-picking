# A股 AI 产业链量化选股

这是一个面向 A 股 AI 产业链股票池的多因子选股和回测项目。它默认从 BaoStock 拉取历史日线，用 AkShare 补充实时估值/行情字段，计算横截面因子分数，输出股票排名、建议仓位，并提供一个按调仓日滚动的回测入口。

项目仅用于个人研究和流程验证，不构成投资建议。

## 现在能做什么

- 对 `ai_stock_pool.csv` 中的股票做多因子排序。
- 用 repo-local skill 从近期 AI 上游新闻中扩展股票池候选。
- 输出推荐评级和目标仓位，默认分为核心配置、卫星配置、观察、不配置。
- 用同一套因子逻辑做周度、月度或季度调仓回测。
- 每次运行写入独立目录：`results/<timestamp>/`。
- 将实时行情和历史日线数据缓存到 `/tmp`，24 小时内重复运行会优先读缓存。

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

运行完整闭环：

```bash
python scripts/run_full_pipeline.py \
  --csv ai_stock_pool.csv \
  --start 2026-03-01 \
  --end 2026-05-08 \
  --lookback-days 180 \
  --top-n 10
```

运行推荐的真实数据闭环：

```bash
make real-run
```

这个快捷入口等价于调用 `scripts/run_real_pipeline.sh`，默认设置 `NO_PROXY=*`、`no_proxy=*`，关闭 Yahoo fallback，并用 BaoStock/AkShare 拉取真实数据。可以通过环境变量覆盖参数，例如：

```bash
END=2026-05-15 LOOKBACK_DAYS=180 TOP_N=12 make real-run
```

## 输出目录

默认每次运行都会创建一个时间戳目录：

```text
results/
└── 20260507_213544/
    ├── ranking_config.csv
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
    ├── backtest_rebalances.csv
    ├── backtest_point_in_time.csv
    ├── backtest_factor_lineage.csv
    ├── backtest_factor_lineage.md
    ├── factor_diagnostics.csv
    ├── factor_diagnostics.md
    ├── portfolio_risk.csv
    ├── backtest_data_fetch_log.csv
    ├── backtest_exceptions.json
    └── backtest_run_metadata.json
```

如果同一秒内多次运行，会自动追加 `_01`、`_02` 之类的后缀，避免覆盖已有结果。

## LLM 股票池扩展

repo 内置了一个 Codex skill：

```text
skills/ai-upstream-stock-research/
```

它用于把最近一周 AI 基础设施新闻转成 A 股候选池，重点看更上游的二阶供应链，而不是泛 AI 应用叙事。例如：

- GPU/AI 服务器 -> 高多层 PCB -> 高频高速 CCL -> 铜箔、树脂、玻纤布。
- HBM/NAND/SSD -> 存储模组、封装测试 -> 前驱体、电子特气、基板材料。
- 数据中心扩建 -> 配电、UPS、变压器、液冷和精密温控。

使用时让 Codex 调用 `ai-upstream-stock-research`，先基于最近 7 天新闻做主题图谱，再输出匹配 `ai_stock_pool.csv` 的候选行。CSV schema 见：

```text
skills/ai-upstream-stock-research/references/csv-schema.md
```

每次扩池前先生成研究证据账本：

```bash
python scripts/create_research_ledger.py \
  --title "AI upstream research" \
  --news-window-start 2026-05-02 \
  --news-window-end 2026-05-08
```

默认会写到：

```text
audits/
└── 20260508_112233/
    └── llm_research/
        ├── ledger.json       # canonical 结构化证据
        ├── candidates.csv    # 候选股票索引
        ├── sources.csv       # 来源和 claim 索引
        └── notes.md
```

`audits/` 是本地审计产物目录，默认不提交到 git。`ledger.json` 会记录新闻窗口、候选股票、供应链路径、证据摘要、来源 URL、置信度、淘汰原因，以及当次 `ai_stock_pool.csv` 的 SHA-256。

如果没有传 `--candidates-json`，脚本会从当前 `ai_stock_pool.csv` 生成一份股票池快照 ledger，`source_type` 会标记为 `stock_pool_snapshot`。这能保证完整 pipeline 总是有可对账的 ledger；真正的外部新闻来源仍应通过 `--candidates-json` 输入。

当前推荐的研究 loop 是：

```text
LLM 新闻/供应链研究 -> 证据账本 -> 更新 ai_stock_pool.csv -> 多因子排名 -> 回测验证 -> 复盘结果和股票池
```

也可以用 `scripts/run_full_pipeline.py` 一次跑完整闭环。它会使用同一个 `run_id` 自动写入：

```text
results/<run_id>/ranking_backtest_scores.csv       # 主结果，按 backtesting_score 再按 ranking 排序
results/<run_id>/training_data/                     # 训练用特征/标签快照
results/<run_id>/run_manifest.json
audits/<run_id>/llm_research/                       # LLM 研究证据账本
audits/<run_id>/pipeline_reconcilliation/           # 对账检查、raw ranking/backtest 和文件 manifest
```

真实 run 完成后，可以把关键摘要归档到一个稳定、可提交的位置：

```bash
make archive-baseline RUN_ID=20260519_215413 NAME=latest_real_run
```

归档结果写到 `docs/baselines/<name>/`，包含 run manifest、回测摘要、对账检查、主结果和 top 10 摘要。完整 `results/` 和 `audits/` 仍然保持本地 ignored。

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
- `ranking_config.csv`: 运行参数和股票池 SHA-256。
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
| `--lookback-days` | `180` | 每个调仓日用于计算信号的历史窗口，至少 60 |
| `--top-n` | `10` | 每次选择的股票数量；默认风险贡献上限下至少 5 |
| `--fee-bps` | `10.0` | 佣金成本，单位 bps；为兼容旧参数名保留 |
| `--stamp-tax-bps` | `5.0` | 卖出印花税，单位 bps |
| `--transfer-fee-bps` | `0.1` | 买卖双边过户费，单位 bps |
| `--slippage-bps` | `5.0` | 买卖双边滑点，单位 bps |
| `--impact-bps` | `0.0` | 买卖双边冲击成本，单位 bps |
| `--max-participation-rate` | `0.10` | 单票单日最大成交额参与率，用于容量约束 |
| `--max-drawdown-budget` | 配置默认值 | 组合回撤预算，触发后降低目标总仓位 |
| `--min-listing-days` | `60` | 上市未满该自然日数的股票不参与调仓买入 |
| `--output-dir` | `results` | 基础输出目录，实际会写入其下的时间戳子目录 |
| `--candidate-visible-dates-json` | 无 | 可选 `{stock_code: YYYY-MM-DD}`，限制 LLM 新候选进入历史回测 universe 的日期 |

回测使用调仓日收盘前已经可见的历史 K 线计算信号，从下一个交易日开始持有。每个调仓日会按 `list_date <= signal_date` 过滤股票池；如果股票池 CSV 有 `pool_entry_date`、`stock_pool_as_of_date` 或 `as_of_date`，还会按该日期过滤当时尚未进入股票池的成员。完整闭环传入 `--candidates-json` 时，accepted/watchlist 的 LLM 新候选默认从 `news_window_end` 起才进入历史 universe，避免把刚研究出的股票穿越进更早的信号。

行业和主题标签也支持点时约束：如果股票池 CSV 有 `industry_as_of_date`、`classification_as_of_date` 或 `sector_as_of_date`，回测会在标签日期晚于调仓信号日时屏蔽该行的 `sector`、`sub_sector` 和 `ai_exposure`，防止未来分类影响行业调整和输出记录。回测里的财务/估值字段默认不读取当前实时财务数据，历史信号只使用价格窗口可推导的点时代理。`backtest_point_in_time.csv` 会记录每个调仓日的可见股票数、上市日期过滤数、股票池进入日期过滤数、LLM 候选过滤数和未来行业标签屏蔽数。默认基准是当期可见股票池等权组合。

主要 CSV 输出都会写入 `as_of_date` 或等价日期字段。排名结果使用运行日作为数据快照日期；回测摘要使用回测结束日，净值表按交易日，调仓和点时报告按信号日；研究账本候选和来源表默认使用 `news_window_end`，若候选或来源自身带有日期则优先保留。这样后续训练、对账和复盘时可以区分“这行数据代表哪个时点”和“文件是什么时候生成的”。

每次回测还会写出 `backtest_factor_lineage.csv` 和 `backtest_factor_lineage.md`，显式标记各类信号的数据血缘：动量和波动率来自严格点时历史 K 线；流动性主要来自点时成交/换手/成交额；成长和质量在缺少点时基本面时使用价格、风险和流动性代理；估值在回测中禁用当前/修订财务字段并使用中性占位；行业调整依赖股票池是否提供分类 as-of 日期。

回测还会输出 `factor_diagnostics.csv` 和 `factor_diagnostics.md`，基于每个调仓信号日的全 universe 因子分数和下一持有期收益计算 Rank IC、ICIR、分组收益 spread、单调性、组合换手率和持仓收益衰减。诊断表也会按行业、市值分组和 AI 暴露输出平均前瞻收益与入选率，并计算剥离行业/市值组别暴露后的中性化 Rank IC，便于检查信号是否只在某类主题或风格里有效。样本期很短时这些诊断只用于流程检查，不应过度解读统计显著性。

调仓买入前会用 BaoStock 日线字段做基础交易约束过滤：停牌或无当日交易行、ST、上市未满 `--min-listing-days`、以及涨跌停锁定的股票不会进入实际持仓权重。组合从调仓信号日后的下一个交易日开始执行，避免同日信号同日成交；交易成本按买入和卖出拆开计算，买卖双边收佣金、过户费、滑点和冲击成本，卖出侧额外收印花税。容量约束使用执行日成交额乘以 `--max-participation-rate` 估算单票单日可交易金额，买入和卖出超过容量时只做部分成交并保留现金或剩余持仓。`backtest_point_in_time.csv` 会记录每个调仓日的可交易股票数、交易约束剔除数量和原因计数。

`backtest_rebalances.csv` 会保留交易执行状态：正常成交写为 `filled`，交易约束导致无法买入写为 `blocked_buy`，持仓因停牌、ST 或涨跌停等约束无法卖出写为 `blocked_sell`，容量不足导致的部分成交写为 `partial_buy` 或 `partial_sell`。对应原因写在 `trade_constraint_reason`、`capacity_reason` 和相关容量字段里。

回测过程中会为每个调仓日生成组合风险暴露表，覆盖行业、子行业、市值、AI 暴露、加权波动率分数、加权动量分数和高动量拥挤权重。后续组合约束和风险输出都基于这张表扩展。

`portfolio_risk.csv` 会输出每个调仓日的组合暴露和单票近似风险贡献，可用于检查行业、主题、风格和风险预算是否符合预期。

每次回测还会保存 `backtest_run_metadata.json`、`backtest_data_fetch_log.csv` 和 `backtest_exceptions.json`。其中 metadata 汇总运行参数、代码 commit、输入股票池 hash、输出文件路径、数据源分布和缓存命中统计；fetch log 逐股票记录 provider、cache hit 和缓存路径；exceptions 记录抓数等阶段异常。

回测权重使用轻量约束优化生成：先按综合分数倾斜分配，再迭代应用单票、行业和子行业上限，并在剩余约束空间内按原始得分倾斜重新分配；无法在约束内配置的部分保留为现金。

风险预算还包括 AI 暴露上限、单票风险贡献上限和最大回撤预算。单票风险贡献使用目标权重乘以波动率反向分数做近似估算；当组合当前回撤触发 `--max-drawdown-budget` 时，调仓目标总仓位会下调。

## 数据缓存

AkShare 的部分接口比较慢，项目默认把结果缓存到：

```text
/tmp/quant_ashare_stock_picking_cache
```

缓存有效期为 24 小时。覆盖范围：

- `stock_zh_a_spot_em`: A 股实时行情全表。
- `baostock_hist` / `yahoo_chart`: 日线行情缓存，默认 BaoStock，Yahoo 只作备用。

可以通过环境变量修改缓存目录：

```bash
export QUANT_ASHARE_CACHE_DIR=/tmp/my_quant_cache
```

实时行情全表接口如果超时，选股会降级使用日线价格特征继续运行。默认超时上限是 120 秒，可以调整：

```bash
export QUANT_SPOT_TIMEOUT_SECONDS=60
```

AkShare 实时行情补充默认会绕开本机系统代理，避免 macOS HTTP 代理导致 `ProxyError` 或 `RemoteDisconnected`。如果确实需要保留系统代理，可以关闭这个行为：

```bash
export QUANT_BYPASS_SYSTEM_PROXY=0
```

历史日线默认使用 BaoStock。BaoStock 是更适合 A 股日频回测的免费数据源，能提供成交额、换手率、交易状态和 ST 标记。Yahoo Finance chart 只作为备用源，且只提供较薄的 OHLCV 数据，缺少换手率、成交额等 A 股专属字段；如需关闭 Yahoo 兜底：

```bash
export QUANT_ENABLE_YAHOO_FALLBACK=0
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

需要注意：当前财务质量、成长和估值数据并不总是有稳定的点时数据源。回测会禁用当前/修订财务字段，并在缺失时降级使用代理或中性分数；具体口径见每次运行生成的 `backtest_factor_lineage.csv` 和 `backtest_factor_lineage.md`。因子有效性初筛见 `factor_diagnostics.csv` 和 `factor_diagnostics.md`。

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
├── audits/                      # 本地审计产物，默认 ignored
├── skills/                      # repo-local Codex skills
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
- `scripts/create_research_ledger.py`: 创建 LLM 扩池证据账本。
- `scripts/run_full_pipeline.py`: 运行完整闭环并写入对账、训练和回测产物。

## 数据来源

核心数据源：

- BaoStock: 默认历史日线行情，用于技术指标、波动率和回测。
- Yahoo Finance chart: 历史日线备用源。
- AkShare `stock_zh_a_spot_em`: 排名流程里的实时行情、估值、量比、市值等补充字段；失败时会降级用日线价格代理因子继续。

日线 provider 通过 `BaseHistoricalDataFetcher` 派生类实现，当前默认顺序是 `BaoStockHistoricalDataFetcher` -> `YahooFinanceHistoricalDataFetcher`。BaoStock 代码会映射为 `sh.600000` / `sz.000001`；Yahoo 会将上交所代码映射为 `.SS`、深交所代码映射为 `.SZ`。Yahoo 不是官方保证的程序化 API，可能被限流或拒绝访问，只适合作为研究场景的尽力兜底。项目会尽量缓存成功结果，但如果接口字段变更或网络不可用，仍然可能需要重跑。

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

后续专业化模块清单见 [docs/todo.md](docs/todo.md)。

## 重要限制

- 这不是交易系统，没有下单、风控执行或实时监控能力。
- 回测已处理基础停牌、ST、新股和涨跌停锁定过滤，但仍不是实盘交易系统；真实分红税费、盘口深度和逐笔成交无法完全模拟。
- 股票池本身带有主观筛选，回测结果受股票池选择影响很大。
- LLM 扩池依赖新闻和供应链资料，必须做来源核验和人工复盘。
- 财务因子缺少完整点时数据时会使用代理变量。
- 所有结果只适合研究和决策辅助，不构成投资建议。
