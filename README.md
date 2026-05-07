# AI产业链股票量化选股系统 (AI Industry Chain Stock Quantitative Selection System)

> **⚠️ 个人自用参考项目 - 仅供学习交流**
> 
> **🤖 AI辅助开发**: 本项目基于 **MiniMax M2.1** Vibe Coding 理念开发，使用AI辅助编写代码和调试。

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

基于六维度量化模型的AI产业链股票智能选股与资产配置系统，帮助投资者进行中期（3-6个月）投资决策。

## 📝 项目说明

本项目为**个人学习研究**目的创建，仅供参考学习，不构成任何投资建议。

### 技术特点
- 使用 **akshare** 开源库获取A股数据
- 基于 **MiniMax M2.1** AI助手辅助开发
- Vibe Coding 模式：自然语言描述需求，AI生成代码

### 致谢
- **MiniMax Agent** - 提供AI编程支持
- **akshare** - 提供免费开源的财经数据接口

## 🚀 核心功能

- **多因子量化模型**：基于动量、质量、成长、估值、波动率、流动性六大因子
- **实时市场数据**：使用akshare获取真实A股市场数据（实时行情、历史价格、财务指标）
- **行业专项调整**：针对AI产业链不同细分领域进行因子权重调整
- **智能资产配置**：基于得分自动优化仓位分配，控制风险
- **回测Pipeline**：按周/月/季度滚动调仓，输出净值、换手、回撤和基准对比
- **数据可视化报告**：生成详细的分析报告和配置建议
- **数据探索工具**：提供`explore_akshare_data.py`探索可用数据源和因子

## 📊 量化因子模型

### 因子权重分配
| 因子名称 | 权重 | 主要指标 | 数据来源 |
|---------|------|---------|---------|
| **动量因子** | 30% | 20/60/120日收益率、动量加速度、MACD、RSI健康度、趋势强度 | 实时行情、历史价格 |
| **质量因子** | 20% | ROE、毛利率、净利率、现金流质量；缺失时用估值/风险/流动性代理 | 财务数据、代理因子 |
| **成长因子** | 15% | 营收增速、净利润增长率、YTD收益率、风险调整动量 | 财务数据、历史价格 |
| **估值因子** | 15% | PE TTM、PB、PS、PCF、PEG | 实时行情 |
| **波动率因子** | 10% | 年化波动、下行波动、最大回撤、ATR、布林带宽度、振幅 | 历史价格、实时行情 |
| **流动性因子** | 10% | 换手率、量比、成交额、流通市值、量能确认 | 实时行情、历史价格 |

### 可用数据源
系统从akshare获取以下数据：
- **实时行情数据** (`stock_zh_a_spot_em`): PE、PB、PS、PCF、市值、收益率(5日/60日/YTD)、换手率、量比、振幅
- **历史价格数据** (`stock_zh_a_hist`): 日线价格、成交量、技术指标(MA、RSI、MACD、ATR、波动率、最大回撤)
- **分红数据** (`stock_dividend_cninfo`): 分红送股信息
- **行业分类** (`stock_board_industry_name_em`): 行业板块数据

**注意**: 历史回测默认只使用调仓日前可见的K线和成交数据；若缺少点时财务数据，质量/成长会自动降级为代理因子。

### 行业专项调整
针对AI产业链不同细分领域进行因子权重微调：
- **上游算力基础设施**：重视估值与成长平衡
- **芯片设计**：更注重估值保护
- **大模型应用**：强调成长性与质量
- **智能驾驶**：平衡成长与波动控制

## 🏗️ 系统架构

