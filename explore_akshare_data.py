"""
探索akshare可用的数据源
识别可用于选股的因子
"""

import akshare as ak
import pandas as pd
from datetime import datetime, timedelta


def explore_stock_data():
    """探索股票相关数据"""
    print("=" * 70)
    print("探索akshare可用的股票数据")
    print("=" * 70)
    
    # 测试股票代码
    test_symbol = "000001"
    
    # 数据源列表 - 使用正确的akshare函数名
    data_sources = [
        ("实时行情数据", lambda: ak.stock_zh_a_spot_em(), None),
        ("历史价格数据", lambda: ak.stock_zh_a_hist(
            symbol=test_symbol, period="daily",
            start_date="20250101", end_date="20250113", adjust="qfq"
        ), None),
        ("财务指标", lambda: ak.stock_financial_indicator(symbol=test_symbol), "报告期"),
        ("分红送股", lambda: ak.stock_dividend_cninfo(symbol=test_symbol), None),
        ("业绩预告", lambda: ak.stock_yjyg_em(symbol=test_symbol), None),
        ("资金流向", lambda: ak.stock_fund_flow_individual(symbol=test_symbol), None),
        ("行业分类", lambda: ak.stock_board_industry_name_em(), None),
    ]
    
    for i, (name, fetch_func, date_col) in enumerate(data_sources, 1):
        print(f"\n{i}. {name}")
        try:
            df = fetch_func()
            print(f"   记录数: {len(df)}")
            print(f"   可用列: {list(df.columns)[:10]}{'...' if len(df.columns) > 10 else ''}")
            if date_col and date_col in df.columns and len(df) > 0:
                print(f"   最新日期: {df[date_col].iloc[-1]}")
            if len(df) > 0:
                print(f"   示例数据:\n{df.head(1).to_string()[:200]}...")
        except Exception as e:
            print(f"   ✗ 获取失败: {e}")
    
    print("\n" + "=" * 70)
    print("数据探索完成!")
    print("=" * 70)


def identify_factors():
    """
    识别可用于选股的因子
    
    基于akshare可用的数据，推荐以下因子:
    """
    print("\n" + "=" * 70)
    print("推荐的股票因子 (基于akshare可用数据)")
    print("=" * 70)
    
    factors = {
        "动量因子": {
            "returns_5d": "5日收益率",
            "returns_20d": "20日收益率", 
            "returns_60d": "60日收益率",
            "returns_120d": "120日收益率",
            "ma_distance_20": "20日均线偏离度",
            "ma_distance_60": "60日均线偏离度",
        },
        "估值因子": {
            "pe_ttm": "市盈率TTM",
            "pb": "市净率",
            "ps": "市销率",
            "pcf": "现金流倍率",
            "dividend_yield": "股息率",
        },
        "质量因子": {
            "roe": "净资产收益率",
            "roa": "总资产收益率",
            "gross_margin": "毛利率",
            "net_margin": "净利率",
            "ocf_to_revenue": "经营现金流/营收",
            "debt_to_assets": "资产负债率",
        },
        "成长因子": {
            "revenue_growth_yoy": "营收同比增长率",
            "profit_growth_yoy": "利润同比增长率",
            "gross_margin_change": "毛利率变化",
            "ocf_growth_yoy": "经营现金流同比",
        },
        "规模因子": {
            "market_cap": "总市值",
            "circ_market_cap": "流通市值",
            "total_share": "总股本",
            "float_share": "流通股",
        },
        "技术因子": {
            "rsi_14": "RSI(14)",
            "volatility_20d": "20日波动率",
            "volatility_60d": "60日波动率",
            "max_drawdown": "最大回撤",
            "turnover_rate": "换手率",
            "turnover_rate_f": "换手率(流通)",
        },
    }
    
    for category, factor_list in factors.items():
        print(f"\n{category}:")
        for factor, desc in factor_list.items():
            print(f"   - {factor}: {desc}")
    
    print("\n" + "=" * 70)
    print("建议使用的5-10个核心因子:")
    print("=" * 70)
    core_factors = [
        ("returns_20d", "动量", "20日收益率"),
        ("returns_60d", "动量", "60日收益率"),
        ("roe", "质量", "净资产收益率"),
        ("gross_margin", "质量", "毛利率"),
        ("pe_ttm", "估值", "市盈率TTM"),
        ("pb", "估值", "市净率"),
        ("revenue_growth_yoy", "成长", "营收同比增长率"),
        ("profit_growth_yoy", "成长", "利润同比增长率"),
        ("volatility_20d", "风险", "20日波动率"),
        ("max_drawdown", "风险", "最大回撤"),
    ]
    
    print("\n序号 | 因子 | 类别 | 描述")
    print("-" * 60)
    for i, (factor, category, desc) in enumerate(core_factors, 1):
        print(f"{i:2d} | {factor:20s} | {category} | {desc}")


if __name__ == "__main__":
    explore_stock_data()
    identify_factors()
