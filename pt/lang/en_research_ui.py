"""英文翻译: 组合页、动量轮动页、稳健性测试、收益分布。"""

EN = {
    # --- 组合页 ---
    "买入持有": "Buy and Hold",
    "择时策略": "Timing Strategy",
    "拉取 {} ({}/{})": "Fetching {} ({}/{})",
    "没有拿到任何数据": "No data returned",
    "组合回测中…": "Running portfolio backtest…",
    "组合回测失败: {}": "Portfolio backtest failed: {}",
    "编辑组成部分": "Edit Sleeve",
    "新的一块": "New sleeve",
    "代码用逗号分隔": "Symbols, comma-separated",
    "标的": "Symbols",
    "轮动回看(根)": "Rotation lookback (bars)",
    "轮动持有前几名": "Rotation: hold top N",
    "权重": "Weight",
    "未命名": "Untitled",
    "组合构成": "Portfolio Composition",
    "金融里唯一免费的午餐是<b>分散</b>：几个相关性低的收益来源拼起来，夏普会高于其中任何一个，回撤还更小。<br>要更高收益，正确做法是调「卫星」的比例，不是去梭哈更疯的标的。":
        "The only free lunch in finance is <b>diversification</b>: combining a few weakly correlated "
        "return streams gives a higher Sharpe than any one of them, with a smaller drawdown.<br>"
        "For more return, raise the satellite share instead of going all in on something wilder.",
    "预设组合": "Preset",
    "添加": "Add",
    "编辑": "Edit",
    "删除": "Delete",
    "回测区间": "Backtest period",
    "每月": "Monthly",
    "每季度": "Quarterly",
    "每半年": "Semi-annually",
    "每年": "Annually",
    "从不": "Never",
    "再平衡": "Rebalance",
    " 倍": "x",
    "散户融资利率 6%，对年化 8% 左右的组合加杠杆通常得不偿失":
        "Retail margin rates are around 6%; leveraging a portfolio that returns about 8% a year "
        "rarely pays off",
    "融资杠杆": "Leverage",
    "0 = 关闭。开启后按实际波动率动态调整总仓位":
        "0 = off. When on, total exposure scales with realized volatility",
    "目标年化波动率": "Target annual volatility",
    "用风险平价自动分配权重（按波动率倒数）": "Risk parity weights (inverse volatility)",
    "运行组合回测": "Run Portfolio Backtest",
    "选好组合后点「运行组合回测」": "Set up the portfolio and click Run Portfolio Backtest",
    "全仓 SPY": "100% SPY",
    "同时画出每一块单独的净值": "Also plot each sleeve's own equity curve",
    "总收益": "Total Return",
    "年化": "CAGR",
    "夏普": "Sharpe",
    "卡玛": "Calmar",
    "全仓SPY": "100% SPY",
    "超额": "Excess",
    "平均相关性": "Avg Correlation",
    "平均仓位": "Avg Exposure",
    "再平衡次数": "Rebalances",
    "相关性": "Correlation",
    "说明": "Meaning",
    "相关性矩阵": "Correlation Matrix",
    "组成部分": "Sleeve",
    "各部分单独表现": "Sleeve Performance",
    "组合里至少要有一块。": "The portfolio needs at least one sleeve.",
    "准备中…": "Preparing…",
    "上一次还在跑": "The previous run is still going",
    "组合回测失败": "Portfolio Backtest Failed",
    "完成 · {} 根 K 线": "Done · {} bars",
    "最大回撤 <b>{:.1f}%</b> vs 全仓 SPY <b>{:.1f}%</b>；年化 {:.1f}% vs {:.1f}%。<br><span style='color:{}'>看卡玛比率（年化÷回撤）而不是只看总收益——回撤才是你真正要承受的东西。平均相关性越低，分散越有效。</span>":
        "Max drawdown <b>{:.1f}%</b> vs 100% SPY <b>{:.1f}%</b>; CAGR {:.1f}% vs {:.1f}%.<br>"
        "<span style='color:{}'>Look at the Calmar ratio (CAGR ÷ drawdown), not just total return: "
        "the drawdown is what you actually have to sit through. The lower the average correlation, "
        "the more the diversification helps.</span>",
    "几乎不相关，分散效果好": "Nearly uncorrelated; good diversification",
    "中度相关": "Moderately correlated",
    "高度相关，分散作用有限": "Highly correlated; limited diversification",

    # --- 收益分布 ---
    "持有 N 个月的收益分布 (任意一天入场, 历史上所有可能的结果)":
        "Returns over N-month holds (every possible entry day in history)",
    "持有时长": "Holding Period",
    "最差": "Worst",
    "较差(10%)": "10th pct",
    "中位": "Median",
    "较好(90%)": "90th pct",
    "最好": "Best",
    "赚钱概率": "P(gain)",
    "赚超50%概率": "P(gain > 50%)",
    "亏超20%概率": "P(loss > 20%)",
    "样本数": "Samples",
    "「中位」才是你该预期的那个数, 「最好」那一列是历史上最幸运的一次入场, 不是你能复制的。重点看最左边那两列 —— 那是你真的会遇到的坏情况。":
        "The median is the number to expect. \"Best\" is the luckiest entry in history, which you cannot "
        "repeat. Focus on the two leftmost columns: those are the bad cases you will really face.",

    # --- 标的池 / 区间选择 ---
    "板块: {} ({})": "Sector: {} ({})",
    "自定义 (手动输入)": "Custom (type symbols)",
    "最近 10 年": "Last 10 years",
    "最近 5 年": "Last 5 years",
    "2004-至今 (含2008)": "2004-present (incl. 2008)",
    "1998-2012 (两次崩盘)": "1998-2012 (two crashes)",
    "2000-2003 互联网泡沫": "2000-2003 dot-com bust",
    "2007-2009 金融危机": "2007-2009 financial crisis",
    "2020 疫情": "2020 COVID crash",
    "2022 加息熊市": "2022 rate-hike bear market",
    "自定义": "Custom",

    # --- 动量轮动 ---
    "只拿到 {} 个标的的数据, 轮动至少需要 2 个": "Only got data for {} symbols; rotation needs at least 2",
    "轮动回测中… ({} 只)": "Running rotation backtest… ({} symbols)",
    "回测失败: {}": "Backtest failed: {}",
    "没有拿到足够长的 K 线": "Could not get enough candles",
    "回测 {} ({}/{})": "Backtesting {} ({}/{})",
    "动量轮动设置": "Momentum Rotation Setup",
    "不再问「这只股票该不该买」, 而是问「这一篮子里哪几只最强」。<br>永远满仓最强的几只, 定期换马; 开了绝对动量的话, 全都在跌时退回现金。":
        "Instead of asking \"should I buy this stock\", ask \"which few in this basket are strongest\".<br>"
        "Always hold the strongest few and rotate on a schedule; with absolute momentum on, "
        "it moves to cash when everything is falling.",
    "标的池": "Universe",
    "日线 120 根 ≈ 半年动量": "120 daily bars ≈ 6-month momentum",
    "动量回看(根)": "Momentum lookback (bars)",
    "0 = 不用。设了就和主窗口取平均, 更稳一些": "0 = off. If set, it is averaged with the main window for stability",
    "第二回看窗口": "Second lookback",
    "跳过最近 N 根 —— 学术上短期有反转效应":
        "Skip the most recent N bars (short-term reversal is documented in the literature)",
    "跳过最近(根)": "Skip recent (bars)",
    "持有前几名": "Hold top N",
    "日线 21 根 ≈ 每月调仓; 太频繁会被手续费吃掉":
        "21 daily bars ≈ monthly rebalance; trading too often gets eaten by fees",
    "调仓间隔(根)": "Rebalance every (bars)",
    "0 = 不用。要求价格在该均线之上才买": "0 = off. Only buy when price is above this MA",
    "趋势均线过滤": "Trend MA filter",
    "1 = 不融资。>1 会按年化利率计息, 且净值击穿维持保证金会被强平":
        "1 = no margin. Above 1, interest accrues at the annual rate, and falling through "
        "maintenance margin triggers forced liquidation",
    "绝对动量 (全都在跌时退回现金)": "Absolute momentum (cash when all fall)",
    "运行轮动回测": "Run Rotation Backtest",
    "选好标的池后点「运行轮动回测」": "Choose a universe and click Run Rotation Backtest",
    "轮动策略": "Rotation",
    "等权买入持有": "Equal-Weight Buy and Hold",
    "超额收益": "Excess Return",
    "换手次数": "Turnover",
    "调仓次数": "Rebalances",
    "调仓日期": "Rebalance Date",
    "持有标的": "Holdings",
    "持仓变迁": "Holdings Over Time",
    "买入价": "Buy Price",
    "卖出价": "Sell Price",
    "盈亏": "P&L",
    "持有K线": "Bars Held",
    "原因": "Reason",
    "换仓明细": "Rotation Trades",
    "轮动至少需要 2 个标的。": "Rotation needs at least 2 symbols.",
    "轮动回测失败": "Rotation Backtest Failed",
    "完成 · {} 只标的 · {} 根 K 线": "Done · {} symbols · {} bars",
    "<span style=\"color:{}\">跑赢等权买入持有 {:.1f} 个百分点</span>":
        "<span style=\"color:{}\">Beat equal-weight buy-and-hold by {:.1f} percentage points</span>",
    "<span style=\"color:{}\">跑输等权买入持有 {:.1f} 个百分点</span>":
        "<span style=\"color:{}\">Trailed equal-weight buy-and-hold by {:.1f} percentage points</span>",
    "<br><span style='color:{}'>期间被追加保证金强制平仓 {} 次 —— 杠杆在高波动标的上会把你在最低点扫出局。</span>":
        "<br><span style='color:{}'>Forced liquidation by margin call {} times. On volatile "
        "symbols, leverage shakes you out right at the bottom.</span>",
    "{}；最大回撤 {:.1f}% vs 基准 {:.1f}%。<br><span style='color:{}'>注意选择偏差: 如果标的池是你按今天的认知挑出来的赢家(比如「现在最强的科技股」), 回测结果会严重虚高。板块 ETF 这类固定名单最可信。</span>":
        "{}; max drawdown {:.1f}% vs benchmark {:.1f}%.<br><span style='color:{}'>Watch out for "
        "selection bias: if the universe is a list of today's winners picked with hindsight "
        "(say, \"the strongest tech stocks right now\"), the backtest will be badly inflated. "
        "Fixed lists such as sector ETFs are the most trustworthy.</span>",
    "空仓 (全都在跌)": "Flat (everything falling)",

    # --- 稳健性测试 ---
    "稳健性测试 —— 别用一只股票的回测结果骗自己":
        "Robustness Test: don't fool yourself with a single-stock backtest",
    "在单只股票上回测出来的漂亮结果, 很可能只是这只股票恰好适合这个策略。这里把每个策略丢到<b>整篮子标的</b>上跑一遍, 看它跑赢自身基准的比例、超额收益的<b>中位数</b>(不是平均数, 平均数会被个别极端值带偏), 以及平均夏普。<br><b>判断标准: 跑赢家数要明显过半, 中位超额要为正, 平均夏普要高于买入持有那一行。</b>":
        "A great backtest on one stock may just mean that stock happens to suit the strategy. "
        "Here every strategy runs across a <b>whole basket</b>, showing how often it beats its own "
        "benchmark, the <b>median</b> excess return (not the mean, which a few outliers can skew), "
        "and the average Sharpe.<br><b>What to look for: clearly more than half beat the benchmark, "
        "the median excess is positive, and the average Sharpe beats the buy-and-hold row.</b>",
    "区间": "Range",          # 不能也叫 Period: 回测页上「周期」已经是 Period 了
    "全策略横评": "Compare All Strategies",
    "停止": "Stop",
    "横评结果 (按平均夏普排序)": "Results (sorted by average Sharpe)",
    "跑赢/总数": "Wins / Total",
    "跑赢比例": "Win Share",
    "中位超额": "Median Excess",
    "平均超额": "Mean Excess",
    "中位收益": "Median Return",
    "平均夏普": "Avg Sharpe",
    "平均回撤": "Avg Drawdown",
    "选中策略的逐只明细": "Per-Symbol Detail for the Selected Strategy",
    "策略收益": "Strategy Return",
    "稳健性测试至少需要 3 个标的。": "The robustness test needs at least 3 symbols.",
    "测试失败": "Test Failed",
    "没有产生结果": "No results",
    "完成 · {} 只标的 × {} 个策略": "Done · {} symbols × {} strategies",
    "{} · 平均夏普高于买入持有的策略: {}": "{} · strategies with a higher average Sharpe than buy-and-hold: {}",
    "一个都没有": "none",
}
