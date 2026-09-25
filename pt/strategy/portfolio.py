"""组合引擎: 把多个收益来源(资产/策略/轮动)按权重拼成一个组合。

核心想法 —— 金融里唯一免费的午餐是**分散**:
两个各自夏普 0.6、相关性 0.2 的收益流, 等权组合后夏普能到 0.8 左右, 回撤还更小。
所以"低风险高收益"的正确做法不是去找一个神策略, 而是:

  1. 找几个**相关性低**的收益来源
  2. 按风险(不是按钱)分配权重
  3. 定期再平衡 —— 这本身就产生超额收益
  4. 如果组合的夏普够高, 再用**杠杆**把收益抬到你想要的水平

第 4 步是关键: 提高收益应该靠给"好组合"加杠杆, 而不是靠买更疯的标的。

实现上用收益率序列做组合模拟, 这样再平衡、权重漂移、杠杆、波动率目标都能正确处理。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..config import Settings
from . import backtest as bt
from . import rotation
from .backtest import BacktestConfig
from .library import create
from .rotation import RotationConfig

ASSET = "asset"          # 单一标的买入持有
STRATEGY = "strategy"    # 在某个标的上跑择时策略
ROTATION = "rotation"    # 在一篮子里做动量轮动
CASH = "cash"            # 现金 (按无风险利率计息)


@dataclass
class Sleeve:
    """组合里的一个"收益来源"。"""
    name: str
    kind: str = ASSET
    symbols: list = field(default_factory=list)
    weight: float = 1.0
    strategy_key: str = "buy_hold"
    params: dict = field(default_factory=dict)
    rotation: dict = field(default_factory=dict)

    def describe(self) -> str:
        if self.kind == CASH:
            return "现金"
        if self.kind == ASSET:
            return "买入持有 " + ", ".join(self.symbols[:4])
        if self.kind == ROTATION:
            return "动量轮动 ({} 只)".format(len(self.symbols))
        return "{} @ {}".format(self.strategy_key, ", ".join(self.symbols[:3]))


@dataclass
class MixConfig:
    initial_cash: float = 100000.0
    rebalance_bars: int = 63          # 组合内部再平衡间隔 (日线 63 ≈ 每季度)
    leverage: float = 1.0
    vol_target: float = 0.0           # >0 时按年化波动率目标动态调整总仓位
    vol_lookback: int = 60
    max_leverage: float = 3.0
    interval: str = "1d"
    rebalance_cost_bps: float = 5.0   # 每次再平衡按换手收取的成本(基点)
    cash_rate: float = 0.04           # 现金/闲置资金的年化利率


@dataclass
class MixResult:
    equity: list = field(default_factory=list)
    benchmark: list = field(default_factory=list)
    sleeve_curves: dict = field(default_factory=dict)     # name -> [(ts, value)]
    sleeve_metrics: dict = field(default_factory=dict)    # name -> metrics
    correlation: dict = field(default_factory=dict)       # (a,b) -> corr
    weights_used: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    exposure_curve: list = field(default_factory=list)    # 波动率目标下的实际仓位
    error: str = ""
    label: str = ""
    symbol: str = "组合"
    strategy_key: str = "mix"
    strategy_label: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.equity)


# ======================================================================
def build_sleeve_curve(sleeve: Sleeve, data: dict, settings: Settings,
                       cfg: MixConfig) -> list:
    """算出单个 sleeve 的净值曲线 (起点统一为 1.0 的相对净值)。"""
    base = BacktestConfig(initial_cash=100000.0, position_pct=98.0,
                          interval=cfg.interval)
    if sleeve.kind == CASH:
        return []            # 现金单独处理

    have = {s: data[s] for s in sleeve.symbols if data.get(s)}
    if not have:
        return []

    if sleeve.kind == ROTATION:
        rc = RotationConfig(interval=cfg.interval, initial_cash=100000.0,
                            position_pct=98.0, **(sleeve.rotation or {}))
        r = rotation.run(have, settings, rc)
        return r.equity if r.ok else []

    if sleeve.kind == ASSET or sleeve.strategy_key == "buy_hold":
        key, params = "buy_hold", {}
    else:
        key, params = sleeve.strategy_key, sleeve.params

    if len(have) == 1:
        sym = next(iter(have))
        r = bt.run(have[sym], create(key, **params), settings, base, sym)
        return r.equity if r.ok else []

    combo, _ = bt.run_portfolio(have, key, params, settings, base)
    return combo.equity if combo.ok else []


def _to_returns(curve: list) -> dict:
    """净值曲线 -> {ts: 收益率}。"""
    out = {}
    for i in range(1, len(curve)):
        prev = curve[i - 1][1]
        if prev > 0:
            out[curve[i][0]] = curve[i][1] / prev - 1.0
    return out


def _corr(a: list, b: list) -> float:
    n = min(len(a), len(b))
    if n < 20:
        return 0.0
    a, b = a[:n], b[:n]
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va <= 0 or vb <= 0:
        return 0.0
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    return cov / math.sqrt(va * vb)


def run_mix(sleeves: list, data: dict, settings: Settings,
            cfg: MixConfig, benchmark_symbol: str = "SPY") -> MixResult:
    res = MixResult()
    active = [s for s in sleeves if s.weight > 0]
    if not active:
        res.error = "没有权重大于 0 的组成部分"
        return res

    curves, rets = {}, {}
    for s in active:
        if s.kind == CASH:
            curves[s.name] = []
            continue
        c = build_sleeve_curve(s, data, settings, cfg)
        if len(c) < 60:
            res.error = "「{}」这一块没跑出足够长的净值 (只有 {} 根)".format(s.name, len(c))
            return res
        curves[s.name] = c
        rets[s.name] = _to_returns(c)

    if not rets:
        res.error = "组合里至少要有一个非现金的部分"
        return res

    # 统一时间轴: 取所有非现金部分的交集, 保证每天都有完整数据
    timeline = None
    for r in rets.values():
        ks = set(r)
        timeline = ks if timeline is None else (timeline & ks)
    timeline = sorted(timeline or [])
    if len(timeline) < 60:
        res.error = "各部分的历史重叠只有 {} 根 K 线, 太短了 (换更短的区间或去掉上市晚的标的)".format(
            len(timeline))
        return res

    bpy = bt.BARS_PER_YEAR.get(cfg.interval, 252)
    cash_per_bar = cfg.cash_rate / bpy

    names = [s.name for s in active]
    total_w = sum(s.weight for s in active)
    target = {s.name: s.weight / total_w for s in active}
    res.weights_used = dict(target)

    # 组合模拟: 权重会随涨跌漂移, 到再平衡日拉回目标
    wts = dict(target)
    value = cfg.initial_cash
    equity = [(timeline[0], value)]
    exposure_curve = []
    port_rets: list = []
    lev = max(cfg.leverage, 0.1)
    turnover_total = 0.0
    rebalances = 0

    for i, ts in enumerate(timeline[1:], start=1):
        step = 0.0
        for s in active:
            r = cash_per_bar if s.kind == CASH else rets[s.name].get(ts, 0.0)
            step += wts[s.name] * r

        # 波动率目标: 用最近的组合波动率反推该上多少仓
        expo = lev
        if cfg.vol_target > 0 and len(port_rets) >= cfg.vol_lookback:
            window = port_rets[-cfg.vol_lookback:]
            m = sum(window) / len(window)
            var = sum((x - m) ** 2 for x in window) / (len(window) - 1)
            rv = math.sqrt(max(var, 1e-12)) * math.sqrt(bpy)
            if rv > 1e-6:
                # leverage 作为倍数叠在波动率目标之上, 而不是被它覆盖 —— 这样
                # "先把夏普做高, 再整体放大" 这条路才表达得出来。lev=1.0 时行为不变。
                expo = min(lev * cfg.vol_target / rv, cfg.max_leverage)
        exposure_curve.append((ts, expo))

        # 杠杆部分要付融资利息
        financed = max(expo - 1.0, 0.0)
        net = step * expo - financed * (settings.margin_rate_annual / bpy)
        if expo < 1.0:
            net += (1.0 - expo) * cash_per_bar     # 没上满的部分吃利息

        port_rets.append(step)
        value *= (1.0 + net)
        if value <= 0:
            value = 0.0
            equity.append((ts, 0.0))
            break

        # 权重漂移
        denom = 1.0 + step
        if abs(denom) > 1e-12:
            for s in active:
                r = cash_per_bar if s.kind == CASH else rets[s.name].get(ts, 0.0)
                wts[s.name] = wts[s.name] * (1.0 + r) / denom
            tot = sum(wts.values()) or 1.0
            for k in wts:
                wts[k] /= tot

        if cfg.rebalance_bars > 0 and i % cfg.rebalance_bars == 0:
            turnover = sum(abs(wts[k] - target[k]) for k in wts) / 2.0
            turnover_total += turnover
            rebalances += 1
            value *= (1.0 - turnover * cfg.rebalance_cost_bps / 10000.0)
            wts = dict(target)

        equity.append((ts, value))

    res.equity = equity
    res.exposure_curve = exposure_curve
    res.sleeve_curves = {k: v for k, v in curves.items() if v}

    # 每个 sleeve 单独的指标 (用同一段时间轴, 便于横向比较)
    tl = set(timeline)
    for s in active:
        if s.kind == CASH:
            continue
        c = [(ts, v) for ts, v in curves[s.name] if ts in tl]
        if len(c) < 10:
            continue
        scaled = [(ts, v / c[0][1] * cfg.initial_cash) for ts, v in c]
        shim = bt.BacktestResult(symbol=s.name, strategy_key="sleeve", strategy_label=s.name)
        shim.equity = scaled
        res.sleeve_metrics[s.name] = bt._metrics(
            shim, BacktestConfig(initial_cash=cfg.initial_cash, interval=cfg.interval), 0.0)

    # 相关性矩阵
    series = {n: [rets[n].get(ts, 0.0) for ts in timeline[1:]] for n in rets}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if a in series and b in series:
                res.correlation[(a, b)] = _corr(series[a], series[b])

    # 基准: 单买 SPY
    bench = data.get(benchmark_symbol)
    if bench:
        bmap = {c.ts: c.close for c in bench}
        first = None
        bcurve = []
        for ts in timeline:
            px = bmap.get(ts)
            if px is None:
                bcurve.append((ts, bcurve[-1][1] if bcurve else cfg.initial_cash))
                continue
            if first is None:
                first = px
            bcurve.append((ts, cfg.initial_cash * px / first))
        res.benchmark = bcurve

    shim = bt.BacktestResult(symbol="组合", strategy_key="mix", strategy_label="组合")
    shim.equity = res.equity
    shim.benchmark = res.benchmark
    res.metrics = bt._metrics(
        shim, BacktestConfig(initial_cash=cfg.initial_cash, interval=cfg.interval), 0.0)
    res.metrics["rebalances"] = rebalances
    res.metrics["avg_turnover"] = (turnover_total / rebalances * 100) if rebalances else 0.0
    res.metrics["avg_exposure"] = (
        sum(e for _, e in exposure_curve) / len(exposure_curve)) if exposure_curve else lev
    res.metrics["avg_correlation"] = (
        sum(res.correlation.values()) / len(res.correlation)) if res.correlation else 0.0
    res.strategy_label = " + ".join(
        "{} {:.0f}%".format(s.name, target[s.name] * 100) for s in active)
    return res


# ======================================================================
def risk_parity_weights(sleeves: list, data: dict, settings: Settings,
                        cfg: MixConfig) -> dict:
    """按波动率倒数分配权重 —— 让每一块贡献差不多的风险, 而不是差不多的钱。"""
    vols = {}
    bpy = bt.BARS_PER_YEAR.get(cfg.interval, 252)
    for s in sleeves:
        if s.kind == CASH:
            vols[s.name] = None
            continue
        c = build_sleeve_curve(s, data, settings, cfg)
        r = list(_to_returns(c).values())
        if len(r) < 30:
            vols[s.name] = None
            continue
        m = sum(r) / len(r)
        var = sum((x - m) ** 2 for x in r) / (len(r) - 1)
        vols[s.name] = math.sqrt(max(var, 1e-12)) * math.sqrt(bpy)

    inv = {}
    for name, v in vols.items():
        inv[name] = (1.0 / v) if (v and v > 1e-6) else 0.0
    # 现金给一个很小的名义波动, 避免权重爆掉
    cash_names = [s.name for s in sleeves if s.kind == CASH]
    if cash_names:
        ref = max([x for x in inv.values() if x > 0] or [1.0])
        for n in cash_names:
            inv[n] = ref * 0.5
    total = sum(inv.values()) or 1.0
    return {k: v / total for k, v in inv.items()}
