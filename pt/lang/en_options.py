"""英文翻译: 期权引擎与期权链。

注意: 到期作废 / 交割 这几条 note 会被 options/engine.py 的 stats() 按关键词
识别 (EXPIRED_MARKS / DELIVER_MARKS)。英文译文里必须分别包含
"expired worthless" 和 "deliver", 否则切到英文后统计会漏掉。
"""

EN = {
    # --- 期权链 ---
    "拿不到 crumb (HTTP {})": "Could not get the crumb (HTTP {})",
    "期权接口鉴权失败: {}": "Options API authentication failed: {}",
    "响应不是 JSON": "Response is not JSON",
    "{} 没有期权链 (可能这只票没有期权)": "{} has no option chain (it may not have listed options)",
    "401 鉴权失效": "401 authentication expired",
    "{} 没有期权": "{} has no options",
    "期权链请求失败: {}": "Option chain request failed: {}",

    # --- 下单校验 ---
    "合约张数必须是正整数": "Number of contracts must be a positive whole number",
    "拿不到 {} 的报价": "No quote for {}",
    "该合约没有有效报价 (bid {:.2f} / ask {:.2f})": "This contract has no valid quote (bid {:.2f} / ask {:.2f})",
    "该合约已于 {} 到期": "This contract expired on {}",
    "没有 {} 的买方持仓可卖出": "No long position in {} to sell",
    "可平 {} 张 (持有 {}, 挂单占用 {})": "{} contracts can be closed (held {}, in open orders {})",
    "没有 {} 的卖方持仓可买回": "No short position in {} to buy back",
    "可平 {} 张 (义务 {}, 挂单占用 {})": "{} contracts can be closed (written {}, in open orders {})",
    "当前是卖方持仓, 请先「买入平仓」": "This is a short position. Buy to Close first.",
    "现金不足: 需要 ${:,.2f}, 可用现金 ${:,.2f} (买入期权不能用融资, 必须全额付现)":
        "Not enough cash: need ${:,.2f}, available ${:,.2f} "
        "(options cannot be bought on margin and must be paid in full)",
    "当前是买方持仓, 请先「卖出平仓」": "This is a long position. Sell to Close first.",
    "现金账户只能做备兑开仓: 需要持有 {} 股 {}, 当前只有 {} 股":
        "Cash accounts can only write covered calls: need {} shares of {}, currently hold {}",
    "卖方保证金不足: 需要 ${:,.2f}, 可用购买力 ${:,.2f}":
        "Not enough margin to write: need ${:,.2f}, buying power ${:,.2f}",
    "未知方向: {}": "Unknown side: {}",
    "成交: {} {} 张 @ ${:.2f}  (总额 ${:,.2f})": "Filled: {} {} contracts @ ${:.2f}  (total ${:,.2f})",

    # --- 到期结算 ---
    "合约已到期, 挂单作废": "Contract expired, order cancelled",
    "{} 到期但拿不到 {} 的价格, 本次跳过": "{} expired but no price for {}; skipped this time",
    "到期作废 (结算价 {:.2f} vs 行权价 {:g})": "Expired worthless (settlement {:.2f} vs strike {:g})",
    "买方权利金全亏": "buyer loses the full premium",
    "卖方权利金全赚": "seller keeps the full premium",
    "{} {} 到期作废 —— {} ${:,.2f}": "{} {} expired worthless: {} ${:,.2f}",
    "多头": "Long",
    "空头": "Short",
    "到期实值, 资金不足无法交割 -> 按内在价值 {:.2f} 现金结算":
        "In the money at expiry, not enough funds to take delivery -> cash-settled at intrinsic value {:.2f}",
    "{} 到期实值但资金不足, 已按内在价值现金结算 ({:+,.2f})":
        "{} expired in the money without enough funds; cash-settled at intrinsic value ({:+,.2f})",
    # 参数: (行权价, 买入/卖出, 股数) —— 英文语序不同, 用显式编号
    "到期实值, 按行权价 {:g} {}交割 {} 股":
        "In the money at expiry, delivered: {1} {2} shares at strike {0:g}",
    # 参数: (代码, 行权价, 买入/卖出, 股数, 正股, 期权腿盈亏)
    "{} 到期行权 —— 以 {:g} {} {} 股 {} (期权腿盈亏 {:+,.2f})":
        "{0} exercised at expiry: {2} {3} shares of {4} at {1:g} (option leg P&L {5:+,.2f})",

    # --- 显示 ---
    "买入开仓": "Buy to Open",
    "卖出平仓": "Sell to Close",
    "卖出开仓": "Sell to Open",
    "买入平仓": "Buy to Close",
    "认购 Call": "Call",
    "认沽 Put": "Put",
    "{} {} {:g} {} ({}张)": "{} {} {:g} {} ({} contracts)",
    "{} 张": "{} contracts",
}
