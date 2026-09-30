"""横截面动量轮动 (Cross-sectional Momentum)。

和前面那些策略的根本区别:

  择时策略问的是 "这只股票现在该不该买?"  —— 牛市里它只会让你少赚
  轮动策略问的是 "这一篮子里哪几只最强?"  —— 它永远满仓, 只是换马

外加一个**绝对动量**开关 (Antonacci 的双动量): 当所有标的动量都为负时退到现金,
这是熊市保命的部分。基准是"等权买入并持有整个篮子", 这才是公平的对照。

同样遵守回测铁律: 第 i 根收盘排名, 第 i+1 根开盘调仓; 成本用同一套 Settings。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import Settings
from . import backtest as bt
from . import indicators as ind
from ..i18n import _tr


@dataclass
class RotationConfig:
    lookback: int = 120          # 动量回看根数 (日线 120 ≈ 半年)
    lookback2: int = 0           # 第二个回看窗口, 0 = 不用; 两个窗口取平均更稳
    skip_recent: int = 0         # 跳过最近 N 根 (短期反转效应)
    top_k: int = 3               # 持有最强的几只
    rebalance_bars: int = 21     # 多少根换一次仓 (日线 21 ≈ 每月)
    abs_momentum: bool = True    # 动量为负就空仓 (熊市保命)
    trend_ma: int = 0            # >0 时要求价格在该均线之上
    initial_cash: float = 100000.0
    position_pct: float = 98.0
    interval: str = "1d"
    leverage: float = 1.0        # >1 = 融资加杠杆, 按 settings.margin_rate_annual 计息


@dataclass
class RotationResult:
    equity: list = field(default_factory=list)
    benchmark: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    holdings: list = field(default_factory=list)     # [(ts, [symbols])]
    metrics: dict = field(default_factory=dict)
    symbols: list = field(default_factory=list)
    error: str = ""
    strategy_label: str = ""
    symbol: str = _tr("轮动组合")
    strategy_key: str = "rotation"
    params: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.equity)


# ----------------------------------------------------------------------
def _align(data: dict) -> tuple:
    """把多个标的对齐到统一时间轴。缺失的位置用前值填充, 上市前为 None。"""
    timeline = sorted({c.ts for cs in data.values() for c in cs})
    idx = {ts: i for i, ts in enumerate(timeline)}
    n = len(timeline)
    closes, opens = {}, {}
    for sym, cs in data.items():
        cl = [None] * n
        op = [None] * n
        for c in cs:
            j = idx[c.ts]
            cl[j] = c.close
            op[j] = c.open
        last = None
        for j in range(n):                 # 前值填充 (停牌/时间轴不齐)
            if cl[j] is None:
                cl[j] = last
                op[j] = last
            else:
                last = cl[j]
        closes[sym] = cl
        opens[sym] = op
    return timeline, closes, opens


def score_one(closes: list, i: int, cfg: RotationConfig,
              ma: list | None = None):
    """单个标的在第 i 根上的动量分。返回 None 表示它这一轮不参选。

    回测(`run`)和实盘(`live_picks`)都调这个函数, 保证选股规则只有一份。
    只用到 `<= i` 的数据, 没有未来函数。
    """
    end = i - cfg.skip_recent
    start = end - cfg.lookback
    if start < 0 or end < 0 or end >= len(closes):
        return None
    a, b = closes[start], closes[end]
    if not a or not b:
        return None
    m = b / a - 1.0
    if cfg.lookback2 > 0:
        start2 = end - cfg.lookback2
        if start2 >= 0 and closes[start2]:
            m = (m + (b / closes[start2] - 1.0)) / 2.0
    if cfg.abs_momentum and m <= 0:
        return None
    if cfg.trend_ma >= 2:
        if ma is None or i >= len(ma):
            return None
        mv, px = ma[i], closes[i]
        if mv is None or not px or px <= mv:
            return None
    return m


def live_picks(candles_by_symbol: dict, cfg: RotationConfig,
               idx_by_symbol: dict | None = None) -> tuple:
    """按**当前已收盘**的数据算出此刻该持有哪几只。

    给自动交易用。`idx_by_symbol` 指定每个标的用第几根当信号根 (默认最后一根),
    调用方必须传**已收盘**那根的下标, 不能传盘中还在变的那根。

    返回 (选中的代码列表, {代码: 动量分})。选中为空表示绝对动量全为负 —— 该空仓。
    """
    scored = []
    for s, candles in candles_by_symbol.items():
        if not candles or len(candles) <= 30:
            continue
        i = (idx_by_symbol or {}).get(s, len(candles) - 1)
        if i < 0 or i >= len(candles):
            continue
        closes = [c.close for c in candles]
        ma = ind.sma(closes, cfg.trend_ma) if cfg.trend_ma >= 2 else None
        m = score_one(closes, i, cfg, ma)
        if m is not None:
            scored.append((m, s))
    scored.sort(reverse=True)
    return [s for _, s in scored[:cfg.top_k]], {s: m for m, s in scored}


def run(data: dict, settings: Settings, cfg: RotationConfig) -> RotationResult:
    symbols = [s for s, c in data.items() if c and len(c) > 30]
    res = RotationResult(symbols=symbols, params={
        "lookback": cfg.lookback, "lookback2": cfg.lookback2,
        "skip_recent": cfg.skip_recent, "top_k": cfg.top_k,
        "rebalance_bars": cfg.rebalance_bars, "abs_momentum": cfg.abs_momentum,
        "trend_ma": cfg.trend_ma})
    if len(symbols) < 2:
        res.error = _tr("轮动至少需要 2 个标的")
        return res

    timeline, closes, opens = _align({s: data[s] for s in symbols})
    n = len(timeline)
    warm = cfg.lookback + cfg.skip_recent + max(cfg.trend_ma, 0) + 2
    if n < warm + 40:
        res.error = _tr("K 线只有 {} 根, 这套参数至少需要 {} 根").format(n, warm + 40)
        return res

    mas = {}
    if cfg.trend_ma >= 2:
        for s in symbols:
            series = [c if c is not None else 0.0 for c in closes[s]]
            mas[s] = ind.sma(series, cfg.trend_ma)

    res.strategy_label = _tr("动量轮动 (回看{}根, 持有前{}名, 每{}根调仓{}{})").format(
        cfg.lookback, cfg.top_k, cfg.rebalance_bars,
        _tr(", 绝对动量") if cfg.abs_momentum else "",
        _tr(", MA{}过滤").format(cfg.trend_ma) if cfg.trend_ma >= 2 else "")

    cash = cfg.initial_cash
    holdings: dict = {}              # symbol -> qty
    entry: dict = {}                 # symbol -> (price, ts, bar_index)
    total_costs = 0.0
    margin_calls = 0
    pending: list | None = None

    def value_at(i: int) -> float:
        v = cash
        for s, q in holdings.items():
            px = closes[s][i]
            if px:
                v += q * px
        return v

    def pick(i: int) -> list:
        # 与实盘的 live_picks() 共用 score_one(), 两边规则不会走偏
        scored = [(m, s) for m, s in
                  ((score_one(closes[s], i, cfg, mas.get(s)), s) for s in symbols)
                  if m is not None]
        scored.sort(reverse=True)
        return [s for _, s in scored[:cfg.top_k]]

    def sell(s: str, i: int, reason: str) -> None:
        nonlocal cash, total_costs
        q = holdings.pop(s, 0)
        if q <= 0:
            return
        px = opens[s][i] or closes[s][i]
        if not px:
            holdings[s] = q
            return
        fp = bt._fill_price(settings, px, False)
        cost = bt._round_trip_costs(settings, q, fp, True)
        cash += q * fp - cost
        total_costs += cost
        ep, ets, ei = entry.pop(s, (fp, timeline[i], i))
        pnl = (fp - ep) * q - cost
        res.trades.append(bt.BTTrade(
            symbol=s, direction=1, qty=q, entry_ts=ets, entry_price=ep,
            exit_ts=timeline[i], exit_price=fp, pnl=pnl,
            pnl_pct=(pnl / (ep * q) * 100.0) if ep * q else 0.0,
            costs=cost, bars_held=i - ei, exit_reason=reason))

    def buy(s: str, i: int, budget: float) -> None:
        nonlocal cash, total_costs
        px = opens[s][i] or closes[s][i]
        if not px or budget <= 0:
            return
        fp = bt._fill_price(settings, px, True)
        lev = max(cfg.leverage, 1.0)
        # 杠杆 1 时不许透支; 杠杆 >1 时现金可以变负(融资)
        room = budget if lev > 1.0 else min(budget, cash)
        q = int(room // fp)
        if q < 1:
            return
        cost = bt._round_trip_costs(settings, q, fp, False)
        if lev <= 1.0 and q * fp + cost > cash:
            q = int((cash - cost) // fp)
            if q < 1:
                return
            cost = bt._round_trip_costs(settings, q, fp, False)
        cash -= q * fp + cost
        total_costs += cost
        holdings[s] = holdings.get(s, 0) + q
        entry[s] = (fp, timeline[i], i)

    # ------------------------------------------------------------------
    for i in range(n):
        if pending is not None:
            target = pending
            pending = None
            for s in list(holdings):
                if s not in target:
                    sell(s, i, _tr("轮出"))
            if target:
                equity_now = value_at(i)
                lev = max(cfg.leverage, 1.0)
                budget = equity_now * (cfg.position_pct / 100.0) * lev / len(target)
                for s in target:
                    if s in holdings:
                        continue
                    buy(s, i, budget)
            res.holdings.append((timeline[i], sorted(holdings)))

        if cash < 0 and settings.margin_rate_annual > 0:
            per_bar = settings.margin_rate_annual / bt.BARS_PER_YEAR.get(cfg.interval, 252)
            interest = -cash * per_bar
            cash -= interest
            total_costs += interest

        # 追保强平: 净值击穿维持保证金就被券商全部卖掉
        if holdings and cfg.leverage > 1.0 and settings.maintenance_margin > 0:
            eq_now = value_at(i)
            exposure = sum(abs(q * (closes[s2][i] or 0)) for s2, q in holdings.items())
            if exposure > 0 and eq_now < exposure * settings.maintenance_margin:
                for s2 in list(holdings):
                    sell(s2, i, _tr("强制平仓(追保)"))
                margin_calls += 1

        res.equity.append((timeline[i], value_at(i)))

        if warm <= i < n - 1 and (i - warm) % cfg.rebalance_bars == 0:
            target = pick(i)
            if set(target) != set(holdings):
                pending = target

    for s in list(holdings):
        sell(s, n - 1, _tr("回测结束"))
    if res.equity:
        res.equity[-1] = (timeline[-1], cash)

    res.benchmark = _equal_weight_benchmark(symbols, timeline, closes, opens,
                                            settings, cfg, start=min(warm + 1, n - 1))
    shim = bt.BacktestResult(symbol=res.symbol, strategy_key="rotation",
                             strategy_label=res.strategy_label)
    shim.equity = res.equity
    shim.benchmark = res.benchmark
    shim.trades = res.trades
    bcfg = bt.BacktestConfig(initial_cash=cfg.initial_cash,
                             position_pct=cfg.position_pct, interval=cfg.interval,
                             leverage=cfg.leverage)
    res.metrics = bt._metrics(shim, bcfg, total_costs)
    res.metrics["rebalances"] = len(res.holdings)
    res.metrics["margin_calls"] = margin_calls
    return res


def _equal_weight_benchmark(symbols, timeline, closes, opens, settings,
                            cfg: RotationConfig, start: int) -> list:
    """等权买入并持有整个篮子 —— 轮动策略唯一公平的对照。"""
    n = len(timeline)
    start = max(0, min(start, n - 1))
    per = cfg.initial_cash / len(symbols)
    cash = cfg.initial_cash
    qty = {}
    for s in symbols:
        px = opens[s][start] or closes[s][start]
        if not px:
            continue
        fp = bt._fill_price(settings, px, True)
        q = int(per // fp)
        if q < 1:
            continue
        cost = bt._round_trip_costs(settings, q, fp, False)
        if q * fp + cost > cash:
            continue
        cash -= q * fp + cost
        qty[s] = q

    out = []
    for i, ts in enumerate(timeline):
        if i < start:
            out.append((ts, cfg.initial_cash))
            continue
        v = cash
        for s, q in qty.items():
            px = closes[s][i]
            if px:
                v += q * px
        out.append((ts, v))
    return out
