"""英文翻译: 策略库、参数优化、组合引擎、预设、轮动、验证。"""

EN = {
    "需要 ${:,.0f}, 可用购买力只有 ${:,.0f}": "Needs ${:,.0f}, but only ${:,.0f} buying power is available",

    # --- 策略库 ---
    "基础策略": "Base strategy",
    "双均线交叉": "Moving Average Crossover",
    "快线上穿慢线做多, 下穿则空仓(或反手做空)。经典趋势跟踪, 震荡市会反复挨打。":
        "Go long when the fast MA crosses above the slow MA, go flat (or short) when it crosses below. "
        "Classic trend following; it gets whipsawed in choppy markets.",
    "快线周期": "Fast period",
    "慢线周期": "Slow period",
    "下穿时反手做空": "Short on the cross down",
    "均线未就绪": "Moving averages not ready",
    "EMA 趋势 + ADX 过滤": "EMA Trend + ADX Filter",
    "价格站上 EMA 且 ADX 高于阈值(确认有趋势)才做多, 避免在震荡市里被来回扫。":
        "Go long only when price is above the EMA and ADX is above the threshold (a confirmed trend), "
        "to avoid getting chopped up in sideways markets.",
    "EMA 周期": "EMA period",
    "ADX 周期": "ADX period",
    "ADX 下限": "ADX minimum",
    "跌破时做空": "Short below the EMA",
    "指标未就绪": "Indicators not ready",
    "价 {:.2f} vs EMA{} {:.2f}, ADX={:.1f}": "Price {:.2f} vs EMA{} {:.2f}, ADX={:.1f}",
    "RSI 均值回归": "RSI Mean Reversion",
    "RSI 跌破超卖线买入, 回到中位线卖出。适合震荡市, 单边下跌行情会一路加仓挨套。":
        "Buy when RSI drops below the oversold line, sell when it returns to the midline. "
        "Works in ranging markets; in a one-way decline it keeps buying into losses.",
    "RSI 周期": "RSI period",
    "超卖买入线": "Oversold buy level",
    "平仓线": "Exit level",
    "RSI 未就绪": "RSI not ready",
    "布林带回归": "Bollinger Band Reversion",
    "触及下轨买入, 回到中轨卖出。和 RSI 回归类似, 但阈值随波动率自适应。":
        "Buy at the lower band, sell back at the middle band. Similar to RSI reversion, "
        "but the thresholds adapt to volatility.",
    "周期": "Period",
    "标准差倍数": "Std-dev multiple",
    "布林带未就绪": "Bollinger Bands not ready",
    "价 {:.2f}  下轨 {:.2f} / 中轨 {:.2f} / 上轨 {:.2f}":
        "Price {:.2f}  lower {:.2f} / middle {:.2f} / upper {:.2f}",
    "唐奇安通道突破 (海龟)": "Donchian Breakout (Turtle)",
    "突破 N 日新高做多, 跌破 M 日新低离场。趋势策略的老祖宗, 胜率低但吃得住大行情。":
        "Go long on an N-day high, exit on an M-day low. The grandfather of trend strategies: "
        "a low win rate, but it rides the big moves.",
    "入场周期(新高)": "Entry period (new high)",
    "离场周期(新低)": "Exit period (new low)",
    "破新低反手做空": "Short on a new low",
    "通道未就绪": "Channel not ready",
    "价 {:.2f}  {}日高 {:.2f}  {}日低 {:.2f}": "Price {:.2f}  {}-day high {:.2f}  {}-day low {:.2f}",
    "MACD 金叉死叉": "MACD Crossover",
    "DIF 上穿 DEA 做多, 下穿离场。比双均线更灵敏, 假信号也更多。":
        "Go long when the MACD line crosses above the signal line, exit on the cross below. "
        "More responsive than an MA crossover, and more false signals.",
    "快线": "Fast",
    "慢线": "Slow",
    "信号线": "Signal",
    "死叉反手做空": "Short on the bearish cross",
    "MACD 未就绪": "MACD not ready",
    "动量 + 长期均线过滤": "Momentum + Long-Term MA Filter",
    "N 日涨幅为正、且站上长期均线才持有。牛市吃肉、熊市空仓, 换手率低。":
        "Hold only when the N-day return is positive and price is above the long-term MA. "
        "Rides bull markets, sits out bear markets, low turnover.",
    "动量周期": "Momentum period",
    "长期均线": "Long-term MA",
    "动量下限 %": "Minimum momentum %",
    "{}日动量 {:+.1f}%, 价 {:.2f} vs MA{} {:.2f}": "{}-day momentum {:+.1f}%, price {:.2f} vs MA{} {:.2f}",
    "RSI2 短线抄底 (Connors)": "RSI(2) Dip Buying (Connors)",
    "只在长期均线之上抄短线的底: 价格站上 MA200 (确认大趋势向上) 且 RSI(2) 极低时买入, 反弹到短期均线上方就走。持仓通常只有几天, 换手高但单笔风险小。":
        "Buy short-term dips only inside an uptrend: price above the MA200 (the big trend is up) and "
        "RSI(2) extremely low; exit once it bounces above the short MA. Holds usually last a few days: "
        "high turnover, but small risk per trade.",
    "买入阈值": "Buy threshold",
    "趋势过滤均线": "Trend filter MA",
    "离场均线": "Exit MA",
    "RSI({})={:.1f}, 价 {:.2f} {} MA{} {:.2f}": "RSI({})={:.1f}, price {:.2f} {} MA{} {:.2f}",
    "吊灯止损趋势跟踪": "Chandelier Exit Trend Following",
    "突破 N 日新高进场, 之后用「入场以来最高价 - K倍ATR」作为移动止损。止损随波动率自适应: 波动大时给足空间, 波动小时收紧, 尽量让利润跑完。":
        "Enter on an N-day high, then trail a stop at \"highest price since entry - K x ATR\". "
        "The stop adapts to volatility: wide when markets are volatile, tight when they are calm, "
        "letting winners run.",
    "ATR 周期": "ATR period",
    "ATR 倍数": "ATR multiple",
    "ATR 未就绪": "ATR not ready",
    "持多, 峰值 {:.2f}, 吊灯止损 {:.2f} (现价 {:.2f})": "Long, peak {:.2f}, chandelier stop {:.2f} (price {:.2f})",
    "空仓, 需突破 {:.2f} (现价 {:.2f})": "Flat, needs a break above {:.2f} (price {:.2f})",
    "波动率挤压突破": "Volatility Squeeze Breakout",
    "布林带宽收窄到近期极低水平 = 市场在蓄力, 随后向上突破上轨时跟进。低波动之后常跟着大行情, 这个策略专门埋伏这种转换。":
        "When Bollinger bandwidth shrinks to a recent extreme low, the market is coiling; "
        "follow it when price breaks above the upper band. Big moves often follow quiet periods, "
        "and this strategy waits for exactly that shift.",
    "布林周期": "Bollinger period",
    "带宽分位回看": "Bandwidth percentile lookback",
    "带宽分位阈值 %": "Bandwidth percentile threshold %",
    "带宽 {:.2f}%, 上轨 {:.2f}, 现价 {:.2f}": "Bandwidth {:.2f}%, upper band {:.2f}, price {:.2f}",
    "趋势 + 低波动过滤": "Trend + Low-Volatility Filter",
    "同时要求: 价格在长期均线上方(趋势向上) 且 近期波动率不在高位(市场不恐慌)。高波动期往往对应下跌, 避开它能明显压低回撤。":
        "Requires both: price above the long-term MA (uptrend) and recent volatility not elevated "
        "(no panic). High-volatility periods tend to coincide with declines; avoiding them cuts "
        "drawdowns noticeably.",
    "趋势均线": "Trend MA",
    "波动率回看": "Volatility lookback",
    "波动率分位上限 %": "Max volatility percentile %",
    "价 {:.2f} vs MA{} {:.2f}, ATR% {:.2f}": "Price {:.2f} vs MA{} {:.2f}, ATR% {:.2f}",
    "买入持有 (基准)": "Buy and Hold (benchmark)",
    "第一根就满仓拿到底。所有策略都该跟它比 —— 跑不赢它的策略没有存在意义。":
        "Fully invested from the first bar to the last. Every strategy should be compared against "
        "this; one that cannot beat it has no reason to exist.",
    "始终满仓": "Always fully invested",
    "未知策略: {}": "Unknown strategy: {}",

    # --- 参数优化 ---
    "夏普比率": "Sharpe ratio",
    "总收益率": "Total return",
    "年化收益": "Annualized return",
    "卡玛比率 (年化/回撤)": "Calmar ratio (CAGR / drawdown)",
    "盈亏比": "Profit factor",
    "最大回撤": "Max drawdown",
    "组合数超过上限, 已均匀抽样到 {} 组": "Too many combinations; sampled evenly down to {}",
    "K 线太少, 无法做训练/验证切分 (至少需要约 300 根)":
        "Too few candles for a train/validation split (need about 300)",
    "已中止 (完成 {}/{} 组)": "Stopped ({}/{} combinations done)",
    "没有产生任何有效结果, 试试放宽参数范围或延长回测区间":
        "No valid results. Try widening the parameter ranges or using a longer period.",

    # --- 组合引擎 ---
    "买入持有 ": "Buy and hold ",
    "动量轮动 ({} 只)": "Momentum rotation ({} symbols)",
    "没有权重大于 0 的组成部分": "No sleeve has a weight above 0",
    "「{}」这一块没跑出足够长的净值 (只有 {} 根)":
        "Sleeve \"{}\" did not produce a long enough equity curve (only {} bars)",
    "组合里至少要有一个非现金的部分": "The portfolio needs at least one non-cash sleeve",
    "各部分的历史重叠只有 {} 根 K 线, 太短了 (换更短的区间或去掉上市晚的标的)":
        "The sleeves only overlap for {} bars, which is too short "
        "(pick a shorter period or drop recently listed symbols)",

    # --- 预设组合 (预设名用 N_ 标记: 存盘用中文原文, 这里只管显示) ---
    "动量轮动": "Momentum Rotation",
    "趋势跟踪": "Trend Following",
    "多资产": "Multi-Asset",
    "保守 · 纯核心三支柱": "Conservative · Three-Pillar Core",
    "平衡 · 核心75 + QQQ25": "Balanced · Core 75 + QQQ 25",
    "QQQ卫星": "QQQ satellite",
    "激进 · 核心50 + QQQ50": "Aggressive · Core 50 + QQQ 50",
    "高波动 · 核心80 + TQQQ20": "High Volatility · Core 80 + TQQQ 20",
    "TQQQ卫星": "TQQQ satellite",
    "经典 · 60/40 股债": "Classic · 60/40 Stocks/Bonds",
    "股票": "Stocks",
    "长债": "Long bonds",
    "经典 · 永久组合四分法": "Classic · Permanent Portfolio",
    "黄金": "Gold",
    "经典 · 全天候近似": "Classic · All-Weather (approx.)",
    "中债": "Intermediate bonds",
    "商品": "Commodities",
    "对照 · 全仓 SPY": "Benchmark · 100% SPY",

    # --- 轮动 ---
    "轮动组合": "Rotation portfolio",
    "轮动至少需要 2 个标的": "Rotation needs at least 2 symbols",
    "K 线只有 {} 根, 这套参数至少需要 {} 根": "Only {} candles; these parameters need at least {}",
    "动量轮动 (回看{}根, 持有前{}名, 每{}根调仓{}{})":
        "Momentum rotation (lookback {}, hold top {}, rebalance every {} bars{}{})",
    ", 绝对动量": ", absolute momentum",
    ", MA{}过滤": ", MA{} filter",
    "轮出": "Rotated out",

    # --- 验证 ---
    "没有候选配置": "No candidate configurations",
    "数据太短: %d 根, 至少需要 %d 根": "Not enough data: %d bars, need at least %d",
}