```
AI产业链股票量化选股系统
├── ai_stock_ranker.py          # 主入口脚本 (CLI)
├── backtest_pipeline.py        # 回测入口脚本 (CLI)
├── explore_akshare_data.py     # 数据源探索工具
├── explore_akshare_financial.py # 财务数据探索工具
├── src/
│   ├── __init__.py             # 包初始化
│   ├── config.py               # 配置 (因子权重、行业调整、仓位限制)
│   ├── data_fetcher.py         # 数据获取 (价格、财务数据)
│   ├── market_features.py      # 历史行情特征工程
│   ├── factor_calculator.py    # 因子计算 (6维度因子)
│   ├── backtester.py           # 回测Pipeline
│   ├── portfolio_optimizer.py  # 组合优化 (资产配置)
│   └── stock_ranker.py         # 主协调器
├── ai_stock_pool.csv           # 股票池
├── results/                    # 输出结果目录
└── requirements.txt            # 依赖
```

### 模块说明
| 模块 | 职责 |
|------|------|
| `config.py` | FACTOR_WEIGHTS, INDUSTRY_ADJUSTMENT, POSITION_LIMITS |
| `data_fetcher.py` | StockDataFetcher - 从akshare获取实时行情和历史价格数据 |
| `market_features.py` | calculate_price_features - 计算点时技术/风险/流动性特征 |
| `factor_calculator.py` | FactorCalculator - 计算6维度因子得分，稳健处理缺失数据 |
| `backtester.py` | BacktestPipeline - 滚动调仓回测、净值和绩效统计 |
| `portfolio_optimizer.py` | PortfolioOptimizer - 资产配置优化 |
| `stock_ranker.py` | StockRanker - 整合各模块的主协调器 |

### 数据探索工具
- `explore_akshare_data.py`: 探索akshare可用数据源，识别可用因子
- `explore_akshare_financial.py`: 探索财务数据接口，发现更多数据源

## 🛠️ 安装与使用

### 环境要求
- Python 3.8+
- pip 包管理器

### 快速安装

```bash
# 克隆项目
git clone https://github.com/your-repo/quant-ashare-stock-picking.git
cd quant-ashare-stock-picking

# 安装依赖
pip install -r requirements.txt
```

### 手动安装核心依赖
```bash
pip install pandas numpy akshare  # akshare替代tushare，提供更全面的A股数据
```

### 使用方法

#### 1. 基础运行（推荐）
```bash
# 使用默认配置
python ai_stock_ranker.py
```

#### 2. 参数说明
| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--csv` | 股票池CSV文件路径 | `ai_stock_pool.csv` |
| `--output` | 输出文件路径 | `results/<timestamp>/ranking_result.csv` |
| `--capital` | 总投资资金（亿元） | `100.0` |
| `--lookback-days` | 历史价格回溯天数 | `240` |
| `--report` | 生成详细分析报告 | `False` |

#### 3. 使用示例
```bash
# 使用默认配置（输入: ai_stock_pool.csv, 输出: results/<timestamp>/）
python ai_stock_ranker.py

# 自定义股票池
python ai_stock_ranker.py --csv my_stock_pool.csv

# 自定义输出路径
python ai_stock_ranker.py --output /path/to/result.csv

# 生成详细报告
python ai_stock_ranker.py --report

# 完整参数示例；指定 --output 时不再自动创建 timestamp 子目录
python ai_stock_ranker.py \
    --csv ai_stock_pool.csv \
    --output results/my_result.csv \
    --capital 100.0 \
    --lookback-days 240 \
    --report
```

#### 4. 回测Pipeline
```bash
# 月度调仓回测，输出到 results/<timestamp>/
python backtest_pipeline.py \
    --csv ai_stock_pool.csv \
    --start 2024-01-01 \
    --end 2025-12-31 \
    --rebalance monthly \
    --lookback-days 180 \
    --top-n 10 \
    --fee-bps 10
