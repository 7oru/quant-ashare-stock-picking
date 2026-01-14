"""
配置模块 - Quant Trader Recommended Weights
Configuration Module - Quant Trader Recommended Weights

基于因子相关性分析优化的权重配置
"""

# ============================================================================
# 推荐权重配置 (Recommended Weights)
# ============================================================================
# 基于因子相关性分析:
# - Momentum: 0.629 correlation → 30% weight (reduced from 35%)
# - Quality: 0.531 correlation → 25% weight (increased from 20%)
# - Growth: 0.572 correlation → 20% weight (increased from 15%)
# - Valuation: 0.187 correlation → 15% weight (keep for risk control)
# - Volatility: -0.013 correlation → 10% weight (reduced from 15%)
# ============================================================================

FACTOR_WEIGHTS_RECOMMENDED = {
    'momentum': 0.30,      # ↓ Reduced from 35% (high correlation with Growth)
    'quality': 0.25,       # ↑ Increased from 20% (strong correlation, underweighted)
    'growth': 0.20,        # ↑ Increased from 15% (strong predictive power)
    'valuation': 0.15,     # → Keep at 15% (low correlation but important for risk control)
    'volatility': 0.10     # ↓ Reduced from 15% (zero correlation with composite score)
}

# ============================================================================
# 保守配置 (Conservative - Quality Focused)
# ============================================================================
FACTOR_WEIGHTS_CONSERVATIVE = {
    'momentum': 0.28,
    'quality': 0.30,       # Significantly increased
    'growth': 0.18,
    'valuation': 0.14,
    'volatility': 0.10
}

# ============================================================================
# 激进配置 (Aggressive - Momentum-Growth Focused)
# ============================================================================
FACTOR_WEIGHTS_AGGRESSIVE = {
    'momentum': 0.35,      # Keep high
    'growth': 0.25,        # Significantly increased
    'quality': 0.20,
    'valuation': 0.12,
    'volatility': 0.08     # Significantly reduced
}

# ============================================================================
# 当前配置 (Current Configuration)
# ============================================================================
FACTOR_WEIGHTS_CURRENT = {
    'momentum': 0.35,
    'quality': 0.20,
    'growth': 0.15,
    'valuation': 0.15,
    'volatility': 0.15
}

# ============================================================================
# 使用推荐配置 (Use Recommended)
# ============================================================================
FACTOR_WEIGHTS = FACTOR_WEIGHTS_RECOMMENDED

# ============================================================================
# 行业调整系数（保持不变）
# ============================================================================
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

# ============================================================================
# 仓位限制（保持不变）
# ============================================================================
POSITION_LIMITS = {
    'max_single_stock': 0.15,      # 单票最大仓位15%
    'max_sector': 0.30,            # 单行业最大仓位30%
    'max_sub_sector': 0.25,        # 单一子行业最大仓位25%
    'min_stock_weight': 0.02,      # 最小入选仓位2%
    'min_rank_for_position': 40    # 排名40名以后不配置
}
