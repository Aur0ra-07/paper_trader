"""英文翻译: 策略页 (回测、参数优化、自动交易、AI 建议)。"""

EN = {
    # --- 后台任务 ---
    "拉取 {} 的 K 线… ({}/{})": "Fetching candles for {}… ({}/{})",
    "没有拿到任何 K 线数据": "No candle data was returned",
    "回测中…": "Backtesting…",
    "{} 只有 {} 根 K 线, 做训练/验证切分至少需要约 300 根 —— 换更长的区间或更短的周期":
        "{} has only {} candles; a train/validation split needs about 300. "
        "Use a longer range or a shorter interval.",
    "优化失败: {}": "Optimization failed: {}",
    "没拿到 K 线, 本轮跳过": "No candles returned; skipping this round",

    # --- 子页签 ---
    "单标的回测": "Backtest",
    "稳健性测试": "Robustness",
    "参数优化": "Optimize",
    "自动交易": "Auto Trading",
    "AI 建议 (Claude Code)": "AI Suggestions (Claude Code)",

    # --- 回测设置 ---
    "回测设置": "Backtest Setup",
    "单只标的": "Single symbol",
    "当前自选股": "Current watchlist",
    "板块: ": "Sector: ",
    "回测标的": "Symbols",
    "每次仓位": "Position size",
    "0 表示不启用": "0 means off",
    "1 = 不融资。>1 会计息, 净值击穿维持保证金会被强制平仓":
        "1 = no margin. Above 1, interest is charged, and falling through maintenance margin "
        "triggers forced liquidation.",
    "运行回测": "Run Backtest",
    "选择策略后点「运行回测」": "Pick a strategy and click Run Backtest",
    "索提诺": "Sortino",
    "交易次数": "Trades",
    "持仓时间占比": "Time in Market",
    "入场时间": "Entry Time",
    "入场价": "Entry Price",
    "出场时间": "Exit Time",
    "出场价": "Exit Price",
    "持仓K线": "Bars Held",
    "离场原因": "Exit Reason",
    "交易明细": "Trades",
    "单只拆解": "Per Symbol",
    "请先指定回测标的。": "Choose the symbols to backtest first.",
    "回测失败": "Backtest Failed",
    "回测": "Backtest",
    "<span style=\"color:{}\">跑赢买入持有 {:.1f} 个百分点</span> —— 但请务必去【参数优化】做样本外验证, 单次回测很容易是运气。":
        "<span style=\"color:{}\">Beat buy-and-hold by {:.1f} percentage points</span>. Validate it "
        "out of sample under Optimize; a single backtest can easily be luck.",
    "<span style=\"color:{}\">跑输买入持有 {:.1f} 个百分点</span> —— 扣掉佣金和滑点后, 多数择时策略都是这个结果。":
        "<span style=\"color:{}\">Trailed buy-and-hold by {:.1f} percentage points</span>. After "
        "commissions and slippage, most timing strategies end up here.",
    "<br><span style=\"color:{}\">期间被追加保证金强制平仓 {} 次</span>":
        "<br><span style=\"color:{}\">Forced liquidation by margin call {} times</span>",
    "多": "Long",
    "空": "Short",

    # --- 参数优化 ---
    "网格搜索 + 样本外验证": "Grid Search + Out-of-Sample Validation",
    "优化目标": "Objective",
    "每个参数取几个候选值, 越大越慢": "How many candidate values per parameter; higher is slower",
    "每参数取样": "Samples per parameter",
    "开始优化": "Start Optimization",
    "只在前 70% 的历史上搜参数, 用后 30% 验证。<b>请按「验证集」列挑参数, 不要按「训练集」挑</b> —— 训练集最漂亮的那组, 往往就是过拟合最严重的那组。":
        "Parameters are searched on the first 70% of history and validated on the last 30%. "
        "<b>Pick parameters by the Validation column, not the Train column</b>: the prettiest "
        "training result is usually the most overfit one.",
    "优化结果 (按验证集表现排序)": "Results (sorted by validation performance)",
    "参数": "Parameters",
    "训练集收益": "Train Return",
    "验证集收益": "Validation Return",
    "验证夏普": "Val. Sharpe",
    "验证回撤": "Val. Drawdown",
    "验证交易数": "Val. Trades",
    "全样本收益": "Full-Sample Return",
    "稳健": "Robust",
    "把选中参数用到【回测】": "Use Selected in Backtest",
    "把选中参数用到【自动交易】": "Use Selected in Auto Trading",
    "搜索中…": "Searching…",
    "%v / %m 组": "%v / %m combos",
    "优化失败": "Optimization Failed",
    "共 {} 组有效结果 · 双击一行应用参数": "{} valid results · double-click a row to apply it",
    "(无参数)": "(no parameters)",
    ", 做空": ", short",
    "请先选中一行结果。": "Select a result row first.",
    "参数已应用到自动交易: {}": "Parameters applied to Auto Trading: {}",
    "参数已应用到回测: {}": "Parameters applied to Backtest: {}",

    # --- 自动交易 ---
    "自动交易设置": "Auto Trading Setup",
    "交易模式": "Mode",
    "单标的择时 (一个策略跑多只股票)": "Single-symbol timing",
    "核心-卫星组合 (按目标权重再平衡)": "Core-satellite portfolio",
    "再平衡容忍带": "Rebalance band",
    "权重偏离目标超过这么多个百分点才动手。\n设 0 会每天产生碎单; 太大则长期偏离目标。2pp 是个合理起点。":
        "Only trade when a weight is this many percentage points off target.\n"
        "0 produces tiny trades every day; too large and it drifts off target for long. "
        "2pp is a reasonable start.",
    "交易标的 (来自自选股)": "Symbols (from the watchlist)",
    "全选": "Select All",
    "全不选": "Select None",
    "信号周期": "Signal interval",
    "评估间隔": "Check every",
    "单票最大仓位": "Max position size",
    "最多持仓数": "Max positions",
    "单笔止损": "Stop-loss per trade",
    "单笔止盈": "Take-profit per trade",
    "每日最多交易": "Max trades per day",
    "回撤熔断": "Drawdown circuit breaker",
    "允许做空": "Allow shorting",
    "仅给建议, 不自动下单 (推荐先这样跑)": "Advice only, no orders (recommended first)",
    "启动自动交易": "Start Auto Trading",
    "本轮决策": "This Round's Decisions",
    "未启动": "Not running",
    "立即评估一次": "Evaluate Now",
    "执行全部可执行决策": "Execute All Actionable",
    "解除熔断": "Reset Circuit Breaker",
    "现状": "Current",
    "目标": "Target",
    "动作": "Action",
    "理由 / 指标": "Reason / Indicators",
    "执行日志": "Execution Log",
    "结果": "Result",
    "理由": "Reason",
    "组合模式下仓位由权重决定": "In portfolio mode, position size comes from the weights",
    "组合模式下持仓数由组合结构决定": "In portfolio mode, the number of holdings comes from the portfolio",
    "组合模式不挂单笔止损 —— 止损卖掉后再平衡会买回来":
        "No per-trade stop in portfolio mode: rebalancing would just buy it back",
    "组合模式不挂单笔止盈": "No per-trade take-profit in portfolio mode",
    "{} 个支柱 · 需要盯 {} 只标的<br>{}<br><b>仓位由权重决定</b>，单票上限 / 持仓数 / 止损在这个模式下不生效；风控靠分散和回撤熔断。":
        "{} sleeves · {} symbols to track<br>{}<br><b>Position sizes come from the weights</b>; "
        "the per-symbol cap, position count and stops do not apply in this mode. "
        "Risk control comes from diversification and the drawdown circuit breaker.",
    "请先勾选至少一个交易标的。": "Check at least one symbol first.",
    "这个组合预设读不出来。": "This portfolio preset could not be loaded.",
    "仅建议": "Advice only",
    "自动下单": "Auto orders",
    "停止自动交易": "Stop Auto Trading",
    "运行中 · {} · 每 {} 秒评估": "Running · {} · evaluating every {} s",
    "已停止": "Stopped",
    "组合预设里没有标的": "The portfolio preset has no symbols",
    "没有勾选标的": "No symbols checked",
    "上一轮还在跑, 跳过本轮": "The previous round is still running; skipping",
    "⛔ 已熔断: {}": "⛔ Circuit breaker tripped: {}",
    "{} 已执行 {} 笔": "{} executed {} trades",
    "{} 评估完成 · {} 条可执行{}": "{} evaluated · {} actionable{}",
    " (仅建议模式)": " (advice-only mode)",
    "本轮没有可执行的决策。": "Nothing actionable this round.",
    "按市价执行 {} 条决策?": "Execute {} decisions at market?",
    "已执行 {} 笔自动交易": "Executed {} auto trades",
    "熔断已解除": "Circuit breaker reset",
    "成功": "Success",
    "失败": "Failed",

    # --- AI 建议 ---
    "怎么用 (不需要 API key, 用你的 Claude Code 订阅)":
        "How it works (no API key needed; uses your Claude Code subscription)",
    "<b>1.</b> 点下面的「导出简报」—— 会把账户、持仓、行情、技术指标、风控约束写成一个 Markdown 文件<br><b>2.</b> 在 Claude Code 里对着这个项目说: <code>读一下 data/ai/briefing.md，按里面的格式把调仓建议写进 data/ai/decisions.json</code><br><b>3.</b> 回到这里点「读取 AI 建议」, 每条建议都会做合法性校验 (持仓够不够、购买力够不够)<br><b>4.</b> 逐条确认后执行 —— <b>永远是你按下最后那个按钮</b>":
        "<b>1.</b> Click Export Briefing below. It writes the account, positions, quotes, technical "
        "indicators and risk limits into a Markdown file.<br>"
        "<b>2.</b> In Claude Code, open this project and say: <code>Read data/ai/briefing.md and "
        "write your rebalancing suggestions to data/ai/decisions.json in the format it describes</code><br>"
        "<b>3.</b> Come back and click Load AI Suggestions. Every suggestion is validated "
        "(enough shares, enough buying power).<br>"
        "<b>4.</b> Confirm each one before it executes. <b>You always press the final button.</b>",
    "导出简报": "Export Briefing",
    "打开 data/ai 文件夹": "Open data/ai Folder",
    "复制提示词": "Copy Prompt",
    "读取 AI 建议": "Load AI Suggestions",
    "AI 建议": "AI Suggestions",
    "还没有读取到建议": "No suggestions loaded yet",
    "信心": "Confidence",
    "校验": "Check",
    "执行选中": "Execute Selected",
    "执行全部合法建议": "Execute All Valid",
    "这是模拟盘。AI 的建议不是投资建议, 执行与否由你决定。":
        "This is paper trading. AI suggestions are not investment advice; whether to act is up to you.",
    "正在拉取 K 线…": "Fetching candles…",
    "{} 在 {} 上回测: 总收益 {:+.1f}%, 买入持有 {:+.1f}%, 夏普 {:.2f}, 最大回撤 {:.1f}%":
        "{} backtested on {}: total return {:+.1f}%, buy-and-hold {:+.1f}%, Sharpe {:.2f}, "
        "max drawdown {:.1f}%",
    "导出失败: {}": "Export failed: {}",
    "已导出 {} 只标的 → {}": "Exported {} symbols → {}",
    "简报已导出: {}": "Briefing exported: {}",
    "读一下 data/ai/briefing.md，按文件末尾的格式把调仓建议写进 data/ai/decisions.json。这是模拟盘，只用文件里给出的数据做判断，每条建议的 reason 要引用具体指标数值。":
        "Read data/ai/briefing.md and write your rebalancing suggestions to data/ai/decisions.json "
        "in the format given at the end of that file. This is a paper trading account: base your "
        "judgment only on the data in the file, and have every suggestion's reason cite specific "
        "indicator values.",
    "提示词已复制到剪贴板": "Prompt copied to the clipboard",
    "<b>AI 备注:</b> {}  <span style='color:{}'>(文件更新于 {:.0f} 分钟前)</span>":
        "<b>AI note:</b> {}  <span style='color:{}'>(file updated {:.0f} minutes ago)</span>",
    "(无)": "(none)",
    "✓ 可执行": "✓ Valid",
    "读取 {} 条, {} 条通过校验": "Loaded {}, {} passed validation",
    "请先选中一行。": "Select a row first.",
    "没有通过校验的建议可执行。": "No suggestions passed validation.",
    "{} {} {} 股{}": "{} {} {} shares{}",
    " @ 限价 {:.2f}": " @ limit {:.2f}",
    " (市价)": " (market)",
    "确认执行 AI 建议": "Confirm AI Suggestions",
    "即将下单:\n\n": "About to place:\n\n",
    "{}: 无行情": "{}: no quote",
    "AI 建议已执行 {} 条": "Executed {} AI suggestions",
    "部分未成功": "Some Did Not Go Through",
    '所有目标权重乘这个倍数, 多出来的钱向券商借, 按设置里的融资年化利率每天计息。\n上限 2 倍 (Reg T); 现金账户不能融资, 会按 1 倍执行。\n实盘不模拟强平: 回撤熔断只会停止交易, 不会自动降杠杆。先在【组合】页回测同样的倍数。': "Every target weight is multiplied by this; the extra is borrowed and charged daily at the margin rate in Settings.\nMax 2x (Reg T); cash accounts can't borrow and run at 1x.\nNo forced liquidation in live mode: the drawdown halt stops trading but does not deleverage. Backtest the same multiple on the Portfolio tab first.",
    '<br><b>{:.2f} 倍杠杆</b>：总仓位 {:.0f}% 净值，借 {:.0f}% 要付利息。': '<br><b>{:.2f}x leverage</b>: total exposure {:.0f}% of equity, borrowing {:.0f}% with interest.',
}
