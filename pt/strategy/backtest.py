"""事件驱动回测引擎。

两条铁律:
1. **不许有未来函数** —— 信号在第 i 根收盘算出, 第 i+1 根开盘成交。
2. **成本必须和实盘一致** —— 佣金、规费、滑点全部复用 config.Settings,
   回测里赚的钱和模拟盘里赚的钱是同一个口径。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..config import Settings
from .library import Strategy
from ..i18n import _tr

# 各周期一年有多少根 K 线 (年化用)
BARS_PER_YEAR = {
    "1m": 252 * 390, "5m": 252 * 78, "15m": 252 * 26,
    "60m": 252 * 7, "1d": 252, "1wk": 52,
}

LONG, FLAT, SHORT = 1, 0, -1


@dataclass
class BTTrade:
    symbol: str
    direction: int
    qty: int
    entry_ts: int
    entry_price: float
    exit_ts: int = 0
    exit_price: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    costs: float = 0.0
    bars_held: int = 0
    exit_reason: str = _tr("信号")

    @property
    def is_win(self) -> bool:
        return self.pnl > 0


@dataclass
class BacktestConfig:
    initial_cash: float = 100000.0
    position_pct: float = 95.0      # 每次投入净值的百分比
    stop_loss_pct: float = 0.0      # 0 = 不启用
    take_profit_pct: float = 0.0
    interval: str = "1d"
    leverage: float = 1.0           # 1.0=不融资, 2.0=两倍保证金 (要付利息)


@dataclass
class BacktestResult:
    symbol: str
    strategy_key: str
    strategy_label: str
    params: dict = field(default_factory=dict)
    equity: list = field(default_factory=list)          # [(ts, value)]
    benchmark: list = field(default_factory=list)       # 买入持有基准
    trades: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.equity)


# ======================================================================
def _round_trip_costs(settings: Settings, qty: int, price: float, is_sell: bool) -> float:
    notional = qty * price
    c = settings.commission(qty, notional)
    if is_sell:
        c += settings.sell_fees(qty, notional)
    return c


def _fill_price(settings: Settings, price: float, is_buy: bool) -> float:
    slip = settings.slippage_bps / 10000.0
    return price * (1 + slip) if is_buy else price * (1 - slip)


def run(candles: list, strategy: Strategy, settings: Settings,
        cfg: BacktestConfig, symbol: str = "") -> BacktestResult:
    res = BacktestResult(symbol=symbol, strategy_key=strategy.key,
                         strategy_label=strategy.label(), params=dict(strategy.p))
    n = len(candles)
    warm = max(strategy.warmup(), 1)
    if n < warm + 5:
        res.error = _tr("K 线只有 {} 根, 该策略至少需要 {} 根").format(n, warm + 5)
        return res

    strategy.prepare(candles)

    cash = cfg.initial_cash
    qty = 0                      # 带符号
    entry_price = 0.0
    entry_ts = 0
    entry_i = 0
    total_costs = 0.0
    margin_calls = 0
    pending = None               # 下一根开盘要切换到的方向

    def close_position(i: int, price: float, reason: str) -> None:
        nonlocal cash, qty, total_costs
        bar = candles[i]
        is_buy = qty < 0                     # 平空 = 买回
        fp = _fill_price(settings, price, is_buy)
        aq = abs(qty)
        cost = _round_trip_costs(settings, aq, fp, is_sell=not is_buy)
        if qty > 0:
            cash += aq * fp - cost
            pnl = (fp - entry_price) * aq - cost
        else:
            cash -= aq * fp + cost
            pnl = (entry_price - fp) * aq - cost
        total_costs += cost
        base = entry_price * aq
        res.trades.append(BTTrade(
            symbol=symbol, direction=1 if qty > 0 else -1, qty=aq,
            entry_ts=entry_ts, entry_price=entry_price,
            exit_ts=bar.ts, exit_price=fp, pnl=pnl,
            pnl_pct=(pnl / base * 100.0) if base else 0.0,
            costs=cost, bars_held=i - entry_i, exit_reason=reason))
        qty = 0

    def open_position(i: int, price: float, direction: int) -> None:
        nonlocal cash, qty, entry_price, entry_ts, entry_i, total_costs
        bar = candles[i]
        is_buy = direction > 0
        fp = _fill_price(settings, price, is_buy)
        if fp <= 0:
            return
        # 平仓状态下 净值 == 现金; 上杠杆就是按净值的倍数买, 现金可以变负(=融资)
        equity_now = max(cash, 0.0)
        lev = max(cfg.leverage, 1.0)
        budget = equity_now * (cfg.position_pct / 100.0) * lev
        size = int(budget // fp)
        if size < 1:
            return
        cost = _round_trip_costs(settings, size, fp, is_sell=not is_buy)
        if is_buy:
            max_notional = equity_now * lev - cost
            if size * fp > max_notional:
                size = int(max_notional // fp)
                if size < 1:
                    return
                cost = _round_trip_costs(settings, size, fp, is_sell=False)
            cash -= size * fp + cost
        else:
            cash += size * fp - cost
        total_costs += cost
        qty = size * direction
        entry_price = fp
        entry_ts = bar.ts
        entry_i = i

    # ------------------------------------------------------------------
    for i in range(n):
        bar = candles[i]

        # 1) 执行上一根收盘发出的信号 (本根开盘价成交)
        if pending is not None:
            if qty != 0 and (pending == FLAT or (pending > 0) != (qty > 0)):
                close_position(i, bar.open, _tr("信号"))
            if pending != FLAT and qty == 0:
                open_position(i, bar.open, pending)
            pending = None

        # 2) 盘中止损 / 止盈 (保守起见, 同根内先判止损)
        if qty != 0 and (cfg.stop_loss_pct > 0 or cfg.take_profit_pct > 0):
            sl, tp = cfg.stop_loss_pct / 100.0, cfg.take_profit_pct / 100.0
            if qty > 0:
                if sl > 0 and bar.low <= entry_price * (1 - sl):
                    close_position(i, entry_price * (1 - sl), _tr("止损"))
                elif tp > 0 and bar.high >= entry_price * (1 + tp):
                    close_position(i, entry_price * (1 + tp), _tr("止盈"))
            else:
                if sl > 0 and bar.high >= entry_price * (1 + sl):
                    close_position(i, entry_price * (1 + sl), _tr("止损"))
                elif tp > 0 and bar.low <= entry_price * (1 - tp):
                    close_position(i, entry_price * (1 - tp), _tr("止盈"))

        # 3) 融资利息 (现金为负 = 借了钱)
        if cash < 0 and settings.margin_rate_annual > 0:
            per_bar = settings.margin_rate_annual / BARS_PER_YEAR.get(cfg.interval, 252)
            interest = -cash * per_bar
            cash -= interest
            total_costs += interest

        # 3b) 追加保证金通知 -> 强制平仓。真实券商不会让你的净值跌成负数,
        #     它会在维持保证金被击穿时直接把你的仓位卖掉。
        if qty != 0 and cfg.leverage > 1.0 and settings.maintenance_margin > 0:
            equity_now = cash + qty * bar.close
            exposure = abs(qty * bar.close)
            if exposure > 0 and equity_now < exposure * settings.maintenance_margin:
                close_position(i, bar.low if qty > 0 else bar.high, _tr("强制平仓(追保)"))
                margin_calls += 1

        res.equity.append((bar.ts, cash + qty * bar.close))

        # 4) 收盘计算下一根的目标方向
        if warm <= i < n - 1:
            try:
                tgt = strategy.target(i)
            except Exception as exc:
                res.error = _tr("策略运行出错 (第 {} 根): {}").format(i, exc)
                return res
            cur = FLAT if qty == 0 else (LONG if qty > 0 else SHORT)
            if tgt != cur:
                pending = tgt

    # 收尾: 最后一根按收盘价平掉, 让净值可比
    if qty != 0:
        close_position(n - 1, candles[-1].close, _tr("回测结束"))
        res.equity[-1] = (candles[-1].ts, cash)

    # 基准与策略同一根起跑 (策略要等预热 + 延迟一根才能建仓), 否则 alpha 不公平
    res.benchmark = _buy_hold_curve(candles, settings, cfg, start=min(warm + 1, n - 1))
    res.metrics = _metrics(res, cfg, total_costs)
    res.metrics["margin_calls"] = margin_calls
    return res


# ----------------------------------------------------------------------
def _buy_hold_curve(candles: list, settings: Settings, cfg: BacktestConfig,
                    start: int = 0) -> list:
    """同样扣佣金滑点的买入持有基准, 从第 start 根开盘建仓。"""
    start = max(0, min(start, len(candles) - 1))
    fp = _fill_price(settings, candles[start].open, True)
    if fp <= 0:
        return [(c.ts, cfg.initial_cash) for c in candles]
    size = int(cfg.initial_cash // fp)
    cost = _round_trip_costs(settings, size, fp, False) if size else 0.0
    cash = cfg.initial_cash - size * fp - cost
    return [(c.ts, cfg.initial_cash if i < start else cash + size * c.close)
            for i, c in enumerate(candles)]


def _metrics(res: BacktestResult, cfg: BacktestConfig, total_costs: float) -> dict:
    eq = [v for _, v in res.equity]
    if not eq:
        return {}
    start, end = cfg.initial_cash, eq[-1]
    total_return = (end / start - 1.0) * 100.0 if start else 0.0

    bpy = BARS_PER_YEAR.get(cfg.interval, 252)
    years = max(len(eq) / bpy, 1e-9)
    cagr = ((end / start) ** (1 / years) - 1.0) * 100.0 if start > 0 and end > 0 else -100.0

    rets = [(eq[i] / eq[i - 1] - 1.0) for i in range(1, len(eq)) if eq[i - 1] > 0]
    sharpe = sortino = 0.0
    if len(rets) > 2:
        mu = sum(rets) / len(rets)
        var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
        sd = math.sqrt(var)
        if sd > 0:
            sharpe = mu / sd * math.sqrt(bpy)
        downs = [r for r in rets if r < 0]
        if downs:
            dsd = math.sqrt(sum(r * r for r in downs) / len(downs))
            if dsd > 0:
                sortino = mu / dsd * math.sqrt(bpy)

    peak, mdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak * 100.0)

    trades = res.trades
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    gross_win = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))

    bench_ret = 0.0
    if res.benchmark:
        b0, b1 = cfg.initial_cash, res.benchmark[-1][1]
        bench_ret = (b1 / b0 - 1.0) * 100.0 if b0 else 0.0

    bars_in = sum(t.bars_held for t in trades)
    return {
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": mdd,
        "calmar": (cagr / mdd) if mdd > 0.01 else 0.0,
        "n_trades": len(trades),
        "win_rate": (len(wins) / len(trades) * 100.0) if trades else 0.0,
        "avg_win": (gross_win / len(wins)) if wins else 0.0,
        "avg_loss": (-gross_loss / len(losses)) if losses else 0.0,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else (
            float("inf") if gross_win > 0 else 0.0),
        "exposure": (bars_in / len(eq) * 100.0) if eq else 0.0,
        "total_costs": total_costs,
        "final_equity": end,
        "benchmark_return": bench_ret,
        "alpha": total_return - bench_ret,
        "bars": len(eq),
        "years": years,
    }


# ======================================================================
def rolling_windows(equity: list, bars: int) -> dict:
    """任意时点入场、持有 bars 根 K 线的收益分布。

    这是回答"几个月能赚多少"唯一诚实的方式: 不是给一个数字, 是给一个分布 ——
    最好的一段、最差的一段、中位数, 以及有多少比例的入场时点是赚钱的。
    """
    if len(equity) <= bars + 1 or bars < 2:
        return {}
    rets = []
    for i in range(len(equity) - bars):
        a = equity[i][1]
        b = equity[i + bars][1]
        if a > 0:
            rets.append((b / a - 1.0) * 100.0)
    if not rets:
        return {}
    rets.sort()
    n = len(rets)

    def q(p):
        return rets[min(int(n * p), n - 1)]

    return {
        "n": n,
        "bars": bars,
        "worst": rets[0],
        "p10": q(0.10),
        "p25": q(0.25),
        "median": q(0.50),
        "p75": q(0.75),
        "p90": q(0.90),
        "best": rets[-1],
        "mean": sum(rets) / n,
        "win_rate": sum(1 for r in rets if r > 0) / n * 100.0,
        "loss_20_rate": sum(1 for r in rets if r <= -20) / n * 100.0,
        "gain_50_rate": sum(1 for r in rets if r >= 50) / n * 100.0,
    }


WINDOW_PRESETS = [(_tr("1 个月"), 21), (_tr("3 个月"), 63), (_tr("6 个月"), 126), (_tr("1 年"), 252)]


def run_portfolio(data: dict, strategy_key: str, params: dict, settings: Settings,
                  cfg: BacktestConfig) -> tuple:
    """一篮子标的等权回测。

    data: {symbol: candles}
    返回 (组合结果, {symbol: 单只结果})
    """
    from .library import create

    symbols = [s for s, c in data.items() if c]
    if not symbols:
        return BacktestResult(_tr("组合"), strategy_key, "", error=_tr("没有可用数据")), {}

    per_cfg = BacktestConfig(
        initial_cash=cfg.initial_cash / len(symbols),
        position_pct=cfg.position_pct,
        stop_loss_pct=cfg.stop_loss_pct,
        take_profit_pct=cfg.take_profit_pct,
        interval=cfg.interval,
        leverage=cfg.leverage)

    singles = {}
    for sym in symbols:
        singles[sym] = run(data[sym], create(strategy_key, **params), settings, per_cfg, sym)

    good = [r for r in singles.values() if r.ok]
    if not good:
        first_err = next((r.error for r in singles.values() if r.error), _tr("全部标的回测失败"))
        return BacktestResult(_tr("组合"), strategy_key, "", error=first_err), singles

    # 按时间戳并集对齐, 缺失用前值填充
    all_ts = sorted({ts for r in good for ts, _ in r.equity})
    curves = []
    for r in good:
        m = dict(r.equity)
        series, last = [], per_cfg.initial_cash
        for ts in all_ts:
            last = m.get(ts, last)
            series.append(last)
        curves.append(series)

    combo = BacktestResult(_tr("组合 ({} 只)").format(len(good)), strategy_key,
                           good[0].strategy_label, params=dict(params))
    combo.equity = [(ts, sum(c[i] for c in curves)) for i, ts in enumerate(all_ts)]

    bench_curves = []
    for r in good:
        m = dict(r.benchmark)
        series, last = [], per_cfg.initial_cash
        for ts in all_ts:
            last = m.get(ts, last)
            series.append(last)
        bench_curves.append(series)
    combo.benchmark = [(ts, sum(c[i] for c in bench_curves)) for i, ts in enumerate(all_ts)]

    combo.trades = [t for r in good for t in r.trades]
    combo.trades.sort(key=lambda t: t.entry_ts)
    total_costs = sum(r.metrics.get("total_costs", 0.0) for r in good)
    # 失败的标的不计入本金, 否则收益率会被摊薄
    combo_cfg = BacktestConfig(
        initial_cash=per_cfg.initial_cash * len(good),
        position_pct=cfg.position_pct, stop_loss_pct=cfg.stop_loss_pct,
        take_profit_pct=cfg.take_profit_pct, interval=cfg.interval,
        leverage=cfg.leverage)
    combo.metrics = _metrics(combo, combo_cfg, total_costs)
    return combo, singles
