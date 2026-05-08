# TODO

这个清单围绕项目目标：LLM 选股票池 -> 量化排名 -> 回测验证 -> 复盘迭代。

## P0: Research Evidence Ledger

- [x] 为每次 LLM 扩池生成研究证据账本，保存到 `audits/<timestamp>/llm_research/`。
- [x] 记录候选股票、新闻窗口、来源 URL、来源日期、供应链路径、证据摘要、置信度、淘汰原因。
- [x] 在股票池 CSV 之外保留来源证据，避免把长文本和 URL 混进 `ai_stock_pool.csv`。
- [x] 让 ranking/backtest 输出记录本次使用的股票池版本或 hash，便于复盘。

## P0: Point-in-Time Discipline

- [x] 回测时冻结当时可见的股票池、行业分类、财务数据和 LLM 候选结果。
- [ ] 禁止使用未来才出现的股票池成员、行业标签或财务修订数据参与历史信号。
- [ ] 给每个数据表增加 `as_of_date` 或等价元数据。
- [ ] 在回测报告里显式标记哪些因子是严格点时数据，哪些只是当前代理数据。

## P1: Factor Validation Layer

- [ ] 增加 Rank IC、ICIR、分组收益、单调性、换手率、持仓衰减等因子检验输出。
- [ ] 支持按行业、市值、AI 暴露分组做稳定性分析。
- [ ] 增加行业/市值中性化后的因子表现，避免主题暴露误判成 alpha。
- [ ] 将因子检验结果写入 `results/<timestamp>/factor_diagnostics.csv` 和摘要文本。

## P1: A-Share Trading Constraints

- [ ] 回测纳入停牌、ST、上市未满指定天数、涨跌停无法成交等过滤条件。
- [ ] 加入 T+1、印花税、佣金、过户费、滑点和冲击成本。
- [ ] 使用成交额或自由流通市值估算容量约束，限制单日成交参与率。
- [ ] 在调仓记录里标记因为交易约束无法买入或卖出的股票。

## P1: Portfolio Risk Model

- [ ] 建立行业、子行业、市值、波动率、动量拥挤度等风险暴露表。
- [ ] 从简单 capped weights 升级为带约束的组合优化。
- [ ] 增加最大行业暴露、最大主题暴露、单票风险贡献和最大回撤预算。
- [ ] 输出组合暴露和风险贡献到 `results/<timestamp>/portfolio_risk.csv`。

## P2: Run Artifact Archiving

- [ ] 每次运行保存参数、代码 commit、输入 CSV hash、数据缓存命中情况和异常日志。
- [x] 将 training data 和主结果统一放在 `results/<timestamp>/`，将 ledger 和 reconciliation 放在 `audits/<timestamp>/`。
- [x] 增加 `run_manifest.json`，记录所有输出文件路径和生成时间。
- [x] 支持按 run id 快速复盘一次完整实验。