```

回测会在每个调仓日收盘后计算信号，从下一个交易日开始持有，避免未来函数。默认基准为股票池等权组合。

## 📈 输出结果说明

### 输出文件
默认每次运行都会创建 `results/<timestamp>/`，其中：
- `ranking_result.csv`: 排名、因子得分、推荐评级和目标仓位
- `ranking_scores.csv`: 不含仓位优化的纯排名得分
- `analysis_report.txt`: 使用 `--report` 时生成的文本报告

`ranking_result.csv` 包含以下字段：

| 字段名 | 说明 |
|--------|------|
| `stock_code` | 股票代码 |
| `stock_name` | 股票名称 |
| `sector` | 行业分类 |
| `sub_sector` | 子行业分类 |
| `ai_exposure` | AI暴露度 |
| `composite_score` | 综合得分 (0-100) |
| `rank` | 综合排名 |
| `momentum_score` | 动量因子得分 (基于20日/60日收益率、MA偏离度) |
| `growth_score` | 成长因子得分 (基于YTD收益率代理或财务数据) |
| `valuation_score` | 估值因子得分 (基于PE/PB/PS，估值越低得分越高) |
| `quality_score` | 质量因子得分 (基于ROE/毛利率，或估值+波动率代理) |
| `volatility_score` | 波动率因子得分 (基于波动率、最大回撤、振幅，波动率越低得分越高) |
| `liquidity_score` | 流动性因子得分 (基于换手率、量比、市值/成交额) |
| `risk_adjusted_momentum` | 风险调整动量原始值 |
| `growth_data_coverage` | 成长财务数据覆盖率 |
| `quality_data_coverage` | 质量财务数据覆盖率 |
| `recommendation` | 推荐评级 (核心配置/卫星配置/观察/不配置) |
| `target_weight` | 建议权重占比 |
| `position_value` | 建议投资金额(亿元) |

### 回测输出
`backtest_pipeline.py` 会保存：
- `backtest_config.csv`: 回测参数
- `backtest_summary.csv`: 总收益、年化收益、年化波动、Sharpe、最大回撤、胜率、换手
- `backtest_equity.csv`: 每日策略净值、基准净值、现金权重、回撤
- `backtest_rebalances.csv`: 每次调仓的入选股票、权重、排名和因子得分

## 📋 投资策略建议

### 配置梯队划分
| 梯队 | 排名区间 | 建议权重 | 投资策略 |
|------|----------|----------|----------|
| **第一梯队**<br/>核心配置 | Top 10 | 60% | 分批建仓，中期持有为主 |
| **第二梯队**<br/>卫星配置 | 11-25 | 30% | 灵活调整，把握轮动机会 |
| **第三梯队**<br/>观察配置 | 26-40 | 10% | 逢低布局，等待机会 |
| **不配置** | 40+ | 0% | 暂不考虑 |

### 风险控制规则
- **单票限制**：最大15%，最小2%
- **行业限制**：单一行业最大30%
- **止损规则**：个股-8%，组合-10%
- **止盈规则**：+20%减仓1/3，+50%至少减仓1/3

## 🔧 数据源配置

### 数据来源
系统使用 [akshare](https://github.com/akfamily/akshare) 获取真实市场数据：

```bash
# 安装依赖
pip install akshare pandas numpy
```

### 可用数据源
系统从akshare实时获取以下数据：

#### 1. 实时行情数据 (`stock_zh_a_spot_em`)
- **估值指标**: 市盈率-动态(PE TTM)、市净率(PB)、市销率(PS)、市现率(PCF)
- **规模指标**: 总市值、流通市值
- **动量指标**: 5日涨跌幅、60日涨跌幅、年初至今涨跌幅
- **技术指标**: 换手率、换手率(自由流通股)、量比、振幅

#### 2. 历史价格数据 (`stock_zh_a_hist`)
- **价格数据**: 开盘、收盘、最高、最低
- **成交量**: 成交量、成交额
- **技术指标**: 计算MA20/MA60/MA120、RSI(14)、MACD、Stochastic、ATR、布林带、波动率、最大回撤

#### 3. 其他数据源
- **分红数据**: `stock_dividend_cninfo` - 分红送股信息
- **行业分类**: `stock_board_industry_name_em` - 行业板块数据

### 数据质量保证
- **使用实际数据**: 系统优先使用真实市场数据，不使用默认值
- **缺失数据处理**: 当数据缺失时，使用中性分数或点时代理因子
- **数据验证**: 只过滤极端异常值，保留正常的高PE/PB值(成长股常见)

### 探索可用数据
运行数据探索工具查看所有可用数据源：
```bash
python explore_akshare_data.py
```

## 📊 示例输出

### 控制台报告示例
```
========================================
AI产业链股票量化选股报告
生成时间: 2026-01-12 14:30:00
========================================

