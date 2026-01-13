"""
利用Python内省功能探索akshare财务数据接口
通过 dir(ak) 和 help(ak.函数名) 发现和测试可用的数据接口
"""

import akshare as ak
import pandas as pd
import re


def list_all_akshare_functions():
    """使用dir()列出akshare所有可用函数"""
    print("=" * 70)
    print("使用 dir(ak) 内省功能 - 列出所有AKShare可用函数")
    print("=" * 70)
    
    all_attrs = dir(ak)
    
    # 过滤出以stock_开头的函数（股票相关）
    stock_funcs = [attr for attr in all_attrs if attr.startswith('stock_')]
    print(f"\n股票相关函数 (stock_*): {len(stock_funcs)} 个")
    
    # 分类显示
    categories = {
        '行情数据': ['stock_zh_a_spot', 'stock_zh_a_hist', 'stock_zh_a_minute', 
                    'stock_zh_index_spot', 'stock_hk_spot', 'stock_us_spot'],
        '财务数据': ['stock_financial_indicator', 'stock_dupont', 'stock_yjbb', 
                    'stock_dividend', 'stock_sg_express'],
        '估值指标': ['stock_valuation_ah', 'stock_valuation', 'stock_valuation_sw',
                    'stock_fund_flow', 'stock_market_activity'],
        '龙虎榜': ['stock_lhb', 'stock_hsgt', 'stock_zt_pool', 'stock_zt_pool_em'],
        '资金流向': ['stock_fund_flow_individual', 'stock_fund_flow', 'stock_market_fund_flow'],
        '股东信息': ['stock_shareholder_holding', 'stock_shareholder_holdernum', 
                    'stock_holder_trade', 'stock_holder_number'],
        'ESG': ['stock_esg'],
        '基本面': ['stock_basics', 'stock_company', 'stock_report_shareholder'],
    }
    
    print("\n按类别整理的常用函数:")
    for category, funcs in categories.items():
        available = [f for f in funcs if f in all_attrs]
        if available:
            print(f"\n  {category}:")
            for f in available:
                print(f"    - {f}")
    
    return stock_funcs


def get_function_help(func_name):
    """使用help()获取函数文档"""
    try:
        func = getattr(ak, func_name)
        print(f"\n{'='*60}")
        print(f"函数: ak.{func_name}")
        print(f"{'='*60}")
        help(func)
    except Exception as e:
        print(f"获取帮助失败: {e}")


