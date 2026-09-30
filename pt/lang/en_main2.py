"""英文翻译: 主窗口 (持仓、订单、成交、绩效、设置、状态栏) 与市场页。"""

EN = {
    # --- 持仓 / 订单 / 成交 ---
    "已实现": "Realized",
    "占比": "Weight",
    "市价平掉选中持仓": "Close Selected at Market",
    "一键清仓 (全部市价平掉)": "Close All (at market)",
    "未成交挂单": "Open Orders",
    "时间": "Time",
    "撤销选中": "Cancel Selected",
    "历史订单": "Order History",
    "成交价": "Fill Price",
    "费用": "Fees",
    "备注": "Note",
    "成交明细": "Fills",
    "金额": "Amount",
    "佣金": "Commission",
    "规费": "Reg. Fees",
    "导出 CSV": "Export CSV",

    # --- 绩效 / 排行榜 ---
    "账户净值曲线": "Account Equity Curve",
    "绩效指标": "Performance Metrics",
    "平仓次数": "Closed Trades",
    "胜率": "Win Rate",
    "平均盈利": "Avg Win",
    "平均亏损": "Avg Loss",
    "累计已实现": "Total Realized",
    "当前浮动": "Current Unrealized",
    "累计费用": "Total Fees",
    "近5日日内交易": "Day Trades (5 days)",
    "账户排行榜 (按总收益率)": "Account Leaderboard (by total return)",
    "提示: 新建多个账户可以并行测试不同策略, 这里横向对比。":
        "Tip: create several accounts to test different strategies side by side and compare them here.",

    # --- 设置 ---
    "行情": "Market Data",
    " 秒": " s",
    "行情刷新间隔": "Quote refresh interval",
    "包含盘前/盘后价格": "Include pre-market / after-hours prices",
    "休市时市价单按最新价立即成交 (关闭则挂起到开盘)":
        "Fill market orders at the last price while closed (off: hold until the open)",
    "绿涨红跌 (美股习惯); 取消勾选为红涨绿跌 (A股习惯)":
        "Green up / red down (US convention); uncheck for red up / green down (China convention)",
    "行情源": "Data Source",
    "自动 (优先 Yahoo, 连不上时切国内源)": "Auto (Yahoo first, falls back to China sources if unreachable)",
    "只用 Yahoo (连不上就报错, 不降级)": "Yahoo only (errors out if unreachable, no fallback)",
    "只用 国内源 腾讯/东财 (国内可用; 用来测试备用源)":
        "China sources only, Tencent/Eastmoney (works in mainland China; for testing the fallback)",
    "使用哪个": "Source",
    "当前实际在用的源显示在窗口右下角状态栏。国内源以<b>腾讯</b>为主，腾讯覆盖不到的（超过 8 年的日线、分钟线）才用东方财富。<br><b>实时报价与 Yahoo 完全一致</b>（实测偏差 0.000%）；但腾讯的历史价<b>不含股息再投</b>，东财的股息算法也和 Yahoo 不同，所以<b>跨多年的回测数字会有差异</b>，正常情况下让它保持「自动」。":
        "The source actually in use is shown in the status bar at the bottom right. The China sources "
        "use <b>Tencent</b> first, and Eastmoney only for what Tencent cannot cover (daily history "
        "beyond 8 years, minute bars).<br><b>Live quotes match Yahoo exactly</b> (measured deviation "
        "0.000%), but Tencent's history <b>does not reinvest dividends</b> and Eastmoney adjusts for "
        "dividends differently from Yahoo, so <b>multi-year backtest numbers will differ</b>. "
        "Leave this on Auto under normal conditions.",
    "成交与费用": "Execution and Fees",
    "市价单滑点": "Market order slippage",
    "按股数 (IBKR 风格)": "Per share (IBKR style)",
    "每笔固定": "Flat per trade",
    "零佣金 (Robinhood 风格)": "Zero commission (Robinhood style)",
    "佣金模式": "Commission model",
    "每股佣金": "Commission per share",
    "每笔最低佣金": "Minimum per trade",
    "固定佣金 (每笔)": "Flat commission (per trade)",
    "风控": "Risk",
    "当前账户类型": "Current account type",
    "启用 PDT 日内交易者规则": "Enforce the PDT (pattern day trader) rule",
    "保存设置": "Save Settings",
    "数据来源: Yahoo Finance 公开行情接口 (无需 API key)。免费源对部分交易所可能有延迟, 仅供模拟练习, 不构成任何投资建议。\n本软件不接入任何真实券商, 不涉及真实资金。":
        "Data: Yahoo Finance public market data (no API key needed). Free data may be delayed for some "
        "exchanges. For practice only; this is not investment advice.\n"
        "This software does not connect to any real broker and involves no real money.",

    # --- 状态与交易反馈 ---
    "正在刷新…": "Refreshing…",
    "✔ 成交  {} {} {} 股 @ ${:.2f}": "✔ Filled  {} {} {} shares @ ${:.2f}",
    "● 未知": "● Unknown",
    "{:,} 根 · 自 {}": "{:,} bars · since {}",
    "无数据": "No data",
    "没有找到匹配的标的": "No matching symbols",
    "已加入 {} 只新标的, 自选股共 {} 只": "Added {} new symbols; the watchlist now has {}",
    "融资中": "On margin",
    "保证金 2x": "Margin 2x",
    "{} 个持仓": "{} positions",
    "最高 {:.2f}   最低 {:.2f}   昨收 {:.2f}   成交量 {:,}":
        "High {:.2f}   Low {:.2f}   Prev close {:.2f}   Volume {:,}",
    "已触发": "Triggered",
    "持仓 {} 个   总市值 {}   浮动盈亏 {}": "{} positions   Market value {}   Unrealized P&L {}",
    "共 {} 笔成交   累计费用 {}   累计已实现 {}": "{} trades   Total fees {}   Total realized {}",
    "  ← 当前": "  ← current",
    "预计支出": "Est. cost",
    "预计收入": "Est. proceeds",
    "成交金额 {}   佣金 {}   规费 {}\n{} <b>{}</b>   可下单上限 {:,} 股":
        "Notional {}   Commission {}   Fees {}\n{} <b>{}</b>   Max order {:,} shares",
    "持有 <b>{}</b> {} 股   成本 {:.3f}   浮动 <span style=\"color:{}\">{}</span> ({})":
        "Holding <b>{}</b> {} shares   Cost {:.3f}   Unrealized <span style=\"color:{}\">{}</span> ({})",
    "还没有拿到 {} 的行情, 请稍候。": "No quote for {} yet, please wait.",
    "订单被拒绝": "Order Rejected",
    "默认": "Default",
    "从自选股移除 {}": "Remove {} from the watchlist",
    "上移": "Move Up",
    "下移": "Move Down",
    "{} 暂无行情, 无法平仓": "No quote for {}, cannot close",
    "平仓失败": "Close Failed",
    "请先选中一行持仓。": "Select a position first.",
    "确认平仓": "Confirm Close",
    "按市价平掉 {} 的全部持仓?": "Close the entire {} position at market?",
    "确认清仓": "Confirm Close All",
    "按市价平掉全部 {} 个持仓?": "Close all {} positions at market?",
    "撤销此单": "Cancel This Order",
    "已撤销 {} 笔挂单": "Cancelled {} open orders",
    "还没有成交记录。": "No trades yet.",
    "导出成交记录": "Export Trade History",
    "已导出到 {}": "Exported to {}",
    "{}\n类型: {}\n初始资金: {}\n持仓 {} 个 · 成交 {} 笔":
        "{}\nType: {}\nStarting capital: {}\n{} positions · {} trades",
    "保证金账户 (2x)": "Margin account (2x)",
    "已切换到账户: {}": "Switched to account: {}",
    "当前账户: {}": "Current account: {}",
    "设置已保存": "Settings saved",

    # --- 行情源状态栏 ---
    "当前是 Yahoo 源，除了代码也能搜公司名。\nYahoo 连不上时会自动切到国内源，那时只能按代码搜。":
        "The data source is Yahoo, so you can search by company name as well as symbol.\n"
        "If Yahoo becomes unreachable it switches to the China sources, which only support symbol search.",
    "行情源 Yahoo": "Data: Yahoo",
    "当前用的是国内行情源，它的搜索接口不返回证券数据，\n所以只能按代码查，搜公司名查不到。\n换回 Yahoo（设置 → 行情源）就能按公司名搜。":
        "A China data source is in use. Its search endpoint does not return securities,\n"
        "so only symbol lookup works; company names will not be found.\n"
        "Switch back to Yahoo (Settings → Data Source) to search by company name.",
    "行情源 腾讯/东财（备用）": "Data: Tencent/Eastmoney (fallback)",
    "Yahoo 连不上，已自动切换到国内源。\n报价走腾讯，与 Yahoo 完全一致（实测偏差 0.000%）；\nK 线也以腾讯为主，超过 8 年或分钟线才用东方财富。\n\n注意：腾讯的历史价不含股息再投，东财的股息算法\n也和 Yahoo 不同，跨多年的回测数字会有差异。":
        "Yahoo is unreachable, so it switched to the China sources automatically.\n"
        "Quotes come from Tencent and match Yahoo exactly (measured deviation 0.000%);\n"
        "candles also come from Tencent, with Eastmoney only for 8+ years or minute bars.\n\n"
        "Note: Tencent's history does not reinvest dividends, and Eastmoney adjusts\n"
        "differently from Yahoo, so multi-year backtest numbers will differ.",
    "Yahoo 行情连不上，已切换到国内源 腾讯/东财（长周期回测数字会有差异）":
        "Yahoo is unreachable; switched to Tencent/Eastmoney (long backtests will differ)",
    "纽约 {}": "New York {}",
    "保存失败: {}": "Save failed: {}",

    # --- 市场页 ---
    "整组加入自选股": "Add Group to Watchlist",
    "成交量": "Volume",
    "双击任意一行即可加入自选股并跳转到交易页  ·  点表头可按价格/涨跌幅/成交量排序  ·  榜单数据缓存 90 秒":
        "Double-click a row to add it to the watchlist and open the Trade tab  ·  "
        "Click a header to sort by price / change / volume  ·  Lists are cached for 90 seconds",
    "实时榜单": "Live Lists",
    "板块分组": "Sectors",
    "{} 只": "{} symbols",
    "加载失败": "Failed to Load",
    "榜单加载失败": "Could not load the list",
    "{}\n\nYahoo 对榜单接口有频率限制, 稍等十几秒再点刷新即可。":
        "{}\n\nYahoo rate-limits the screener endpoint. Wait 10-20 seconds and refresh.",
    "确认": "Confirm",
    "把「{}」的 {} 只全部加入自选股?\n自选股太多会拖慢行情刷新, 建议控制在 60 只以内。":
        "Add all {1} symbols in \"{0}\" to the watchlist?\n"
        "A very long watchlist slows quote refreshes; keeping it under 60 is recommended.",

    # --- 后台线程 ---
    "暂无净值记录 — 运行一段时间后自动生成": "No equity history yet; it builds up as the app runs",
    "行情拉取失败, 正在重试…": "Quote fetch failed, retrying…",
    "行情异常: {}": "Market data error: {}",
    "K线加载失败 {}: {}": "Failed to load candles for {}: {}",
}
