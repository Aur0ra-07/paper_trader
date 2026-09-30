"""英文翻译: 主窗口、账户管理、K 线图、市场页。"""

EN = {
    # --- 危险操作确认 ---
    "确认执行": "Confirm",
    "请输入 <b style='color:{}'>{}</b> 以确认：": "Type <b style='color:{}'>{}</b> to confirm:",
    "执行前会自动备份一份快照，在【账户管理 → 备份】里可以找回。":
        "A snapshot is backed up automatically first. You can get it back under Account Manager → Backups.",
    "取消": "Cancel",

    # --- 账户编辑 ---
    "编辑账户": "Edit Account",
    "新建模拟账户": "New Paper Account",
    "模拟账户": "Paper Account",
    "账户名称": "Account name",
    "初始资金": "Starting capital",
    "保证金账户 (2倍购买力, 可做空)": "Margin account (2x buying power, shorting allowed)",
    "现金账户 (无杠杆, 不可做空)": "Cash account (no leverage, no shorting)",
    "账户类型": "Account type",
    "改「初始资金」只会改变收益率的计算基准，不会往账户里打钱，也不会动持仓。":
        "Changing the starting capital only changes the baseline for returns. "
        "It does not add money to the account or touch positions.",

    # --- 账户管理 ---
    "账户管理": "Account Manager",
    "账户": "Account",
    "备份": "Backups",
    "关闭": "Close",
    "类型": "Type",
    "总资产": "Total Equity",
    "总盈亏": "Total P&L",
    "收益率": "Return",
    "持仓": "Positions",
    "成交": "Trades",
    "创建于": "Created",
    "切换到选中账户": "Switch to Selected",
    "新建账户": "New Account",
    "重命名 / 修改": "Rename / Edit",
    "复制一份": "Duplicate",
    "导出 JSON": "Export JSON",
    "危险操作": "Danger Zone",
    "重置选中账户…": "Reset Selected Account…",
    "删除选中账户…": "Delete Selected Account…",
    "两个操作都需要手动输入账户名确认，并会先自动备份。":
        "Both actions require typing the account name to confirm, and back up automatically first.",
    "程序每 20 分钟自动存一份快照，重置或删除账户前也会先存一份（48 小时内全部保留，更早的每天留一份）。选中一份可以恢复成一个<b>新账户</b>，不会覆盖现有账户。":
        "A snapshot is saved automatically every 20 minutes, and before any reset or delete "
        "(everything from the last 48 hours is kept, one per day before that). "
        "Select one to restore it as a <b>new account</b>; existing accounts are never overwritten.",
    "备份时间": "Backed up",
    "内容": "Contents",
    "文件": "File",
    "恢复为新账户": "Restore as New Account",
    "打开备份文件夹": "Open Backup Folder",
    "刷新": "Refresh",
    "  (当前)": "  (current)",
    "保证金": "Margin",
    "提示": "Notice",
    "请先在上面选中一个账户。": "Select an account above first.",
    " 副本": " copy",
    "导出账户": "Export Account",
    "已导出": "Exported",
    "导出失败": "Export Failed",
    "重置账户": "Reset Account",
    "将清空「<b>{}</b>」的全部持仓、挂单、成交记录和净值曲线，资金恢复到 {}。<br>当前该账户有 <b>{}</b> 个持仓、<b>{}</b> 笔成交。":
        "This clears every position, open order, trade and the equity curve of "
        "\"<b>{}</b>\", and resets the cash to {}.<br>"
        "The account currently has <b>{}</b> positions and <b>{}</b> trades.",
    "已重置": "Reset Complete",
    "账户已重置。\n\n重置前的快照已保存：\n{}": "Account reset.\n\nA snapshot from before the reset was saved:\n{}",
    "至少要保留一个账户。": "At least one account must remain.",
    "删除账户": "Delete Account",
    "将<b>永久删除</b>账户「<b>{}</b>」及其全部记录（{} 个持仓、{} 笔成交）。":
        "This <b>permanently deletes</b> the account \"<b>{}</b>\" and all its records "
        "({} positions, {} trades).",
    "永久删除": "Delete Permanently",
    "已删除": "Deleted",
    "账户已删除。\n\n删除前的快照已保存：\n{}": "Account deleted.\n\nA snapshot from before the delete was saved:\n{}",
    "请先选中一份备份。": "Select a backup first.",
    "恢复失败": "Restore Failed",
    "这份备份读不出来。": "This backup could not be read.",
    "{} (恢复 {})": "{} (restored {})",
    "已恢复": "Restored",
    "已恢复为新账户「{}」，原有账户没有被动过。":
        "Restored as a new account \"{}\". Your existing accounts were not touched.",

    # --- K 线图 ---
    "加载中…": "Loading…",
    "持仓成本 {:.2f}": "Cost basis {:.2f}",
    "<span style=\"color:{dim}\">{t}</span>  开 <b>{o:.2f}</b>  高 <b>{h:.2f}</b>  低 <b>{l:.2f}</b>  收 <b style=\"color:{col}\">{c:.2f}</b>  <span style=\"color:{col}\">{p:+.2f}%</span>  量 <b>{v:,}</b>":
        "<span style=\"color:{dim}\">{t}</span>  O <b>{o:.2f}</b>  H <b>{h:.2f}</b>  L <b>{l:.2f}</b>  "
        "C <b style=\"color:{col}\">{c:.2f}</b>  <span style=\"color:{col}\">{p:+.2f}%</span>  Vol <b>{v:,}</b>",

    # --- 主窗口框架 ---
    "● 交易中": "● Market Open",
    "● 盘前": "● Pre-market",
    "● 盘后": "● After-hours",
    "● 休市": "● Market Closed",
    "Paper Trader — 美股模拟交易终端": "Paper Trader — US Stock Trading Simulator",
    "交易": "Trade",
    "市场": "Markets",
    "策略": "Strategy",
    "期权": "Options",
    "订单": "Orders",
    "成交记录": "Trade History",
    "绩效": "Performance",
    "排行榜": "Leaderboard",
    "设置": "Settings",
    "就绪": "Ready",
    "没找到账户文件，已经自动从备份恢复：\n    %s\n\n如果这不是你想要的那份，去「账户管理… → 从备份恢复」\n里挑别的时间点。":
        "No account file was found, so it was restored from a backup automatically:\n    %s\n\n"
        "If this is not the one you want, pick another point in time under\n"
        "Account Manager… → Backups.",
    "账户文件读不出来（%s）：\n    %s\n坏掉的原文件已改名保留在：\n    %s":
        "Could not read the account file (%s):\n    %s\nThe damaged original was renamed and kept at:\n    %s",
    "账户数据有问题": "Account Data Problem",
    "数据目录：%s": "Data folder: %s",
    "账户管理…": "Accounts…",
    "新建 / 重命名 / 复制 / 导出 / 重置 / 删除 / 从备份恢复":
        "New / rename / duplicate / export / reset / delete / restore from backup",
    "● 连接中": "● Connecting",
    "立即刷新": "Refresh Now",
    "可用现金": "Cash",
    "购买力": "Buying Power",
    "持仓市值": "Market Value",
    "浮动盈亏": "Unrealized P&L",
    "已实现盈亏": "Realized P&L",

    # --- 自选股 ---
    "自选股": "Watchlist",
    "搜索代码, 回车确认 (如 AAPL)": "Search a symbol, press Enter (e.g. AAPL)",
    "代码": "Symbol",
    "最新价": "Last",
    "涨跌幅": "Change",
    "← 返回自选股": "← Back to Watchlist",
    "名称": "Name",
    "交易所": "Exchange",
    "双击添加到自选股": "Double-click to add to the watchlist",
    "范围": "Range",
    "要加载多长的历史。各周期能拉多少受接口限制:\n分钟线最多 1 个月, 60 分钟最多 2 年, 日线/周线可以到上市当天。":
        "How much history to load. The data source limits each interval:\n"
        "minute bars up to 1 month, 60-minute up to 2 years, daily/weekly back to the listing date.",
    "<span style=\"color:#f0b429\">MA5</span>  <span style=\"color:#3b82f6\">MA20</span>  <span style=\"color:#a855f7\">MA60</span>  <span style=\"color:{}\">- - 持仓成本</span>":
        "<span style=\"color:#f0b429\">MA5</span>  <span style=\"color:#3b82f6\">MA20</span>  "
        "<span style=\"color:#a855f7\">MA60</span>  <span style=\"color:{}\">- - Cost basis</span>",

    # --- 下单面板 ---
    "下单": "Order Entry",
    "当前无持仓": "No position",
    "订单类型": "Order type",
    "股数": "Shares",
    "限价": "Limit",
    "触发价": "Stop",
    "当日有效 (DAY)": "Day (DAY)",
    "撤销前有效 (GTC)": "Good till cancelled (GTC)",
    "有效期": "Time in force",
    "当前挂单": "Open Orders",
    "状态": "Status",
    "撤选中": "Cancel Selected",
    "全部撤单": "Cancel All",
    "方向": "Side",
    "成本价": "Avg Cost",
    "现价": "Price",
    "市值": "Value",
    "盈亏%": "P&L %",
}