def explore_and_test_functions(stock_funcs):
    """探索并测试财务相关函数"""
    print("\n" + "=" * 70)
    print("测试可用的财务数据接口")
    print("=" * 70)
    
    test_symbol = "000977"  # 浪潮信息 - 稳定的测试股票
    
    # 定义要测试的函数列表（按优先级排序）
    test_functions = [
        # 核心财务数据
        ('stock_financial_indicator', '财务指标'),
        ('stock_dupont', '杜邦分析'),
        ('stock_yjbb', '业绩报表'),
        ('stock_dividend_cninfo', '分红配股'),
        ('stock_dividend', '分红数据'),
        
        # 实时行情数据
        ('stock_zh_a_spot_em', '实时行情(东方财富)'),
        ('stock_zh_a_hist', '历史K线'),
        ('stock_zh_index_spot', '指数实时行情'),
        
        # 资金流向
        ('stock_fund_flow_individual', '个股资金流向'),
        ('stock_fund_flow', '资金流向'),
        ('stock_market_fund_flow', '市场资金流向'),
        
        # 龙虎榜/涨停
        ('stock_lhb', '龙虎榜'),
        ('stock_zt_pool_em', '涨停板(东方财富)'),
        ('stock_zt_pool', '涨停板'),
        
        # 股东信息
        ('stock_shareholder_holdernum', '股东人数'),
        ('stock_holder_trade', '股东增减持'),
        ('stock_holder_number', '股东人数(新版)'),
        
        # ESG
        ('stock_esg', 'ESG评级'),
        
        # 公司信息
        ('stock_company', '公司信息'),
        ('stock_basics', '股票基础数据'),
        
        # 估值数据
        ('stock_valuation_ah', 'AH股估值'),
        ('stock_valuation', '股票估值'),
        ('stock_valuation_sw', '申万估值'),
        
        # 资金持仓
        ('stock_fund_flow_hsgt', '沪深港通资金流向'),
        ('stock_hsgt', '沪深港通持股'),
        
        # 业绩预告
        ('stock_yjyg', '业绩预告'),
        ('stock_yyss', '业绩快报'),
    ]
    
    available_count = 0
    unavailable_count = 0
    
    for func_name, description in test_functions:
        if func_name in stock_funcs:
            available_count += 1
            print(f"\n✓ {description} ({func_name})")
            try:
                func = getattr(ak, func_name)
                
                # 根据函数特点选择不同参数
                if 'symbol' in func.__code__.co_varnames:
                    if func_name == 'stock_zh_a_spot_em':
                        result = func()
                    elif func_name == 'stock_zh_index_spot':
                        result = func()
                    elif func_name == 'stock_fund_flow':
                        result = func()
                    elif func_name == 'stock_market_fund_flow':
                        result = func()
                    elif func_name == 'stock_zt_pool_em':
                        result = func()
                    elif func_name == 'stock_zt_pool':
                        result = func()
                    elif func_name == 'stock_hsgt':
                        result = func()
                    elif func_name == 'stock_fund_flow_hsgt':
                        result = func()
                    else:
                        result = func(symbol=test_symbol)
                else:
                    result = func()
                
                if isinstance(result, pd.DataFrame):
                    print(f"  数据行数: {len(result)}")
                    print(f"  可用列: {list(result.columns)[:10]}...")  # 只显示前10列
                    if len(result) > 0:
                        print(f"  数据预览:\n{result.head(2).to_string()}")
                else:
                    print(f"  返回类型: {type(result)}")
                    print(f"  结果: {result}")
                    
            except Exception as e:
                print(f"  ✗ 获取失败: {e}")
        else:
            unavailable_count += 1
            print(f"\n✗ {description} ({func_name}) - 函数不存在")
    
    print(f"\n{'='*60}")
    print(f"测试完成: 可用 {available_count} 个, 不可用 {unavailable_count} 个")
    return available_count


