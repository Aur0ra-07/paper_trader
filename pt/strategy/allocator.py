"""把组合规格翻译成「此刻每个标的该占多少权重」。

自动交易原来只有**单标的择时**模式: 一个策略套到每个标的上, 各自全仓或空仓。
组合是另一套逻辑 —— 多个支柱、各有目标权重、定期再平衡, 仓位是**比例**而不是有无。
这个模块负责前半段: 算目标权重。后半段(和现有持仓比对、生成买卖单)在 autotrader 里。

规则和回测完全共用:

* 轮动支柱走 `rotation.live_picks()`, 和回测的 `pick()` 共用 `score_one()`
* 择时支柱走 `library.create()` 的同一份策略代码
* 买入持有支柱在其标的间等权

**只用已收盘的 K 线**(不变量 3): 调用方通过 `idx_by_symbol` 指定信号根下标。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import rotation
from .library import create
from .portfolio import ASSET, CASH, ROTATION, STRATEGY, Sleeve
from .rotation import RotationConfig
from ..i18n import _tr


@dataclass
class SleeveTarget:
    name: str
    kind: str
    weight: float                            # 该支柱在组合里的权重
    holdings: dict = field(default_factory=dict)   # sym -> 支柱内部权重 (和 <= 1)
    note: str = ""

    @property
    def invested(self) -> float:
        return sum(self.holdings.values())


@dataclass
class AllocPlan:
    targets: dict = field(default_factory=dict)    # sym -> 占总权益的目标权重
    sleeves: list = field(default_factory=list)    # [SleeveTarget]
    warnings: list = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def cash_weight(self) -> float:
        return max(0.0, 1.0 - sum(self.targets.values()))


# ======================================================================
def _usable(sleeve: Sleeve, candles_by_symbol: dict, min_bars: int = 30) -> list:
    return [s for s in sleeve.symbols
            if candles_by_symbol.get(s) and len(candles_by_symbol[s]) > min_bars]


def sleeve_target(sleeve: Sleeve, candles_by_symbol: dict,
                  idx_by_symbol: dict | None = None,
                  allow_short: bool = False) -> SleeveTarget:
    """算单个支柱此刻的内部持仓权重。

    内部权重之和可能小于 1 —— 差额就是这个支柱该拿着的现金
    (轮动在绝对动量全为负时空仓, 择时策略信号为 0 时空仓)。
    """
    out = SleeveTarget(sleeve.name, sleeve.kind, sleeve.weight)
    idx = idx_by_symbol or {}

    if sleeve.kind == CASH:
        out.note = _tr("现金")
        return out

    syms = _usable(sleeve, candles_by_symbol)
    if not syms:
        out.note = _tr("没有可用 K 线, 按空仓处理")
        return out

    if sleeve.kind == ROTATION:
        rc = RotationConfig(**(sleeve.rotation or {}))
        sub = {s: candles_by_symbol[s] for s in syms}
        picks, scores = rotation.live_picks(sub, rc, idx)
        if not picks:
            out.note = _tr("动量全为负 → 空仓 (绝对动量保护)")
            return out
        w = 1.0 / len(picks)
        out.holdings = {s: w for s in picks}
        out.note = _tr("轮动选中 ") + ", ".join(
            "{} ({:+.1f}%)".format(s, scores.get(s, 0) * 100) for s in picks)
        return out

    if sleeve.kind == ASSET or sleeve.strategy_key == "buy_hold":
        w = 1.0 / len(syms)
        out.holdings = {s: w for s in syms}
        out.note = _tr("等权持有 ") + ", ".join(syms)
        return out

    # STRATEGY: 每个标的独立择时, 信号为多才占该支柱的 1/n, 否则那份留现金
    w = 1.0 / len(syms)
    on, off = [], []
    for s in syms:
        candles = candles_by_symbol[s]
        i = idx.get(s, len(candles) - 1)
        strat = create(sleeve.strategy_key, **(sleeve.params or {}))
        if i < strat.warmup():
            off.append(s + _tr("(预热不足)"))
            continue
        strat.prepare(candles)
        try:
            tgt = 0
            for k in range(strat.warmup(), i + 1):
                tgt = strat.target(k)
        except Exception as exc:                       # 单个标的出错不该拖垮整个组合
            off.append(_tr("{}(出错:{})").format(s, exc))
            continue
        if tgt < 0 and not allow_short:
            tgt = 0
        if tgt > 0:
            out.holdings[s] = w
            on.append(s)
        else:
            off.append(s)
    out.note = _tr("{}: 持有 {} / 空仓 {}").format(
        sleeve.strategy_key, ", ".join(on) or _tr("无"), ", ".join(off) or _tr("无"))
    return out


def plan(sleeves: list, candles_by_symbol: dict,
         idx_by_symbol: dict | None = None,
         allow_short: bool = False) -> AllocPlan:
    """把一组支柱翻译成 {代码: 占总权益的目标权重}。"""
    p = AllocPlan()
    if not sleeves:
        p.error = _tr("组合里一个支柱都没有")
        return p
    total_w = sum(s.weight for s in sleeves)
    if total_w <= 0:
        p.error = _tr("支柱权重之和为 0")
        return p
    if abs(total_w - 1.0) > 0.02:
        p.warnings.append(_tr("支柱权重之和是 {:.0%}, 不是 100%").format(total_w))

    for sl in sleeves:
        st = sleeve_target(sl, candles_by_symbol, idx_by_symbol, allow_short)
        p.sleeves.append(st)
        for sym, iw in st.holdings.items():
            p.targets[sym] = p.targets.get(sym, 0.0) + sl.weight * iw

        missing = [s for s in sl.symbols if not candles_by_symbol.get(s)]
        if missing and sl.kind != CASH:
            p.warnings.append(_tr("{}: 拿不到 {} 的行情").format(sl.name, ", ".join(missing)))

    # 数值毛刺清理
    p.targets = {k: v for k, v in p.targets.items() if v > 1e-6}
    return p
