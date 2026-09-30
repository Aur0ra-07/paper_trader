"""市场浏览: Yahoo 实时榜单 + 本地板块分组。

板块分组是固定代码表, 打开时才批量拉报价; 榜单走 Yahoo screener 接口。
"""
from __future__ import annotations
from .i18n import _tr

# Yahoo predefined screener: (显示名, scrId)
SCREENERS = [
    (_tr("涨幅榜"), "day_gainers"),
    (_tr("跌幅榜"), "day_losers"),
    (_tr("成交活跃"), "most_actives"),
    (_tr("小盘涨幅榜"), "small_cap_gainers"),
    (_tr("做空最多"), "most_shorted_stocks"),
    (_tr("科技成长股"), "growth_technology_stocks"),
    (_tr("低估值成长股"), "undervalued_growth_stocks"),
    (_tr("低估值大盘股"), "undervalued_large_caps"),
    (_tr("激进小盘股"), "aggressive_small_caps"),
]

# 本地板块分组
SECTORS = [
    (_tr("科技七巨头"), ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]),
    (_tr("半导体 / AI"), [
        "NVDA", "AMD", "INTC", "TSM", "AVGO", "QCOM", "MU", "AMAT", "LRCX", "KLAC",
        "ARM", "MRVL", "TXN", "ADI", "NXPI", "ON", "SMCI", "ASML", "SNPS", "CDNS",
        "PLTR", "AI", "SOUN", "BBAI", "CRWV", "VRT", "ANET", "DELL", "HPE", "IONQ"]),
    (_tr("软件 / 互联网"), [
        "CRM", "ORCL", "ADBE", "NOW", "SNOW", "DDOG", "MDB", "NET", "CRWD", "ZS",
        "PANW", "OKTA", "TEAM", "SHOP", "SQ", "PYPL", "UBER", "LYFT", "ABNB", "DASH",
        "SPOT", "NFLX", "RBLX", "U", "TTD", "APP", "SNAP", "PINS", "RDDT", "COIN"]),
    (_tr("中概股"), [
        "BABA", "PDD", "JD", "NTES", "BIDU", "TCOM", "LI", "NIO", "XPEV", "BILI",
        "TME", "YUMC", "ZTO", "BEKE", "IQ", "VIPS", "FUTU", "TIGR", "EDU", "TAL",
        "ATAT", "DDL", "GDS", "HTHT", "LX", "QFIN", "YMM", "ZLAB"]),
    (_tr("指数 / 宽基 ETF"), [
        "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "IVV", "EFA", "EEM", "VEA",
        "VWO", "ARKK", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU",
        "SMH", "SOXX", "IBIT", "GLD", "SLV", "TLT", "HYG", "VNQ", "KWEB", "FXI"]),
    (_tr("杠杆 / 波动 ETF"), [
        "TQQQ", "SQQQ", "SPXL", "SPXS", "SOXL", "SOXS", "TNA", "TZA", "LABU", "LABD",
        "NVDL", "TSLL", "UVXY", "VXX", "SVIX", "UPRO", "SDOW", "UDOW", "YINN", "YANG"]),
    (_tr("银行 / 金融"), [
        "JPM", "BAC", "WFC", "C", "GS", "MS", "SCHW", "BLK", "BX", "KKR",
        "AXP", "V", "MA", "COF", "USB", "PNC", "TFC", "MET", "PRU", "AIG",
        "BRK-B", "SPGI", "CME", "ICE", "COIN", "HOOD", "SOFI", "ALLY"]),
    (_tr("能源 / 资源"), [
        "XOM", "CVX", "COP", "SLB", "EOG", "PSX", "MPC", "VLO", "OXY", "HAL",
        "DVN", "FANG", "HES", "KMI", "WMB", "LNG", "FCX", "NEM", "AA", "CLF",
        "X", "NUE", "STLD", "MP", "UEC", "CCJ", "LEU", "SMR", "OKLO", "VST"]),
    (_tr("医药 / 生物"), [
        "LLY", "UNH", "JNJ", "ABBV", "MRK", "PFE", "TMO", "ABT", "DHR", "BMY",
        "AMGN", "GILD", "VRTX", "REGN", "MRNA", "BNTX", "NVO", "AZN", "CVS", "CI",
        "ISRG", "SYK", "BSX", "MDT", "ZTS", "HIMS", "RXRX", "CRSP", "NTLA", "BEAM"]),
    (_tr("消费 / 零售"), [
        "WMT", "COST", "TGT", "HD", "LOW", "NKE", "SBUX", "MCD", "CMG", "KO",
        "PEP", "PG", "CL", "KMB", "MDLZ", "KHC", "GIS", "HSY", "MO", "PM",
        "LULU", "TJX", "ROST", "DG", "DLTR", "ULTA", "BBY", "EBAY", "ETSY", "CHWY"]),
    (_tr("航空 / 旅游 / 汽车"), [
        "DAL", "UAL", "AAL", "LUV", "ALK", "JBLU", "BA", "RTX", "GE", "HON",
        "MAR", "HLT", "BKNG", "EXPE", "RCL", "CCL", "NCLH", "MGM", "LVS", "WYNN",
        "F", "GM", "STLA", "RIVN", "LCID", "TSLA", "HTZ", "UBER", "LYFT"]),
    (_tr("散户热门股"), [
        "GME", "AMC", "BB", "NOK", "PLTR", "SOFI", "HOOD", "RIVN", "LCID", "NIO",
        "MARA", "RIOT", "CLSK", "MSTR", "COIN", "TLRY", "CGC", "SNDL", "SPCE", "DJT",
        "RDDT", "CVNA", "UPST", "AFRM", "OPEN", "WKHS", "FFIE", "MULN", "BBAI", "SOUN"]),
    (_tr("加密相关"), [
        "COIN", "MSTR", "MARA", "RIOT", "CLSK", "HUT", "BITF", "CIFR", "WULF", "CORZ",
        "HOOD", "BITO", "IBIT", "FBTC", "ETHE", "GBTC", "BTBT", "SDIG", "GLXY",
        "BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD", "BNB-USD"]),
    (_tr("国防 / 航天"), [
        "LMT", "RTX", "NOC", "GD", "BA", "LHX", "HII", "TXT", "LDOS", "BAH",
        "KTOS", "AVAV", "RKLB", "ASTS", "LUNR", "PL", "SPCE", "HEI", "TDG", "CW"]),
    (_tr("房地产 REITs"), [
        "PLD", "AMT", "EQIX", "CCI", "PSA", "SPG", "O", "WELL", "DLR", "VICI",
        "AVB", "EQR", "INVH", "MAA", "ESS", "ARE", "BXP", "KIM", "HST", "IRM"]),
    (_tr("公用 / 电力 / 核能"), [
        "NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE", "XEL", "ED", "PEG",
        "VST", "CEG", "NRG", "TLN", "SMR", "OKLO", "LEU", "CCJ", "UEC", "BWXT"]),
    (_tr("⚡3倍杠杆 ETF (激进)"), [
        "TQQQ", "SOXL", "SPXL", "UPRO", "TNA", "UDOW", "LABU", "FNGU", "BULZ",
        "WEBL", "DFEN", "DPST", "RETL", "NAIL", "CURE", "TECL", "FAS", "ERX",
        "YINN", "GUSH", "MIDU", "UMDD", "URTY"]),
    (_tr("⚡单股杠杆 ETF (极激进)"), [
        "NVDL", "TSLL", "MSTX", "MSTU", "AAPU", "AMZU", "GGLL", "MSFU", "METU",
        "PLTU", "AMDL", "CONL", "ELIL", "SMCX", "TSMX", "AVL", "MUU"]),
    (_tr("⚡高波动成长股 (激进)"), [
        "NVDA", "AMD", "SMCI", "PLTR", "COIN", "MSTR", "MARA", "RIOT", "CLSK",
        "TSLA", "RIVN", "LCID", "SOUN", "BBAI", "IONQ", "RGTI", "QBTS", "ARQQ",
        "OKLO", "SMR", "LEU", "ASTS", "RKLB", "LUNR", "CRWV", "VRT", "HIMS",
        "HOOD", "AFRM", "UPST", "CVNA", "APP", "RDDT", "ARM", "ONDS"]),
    (_tr("道指 30 成分股"), [
        "AAPL", "AMGN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS", "DOW",
        "GS", "HD", "HON", "IBM", "JNJ", "JPM", "KO", "MCD", "MMM", "MRK",
        "MSFT", "NKE", "NVDA", "PG", "SHW", "TRV", "UNH", "V", "VZ", "WMT"]),
]

SECTOR_NAMES = [name for name, _ in SECTORS]
SECTOR_MAP = dict(SECTORS)