def discover_popular_factors():
    """分析并列举热门因子"""
    print("\n" + "=" * 70)
    print("热门因子分析 (可使用的10-20个热门因子)")
    print("=" * 70)
    
    # 获取实时行情数据来展示可用的因子
    try:
        spot_df = ak.stock_zh_a_spot_em()
        print(f"\n从 stock_zh_a_spot_em 获取到的字段 (共 {len(spot_df.columns)} 个):")
        for i, col in enumerate(spot_df.columns, 1):
            print(f"  {i:2d}. {col}")
    except Exception as e:
        print(f"获取实时行情失败: {e}")
        spot_df = None
    
    factors = {
        # ==================== 估值因子 ====================
        "valuation_factors": {
            "PE_TTM": {
                "name": "市盈率(TTM)",
                "field": "市盈率-动态",
                "description": "股价除以过去12个月每股收益，衡量股价相对盈利水平的指标",
                "usage": "低PE通常表示股票被低估，但需结合行业和成长性判断",
                "typical_range": "0-50 (周期性行业可达100+)"
            },
            "PE_LYR": {
                "name": "市盈率(静态)",
                "field": "市盈率",
                "description": "股价除以上一年度每股收益",
                "usage": "适用于成熟稳定的企业估值",
                "typical_range": "0-50"
            },
            "PB": {
                "name": "市净率",
                "field": "市净率",
                "description": "股价除以每股净资产，衡量股价相对于公司资产的溢价程度",
                "usage": "适用于重资产行业和银行业，PB<1可能被低估",
                "typical_range": "1-10 (银行股常见0.5-1.5)"
            },
            "PS": {
                "name": "市销率",
                "field": "市销率",
                "description": "股价除以每股销售额",
                "usage": "适用于成长型企业或亏损企业",
                "typical_range": "1-20"
            },
            "PCF": {
                "name": "市现率",
                "field": "市现率",
                "description": "股价除以每股现金流",
                "usage": "现金流稳定的企业适用",
                "typical_range": "5-20"
            },
        },
        
        # ==================== 规模因子 ====================
        "size_factors": {
            "MARKET_CAP": {
                "name": "总市值",
                "field": "总市值",
                "description": "公司总股本乘以股价",
                "usage": "用于区分大盘股、中盘股、小盘股",
                "typical_range": "大盘>500亿, 中盘50-500亿, 小盘<50亿"
            },
            "CIRC_MARKET_CAP": {
                "name": "流通市值",
                "field": "流通市值",
                "description": "流通股本乘以股价，反映实际可交易市值",
                "usage": "流通盘大小影响流动性和股价波动性",
                "typical_range": "同上"
            },
        },
        
        # ==================== 成长因子 ====================
        "growth_factors": {
            "REVENUE_GROWTH": {
                "name": "营收增长率",
                "field": "营收同比增长",
                "description": "当期营业收入相比上期的增长比例",
                "usage": "高成长企业通常有较高营收增速",
                "typical_range": "-50% ~ +100%+"
            },
            "PROFIT_GROWTH": {
                "name": "利润增长率",
                "field": "利润同比增长",
                "description": "当期净利润相比上期的增长比例",
                "usage": "核心成长指标，需注意波动性",
                "typical_range": "-100% ~ +500%+"
            },
            "NP_GROWTH": {
                "name": "净利润增长率",
                "field": "净利润同比增长",
                "description": "归属于母公司净利润的增长比例",
                "usage": "衡量企业盈利能力增长",
                "typical_range": "-100% ~ +500%+"
            },
        },
        
        # ==================== 盈利能力因子 ====================
        "profitability_factors": {
            "ROE": {
                "name": "净资产收益率",
                "field": None,  # 需要从财务数据计算
                "description": "净利润/净资产，衡量股东权益回报水平",
                "usage": "ROE>15%通常被认为是优质企业",
                "typical_range": "5% ~ 30%"
            },
            "ROA": {
                "name": "总资产收益率",
                "field": None,
                "description": "净利润/总资产，衡量资产使用效率",
                "usage": "银行等重资产行业参考",
                "typical_range": "1% ~ 10%"
            },
            "GROSS_MARGIN": {
                "name": "毛利率",
                "field": "毛利率",
                "description": "(营业收入-营业成本)/营业收入",
                "usage": "反映产品定价权和竞争力",
                "typical_range": "10% ~ 80%"
            },
            "NET_MARGIN": {
                "name": "净利率",
                "field": "净利率",
                "description": "净利润/营业收入",
                "usage": "反映最终盈利能力",
                "typical_range": "2% ~ 30%"
            },
        },
        
        # ==================== 动量因子 ====================
        "momentum_factors": {
            "RETURNS_5D": {
                "name": "5日涨跌幅",
                "field": "5日涨跌幅",
                "description": "最近5个交易日的累计涨跌幅",
                "usage": "短期动量指标，注意反转效应",
                "typical_range": "-30% ~ +50%"
            },
            "RETURNS_10D": {
                "name": "10日涨跌幅",
                "field": "10日涨跌幅",
                "description": "最近10个交易日的累计涨跌幅",
                "usage": "中期动量指标",
                "typical_range": "-40% ~ +70%"
            },
            "RETURNS_60D": {
                "name": "60日涨跌幅",
                "field": "60日涨跌幅",
                "description": "最近60个交易日的累计涨跌幅",
                "usage": "长期动量指标",
                "typical_range": "-60% ~ +150%"
            },
            "RETURNS_YTD": {
                "name": "年初至今涨跌幅",
                "field": "年初至今涨跌幅",
                "description": "当年以来累计涨跌幅",
                "usage": "年度表现指标",
                "typical_range": "-50% ~ +200%"
            },
        },
        
        # ==================== 流动性因子 ====================
        "liquidity_factors": {
            "TURNOVER_RATE": {
                "name": "换手率",
                "field": "换手率",
                "description": "成交量/流通股本，反映交易活跃度",
                "usage": "高换手可能表示炒作或主力出货",
                "typical_range": "0.5% ~ 10%"
            },
            "TURNOVER_RATE_F": {
                "name": "换手率(自由流通股)",
                "field": "换手率(自由流通股)",
                "description": "成交量/自由流通股，反映真实换手情况",
                "usage": "更准确的流动性指标",
                "typical_range": "0.5% ~ 15%"
            },
            "VOLUME_RATIO": {
                "name": "量比",
                "field": "量比",
                "description": "当日成交量/过去5日平均成交量",
                "usage": "量比>2可能表示异动",
                "typical_range": "0.2 ~ 5"
            },
        },
        
        # ==================== 市场情绪因子 ====================
        "sentiment_factors": {
            "ADVANCE_DECLINE": {
                "name": "涨跌停状态",
                "field": "涨跌幅",
                "description": "当日涨跌幅",
                "usage": "判断股票短期强势/弱势",
                "typical_range": "-10% ~ +10%"
            },
            "AMPLITUDE": {
                "name": "振幅",
                "field": "振幅",
                "description": "当日最高价与最低价之差/昨收",
                "usage": "反映日内波动程度",
                "typical_range": "0% ~ 20%"
            },
        },
        
        # ==================== 财务健康因子 ====================
        "health_factors": {
            "CURRENT_RATIO": {
                "name": "流动比率",
                "field": None,
                "description": "流动资产/流动负债",
                "usage": "短期偿债能力指标，>1.5较为安全",
                "typical_range": "0.5 ~ 3"
            },
            "DEBT_TO_ASSET": {
                "name": "资产负债率",
                "field": None,
                "description": "总负债/总资产",
                "usage": "财务杠杆水平，过高有风险",
                "typical_range": "20% ~ 70%"
            },
        },
    }
    
    print("\n" + "-" * 70)
    print("热门因子详细列表")
    print("-" * 70)
    
    all_factors = []
    for category, factor_dict in factors.items():
        print(f"\n【{category.upper()}】")
        for key, info in factor_dict.items():
            all_factors.append(info)
            field_str = info["field"] if info["field"] else "需计算"
            print(f"\n  {key}: {info['name']}")
            print(f"    字段: {field_str}")
            print(f"    描述: {info['description']}")
            print(f"    用途: {info['usage']}")
            print(f"    常见范围: {info['typical_range']}")
    
    print("\n" + "=" * 70)
    print(f"共整理 {len(all_factors)} 个热门因子")
    print("=" * 70)
    
    # 生成可直接使用的字段列表
    print("\n可直接从 stock_zh_a_spot_em 获取的因子字段:")
    if spot_df is not None:
        available_fields = []
        for category, factor_dict in factors.items():
            for key, info in factor_dict.items():
                if info["field"] and info["field"] in spot_df.columns:
                    available_fields.append(info["field"])
                    print(f"  ✓ {info['field']}")
        
        print(f"\n可直接使用: {len(available_fields)}/{len(all_factors)} 个字段")
    
    return factors


