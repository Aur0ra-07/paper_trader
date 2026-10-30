"""Claude Code 协作桥 —— 不需要 Anthropic API key。

思路很简单: 用文件当接口。

    软件  --写-->  data/ai/briefing.md     (账户 + 行情 + 指标 + 风控快照)
    你在 Claude Code 里说 "读一下 briefing 给建议"
    Claude --写--> data/ai/decisions.json  (每条建议带理由)
    软件  --读-->  在「AI 建议」页逐条确认执行

这样用的是你已有的 Claude Code 订阅席位, 不走 API 计费。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime

from ..config import DATA_DIR
from ..engine import ET, et_date
from ..models import SIDE_CN, BUY, SELL, SHORT, COVER
from . import indicators as ind
from ..i18n import _tr

AI_DIR = os.path.join(DATA_DIR, "ai")
BRIEFING_PATH = os.path.join(AI_DIR, "briefing.md")
DECISIONS_PATH = os.path.join(AI_DIR, "decisions.json")

VALID_ACTIONS = {BUY, SELL, SHORT, COVER}


@dataclass
class AIDecision:
    symbol: str
    action: str
    qty: int = 0
    reason: str = ""
    confidence: float = 0.0
    order_type: str = "MARKET"
    limit_price: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


# ======================================================================
def _snapshot_indicators(candles: list) -> dict:
    """给 AI 看的技术面摘要。"""
    if len(candles) < 30:
        return {}
    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    last = closes[-1]

    out = {"last": last}
    for p in (20, 50, 200):
        m = ind.sma(closes, p)
        if m[-1]:
            out["ma{}".format(p)] = m[-1]
            out["vs_ma{}".format(p)] = (last / m[-1] - 1) * 100

    r = ind.rsi(closes, 14)
    if r[-1] is not None:
        out["rsi14"] = r[-1]

    mid, up, dn = ind.bollinger(closes, 20, 2.0)
    if mid[-1] and up[-1] and dn[-1] and up[-1] > dn[-1]:
        out["boll_pos"] = (last - dn[-1]) / (up[-1] - dn[-1]) * 100   # 0=下轨 100=上轨

    a = ind.atr(highs, lows, closes, 14)
    if a[-1] and last:
        out["atr_pct"] = a[-1] / last * 100

    ad = ind.adx(highs, lows, closes, 14)
    if ad[-1] is not None:
        out["adx"] = ad[-1]

    for p in (5, 20, 60):
        rc = ind.roc(closes, p)
        if rc[-1] is not None:
            out["roc{}".format(p)] = rc[-1]

    win = closes[-252:] if len(closes) >= 252 else closes
    hi52, lo52 = max(win), min(win)
    out["from_52w_high"] = (last / hi52 - 1) * 100 if hi52 else 0.0
    out["from_52w_low"] = (last / lo52 - 1) * 100 if lo52 else 0.0
    return out


def _fmt(v, suffix="", dp=2):
    if v is None:
        return "—"
    return "{:.{}f}{}".format(v, dp, suffix)


def export_briefing(account, engine, quotes: dict, prices: dict,
                    candles_by_symbol: dict, auto_config=None,
                    backtest_note: str = "", path: str = "") -> str:
    """生成给 Claude Code 读的简报, 返回文件路径。"""
    path = path or BRIEFING_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)

    now = datetime.now(ET)
    sample = next(iter(quotes.values()), None)
    state = {"REGULAR": _tr("交易中"), "PRE": _tr("盘前"), "POST": _tr("盘后"),
             "CLOSED": _tr("休市")}.get(sample.market_state if sample else "CLOSED", _tr("未知"))

    eq = account.equity(prices)
    stats = engine.stats(prices)
    L = []
    A = L.append

    A(_tr("# 模拟交易账户简报"))
    A("")
    A(_tr("> 这是一个**模拟盘**（虚拟资金，不接任何真实券商）。行情是真的，钱是假的。"))
    A(_tr("> 请基于下面的数据给出调仓建议，写入 `data/ai/decisions.json`（格式见文末）。"))
    A("")
    A(_tr("- 生成时间：{}（纽约时间），市场状态：**{}**").format(
        now.strftime("%Y-%m-%d %H:%M:%S"), state))
    A(_tr("- 账户：{}（{}）").format(
        account.name, _tr("保证金账户 2x") if account.account_type == "MARGIN" else _tr("现金账户")))
    A("")

    # ---------------- 账户 ----------------
    A(_tr("## 1. 账户状态"))
    A("")
    A(_tr("| 项目 | 数值 |"))
    A("|---|---|")
    A(_tr("| 总资产 | ${:,.2f} |").format(eq))
    A(_tr("| 初始资金 | ${:,.2f} |").format(account.initial_cash))
    A(_tr("| 总收益率 | {:+.2f}% |").format(account.total_return_pct(prices)))
    A(_tr("| 可用现金 | ${:,.2f} |").format(account.cash))
    A(_tr("| 购买力 | ${:,.2f} |").format(account.buying_power(prices)))
    A(_tr("| 持仓市值 | ${:,.2f} |").format(account.positions_value(prices)))
    A(_tr("| 浮动盈亏 | ${:+,.2f} |").format(account.unrealized_total(prices)))
    A(_tr("| 已实现盈亏 | ${:+,.2f} |").format(account.realized_total()))
    A(_tr("| 累计费用 | ${:,.2f} |").format(account.fees_total()))
    A(_tr("| 胜率 / 平仓次数 | {:.0f}% / {} |").format(stats["win_rate"], stats["closed_trades"]))
    A(_tr("| 最大回撤 | {:.2f}% |").format(stats["max_drawdown"]))
    A(_tr("| 近5日日内交易 | {} 次（PDT 上限 3 次，净值 <$25k 时生效）|").format(stats["day_trades"]))
    A("")

    # ---------------- 持仓 ----------------
    A(_tr("## 2. 当前持仓"))
    A("")
    positions = account.open_positions()
    if not positions:
        A(_tr("*当前空仓。*"))
    else:
        A(_tr("| 代码 | 方向 | 股数 | 成本 | 现价 | 市值 | 浮动盈亏 | 盈亏% | 占净值 | 持有天数 |"))
        A("|---|---|---|---|---|---|---|---|---|---|")
        for p in sorted(positions, key=lambda x: x.symbol):
            px = prices.get(p.symbol) or p.avg_cost
            days = max(int((time.time() - p.opened_at) / 86400), 0)
            A("| {} | {} | {:,} | {:.2f} | {:.2f} | ${:,.0f} | ${:+,.0f} | {:+.2f}% | {:.1f}% | {} |".format(
                p.symbol, _tr("空头") if p.is_short else _tr("多头"), p.abs_qty, p.avg_cost, px,
                abs(p.market_value(px)), p.unrealized(px), p.unrealized_pct(px),
                abs(p.market_value(px)) / eq * 100 if eq else 0, days))
    A("")

    # ---------------- 挂单 ----------------
    open_orders = account.open_orders()
    if open_orders:
        A(_tr("## 3. 未成交挂单"))
        A("")
        A(_tr("| 代码 | 内容 | 挂单时间 |"))
        A("|---|---|---|")
        for o in open_orders:
            A("| {} | {} | {} |".format(
                o.symbol, o.describe(),
                datetime.fromtimestamp(o.created_at).strftime("%m-%d %H:%M")))
        A("")

    # ---------------- 行情 + 指标 ----------------
    A(_tr("## 4. 关注标的行情与技术指标"))
    A("")
    A(_tr("`vs MA` 为正表示价格在均线上方；`布林位置` 0=下轨 100=上轨；"
      "`ATR%` 为日均波动幅度；`ADX` >25 表示趋势明确。"))
    A("")
    A(_tr("| 代码 | 现价 | 今日 | RSI14 | vs MA20 | vs MA50 | vs MA200 | 布林位置 | ADX | ATR% | 20日动量 | 距52周高 |"))
    A("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for sym in sorted(quotes):
        q = quotes[sym]
        s = _snapshot_indicators(candles_by_symbol.get(sym) or [])
        # 现价是下单会成交的价 (盘前盘后用延伸价), 涨跌幅就得用同一个价较昨收算,
        # 不能拿常规时段的 change_pct 配盘后价
        px = q.tradable_price
        chg = (px / q.prev_close - 1) * 100 if q.prev_close else 0.0
        A("| {} | {:.2f} | {:+.2f}% | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            sym, px, chg,
            _fmt(s.get("rsi14"), "", 1),
            _fmt(s.get("vs_ma20"), "%", 1), _fmt(s.get("vs_ma50"), "%", 1),
            _fmt(s.get("vs_ma200"), "%", 1), _fmt(s.get("boll_pos"), "", 0),
            _fmt(s.get("adx"), "", 0), _fmt(s.get("atr_pct"), "%", 1),
            _fmt(s.get("roc20"), "%", 1), _fmt(s.get("from_52w_high"), "%", 1)))
    A("")

    # ---------------- 最近成交 ----------------
    recent = sorted(account.trades, key=lambda t: -t.ts)[:15]
    if recent:
        A(_tr("## 5. 最近成交"))
        A("")
        A(_tr("| 时间 | 代码 | 方向 | 股数 | 价格 | 已实现盈亏 |"))
        A("|---|---|---|---|---|---|")
        for t in recent:
            A("| {} | {} | {} | {:,} | {:.2f} | {} |".format(
                datetime.fromtimestamp(t.ts).strftime("%m-%d %H:%M"), t.symbol,
                SIDE_CN.get(t.side, t.side), t.qty, t.price,
                "${:+,.2f}".format(t.realized_pnl) if t.side in (SELL, COVER) else "—"))
        A("")

    # ---------------- 约束 ----------------
    A(_tr("## 6. 必须遵守的约束"))
    A("")
    if auto_config is not None:
        lim = auto_config.limits()
        A(_tr("- 单只标的最多占净值 **{:.0f}%**").format(lim.max_position_pct))
        A(_tr("- 最多同时持有 **{} 只**").format(lim.max_positions))
        A(_tr("- 每日最多 **{} 笔**交易").format(lim.max_trades_per_day))
        A(_tr("- 做空：{}").format(_tr("允许") if lim.allow_short else _tr("**不允许**")))
    A(_tr("- 可用购买力 **${:,.2f}**，不要给出超出购买力的建议").format(
        account.buying_power(prices)))
    A(_tr("- 卖出/回补的股数不能超过现有持仓"))
    A(_tr("- 账户净值低于 $25,000 时，5 个交易日内最多 3 次日内交易（当日买当日卖）"))
    if backtest_note:
        A("")
        A(_tr("**回测参考**：{}").format(backtest_note))
    A("")

    # ---------------- 输出格式 ----------------
    A(_tr("## 7. 请输出的格式"))
    A("")
    A(_tr("把建议写入 `data/ai/decisions.json`，覆盖原文件："))
    A("")
    A("```json")
    A(json.dumps({
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "note": _tr("一句话总结本次调仓思路"),
        "decisions": [
            {"symbol": "AAPL", "action": "BUY", "qty": 50,
             "order_type": "MARKET", "limit_price": 0,
             "confidence": 0.7, "reason": _tr("为什么这么做，引用上面表格里的具体数字")},
            {"symbol": "TSLA", "action": "SELL", "qty": 20,
             "order_type": "LIMIT", "limit_price": 370.5,
             "confidence": 0.5, "reason": "……"}
        ]
    }, ensure_ascii=False, indent=2))
    A("```")
    A("")
    A(_tr("- `action` 只能是 `BUY`(买入开多) / `SELL`(卖出平多) / `SHORT`(做空) / `COVER`(买入回补)"))
    A(_tr("- `order_type` 为 `MARKET` 或 `LIMIT`；用 `LIMIT` 时必须给 `limit_price`"))
    A(_tr("- 不需要调仓就返回空的 `decisions` 数组，并在 `note` 里说明为什么按兵不动"))
    A(_tr("- `reason` 要具体，引用上面的指标数字，不要写“看起来不错”这类空话"))

    text = "\n".join(L)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# ======================================================================
def load_decisions(account, engine, prices: dict, path: str = "") -> tuple:
    """读取 Claude 写的 decisions.json。返回 (决策列表, 备注, 错误)。"""
    path = path or DECISIONS_PATH
    if not os.path.exists(path):
        return [], "", _tr("还没有 decisions.json —— 先导出简报, 让 Claude 读完写一份")
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return [], "", _tr("decisions.json 解析失败: {}").format(exc)

    if not isinstance(raw, dict):
        return [], "", _tr("decisions.json 顶层必须是一个 JSON 对象")
    note = str(raw.get("note") or "")
    items = raw.get("decisions")
    if not isinstance(items, list):
        return [], note, _tr("decisions 字段必须是数组")

    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        d = AIDecision(
            symbol=str(it.get("symbol", "")).upper().strip(),
            action=str(it.get("action", "")).upper().strip(),
            reason=str(it.get("reason") or ""),
            order_type=str(it.get("order_type") or "MARKET").upper().strip(),
        )
        try:
            d.qty = int(it.get("qty") or 0)
        except (TypeError, ValueError):
            d.qty = 0
        try:
            d.confidence = float(it.get("confidence") or 0)
        except (TypeError, ValueError):
            d.confidence = 0.0
        try:
            d.limit_price = float(it.get("limit_price") or 0)
        except (TypeError, ValueError):
            d.limit_price = 0.0

        # -- 校验 --
        if not d.symbol:
            d.error = _tr("缺少 symbol")
        elif d.action not in VALID_ACTIONS:
            d.error = _tr("action 无效: {}").format(d.action or _tr("(空)"))
        elif d.qty < 1:
            d.error = _tr("qty 必须是正整数")
        elif d.order_type not in ("MARKET", "LIMIT"):
            d.error = _tr("order_type 只能是 MARKET 或 LIMIT")
        elif d.order_type == "LIMIT" and d.limit_price <= 0:
            d.error = _tr("限价单必须给出 limit_price")
        else:
            pos = engine.position(d.symbol)
            if d.action == SELL and d.qty > pos.qty:
                d.error = _tr("只持有 {} 股多头, 卖不了 {} 股").format(max(pos.qty, 0), d.qty)
            elif d.action == COVER and d.qty > pos.abs_qty:
                d.error = _tr("只持有 {} 股空头, 回补不了 {} 股").format(
                    pos.abs_qty if pos.qty < 0 else 0, d.qty)
            elif d.action in (BUY, SHORT):
                px = prices.get(d.symbol, 0.0)
                if px <= 0:
                    # 没有行情 = 代码不存在或没在关注列表里, 不能放行
                    d.error = _tr("拿不到 {} 的行情, 无法校验 (代码写错了?)").format(d.symbol)
                else:
                    avail = account.buying_power(prices) - engine.reserved_buying_power()
                    if d.qty * px > avail:
                        d.error = _tr("需要 ${:,.0f}, 可用购买力只有 ${:,.0f}").format(
                            d.qty * px, max(avail, 0))
        out.append(d)
    return out, note, ""


def decisions_age() -> float:
    """decisions.json 距今多少秒, 不存在返回 -1。"""
    if not os.path.exists(DECISIONS_PATH):
        return -1.0
    return time.time() - os.path.getmtime(DECISIONS_PATH)
