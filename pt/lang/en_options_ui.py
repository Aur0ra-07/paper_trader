"""英文翻译: 期权页 (期权链、持仓、策略构建、损益图)。"""

EN = {
    # --- 期权链表头 ---
    "未平仓": "Open Int.",
    "隐波": "IV",
    "买价": "Bid",
    "卖价": "Ask",
    "行权价": "Strike",
    "价内/价外": "ITM/OTM",
    "价差": "Spread",

    # --- 策略预设 ---
    "单腿 · 买入认购 (看涨)": "Single leg · Long call (bullish)",
    "单腿 · 买入认沽 (看跌)": "Single leg · Long put (bearish)",
    "单腿 · 卖出认沽 (现金担保)": "Single leg · Short put (cash-secured)",
    "单腿 · 备兑开仓 (持股卖call)": "Single leg · Covered call (own stock, sell call)",
    "价差 · 牛市认购价差": "Spread · Bull call spread",
    "价差 · 熊市认沽价差": "Spread · Bear put spread",
    "波动 · 跨式 (赌大涨大跌)": "Volatility · Straddle (bet on a big move)",
    "波动 · 宽跨式 (更便宜)": "Volatility · Strangle (cheaper)",
    "收租 · 铁鹰 (赌不动)": "Income · Iron condor (bet on no move)",

    # --- 期权链页 ---
    "期权链加载失败: {}": "Failed to load the option chain: {}",
    "期权链": "Option Chain",
    "我的期权持仓": "My Options",
    "策略组合": "Strategy Builder",
    "标的与到期日": "Underlying and Expiry",
    "股票代码": "Symbol",
    "加载": "Load",
    "到期日": "Expiry",
    "只看有流动性的": "Liquid only",
    "过滤掉几乎没人交易、买卖价差极宽的合约": "Hide contracts that barely trade or have very wide spreads",
    "只看现价 ±20% 范围": "Strikes within ±20% only",
    "输入代码后点「加载」": "Enter a symbol and click Load",
    "看涨 Call": "Calls",
    "只看认购合约——赌股价上涨": "Show calls only: a bet the stock goes up",
    "看跌 Put": "Puts",
    "只看认沽合约——赌股价下跌": "Show puts only: a bet the stock goes down",
    "两边对照": "Both Sides",
    "券商常见的 T 型链: 认购在左, 认沽在右": "The usual broker layout: calls on the left, puts on the right",
    "还没选合约": "No contract selected",
    "合约张数": "Contracts",
    "市价 (吃对手价)": "Market (cross the spread)",
    "限价 (每股)": "Limit (per share)",
    "到期损益预览": "P&L at Expiry",
    "上一次还在加载, 请稍候": "Still loading the previous request, please wait",
    "{}  ({} 天)": "{}  ({} days)",
    "加载 {} 的链…": "Loading the chain for {}…",
    "期权数据": "Options Data",
    "{}<br>平值隐波 {:.1f}%<br>到期前 1 个标准差波动 ±{:.2f} ({:.1f}%)":
        "{}<br>ATM IV {:.1f}%<br>1 standard deviation move by expiry ±{:.2f} ({:.1f}%)",
    "{} · 到期 {} · 剩 {} 天": "{} · expires {} · {} days left",
    "共 {} 个合约": "{} contracts",
    "<span style=\"color:{}\">◀ 左边六列 = 认购 Call</span>　<span style=\"color:{}\">右边六列 = 认沽 Put ▶</span>　·　点哪一边就选哪一边的合约　·　觉得绕就切到上面的「看涨」或「看跌」":
        "<span style=\"color:{}\">◀ Left six columns = Calls</span>　"
        "<span style=\"color:{}\">Right six columns = Puts ▶</span>　·　"
        "click a side to select that contract　·　switch to Calls or Puts above if this is confusing",
    "当前只显示 <span style=\"color:{}\"><b>{}</b></span>　·　点任意一行即可选中该合约":
        "Showing only <span style=\"color:{}\"><b>{}</b></span>　·　click any row to select that contract",
    "价内": "ITM",
    "价外": "OTM",
    "平值": "ATM",
    "买价 <b>{:.2f}</b>　卖价 <b>{:.2f}</b>　价差 {:.1f}%<br>隐波 {:.1f}%　未平仓 {:,}　成交量 {:,}{}":
        "Bid <b>{:.2f}</b>　Ask <b>{:.2f}</b>　Spread {:.1f}%<br>IV {:.1f}%　Open int. {:,}　Volume {:,}{}",
    "<br><span style=\"color:{}\">流动性差, 真实成交可能比这个价还糟</span>":
        "<br><span style=\"color:{}\">Illiquid: a real fill may be worse than this</span>",
    "先用上方的「看涨 Call / 看跌 Put」选边，再点报价表里的任意一行来选合约。":
        "Pick Calls or Puts above, then click any row in the quote table to select a contract.",
    "{}  {} 张": "{}  {} contracts",
    "<b>需要付出 {}</b>（含佣金 {}）": "<b>You pay {}</b> (incl. commission {})",
    "<b>收到权利金 {}</b>（扣佣金后 {}）": "<b>You receive {} in premium</b> ({} after commission)",
    "盈亏平衡价 <b>{:.2f}</b>（{}需{} {:.1f}%）": "Breakeven <b>{:.2f}</b> ({} needs to {} {:.1f}%)",
    "股价": "the stock",
    "涨": "rise",
    "跌": "fall",
    "到期变实值 <b>{:.0f}%</b>　真正赚钱 <b style=\"color:{}\">{:.0f}%</b>":
        "Finishes ITM <b>{:.0f}%</b>　Actually profitable <b style=\"color:{}\">{:.0f}%</b>",
    "每天时间损耗 <span style=\"color:{}\">{}</span>　最大亏损 <span style=\"color:{}\">{}</span>（100%）":
        "Time decay per day <span style=\"color:{}\">{}</span>　Max loss <span style=\"color:{}\">{}</span> (100%)",
    "占用保证金约 <b>{}</b>": "Margin required about <b>{}</b>",
    "到期被指派概率约 <b>{:.0f}%</b>": "Chance of assignment at expiry about <b>{:.0f}%</b>",
    "<span style=\"color:{}\">裸卖认购理论上亏损无上限</span>":
        "<span style=\"color:{}\">A naked short call has unlimited loss in theory</span>",
    "最坏情况: 以 {:g} 接货 {} 股, 需 {}": "Worst case: buy {1} shares at {0:g}, needing {2}",
    "<span style=\"color:{}\">Delta {:+.3f}　Gamma {:.4f}　Theta {:+.2f}/天　Vega {:.3f}</span>":
        "<span style=\"color:{}\">Delta {:+.3f}　Gamma {:.4f}　Theta {:+.2f}/day　Vega {:.3f}</span>",
    "<span style=\"color:{}\">剩余 {} 天</span>": "<span style=\"color:{}\">{} days left</span>",
    "期权 ": "Option ",

    # --- 期权持仓页 ---
    "组合希腊字母": "Portfolio Greeks",
    "期权持仓": "Option Positions",
    "期权市值": "Options Value",
    "占用保证金": "Margin Used",
    "总Delta(等效股数)": "Total Delta (share equivalent)",
    "总Theta(每天)": "Total Theta (per day)",
    "总Vega": "Total Vega",
    "7天内到期": "Expiring in 7 days",
    "合约": "Contract",
    "张数": "Qty",
    "成本/股": "Cost/share",
    "Theta/天": "Theta/day",
    "内在价值": "Intrinsic",
    "时间价值": "Time Value",
    "剩余天数": "Days Left",
    "平掉选中持仓": "Close Selected",
    "刷新报价": "Refresh Quotes",
    "立即处理到期合约": "Process Expirations Now",
    "正常情况下会自动处理; 这里可以手动触发一次": "Normally handled automatically; this triggers it by hand",
    "期权成交与到期记录": "Option Trades and Expirations",
    "操作": "Action",
    "价格": "Price",
    "买方": "Long",
    "卖方": "Short",
    "无报价": "No quote",
    "拿不到该合约的报价, 无法平仓。": "No quote for this contract, cannot close.",
    "按市价{} {} 张 {}?": "{} {} contracts of {} at market?",
    "期权到期: ": "Options expiry: ",
    "期权到期处理": "Option Expiration",

    # --- 策略构建 ---
    "策略构建": "Strategy Builder",
    "选一个预设结构, 系统会按当前期权链自动挑行权价; 也可以在下面的腿列表里手动改。":
        "Pick a preset structure and strikes are chosen from the current chain automatically; "
        "you can also edit the legs below by hand.",
    "组数": "Quantity",
    "价差/铁鹰两腿之间隔几档行权价": "How many strikes apart the legs of a spread / iron condor are",
    "价差宽度(档)": "Spread width (strikes)",
    "按当前期权链生成": "Build from Current Chain",
    "腿": "Legs",
    "把选中合约加为一腿": "Add Selected as Long Leg",
    "加为卖出腿": "Add as Short Leg",
    "删除选中腿": "Remove Selected Leg",
    "清空": "Clear",
    "一次性下单全部腿": "Place All Legs",
    "到期损益图": "Payoff at Expiry",
    "先在【期权链】里加载一个标的。": "Load an underlying in the Option Chain tab first.",
    "先在【期权链】里双击选中一个合约。": "Double-click a contract in the Option Chain tab first.",
    "{} 正股": "{} stock",
    "{:,} 股": "{:,} shares",
    "{} <b>{}</b><br>最大盈利 <span style=\"color:{}\">{}</span>{}<br>最大亏损 <span style=\"color:{}\">{}</span>{}<br>盈亏平衡 {}<br>剩余 {} 天":
        "{} <b>{}</b><br>Max profit <span style=\"color:{}\">{}</span>{}<br>"
        "Max loss <span style=\"color:{}\">{}</span>{}<br>Breakeven {}<br>{} days left",
    "净支出": "Net debit",
    "净收入": "Net credit",
    "（区间外还会继续涨）": " (keeps growing outside the range)",
    "（理论无下限）": " (unlimited in theory)",
    "这个结构包含正股腿。请先到【交易】页买入 {} 股 {}，再回来下期权腿。":
        "This structure has a stock leg. Buy {} shares of {} on the Trade tab first, "
        "then come back for the option legs.",
    "{} {} 张 {} {:g}{}": "{} {} contracts {} {:g}{}",
    "确认下单": "Confirm Order",
    "按市价执行以下 {} 条腿:\n\n{}": "Execute these {} legs at market:\n\n{}",
    "组合下单: 成功 {} 条腿": "Combo order: {} legs filled",
    "部分腿未成交": "Some Legs Did Not Fill",

    # --- 损益图 ---
    "到期时底层价格": "Underlying price at expiry",
    "现价 {value:.2f}": "Price {value:.2f}",
    "到期损益": "P&L at expiry",
    "当前损益": "P&L now",
    "选好合约后这里会画出损益图": "Select a contract to draw its payoff here",
    "平衡 {:.2f}": "Breakeven {:.2f}",
    "底层 <b>{:.2f}</b> 时  到期损益 <b style=\"color:{}\">{}</b>":
        "At <b>{:.2f}</b>  P&L at expiry <b style=\"color:{}\">{}</b>",
    "   现在平掉 <span style=\"color:{}\">{}</span>": "   Close now <span style=\"color:{}\">{}</span>",
}
