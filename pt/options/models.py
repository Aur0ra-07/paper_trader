"""期权合约模型与 OCC 代码解析。

OCC 代码格式: 根代码 + YYMMDD + C/P + 行权价×1000 (补足 8 位)
例: AAPL261016C00335000 = AAPL 2026-10-16 到期 335 美元 call
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime

from .pricing import CALL, PUT
from ..i18n import _tr

OCC_RE = re.compile(r"^([A-Z0-9.\-]{1,6}?)(\d{6})([CP])(\d{8})$")

# 方向
BUY_OPEN = "BUY_OPEN"       # 买入开仓 (做多期权)
SELL_CLOSE = "SELL_CLOSE"   # 卖出平仓
SELL_OPEN = "SELL_OPEN"     # 卖出开仓 (做空期权 / 义务方)
BUY_CLOSE = "BUY_CLOSE"     # 买入平仓

OPT_SIDE_CN = {
    BUY_OPEN: _tr("买入开仓"), SELL_CLOSE: _tr("卖出平仓"),
    SELL_OPEN: _tr("卖出开仓"), BUY_CLOSE: _tr("买入平仓"),
}
OPT_OPENING = (BUY_OPEN, SELL_OPEN)
OPT_CLOSING = (SELL_CLOSE, BUY_CLOSE)
OPT_BUY_SIDES = (BUY_OPEN, BUY_CLOSE)      # 花钱的一侧
OPT_SELL_SIDES = (SELL_OPEN, SELL_CLOSE)   # 收钱的一侧

RIGHT_CN = {CALL: _tr("认购 Call"), PUT: _tr("认沽 Put")}


def build_occ(underlying: str, expiry: date, right: str, strike: float) -> str:
    return "{}{}{}{:08d}".format(
        underlying.upper(), expiry.strftime("%y%m%d"), right,
        int(round(strike * 1000)))


def parse_occ(symbol: str) -> tuple:
    """返回 (底层, 到期日, C/P, 行权价); 解析失败返回 (None, None, None, None)。"""
    m = OCC_RE.match((symbol or "").upper().strip())
    if not m:
        return None, None, None, None
    root, ymd, right, strike = m.groups()
    try:
        exp = datetime.strptime(ymd, "%y%m%d").date()
    except ValueError:
        return None, None, None, None
    return root, exp, right, int(strike) / 1000.0


@dataclass
class OptionQuote:
    """期权链里的一行。价格一律来自市场, 不用模型价。"""
    symbol: str
    underlying: str
    right: str
    strike: float
    expiry: date
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    volume: int = 0
    open_interest: int = 0
    iv: float = 0.0              # 市场隐含波动率 (小数)
    in_the_money: bool = False
    multiplier: int = 100

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return self.ask or self.bid or self.last

    @property
    def spread(self) -> float:
        return max(self.ask - self.bid, 0.0)

    @property
    def spread_pct(self) -> float:
        m = self.mid
        return (self.spread / m * 100.0) if m > 0 else 0.0

    @property
    def liquid(self) -> bool:
        """价差过宽或几乎没人交易的合约, 模拟成交也没有意义。"""
        return self.bid > 0 and self.ask > 0 and (
            self.open_interest >= 10 or self.volume >= 10) and self.spread_pct < 60

    def fill_price(self, side: str) -> float:
        """买入吃卖价, 卖出砸买价 —— 期权价差很宽, 这是最大的隐性成本。"""
        if side in OPT_BUY_SIDES:
            return self.ask or self.mid
        return self.bid or self.mid

    def days_left(self, today: date | None = None) -> int:
        return max((self.expiry - (today or date.today())).days, 0)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["expiry"] = self.expiry.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "OptionQuote":
        d = dict(d)
        d["expiry"] = date.fromisoformat(d["expiry"])
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class OptionPosition:
    """期权持仓。qty 单位是**合约张数**, 正=买方(权利), 负=卖方(义务)。"""
    symbol: str
    underlying: str
    right: str
    strike: float
    expiry: str                    # ISO 日期字符串, 方便 JSON 持久化
    qty: int = 0
    avg_cost: float = 0.0          # 每股权利金 (已含佣金分摊)
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    multiplier: int = 100
    opened_at: float = 0.0

    @property
    def expiry_date(self) -> date:
        return date.fromisoformat(self.expiry)

    @property
    def is_short(self) -> bool:
        return self.qty < 0

    @property
    def abs_qty(self) -> int:
        return abs(self.qty)

    @property
    def shares(self) -> int:
        """对应多少股正股。"""
        return self.abs_qty * self.multiplier

    def days_left(self, today: date | None = None) -> int:
        return max((self.expiry_date - (today or date.today())).days, 0)

    def cost_basis(self) -> float:
        return self.abs_qty * self.avg_cost * self.multiplier

    def market_value(self, price: float) -> float:
        """持仓市值 (卖方为负, 代表负债)。price = 每股期权价。"""
        return self.qty * price * self.multiplier

    def unrealized(self, price: float) -> float:
        if self.qty == 0:
            return 0.0
        if self.qty > 0:
            return (price - self.avg_cost) * self.qty * self.multiplier
        return (self.avg_cost - price) * self.abs_qty * self.multiplier

    def unrealized_pct(self, price: float) -> float:
        base = self.cost_basis()
        return (self.unrealized(price) / base * 100.0) if base else 0.0

    def intrinsic_value(self, spot: float) -> float:
        from .pricing import intrinsic
        return intrinsic(spot, self.strike, self.right)

    # -- 记账 (和股票持仓一致的口径: 费用计入成本) ----------------------
    def apply_open(self, qty: int, price: float, cost: float, direction: int) -> None:
        old = self.abs_qty
        old_total = old * self.avg_cost
        per_share_cost = cost / (qty * self.multiplier) if qty else 0.0
        if direction > 0:
            new_total = old_total + qty * (price + per_share_cost)
        else:
            new_total = old_total + qty * (price - per_share_cost)
        new_abs = old + qty
        self.avg_cost = new_total / new_abs if new_abs else 0.0
        self.qty = new_abs * direction
        self.fees_paid += cost
        if old == 0:
            import time as _t
            self.opened_at = _t.time()

    def apply_close(self, qty: int, price: float, cost: float) -> float:
        mult = self.multiplier
        if self.qty > 0:
            pnl = (price * qty * mult - cost) - self.avg_cost * qty * mult
            self.qty -= qty
        else:
            pnl = self.avg_cost * qty * mult - (price * qty * mult + cost)
            self.qty += qty
        self.realized_pnl += pnl
        self.fees_paid += cost
        if self.qty == 0:
            self.avg_cost = 0.0
        return pnl

    def describe(self) -> str:
        return _tr("{} {} {:g} {} ({}张)").format(
            self.underlying, self.expiry, self.strike,
            "Call" if self.right == CALL else "Put", self.qty)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "OptionPosition":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class OptionTrade:
    symbol: str
    underlying: str
    side: str
    qty: int                       # 合约张数
    price: float                   # 每股权利金
    right: str = CALL
    strike: float = 0.0
    expiry: str = ""
    commission: float = 0.0
    fees: float = 0.0
    realized_pnl: float = 0.0
    ts: float = 0.0
    order_id: str = ""
    id: str = ""
    multiplier: int = 100
    note: str = ""                 # 到期行权/作废等会写在这里

    def __post_init__(self):
        import time as _t, uuid
        if not self.id:
            self.id = uuid.uuid4().hex[:10]
        if not self.ts:
            self.ts = _t.time()

    @property
    def notional(self) -> float:
        return self.qty * self.price * self.multiplier

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "OptionTrade":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class OptionOrder:
    symbol: str
    side: str
    qty: int                       # 合约张数, 正数
    underlying: str = ""
    right: str = CALL
    strike: float = 0.0
    expiry: str = ""
    order_type: str = "MARKET"     # MARKET | LIMIT
    limit_price: float = 0.0       # 每股权利金
    id: str = ""
    status: str = "PENDING"
    created_at: float = 0.0
    updated_at: float = 0.0
    fill_price: float = 0.0
    commission: float = 0.0
    realized_pnl: float = 0.0
    note: str = ""
    multiplier: int = 100

    def __post_init__(self):
        import time as _t
        import uuid
        if not self.id:
            self.id = uuid.uuid4().hex[:10]
        if not self.created_at:
            self.created_at = _t.time()
        if not self.updated_at:
            self.updated_at = self.created_at
        if not self.underlying or not self.expiry:
            u, e, r, k = parse_occ(self.symbol)
            if u:
                self.underlying = self.underlying or u
                self.expiry = self.expiry or e.isoformat()
                self.right = r
                self.strike = self.strike or k

    @property
    def is_open(self) -> bool:
        return self.status == "PENDING"

    def describe(self) -> str:
        bits = [OPT_SIDE_CN.get(self.side, self.side),
                "{} {:g}{}".format(self.expiry, self.strike,
                                   "C" if self.right == CALL else "P"),
                _tr("{} 张").format(self.qty)]
        if self.order_type == "LIMIT":
            bits.append(_tr("限价 {:.2f}").format(self.limit_price))
        return " ".join(bits)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "OptionOrder":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})
