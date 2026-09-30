"""样本外验证: nested walk-forward + Deflated Sharpe Ratio。

这个模块回答的不是"夏普有多高", 而是:

    考虑到我为了得到这个夏普, 前前后后试了上百组策略/参数/权重,
    这个数字还值得相信吗?

两件事:

1. **Nested walk-forward** —— 只用某个时点**之前**的数据挑配置, 然后在紧接着的、
   完全没参与挑选的一段上跑; 向前滚动, 把所有真正样本外的收益拼起来再算夏普。
   样本内 0.96 / 样本外 0.91 说明优化有点过拟合但确实有东西;
   样本内 0.96 / 样本外 0.40 说明那 0.96 基本是挑出来的。

2. **Deflated Sharpe Ratio (Bailey & López de Prado, 2014)** —— 即使 N 组配置的
   真实夏普**全部为 0**, 纯靠噪声, 其中最好的那个看起来也会相当漂亮。DSR 把
   「试了多少次」「收益分布有多偏/多厚尾」「样本有多长」一起算进去, 给出
   「真实夏普 > 基准」的概率。

注意 DSR 公式里所有夏普都是**未年化**的 (按单根 K 线计), 别传年化值进来。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import NormalDist
from ..i18n import _tr

EULER = 0.5772156649015329          # Euler-Mascheroni 常数
_N = NormalDist()


# ======================================================================
# 基础统计
# ======================================================================
def to_returns(equity: list) -> list:
    """净值曲线 [(ts, value)] -> 逐根收益率 [(ts, r)]。"""
    out = []
    for i in range(1, len(equity)):
        prev = equity[i - 1][1]
        if prev > 0:
            out.append((equity[i][0], equity[i][1] / prev - 1.0))
    return out


def moments(rets: list) -> tuple:
    """-> (均值, 标准差, 偏度 γ3, 峰度 γ4[正态=3])。"""
    n = len(rets)
    if n < 3:
        return 0.0, 0.0, 0.0, 3.0
    mu = sum(rets) / n
    m2 = sum((r - mu) ** 2 for r in rets) / n
    sd = math.sqrt(max(m2, 1e-30))
    m3 = sum((r - mu) ** 3 for r in rets) / n
    m4 = sum((r - mu) ** 4 for r in rets) / n
    return mu, sd, m3 / sd ** 3, m4 / sd ** 4


def sharpe_raw(rets: list) -> float:
    """未年化夏普 (per-bar)。"""
    mu, sd, _, _ = moments(rets)
    return mu / sd if sd > 0 else 0.0


def annualize(sr_raw: float, bpy: int = 252) -> float:
    return sr_raw * math.sqrt(bpy)


# ======================================================================
# PSR / DSR
# ======================================================================
def probabilistic_sharpe(rets: list, sr_benchmark_raw: float = 0.0) -> float:
    """PSR: 真实夏普 > sr_benchmark 的概率。夏普均为未年化值。

    PSR = Z[ (SR - SR*) * sqrt(T-1) / sqrt(1 - γ3·SR + (γ4-1)/4 · SR²) ]
    """
    t = len(rets)
    if t < 3:
        return float("nan")
    _, sd, g3, g4 = moments(rets)
    if sd <= 0:
        return float("nan")
    sr = sharpe_raw(rets)
    denom = 1.0 - g3 * sr + (g4 - 1.0) / 4.0 * sr * sr
    if denom <= 0:
        return float("nan")
    z = (sr - sr_benchmark_raw) * math.sqrt(t - 1) / math.sqrt(denom)
    return _N.cdf(z)


def expected_max_sharpe(n_trials: int, sr_variance: float) -> float:
    """N 组真实夏普全为 0 的配置里, 最好那个的期望夏普 (未年化)。

    SR0 = sqrt(V) · [ (1-γ)·Z⁻¹(1 - 1/N) + γ·Z⁻¹(1 - 1/(N·e)) ]
    """
    n = max(int(n_trials), 2)
    v = max(sr_variance, 0.0)
    if v <= 0:
        return 0.0
    a = _N.inv_cdf(1.0 - 1.0 / n)
    b = _N.inv_cdf(1.0 - 1.0 / (n * math.e))
    return math.sqrt(v) * ((1.0 - EULER) * a + EULER * b)


def deflated_sharpe(rets: list, n_trials: int, sr_variance: float) -> dict:
    """DSR: 扣掉「试了 N 次」的选择偏差之后, 真实夏普 > 0 的概率。

    sr_variance 是这 N 次试验得到的**未年化**夏普的方差。
    """
    sr0 = expected_max_sharpe(n_trials, sr_variance)
    return {
        "sharpe_raw": sharpe_raw(rets),
        "sharpe_ann": annualize(sharpe_raw(rets)),
        "sr0_raw": sr0,
        "sr0_ann": annualize(sr0),
        "n_trials": n_trials,
        "psr_vs_zero": probabilistic_sharpe(rets, 0.0),
        "dsr": probabilistic_sharpe(rets, sr0),
        "n_obs": len(rets),
    }


# ======================================================================
# Nested walk-forward
# ======================================================================
@dataclass
class WFSegment:
    train_from: int = 0
    train_to: int = 0
    test_from: int = 0
    test_to: int = 0
    picked: str = ""
    train_sharpe: float = 0.0
    test_sharpe: float = 0.0
    test_return: float = 0.0


@dataclass
class WFResult:
    oos_returns: list = field(default_factory=list)   # [(ts, r)] 拼接后的真样本外
    segments: list = field(default_factory=list)      # [WFSegment]
    pick_counts: dict = field(default_factory=dict)   # 配置名 -> 被选中次数
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.oos_returns)


def walk_forward(curves: dict, train_bars: int = 1260, test_bars: int = 252,
                 anchored: bool = False, score=None) -> WFResult:
    """对一组**已冻结**的候选配置做滚动样本外验证。

    curves: 配置名 -> 净值曲线 [(ts, value)]，所有曲线必须共用同一条时间轴。
    train_bars: 每次挑配置能看到的历史长度 (日线 1260 ≈ 5 年)。
    test_bars:  挑完之后向前推进、完全不参与挑选的长度 (252 ≈ 1 年)。
    anchored:   True = 训练窗口从头开始不断变长; False = 固定长度滚动。
    score:      打分函数 (rets)->float, 默认用未年化夏普。

    关键: 第 k 段测试期的配置, 只用第 k 段**开始之前**的数据挑出来。
    """
    if not curves:
        return WFResult(error=_tr("没有候选配置"))
    score = score or sharpe_raw
    names = sorted(curves)
    rets = {k: to_returns(curves[k]) for k in names}
    n = min(len(rets[k]) for k in names)
    if n < train_bars + test_bars:
        return WFResult(error=_tr("数据太短: %d 根, 至少需要 %d 根") % (n, train_bars + test_bars))
    ts_axis = [t for t, _ in rets[names[0]][:n]]
    series = {k: [r for _, r in rets[k][:n]] for k in names}

    res = WFResult()
    start = train_bars
    while start + test_bars <= n:
        tr_lo = 0 if anchored else start - train_bars
        train = {k: series[k][tr_lo:start] for k in names}
        best, best_s = None, -1e18
        for k in names:
            s = score(train[k])
            if s > best_s:
                best, best_s = k, s
        te = series[best][start:start + test_bars]
        res.oos_returns.extend(zip(ts_axis[start:start + test_bars], te))
        cum = 1.0
        for r in te:
            cum *= (1.0 + r)
        res.segments.append(WFSegment(
            train_from=ts_axis[tr_lo], train_to=ts_axis[start - 1],
            test_from=ts_axis[start], test_to=ts_axis[start + test_bars - 1],
            picked=best, train_sharpe=annualize(best_s),
            test_sharpe=annualize(sharpe_raw(te)), test_return=(cum - 1.0) * 100.0))
        res.pick_counts[best] = res.pick_counts.get(best, 0) + 1
        start += test_bars
    return res


def curve_from_returns(rets: list, initial: float = 100000.0) -> list:
    """[(ts, r)] -> [(ts, value)]，方便复用现有的指标/滚动窗口函数。"""
    out, v = [], initial
    for ts, r in rets:
        v *= (1.0 + r)
        out.append((ts, v))
    return out
