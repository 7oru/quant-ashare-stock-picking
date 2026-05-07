"""
配置模块
Configuration Module

包含因子权重、行业调整系数、仓位限制等配置参数
"""

# 因子权重配置
FACTOR_WEIGHTS = {
    'momentum': 0.30,      # 趋势、加速度、风险调整动量
    'quality': 0.20,       # 盈利质量；缺失时用估值/风险/流动性代理
    'growth': 0.15,        # 财务成长；缺失时用YTD和风险调整动量代理
    'valuation': 0.15,     # PE/PB/PS/PCF/PEG，低估值高分
    'volatility': 0.10,    # 年化波动、下行波动、回撤、ATR
    'liquidity': 0.10      # 换手、量比、市值/成交额
}

# 行业调整系数（不同行业的因子需要调整）
INDUSTRY_ADJUSTMENT = {
    '上游-算力基础设施': {'valuation': 1.0, 'growth': 1.0, 'quality': 1.0},
    '上游-液冷技术': {'valuation': 1.0, 'growth': 1.1, 'quality': 1.0},
    '上游-电力设备': {'valuation': 0.9, 'growth': 0.9, 'quality': 1.1},
    '中游-芯片': {'valuation': 1.2, 'growth': 1.2, 'quality': 0.9},
    '中游-光模块': {'valuation': 1.0, 'growth': 1.1, 'quality': 1.0},
    '中游-数据平台': {'valuation': 0.9, 'growth': 1.0, 'quality': 1.0},
    '中游-大模型': {'valuation': 1.3, 'growth': 1.3, 'quality': 0.8},
    '下游-智能驾驶': {'valuation': 1.0, 'growth': 1.1, 'quality': 1.0},
    '下游-AI办公': {'valuation': 1.0, 'growth': 1.1, 'quality': 1.0},
    '下游-AI金融': {'valuation': 0.9, 'growth': 1.0, 'quality': 1.1},
    '数据中心基础设施': {'valuation': 0.85, 'growth': 0.9, 'quality': 1.1},
    '电力设备': {'valuation': 0.85, 'growth': 0.85, 'quality': 1.1},
    '液冷技术': {'valuation': 1.0, 'growth': 1.1, 'quality': 1.0},
    '智能机器人': {'valuation': 1.1, 'growth': 1.2, 'quality': 0.95},
    'AI应用软件': {'valuation': 1.0, 'growth': 1.0, 'quality': 1.0}
}

# 单票和行业配置限制
POSITION_LIMITS = {
    'max_single_stock': 0.15,      # 单票最大仓位15%
    'max_sector': 0.30,            # 单行业最大仓位30%
    'max_sub_sector': 0.25,        # 单一子行业最大仓位25%
    'min_stock_weight': 0.02,      # 最小入选仓位2%
    'min_rank_for_position': 40    # 排名40名以后不配置
}