def explore_additional_data_sources():
    """探索其他数据源"""
    print("\n" + "=" * 70)
    print("探索其他数据源")
    print("=" * 70)
    
    # 探索指数数据
    print("\n【指数数据】")
    try:
        index_df = ak.stock_zh_index_spot()
        print(f"可用指数: {list(index_df['代码'].head(20))}")
    except Exception as e:
        print(f"获取失败: {e}")
    
    # 探索期货数据
    print("\n【期货数据】")
    try:
        futures = [attr for attr in dir(ak) if 'futures' in attr.lower() or 'future' in attr.lower()]
        print(f"期货相关函数: {futures[:10]}")
    except Exception as e:
        print(f"获取失败: {e}")
    
    # 探索宏观经济数据
    print("\n【宏观经济数据】")
    try:
        macro = [attr for attr in dir(ak) if 'macro' in attr.lower()]
        print(f"宏观相关函数: {macro[:10]}")
    except Exception as e:
        print(f"获取失败: {e}")


def analyze_factor_availability():
    """分析各数据源可提供的因子"""
    print("\n" + "=" * 70)
    print("数据源与因子对应关系")
    print("=" * 70)
    
    data_source_factors = {
        "stock_zh_a_spot_em": {
            "description": "东方财富A股实时行情",
            "factors": [
                "代码", "名称", "最新价", "涨跌幅", "涨跌额", "成交量", "成交额",
                "振幅", "最高", "最低", "今开", "昨收", "换手率", "换手率(自由流通股)",
                "市盈率-动态", "市盈率", "市净率", "市销率", "市现率",
                "总市值", "流通市值", "涨跌幅", "5日涨跌幅", "10日涨跌幅",
                "60日涨跌幅", "年初至今涨跌幅", "量比"
            ],
            "usage": "实时选股、因子监控、交易信号"
        },
        "stock_financial_indicator": {
            "description": "财务指标数据",
            "factors": [
                "每股收益EPS", "净资产收益率ROE", "毛利率", "净利率",
                "资产负债率", "营业利润率", "营收增长率", "利润增长率"
            ],
            "usage": "基本面选股、价值投资、财报分析"
        },
        "stock_dupont": {
            "description": "杜邦分析",
            "factors": [
                "ROE", "净利率", "总资产周转率", "权益乘数",
                "销售净利率", "总资产周转率", "权益乘数"
            ],
            "usage": "盈利能力分解、财务质量分析"
        },
        "stock_yjbb": {
            "description": "业绩报表",
            "factors": [
                "报告期", "每股收益", "营收收入", "净利润",
                "扣非净利润", "经营现金流"
            ],
            "usage": "业绩趋势分析、盈利预测"
        },
        "stock_lhb": {
            "description": "龙虎榜数据",
            "factors": [
                "上榜原因", "买入金额", "卖出金额", "净额",
                "买入营业部", "卖出营业部"
            ],
            "usage": "主力资金追踪、席位分析"
        },
        "stock_fund_flow_individual": {
            "description": "个股资金流向",
            "factors": [
                "主力净流入", "超大单净流入", "大单净流入",
                "中单净流入", "小单净流入"
            ],
            "usage": "资金情绪分析、短期择时"
        },
    }
    
    for source, info in data_source_factors.items():
        print(f"\n【{source}】")
        print(f"  说明: {info['description']}")
        print(f"  用途: {info['usage']}")
        print(f"  因子 ({len(info['factors'])}个): {', '.join(info['factors'][:8])}...")


if __name__ == "__main__":
    print("=" * 70)
    print("AKShare 财务数据接口探索工具")
    print("利用Python内省功能: dir(ak) 和 help(ak.函数名)")
    print("=" * 70)
    
    # 1. 使用dir()内省列出所有函数
    stock_funcs = list_all_akshare_functions()
    
    # 2. 探索并测试可用函数
    explore_and_test_functions(stock_funcs)
    
    # 3. 分析热门因子
    factors = discover_popular_factors()
    
    # 4. 探索其他数据源
    explore_additional_data_sources()
    
    # 5. 分析因子可用性
    analyze_factor_availability()
    
    print("\n" + "=" * 70)
    print("探索完成!")
    print("=" * 70)
