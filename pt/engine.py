"""模拟撮合引擎: 订单校验、成交、盈亏记账、Reg T 与 PDT 风控。"""
from __future__ import annotations

import time
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

from .config import Settings
from .market import Quote
from .models import (
    Account, Order, Position, Trade,
    BUY, SELL, SHORT, COVER, SIDE_CN,
    MARKET, LIMIT, STOP, STOP_LIMIT,
    PENDING, FILLED, CANCELLED, REJECTED, EXPIRED,
    DAY, GTC, OPENING_SIDES, CLOSING_SIDES, BUY_SIDES, SELL_SIDES,
)

ET = ZoneInfo("America/New_York")
MAX_CURVE_POINTS = 20000


def et_date(ts: float) -> date:
    return datetime.fromtimestamp(ts, ET).date()


class RejectError(Exception):
    """订单被风控拒绝。"""


class TradingEngine:
    def __init__(self, account: Account, settings: Settings):
        self.account = account
        self.settings = settings
        self._last_curve_ts = 0.0

    # ==================================================================
    # 费用
    # ==================================================================
    def _costs(self, side: str, qty: int, price: float) -> tuple[float, float]:
        notional = qty * price
        comm = self.settings.commission(qty, notional)
        fees = self.settings.sell_fees(qty, notional) if side in SELL_SIDES else 0.0
        return comm, fees

    def _fill_price(self, side: str, px: float) -> float:
        slip = self.settings.slippage_bps / 10000.0
        adj = (1 + slip) if side in BUY_SIDES else (1 - slip)
        return round(px * adj, 4)

    # ==================================================================
    # 风控
    # ==================================================================
    def position(self, symbol: str) -> Position:
        return self.account.positions.get(symbol.upper()) or Position(symbol.upper())

    def reserved_buying_power(self) -> float:
        """已被挂单占用的购买力。"""
        total = 0.0
        for o in self.account.open_orders():
            if o.side not in BUY_SIDES and o.side != SHORT:
                continue
            ref = o.limit_price or o.stop_price
            if ref:
                total += o.qty * ref
        return total

    def day_trade_count(self, window_days: int = 5) -> int:
        """滚动 5 个交易日内的日内交易次数 (同日同标的开+平 算一次)。"""
        cutoff = date.today() - timedelta(days=window_days + 4)
        buckets: dict[tuple, list[int]] = {}
        for t in self.account.trades:
            d = et_date(t.ts)
            if d < cutoff:
                continue
            key = (d, t.symbol)
            b = buckets.setdefault(key, [0, 0])
            if t.side in OPENING_SIDES:
                b[0] += 1
            else:
                b[1] += 1
        # 只保留最近 window_days 个有交易的日期
        days = sorted({k[0] for k in buckets}, reverse=True)[:window_days]
        return sum(min(v[0], v[1]) for k, v in buckets.items() if k[0] in days)

    def _opened_today(self, symbol: str) -> bool:
        today = et_date(time.time())
        return any(t.symbol == symbol and t.side in OPENING_SIDES and et_date(t.ts) == today
                   for t in self.account.trades)

    def _check_pdt(self, order: Order, prices: dict) -> None:
        s = self.settings
        if not s.enforce_pdt or order.side not in CLOSING_SIDES:
            return
        if self.account.equity(prices) >= s.pdt_equity_threshold:
            return
        if not self._opened_today(order.symbol):
            return
        if self.day_trade_count() >= s.pdt_max_day_trades:
            raise RejectError(
                "触发 PDT 规则: 账户净值低于 ${:,.0f} 时, 5 个交易日内最多 {} 次日内交易 "
                "(当前已 {} 次)。可在【设置】中关闭该规则。".format(
                    s.pdt_equity_threshold, s.pdt_max_day_trades, self.day_trade_count()))

    def validate(self, order: Order, quote: Quote, prices: dict) -> None:
        """校验订单, 不通过则抛 RejectError。"""
        acc = self.account
        if order.qty <= 0:
            raise RejectError("股数必须为正整数")
        px = quote.tradable_price if quote else 0.0
        if px <= 0:
            raise RejectError("拿不到 {} 的有效行情, 无法下单".format(order.symbol))

        if order.order_type in (LIMIT, STOP_LIMIT) and order.limit_price <= 0:
            raise RejectError("限价必须大于 0")
        if order.order_type in (STOP, STOP_LIMIT) and order.stop_price <= 0:
            raise RejectError("触发价必须大于 0")
        if order.order_type == STOP:
            if order.side in BUY_SIDES and order.stop_price <= px:
                raise RejectError("买入止损单的触发价需高于现价 {:.2f}".format(px))
            if order.side in SELL_SIDES and order.stop_price >= px:
                raise RejectError("卖出止损单的触发价需低于现价 {:.2f}".format(px))

        pos = self.position(order.symbol)
        if order.side == SELL:
            pending = sum(o.qty for o in acc.open_orders()
                          if o.symbol == order.symbol and o.side == SELL)
            if pos.qty <= 0:
                raise RejectError("没有 {} 的多头持仓, 做空请用【做空】".format(order.symbol))
            if order.qty + pending > pos.qty:
                raise RejectError("可卖 {} 股 (持仓 {}, 挂单占用 {})".format(
                    pos.qty - pending, pos.qty, pending))
        elif order.side == COVER:
            pending = sum(o.qty for o in acc.open_orders()
                          if o.symbol == order.symbol and o.side == COVER)
            if pos.qty >= 0:
                raise RejectError("没有 {} 的空头持仓可回补".format(order.symbol))
            if order.qty + pending > pos.abs_qty:
                raise RejectError("可回补 {} 股 (空头 {}, 挂单占用 {})".format(
                    pos.abs_qty - pending, pos.abs_qty, pending))
        elif order.side == BUY:
            if pos.qty < 0:
                raise RejectError("{} 当前是空头持仓, 请先【回补】再买入".format(order.symbol))
        elif order.side == SHORT:
            if acc.account_type == "CASH":
                raise RejectError("现金账户不能做空, 请在【设置】中改为保证金账户")
            if pos.qty > 0:
                raise RejectError("{} 当前是多头持仓, 请先【卖出】再做空".format(order.symbol))

        # 购买力: 开仓方向才占用
        if order.side in (BUY, SHORT):
            ref = order.limit_price or order.stop_price or px
            need = order.qty * ref
            comm, fees = self._costs(order.side, order.qty, ref)
            need += comm
            avail = acc.buying_power(prices) - self.reserved_buying_power()
            if need > avail + 1e-6:
                raise RejectError("购买力不足: 需要 ${:,.2f}, 可用 ${:,.2f}".format(need, max(avail, 0)))

        self._check_pdt(order, prices)

    # ==================================================================
    # 下单
    # ==================================================================
    def submit(self, order: Order, quote: Quote, prices: dict) -> tuple[bool, str]:
        try:
            self.validate(order, quote, prices)
        except RejectError as exc:
            order.status = REJECTED
            order.note = str(exc)
            order.updated_at = time.time()
            self.account.orders.append(order)
            return False, str(exc)

        self.account.orders.append(order)

        if order.order_type == MARKET:
            if quote.market_state == "CLOSED" and not self.settings.allow_closed_market_fill:
                order.note = "休市中, 开盘后按市价成交"
                return True, "已提交: {} (休市挂起)".format(order.describe())
            self._execute(order, quote.tradable_price)
            tag = "" if quote.market_state == "REGULAR" else " [{}]".format(
                {"PRE": "盘前", "POST": "盘后", "CLOSED": "休市价"}.get(quote.market_state, ""))
            return True, "成交: {} {} 股 @ ${:.2f}{}".format(
                SIDE_CN.get(order.side, order.side), order.qty, order.fill_price, tag)

        # 挂单: 立刻用当前行情试一次撮合
        filled = self._try_fill(order, quote.tradable_price)
        if filled:
            return True, "立即成交: {} {} 股 @ ${:.2f}".format(
                SIDE_CN.get(order.side, order.side), order.qty, order.fill_price)
        return True, "已挂单: {}".format(order.describe())

    def cancel(self, order_id: str) -> bool:
        for o in self.account.orders:
            if o.id == order_id and o.is_open:
                o.status = CANCELLED
                o.updated_at = time.time()
                return True
        return False

    def cancel_all(self) -> int:
        n = 0
        for o in self.account.open_orders():
            o.status = CANCELLED
            o.updated_at = time.time()
            n += 1
        return n

    # ==================================================================
    # 撮合
    # ==================================================================
    def on_quotes(self, quotes: dict) -> list:
        """行情推进一步, 返回本次新成交的订单。"""
        self.expire_day_orders()
        filled = []
        for o in list(self.account.open_orders()):
            q = quotes.get(o.symbol)
            if not q:
                continue
            px = q.tradable_price
            if px <= 0:
                continue
            if o.order_type == MARKET:
                if q.market_state == "CLOSED" and not self.settings.allow_closed_market_fill:
                    continue
                self._execute(o, px)
                filled.append(o)
            elif self._try_fill(o, px):
                filled.append(o)
        return filled

    def _try_fill(self, o: Order, px: float) -> bool:
        # 止损触发
        if o.order_type in (STOP, STOP_LIMIT) and not o.stop_triggered:
            hit = (px >= o.stop_price) if o.side in BUY_SIDES else (px <= o.stop_price)
            if not hit:
                return False
            o.stop_triggered = True
            if o.order_type == STOP:
                self._execute(o, px)
                return True

        if o.order_type in (LIMIT, STOP_LIMIT):
            if not (o.order_type == LIMIT or o.stop_triggered):
                return False
            if o.side in BUY_SIDES:
                if px > o.limit_price:
                    return False
                self._execute(o, min(px, o.limit_price), slippage=False)
            else:
                if px < o.limit_price:
                    return False
                self._execute(o, max(px, o.limit_price), slippage=False)
            return True
        return False

    def _execute(self, o: Order, px: float, slippage: bool = True) -> None:
        acc = self.account
        price = self._fill_price(o.side, px) if slippage else round(px, 4)
        qty = o.qty
        comm, fees = self._costs(o.side, qty, price)
        cost = comm + fees
        notional = qty * price

        pos = acc.positions.get(o.symbol)
        if pos is None:
            pos = Position(o.symbol)
            acc.positions[o.symbol] = pos

        realized = 0.0
        if o.side == BUY:
            pos.apply_open(qty, price, cost, +1)
            acc.cash -= notional + cost
        elif o.side == SHORT:
            pos.apply_open(qty, price, cost, -1)
            acc.cash += notional - cost
        elif o.side == SELL:
            realized = pos.apply_close(qty, price, cost)
            acc.cash += notional - cost
        elif o.side == COVER:
            realized = pos.apply_close(qty, price, cost)
            acc.cash -= notional + cost

        o.status = FILLED
        o.fill_price = price
        o.commission = comm
        o.fees = fees
        o.realized_pnl = realized
        o.updated_at = time.time()

        acc.trades.append(Trade(symbol=o.symbol, side=o.side, qty=qty, price=price,
                                commission=comm, fees=fees, realized_pnl=realized,
                                order_id=o.id))

    # ==================================================================
    def expire_day_orders(self) -> int:
        today = et_date(time.time())
        n = 0
        for o in self.account.open_orders():
            if o.tif == DAY and et_date(o.created_at) < today:
                o.status = EXPIRED
                o.note = "当日有效单已过期"
                o.updated_at = time.time()
                n += 1
        return n

    def record_equity(self, prices: dict, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_curve_ts < 60:
            return
        self._last_curve_ts = now
        eq = round(self.account.equity(prices), 2)
        curve = self.account.equity_curve
        if curve and abs(curve[-1][1] - eq) < 0.005 and now - curve[-1][0] < 900:
            return
        curve.append([now, eq])
        if len(curve) > MAX_CURVE_POINTS:
            del curve[:len(curve) - MAX_CURVE_POINTS]

    # ==================================================================
    def stats(self, prices: dict) -> dict:
        """账户统计: 胜率、盈亏比、最大回撤等。"""
        acc = self.account
        closes = [t for t in acc.trades if t.side in CLOSING_SIDES]
        wins = [t.realized_pnl for t in closes if t.realized_pnl > 0]
        losses = [t.realized_pnl for t in closes if t.realized_pnl <= 0]
        gross_win = sum(wins)
        gross_loss = abs(sum(losses))

        curve = [p[1] for p in acc.equity_curve] or [acc.initial_cash]
        peak, mdd = curve[0], 0.0
        for v in curve:
            peak = max(peak, v)
            if peak > 0:
                mdd = max(mdd, (peak - v) / peak * 100.0)

        return {
            "closed_trades": len(closes),
            "win_rate": (len(wins) / len(closes) * 100.0) if closes else 0.0,
            "avg_win": (gross_win / len(wins)) if wins else 0.0,
            "avg_loss": (-gross_loss / len(losses)) if losses else 0.0,
            "profit_factor": (gross_win / gross_loss) if gross_loss else (float("inf") if gross_win else 0.0),
            "max_drawdown": mdd,
            "day_trades": self.day_trade_count(),
            "fees": acc.fees_total(),
            "realized": acc.realized_total(),
            "unrealized": acc.unrealized_total(prices),
        }
