# A股 AI 产业链量化选股

这是一个面向 A 股 AI 产业链股票池的多因子选股和回测项目。它从 AkShare 拉取行情数据，计算横截面因子分数，输出股票排名、建议仓位，并提供一个按调仓日滚动的回测入口。

项目仅用于个人研究和流程验证，不构成投资建议。

## 现在能做什么

- 对 `ai_stock_pool.csv` 中的股票做多因子排序。
- 用 repo-local skill 从近期 AI 上游新闻中扩展股票池候选。
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

运行完整闭环：

```bash
python scripts/run_full_pipeline.py \
  --csv ai_stock_pool.csv \
  --start 2026-03-01 \
  --end 2026-05-08 \
  --lookback-days 60 \
  --top-n 10
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
    └── backtest_rebalances.csv
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
research_ledgers/
└── 20260508_112233/
    ├── ledger.json       # canonical 结构化证据
    ├── candidates.csv    # 候选股票索引
    ├── sources.csv       # 来源和 claim 索引
    └── notes.md
```

`research_ledgers/` 是本地产物目录，默认不提交到 git。`ledger.json` 会记录新闻窗口、候选股票、供应链路径、证据摘要、来源 URL、置信度、淘汰原因，以及当次 `ai_stock_pool.csv` 的 SHA-256。

如果没有传 `--candidates-json`，脚本会从当前 `ai_stock_pool.csv` 生成一份股票池快照 ledger，`source_type` 会标记为 `stock_pool_snapshot`。这能保证完整 pipeline 总是有可对账的 ledger；真正的外部新闻来源仍应通过 `--candidates-json` 输入。

当前推荐的研究 loop 是：

```text
LLM 新闻/供应链研究 -> 证据账本 -> 更新 ai_stock_pool.csv -> 多因子排名 -> 回测验证 -> 复盘结果和股票池
```

也可以用 `scripts/run_full_pipeline.py` 一次跑完整闭环。它会使用同一个 `run_id` 自动写入：

```text
research_ledgers/<run_id>/       # LLM 研究证据账本
results/<run_id>/ranking/        # 排名结果
results/<run_id>/backtest/       # 回测结果
training_data/<run_id>/          # 训练用特征/标签快照
reconciliation/<run_id>/         # 对账检查和文件 manifest
results/<run_id>/run_manifest.json
```

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

实时行情全表接口如果超时，选股会降级使用日线价格特征继续运行。默认超时上限是 120 秒，可以调整：

```bash
export QUANT_SPOT_TIMEOUT_SECONDS=60
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
├── reconciliation/              # 本地对账产物，默认 ignored
├── research_ledgers/            # LLM 研究证据账本，本地生成内容默认 ignored
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
├── training_data/               # 本地训练数据快照，默认 ignored
└── results/                     # 运行结果
```

辅助脚本：

- `scripts/explore_akshare_data.py`: 探索 AkShare 可用数据源。
- `scripts/explore_akshare_financial.py`: 探索财务相关接口。
- `scripts/create_research_ledger.py`: 创建 LLM 扩池证据账本。
- `scripts/run_full_pipeline.py`: 运行完整闭环并写入对账、训练和回测产物。

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

后续专业化模块清单见 [docs/todo.md](docs/todo.md)。

## 重要限制

- 这不是交易系统，没有下单、风控执行或实时监控能力。
- 回测没有处理停牌、涨跌停无法成交、真实滑点、分红税费等交易细节。
- 股票池本身带有主观筛选，回测结果受股票池选择影响很大。
- LLM 扩池依赖新闻和供应链资料，必须做来源核验和人工复盘。
- 财务因子缺少完整点时数据时会使用代理变量。
- 所有结果只适合研究和决策辅助，不构成投资建议。
