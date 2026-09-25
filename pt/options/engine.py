"""期权交易引擎: 下单校验、成交、卖方保证金、到期行权与指派。

设计要点:
* **价格一律用市场 bid/ask** —— 买入吃 ask, 卖出砸 bid。期权价差很宽(实测平值 4%,
  虚值 6%+), 这是最大的隐性成本, 用中间价成交等于自己骗自己。
* **卖方要占保证金** —— 裸卖 call/put 按 Reg T 近似计算; 有正股/现金担保的不额外占用。
* **到期实物交割** —— 实值自动行权成正股; 购买力不够时退化为按内在价值现金结算,
  并在成交记录里注明 (真实券商也是强制平仓处理)。
"""
from __future__ import annotations

import time
from datetime import date, datetime

from ..config import Settings
from ..engine import ET, et_date
from ..models import Account, Position, Trade, BUY, SELL, SHORT, COVER
from .models import (
    OptionOrder, OptionPosition, OptionQuote, OptionTrade,
    BUY_OPEN, SELL_CLOSE, SELL_OPEN, BUY_CLOSE,
    OPT_SIDE_CN, OPT_OPENING, OPT_CLOSING, OPT_BUY_SIDES, OPT_SELL_SIDES,
    parse_occ,
)
from .pricing import CALL, PUT, intrinsic

MARKET = "MARKET"
LIMIT = "LIMIT"


class OptionRejectError(Exception):
    pass