【执行摘要】
分析股票数量: 48
平均综合得分: 65.23
得分标准差: 12.45

【第一梯队 - 核心配置】(Top 10)
  1. 浪潮信息 (000977.SZ) - 综合得分: 89.5 - 动量: 85.2 - 成长: 92.1
  2. 中科曙光 (603019.SH) - 综合得分: 87.3 - 动量: 88.7 - 成长: 85.9
  ...

【配置建议】
核心配置 (10支): 建议权重合计 60.0%
卫星配置 (15支): 建议权重合计 30.0%
```

### 行业分布示例
```
【行业分布】
上游-算力基础设施: 25.0%
中游-芯片: 20.0%
下游-智能驾驶: 18.0%
...
```

## 🔄 维护建议

### 定期更新频率
- **每周**：运行排序脚本，检查止损线，关注行业轮动
- **每月**：审视组合健康度，检查再平衡需求
- **每季度**：评估基本面变化，调整因子权重

### 模型优化
- 使用 `backtest_pipeline.py` 定期回测因子有效性
- 根据市场环境调整权重
- 扩展新的量化因子
- 探索更多akshare数据源（运行`explore_akshare_data.py`）

### 数据更新
- 系统每次运行都会获取最新实时数据
- 历史价格数据默认回溯240天
- 建议在交易时间后运行以获取完整当日数据

## ⚠️ 重要声明

1. **模型风险**：量化模型基于历史数据，不保证未来表现
2. **市场风险**：AI行业波动较大，建议控制仓位
3. **数据风险**：使用真实数据时，请确保数据源可靠性
4. **投资建议**：本系统仅供参考，请结合基本面分析
5. **免责声明**：投资有风险，入市需谨慎

## 🤝 贡献与反馈

欢迎提交Issue和Pull Request来改进系统！

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

## 👨‍💻 关于作者

- **创建者**: 个人开发者
- **AI助手**: MiniMax M2.1 / Cursor AI
- **版本**: 2.1 (Advanced Factors + Backtest Pipeline)
- **最后更新**: 2026-05-07

---

## 🤖 AI生成声明

本项目采用 **Vibe Coding** 开发模式：
- 用户用自然语言描述需求
- AI助手理解需求并生成代码
- 用户反馈和迭代优化
- 最终完成功能实现

**核心依赖**:
- [akshare](https://github.com/akfamily/akshare) - 开源财经数据接口，提供实时行情和历史数据
- [MiniMax Agent](https://minimax.chat/) / Cursor AI - AI编程助手

**主要改进 (v2.1)**:
- ✅ 使用真实市场数据替代默认值
- ✅ 从实时行情提取15+因子（PE、PB、PS、收益率、换手率等）
- ✅ 使用稳健横截面百分位打分，修复低值高分因子的方向问题
- ✅ 新增流动性因子和风险调整动量
- ✅ 新增滚动调仓回测Pipeline
- ✅ 智能处理缺失数据（中性分数、代理因子）
- ✅ 数据探索工具帮助发现可用数据源
- ✅ 改进的因子计算逻辑，支持None值处理

## ⚠️ 免责声明

1. **个人项目**: 本项目仅供学习研究，不构成投资建议
2. **AI辅助**: 代码由AI生成，可能存在bugs，请谨慎使用
3. **数据风险**: 股市有风险，投资需谨慎
4. **无担保**: 作者不对任何投资损失负责

---

**祝投资顺利！** 📈
