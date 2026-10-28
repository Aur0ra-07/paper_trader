"""数据模型: 订单 / 成交 / 持仓 / 账户。"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from .i18n import N_, _tr

# 系统起的默认账户名。存盘永远是这个中文原文, 显示时跟着界面语言走。
DEFAULT_ACCOUNT_NAME = N_("我的模拟账户")

# ---- 方向 ---------------------------------------------------------------
BUY = "BUY"        # 买入开多 / 加多
SELL = "SELL"      # 卖出平多
SHORT = "SHORT"    # 融券做空开仓
COVER = "COVER"    # 买入回补平空

SIDE_CN = {BUY: _tr("买入"), SELL: _tr("卖出"), SHORT: _tr("做空"), COVER: _tr("回补")}
OPENING_SIDES = (BUY, SHORT)
CLOSING_SIDES = (SELL, COVER)
BUY_SIDES = (BUY, COVER)     # 需要资金 / 推高成本的一侧
SELL_SIDES = (SELL, SHORT)   # 产生现金 / 需要缴规费的一侧

# ---- 订单类型 -----------------------------------------------------------
MARKET = "MARKET"
LIMIT = "LIMIT"
STOP = "STOP"
STOP_LIMIT = "STOP_LIMIT"

TYPE_CN = {MARKET: _tr("市价单"), LIMIT: _tr("限价单"), STOP: _tr("止损单"), STOP_LIMIT: _tr("止损限价单")}

# ---- 状态 ---------------------------------------------------------------
PENDING = "PENDING"
FILLED = "FILLED"
CANCELLED = "CANCELLED"
REJECTED = "REJECTED"
EXPIRED = "EXPIRED"

STATUS_CN = {PENDING: _tr("挂单中"), FILLED: _tr("已成交"), CANCELLED: _tr("已撤单"),
             REJECTED: _tr("已拒绝"), EXPIRED: _tr("已过期")}

DAY = "DAY"
GTC = "GTC"


def _uid() -> str:
    return uuid.uuid4().hex[:10]


@dataclass
class Order:
    symbol: str
    side: str
    qty: int
    order_type: str = MARKET
    limit_price: float = 0.0
    stop_price: float = 0.0
    tif: str = DAY
    id: str = field(default_factory=_uid)
    status: str = PENDING
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    fill_price: float = 0.0
    commission: float = 0.0
    fees: float = 0.0
    realized_pnl: float = 0.0
    note: str = ""
    stop_triggered: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Order":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})

    @property
    def is_open(self) -> bool:
        return self.status == PENDING

    def describe(self) -> str:
        bits = [SIDE_CN.get(self.side, self.side), TYPE_CN.get(self.order_type, self.order_type),
                _tr("{} 股").format(self.qty)]
        if self.order_type in (LIMIT, STOP_LIMIT):
            bits.append(_tr("限价 {:.2f}").format(self.limit_price))
        if self.order_type in (STOP, STOP_LIMIT):
            bits.append(_tr("触发 {:.2f}").format(self.stop_price))
        return " ".join(bits)


@dataclass
class Trade:
    symbol: str
    side: str
    qty: int
    price: float
    commission: float = 0.0
    fees: float = 0.0
    realized_pnl: float = 0.0
    ts: float = field(default_factory=time.time)
    order_id: str = ""
    id: str = field(default_factory=_uid)

    @property
    def notional(self) -> float:
        return self.qty * self.price

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Trade":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Position:
    symbol: str
    qty: int = 0                 # 正=多头, 负=空头
    avg_cost: float = 0.0        # 每股平均成本(多)/平均卖出净价(空), 已含佣金与规费
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    opened_at: float = field(default_factory=time.time)

    @property
    def is_short(self) -> bool:
        return self.qty < 0

    @property
    def abs_qty(self) -> int:
        return abs(self.qty)

    def market_value(self, price: float) -> float:
        """持仓市值 (空头为负, 代表负债)。"""
        return self.qty * price

    def cost_basis(self) -> float:
        return self.abs_qty * self.avg_cost

    def unrealized(self, price: float) -> float:
        if self.qty == 0:
            return 0.0
        if self.qty > 0:
            return (price - self.avg_cost) * self.qty
        return (self.avg_cost - price) * self.abs_qty

    def unrealized_pct(self, price: float) -> float:
        base = self.cost_basis()
        return (self.unrealized(price) / base * 100.0) if base else 0.0

    # -- 记账 -----------------------------------------------------------
    def apply_open(self, qty: int, price: float, cost: float, direction: int) -> None:
        """加仓。direction: +1 多头, -1 空头。cost = 佣金+规费。"""
        old_abs = self.abs_qty
        old_total = old_abs * self.avg_cost
        if direction > 0:
            new_total = old_total + qty * price + cost   # 买入: 费用推高成本
        else:
            new_total = old_total + qty * price - cost   # 做空: 费用压低净收
        new_abs = old_abs + qty
        self.avg_cost = new_total / new_abs if new_abs else 0.0
        self.qty = new_abs * direction
        self.fees_paid += cost
        if old_abs == 0:
            self.opened_at = time.time()

    def apply_close(self, qty: int, price: float, cost: float) -> float:
        """平仓, 返回本次已实现盈亏。"""
        if self.qty > 0:
            pnl = (price * qty - cost) - self.avg_cost * qty
            self.qty -= qty
        else:
            pnl = self.avg_cost * qty - (price * qty + cost)
            self.qty += qty
        self.realized_pnl += pnl
        self.fees_paid += cost
        if self.qty == 0:
            self.avg_cost = 0.0
        return pnl

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Position":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "SPY", "QQQ"]


@dataclass
class Account:
    name: str = DEFAULT_ACCOUNT_NAME
    id: str = field(default_factory=_uid)
    account_type: str = "MARGIN"       # CASH | MARGIN
    initial_cash: float = 100000.0
    cash: float = 100000.0
    created_at: float = field(default_factory=time.time)
    positions: dict = field(default_factory=dict)      # symbol -> Position
    orders: list = field(default_factory=list)         # list[Order]
    trades: list = field(default_factory=list)         # list[Trade]
    watchlist: list = field(default_factory=lambda: list(DEFAULT_WATCHLIST))
    equity_curve: list = field(default_factory=list)   # list[[ts, equity]]
    # --- 期权 (OCC 代码为 key, 和股票持仓分开存) ---
    option_positions: dict = field(default_factory=dict)
    option_orders: list = field(default_factory=list)
    option_trades: list = field(default_factory=list)
    # --- 融资利息 (现金为负 = 借了券商的钱, 按天计息) ---
    interest_ts: float = 0.0           # 上次结息的时间
    interest_paid: float = 0.0         # 累计付过的利息

    # -- 计算 -----------------------------------------------------------
    @property
    def display_name(self) -> str:
        """界面上显示的名字。默认名跟着语言走, 用户自己起的名字原样显示。

        删除/重置时要手打账户名确认 —— 那里显示和校验必须都用这个,
        否则显示的是英文、校验的是中文, 永远确认不了。
        """
        return _tr(self.name) if self.name == DEFAULT_ACCOUNT_NAME else self.name

    def open_positions(self) -> list:
        return [p for p in self.positions.values() if p.qty != 0]

    # -- 期权 -----------------------------------------------------------
    def open_option_positions(self) -> list:
        return [p for p in self.option_positions.values() if p.qty != 0]

    def open_option_orders(self) -> list:
        return [o for o in self.option_orders if o.is_open]

    def options_value(self, prices: dict) -> float:
        """期权持仓市值 (卖方为负)。prices 用 OCC 代码取每股期权价。"""
        total = 0.0
        for p in self.open_option_positions():
            px = prices.get(p.symbol)
            total += p.market_value(px if px is not None else p.avg_cost)
        return total

    def options_unrealized(self, prices: dict) -> float:
        return sum(p.unrealized(prices.get(p.symbol, p.avg_cost))
                   for p in self.open_option_positions())

    def options_realized(self) -> float:
        return sum(getattr(t, "realized_pnl", 0.0) for t in self.option_trades)

    def positions_value(self, prices: dict) -> float:
        total = 0.0
        for p in self.open_positions():
            px = prices.get(p.symbol)
            total += p.market_value(px if px else p.avg_cost)
        return total

    def gross_exposure(self, prices: dict) -> float:
        total = 0.0
        for p in self.open_positions():
            px = prices.get(p.symbol) or p.avg_cost
            total += abs(p.qty * px)
        for p in self.open_option_positions():
            px = prices.get(p.symbol)
            total += abs(p.market_value(px if px is not None else p.avg_cost))
        return total

    def equity(self, prices: dict) -> float:
        return self.cash + self.positions_value(prices) + self.options_value(prices)

    def buying_power(self, prices: dict, option_margin: float = 0.0) -> float:
        if self.account_type == "CASH":
            return max(self.cash - option_margin, 0.0)
        # Reg T 近似: 2 倍净值减去当前总敞口, 再扣掉卖方期权占用的保证金
        base = 2.0 * self.equity(prices) - self.gross_exposure(prices)
        return max(base - option_margin, 0.0)

    def total_return_pct(self, prices: dict) -> float:
        if not self.initial_cash:
            return 0.0
        return (self.equity(prices) - self.initial_cash) / self.initial_cash * 100.0

    def unrealized_total(self, prices: dict) -> float:
        stock = sum(p.unrealized(prices.get(p.symbol) or p.avg_cost)
                    for p in self.open_positions())
        return stock + self.options_unrealized(prices)

    def realized_total(self) -> float:
        return sum(t.realized_pnl for t in self.trades) + self.options_realized()

    def fees_total(self) -> float:
        return (sum(t.commission + t.fees for t in self.trades)
                + sum(getattr(t, "commission", 0.0) + getattr(t, "fees", 0.0)
                      for t in self.option_trades))

    def open_orders(self) -> list:
        return [o for o in self.orders if o.is_open]

    # -- 序列化 ---------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "name": self.name, "id": self.id, "account_type": self.account_type,
            "initial_cash": self.initial_cash, "cash": self.cash,
            "created_at": self.created_at,
            "positions": {k: v.to_dict() for k, v in self.positions.items()},
            "orders": [o.to_dict() for o in self.orders],
            "trades": [t.to_dict() for t in self.trades],
            "watchlist": self.watchlist,
            "equity_curve": self.equity_curve,
            "option_positions": {k: v.to_dict() for k, v in self.option_positions.items()},
            "option_orders": [o.to_dict() for o in self.option_orders],
            "option_trades": [t.to_dict() for t in self.option_trades],
            "interest_ts": self.interest_ts, "interest_paid": self.interest_paid,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Account":
        acc = cls(
            name=d.get("name", DEFAULT_ACCOUNT_NAME),
            id=d.get("id", _uid()),
            account_type=d.get("account_type", "MARGIN"),
            initial_cash=float(d.get("initial_cash", 100000.0)),
            cash=float(d.get("cash", 100000.0)),
            created_at=float(d.get("created_at", time.time())),
            watchlist=list(d.get("watchlist") or DEFAULT_WATCHLIST),
            equity_curve=list(d.get("equity_curve") or []),
            interest_ts=float(d.get("interest_ts") or 0.0),
            interest_paid=float(d.get("interest_paid") or 0.0),
        )
        acc.positions = {k: Position.from_dict(v) for k, v in (d.get("positions") or {}).items()}
        acc.orders = [Order.from_dict(o) for o in (d.get("orders") or [])]
        acc.trades = [Trade.from_dict(t) for t in (d.get("trades") or [])]
        # 期权部分, 老存档里没有这些字段, 缺省为空
        from .options.models import OptionPosition, OptionOrder, OptionTrade
        acc.option_positions = {k: OptionPosition.from_dict(v)
                                for k, v in (d.get("option_positions") or {}).items()}
        acc.option_orders = [OptionOrder.from_dict(o) for o in (d.get("option_orders") or [])]
        acc.option_trades = [OptionTrade.from_dict(t) for t in (d.get("option_trades") or [])]
        return acc