# ======================================================================
# 保证金
# ======================================================================
def position_margin(pos: OptionPosition, spot: float, account: Account,
                    opt_price: float | None = None) -> float:
    """单个卖方持仓占用的保证金 (Reg T 近似)。买方(qty>0)不占保证金。

    裸卖公式: (权利金 + max(20%%×股价 − 虚值幅度, 10%%×股价)) × 100 × 张数
    备兑(有对应正股)或现金担保不额外占用。
    """
    if pos.qty >= 0 or spot <= 0:
        return 0.0
    n = pos.abs_qty
    mult = pos.multiplier
    K = pos.strike
    prem = opt_price if opt_price is not None else pos.avg_cost

    if pos.right == CALL:
        # 有对应正股就是备兑, 不额外占保证金
        stock = account.positions.get(pos.underlying)
        covered = min(n, int((stock.qty if stock else 0) // mult))
        naked = n - covered
        if naked <= 0:
            return 0.0
        otm = max(K - spot, 0.0)
        per = (prem + max(0.20 * spot - otm, 0.10 * spot)) * mult
        return per * naked
    # PUT: 卖出认沽最大风险是 K, 取 Reg T 近似与现金担保的较小者
    otm = max(spot - K, 0.0)
    per = min((prem + max(0.20 * spot - otm, 0.10 * K)) * mult, K * mult)
    return per * n


def total_option_margin(account: Account, spots: dict, prices: dict | None = None) -> float:
    total = 0.0
    prices = prices or {}
    for p in account.open_option_positions():
        s = spots.get(p.underlying, 0.0)
        total += position_margin(p, s, account, prices.get(p.symbol))
    return total


# ======================================================================
class OptionsEngine:
    def __init__(self, account: Account, settings: Settings):
        self.account = account
        self.settings = settings

    # ------------------------------------------------------------------
    def position(self, symbol: str) -> OptionPosition:
        p = self.account.option_positions.get(symbol.upper())
        if p:
            return p
        und, exp, right, strike = parse_occ(symbol)
        return OptionPosition(symbol=symbol.upper(), underlying=und or "",
                              right=right or CALL, strike=strike or 0.0,
                              expiry=exp.isoformat() if exp else "")

    def commission(self, contracts: int) -> float:
        """期权佣金: 按张收, 沿用设置里的口径 (零佣金模式下仍收交易所规费)。"""
        s = self.settings
        if s.commission_mode == "zero":
            return round(contracts * 0.65 * 0.0, 2)      # 零佣金券商期权也常免佣
        if s.commission_mode == "flat":
            return round(s.commission_flat, 2)
        return round(max(contracts * s.option_commission_per_contract,
                         s.option_commission_min), 2)

    def buying_power(self, prices: dict, spots: dict) -> float:
        return self.account.buying_power(
            prices, total_option_margin(self.account, spots, prices))

    # ------------------------------------------------------------------
    def validate(self, order: OptionOrder, quote: OptionQuote,
                 prices: dict, spots: dict) -> None:
        acc = self.account
        if order.qty <= 0:
            raise OptionRejectError("合约张数必须是正整数")
        if quote is None:
            raise OptionRejectError("拿不到 {} 的报价".format(order.symbol))
        px = quote.fill_price(order.side)
        if px <= 0:
            raise OptionRejectError("该合约没有有效报价 (bid {:.2f} / ask {:.2f})".format(
                quote.bid, quote.ask))
        if quote.expiry < et_date(time.time()):
            raise OptionRejectError("该合约已于 {} 到期".format(quote.expiry))
        if order.order_type == LIMIT and order.limit_price <= 0:
            raise OptionRejectError("限价必须大于 0")

        pos = self.position(order.symbol)
        pending = sum(o.qty for o in acc.open_option_orders()
                      if o.symbol == order.symbol and o.side == order.side)

        if order.side == SELL_CLOSE:
            if pos.qty <= 0:
                raise OptionRejectError("没有 {} 的买方持仓可卖出".format(order.symbol))
            if order.qty + pending > pos.qty:
                raise OptionRejectError("可平 {} 张 (持有 {}, 挂单占用 {})".format(
                    pos.qty - pending, pos.qty, pending))
        elif order.side == BUY_CLOSE:
            if pos.qty >= 0:
                raise OptionRejectError("没有 {} 的卖方持仓可买回".format(order.symbol))
            if order.qty + pending > pos.abs_qty:
                raise OptionRejectError("可平 {} 张 (义务 {}, 挂单占用 {})".format(
                    pos.abs_qty - pending, pos.abs_qty, pending))
        elif order.side == BUY_OPEN:
            if pos.qty < 0:
                raise OptionRejectError("当前是卖方持仓, 请先「买入平仓」")
            cost = px * order.qty * quote.multiplier + self.commission(order.qty)
            # Reg T: 买入期权不能用融资, 必须全额付现 (期权没有抵押价值)
            reserved = sum(o.qty * (o.limit_price or 0) * o.multiplier
                           for o in acc.open_option_orders() if o.side in OPT_BUY_SIDES)
            avail = acc.cash - reserved
            if cost > avail + 1e-6:
                raise OptionRejectError(
                    "现金不足: 需要 ${:,.2f}, 可用现金 ${:,.2f} "
                    "(买入期权不能用融资, 必须全额付现)".format(cost, max(avail, 0)))
        elif order.side == SELL_OPEN:
            if pos.qty > 0:
                raise OptionRejectError("当前是买方持仓, 请先「卖出平仓」")
            if acc.account_type == "CASH" and quote.right == CALL:
                stock = acc.positions.get(quote.underlying)
                covered = int((stock.qty if stock else 0) // quote.multiplier)
                if order.qty > covered:
                    raise OptionRejectError(
                        "现金账户只能做备兑开仓: 需要持有 {} 股 {}, 当前只有 {} 股".format(
                            order.qty * quote.multiplier, quote.underlying,
                            stock.qty if stock else 0))
            probe = OptionPosition(
                symbol=order.symbol, underlying=quote.underlying, right=quote.right,
                strike=quote.strike, expiry=quote.expiry.isoformat(),
                qty=-(pos.abs_qty + order.qty), avg_cost=px,
                multiplier=quote.multiplier)
            spot = spots.get(quote.underlying, 0.0)
            need = position_margin(probe, spot, acc) - position_margin(pos, spot, acc)
            avail = self.buying_power(prices, spots)
            if need > avail + 1e-6:
                raise OptionRejectError(
                    "卖方保证金不足: 需要 ${:,.2f}, 可用购买力 ${:,.2f}".format(need, max(avail, 0)))
        else:
            raise OptionRejectError("未知方向: {}".format(order.side))

    # ------------------------------------------------------------------
    def submit(self, order: OptionOrder, quote: OptionQuote,
               prices: dict, spots: dict) -> tuple:
        try:
            self.validate(order, quote, prices, spots)
        except OptionRejectError as exc:
            order.status = "REJECTED"
            order.note = str(exc)
            order.updated_at = time.time()
            self.account.option_orders.append(order)
            return False, str(exc)

        self.account.option_orders.append(order)
        if order.order_type == LIMIT:
            if not self._limit_hit(order, quote):
                return True, "已挂单: {}".format(order.describe())
            self._execute(order, quote, self._limit_fill(order, quote))
        else:
            self._execute(order, quote, quote.fill_price(order.side))
        return True, "成交: {} {} 张 @ ${:.2f}  (总额 ${:,.2f})".format(
            OPT_SIDE_CN.get(order.side, order.side), order.qty, order.fill_price,
            order.fill_price * order.qty * order.multiplier)

    def _limit_hit(self, order: OptionOrder, quote: OptionQuote) -> bool:
        if order.side in OPT_BUY_SIDES:
            return quote.ask > 0 and quote.ask <= order.limit_price
        return quote.bid > 0 and quote.bid >= order.limit_price

    def _limit_fill(self, order: OptionOrder, quote: OptionQuote) -> float:
        if order.side in OPT_BUY_SIDES:
            return min(quote.ask, order.limit_price)
        return max(quote.bid, order.limit_price)

    def on_quotes(self, quotes: dict) -> list:
        """撮合挂单。quotes: OCC 代码 -> OptionQuote。"""
        filled = []
        for o in list(self.account.open_option_orders()):
            q = quotes.get(o.symbol)
            if not q:
                continue
            if q.expiry < et_date(time.time()):
                o.status = "EXPIRED"
                o.note = "合约已到期, 挂单作废"
                o.updated_at = time.time()
                continue
            if o.order_type == LIMIT and not self._limit_hit(o, q):
                continue
            self._execute(o, q, self._limit_fill(o, q) if o.order_type == LIMIT
                          else q.fill_price(o.side))
            filled.append(o)
        return filled

    def cancel(self, order_id: str) -> bool:
        for o in self.account.option_orders:
            if o.id == order_id and o.is_open:
                o.status = "CANCELLED"
                o.updated_at = time.time()
                return True
        return False

    # ------------------------------------------------------------------
    def _execute(self, order: OptionOrder, quote: OptionQuote, price: float) -> None:
        acc = self.account
        qty = order.qty
        mult = quote.multiplier
        comm = self.commission(qty)
        notional = price * qty * mult

        pos = acc.option_positions.get(order.symbol)
        if pos is None:
            pos = OptionPosition(
                symbol=order.symbol, underlying=quote.underlying, right=quote.right,
                strike=quote.strike, expiry=quote.expiry.isoformat(), multiplier=mult)
            acc.option_positions[order.symbol] = pos

        realized = 0.0
        if order.side == BUY_OPEN:
            pos.apply_open(qty, price, comm, +1)
            acc.cash -= notional + comm
        elif order.side == SELL_OPEN:
            pos.apply_open(qty, price, comm, -1)
            acc.cash += notional - comm
        elif order.side == SELL_CLOSE:
            realized = pos.apply_close(qty, price, comm)
            acc.cash += notional - comm
        elif order.side == BUY_CLOSE:
            realized = pos.apply_close(qty, price, comm)
            acc.cash -= notional + comm

        order.status = "FILLED"
        order.fill_price = price
        order.commission = comm
        order.realized_pnl = realized
        order.multiplier = mult
        order.updated_at = time.time()

        acc.option_trades.append(OptionTrade(
            symbol=order.symbol, underlying=quote.underlying, side=order.side,
            qty=qty, price=price, right=quote.right, strike=quote.strike,
            expiry=quote.expiry.isoformat(), commission=comm,
            realized_pnl=realized, order_id=order.id, multiplier=mult))

    # ==================================================================
    # 到期处理
    # ==================================================================
    def process_expirations(self, spots: dict, today: date | None = None,
                            force: bool = False) -> list:
        """处理已到期的期权。返回人类可读的处理记录。

        实值自动行权/被指派成正股; 购买力不够时按内在价值现金结算。
        force=True 时忽略"是否已过收盘"的判断, 用于测试。
        """
        acc = self.account
        today = today or et_date(time.time())
        now_et = datetime.now(ET)
        past_close = force or now_et.hour >= 16 or now_et.date() > today

        logs = []
        for pos in list(acc.open_option_positions()):
            exp = pos.expiry_date
            if exp > today or (exp == today and not past_close):
                continue
            spot = spots.get(pos.underlying, 0.0)
            if spot <= 0:
                logs.append("{} 到期但拿不到 {} 的价格, 本次跳过".format(
                    pos.symbol, pos.underlying))
                continue
            logs.append(self._settle(pos, spot, exp))
        return logs

    def _settle(self, pos: OptionPosition, spot: float, exp: date) -> str:
        acc = self.account
        n = pos.abs_qty
        mult = pos.multiplier
        shares = n * mult
        intr = intrinsic(spot, pos.strike, pos.right)
        long_side = pos.qty > 0

        # --- 虚值: 作废 ---
        if intr <= 0.005:
            realized = pos.apply_close(n, 0.0, 0.0)
            note = "到期作废 (结算价 {:.2f} vs 行权价 {:g})".format(spot, pos.strike)
            self._log_settlement(pos, 0.0, realized, note)
            side = "买方权利金全亏" if long_side else "卖方权利金全赚"
            return "{} {} 到期作废 —— {} ${:,.2f}".format(
                pos.symbol, "多头" if long_side else "空头", side, abs(realized))

        # --- 实值: 先按内在价值平掉期权腿 ---
        cash_needed = 0.0
        if long_side and pos.right == CALL:
            cash_needed = pos.strike * shares          # 行权买入正股要花钱
        elif not long_side and pos.right == PUT:
            cash_needed = pos.strike * shares          # 被指派要买入正股

        can_deliver = True
        if cash_needed > 0:
            avail = acc.cash + max(
                acc.buying_power({}, total_option_margin(acc, {})) - acc.cash, 0.0)
            if cash_needed > max(acc.cash, 0) and acc.account_type == "CASH":
                can_deliver = False
            elif cash_needed > max(avail, 0):
                can_deliver = False

        realized = pos.apply_close(n, intr, 0.0)
        if long_side:
            acc.cash += intr * shares       # 先按内在价值收回权利
        else:
            acc.cash -= intr * shares

        if not can_deliver:
            note = "到期实值, 资金不足无法交割 -> 按内在价值 {:.2f} 现金结算".format(intr)
            self._log_settlement(pos, intr, realized, note)
            return "{} 到期实值但资金不足, 已按内在价值现金结算 ({:+,.2f})".format(
                pos.symbol, realized)

        # --- 实物交割: 转成正股持仓 ---
        if long_side and pos.right == CALL:
            stock_side, stock_qty, direction = BUY, shares, +1
        elif long_side and pos.right == PUT:
            stock_side, stock_qty, direction = SELL, shares, -1
        elif not long_side and pos.right == CALL:
            stock_side, stock_qty, direction = SELL, shares, -1
        else:
            stock_side, stock_qty, direction = BUY, shares, +1

        self._deliver(pos.underlying, stock_side, stock_qty, pos.strike, direction, intr)
        note = "到期实值, 按行权价 {:g} {}交割 {} 股".format(
            pos.strike, "买入" if direction > 0 else "卖出", stock_qty)
        self._log_settlement(pos, intr, realized, note)
        return "{} 到期行权 —— 以 {:g} {} {} 股 {} (期权腿盈亏 {:+,.2f})".format(
            pos.symbol, pos.strike, "买入" if direction > 0 else "卖出",
            stock_qty, pos.underlying, realized)

    def _deliver(self, underlying: str, side: str, shares: int, strike: float,
                 direction: int, intr: float) -> None:
        """行权/指派产生的正股交割。按行权价成交, 不收佣金 (多数券商行权免佣)。"""
        acc = self.account
        stock = acc.positions.get(underlying)
        if stock is None:
            stock = Position(underlying)
            acc.positions[underlying] = stock

        notional = strike * shares
        # 先抵消反向持仓, 剩下的才开新仓
        if stock.qty != 0 and (stock.qty > 0) != (direction > 0):
            close_qty = min(abs(stock.qty), shares)
            realized = stock.apply_close(close_qty, strike, 0.0)
            acc.cash += (strike * close_qty) if direction < 0 else -(strike * close_qty)
            acc.trades.append(Trade(symbol=underlying,
                                    side=SELL if direction < 0 else COVER,
                                    qty=close_qty, price=strike,
                                    realized_pnl=realized))
            shares -= close_qty
            notional = strike * shares
        if shares <= 0:
            return

        stock.apply_open(shares, strike, 0.0, direction)
        acc.cash += -notional if direction > 0 else notional
        acc.trades.append(Trade(symbol=underlying,
                                side=BUY if direction > 0 else SHORT,
                                qty=shares, price=strike, realized_pnl=0.0))

    def _log_settlement(self, pos: OptionPosition, price: float,
                        realized: float, note: str) -> None:
        self.account.option_trades.append(OptionTrade(
            symbol=pos.symbol, underlying=pos.underlying,
            side=SELL_CLOSE if pos.qty >= 0 else BUY_CLOSE,
            qty=pos.abs_qty or 1, price=price, right=pos.right, strike=pos.strike,
            expiry=pos.expiry, realized_pnl=realized,
            multiplier=pos.multiplier, note=note))

    # ==================================================================
    def stats(self, prices: dict, spots: dict) -> dict:
        acc = self.account
        closed = [t for t in acc.option_trades if t.side in OPT_CLOSING]
        wins = [t for t in closed if t.realized_pnl > 0]
        expired = [t for t in closed if "作废" in (t.note or "")]
        exercised = [t for t in closed if "交割" in (t.note or "")]
        return {
            "positions": len(acc.open_option_positions()),
            "margin_used": total_option_margin(acc, spots),
            "market_value": acc.options_value(prices),
            "unrealized": acc.options_unrealized(prices),
            "realized": acc.options_realized(),
            "closed_trades": len(closed),
            "win_rate": (len(wins) / len(closed) * 100.0) if closed else 0.0,
            "expired_worthless": len(expired),
            "exercised": len(exercised),
        }
