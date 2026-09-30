"""参数优化 + 样本外验证。

网格搜索最大的坑是**过拟合**: 在历史上调出一组漂亮参数, 拿到实盘就废。
所以这里强制做训练/验证切分 —— 只在前 70% 数据上搜参数, 在后 30% 上验证。
只有 train 和 test 都不差的参数才值得用。
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from ..config import Settings
from . import backtest as bt
from .library import REGISTRY, create
from ..i18n import _tr

METRICS = {
    "sharpe": (_tr("夏普比率"), True),
    "total_return": (_tr("总收益率"), True),
    "cagr": (_tr("年化收益"), True),
    "calmar": (_tr("卡玛比率 (年化/回撤)"), True),
    "profit_factor": (_tr("盈亏比"), True),
    "max_drawdown": (_tr("最大回撤"), False),      # 越小越好
}


@dataclass
class OptRow:
    params: dict
    train: dict = field(default_factory=dict)
    test: dict = field(default_factory=dict)
    full: dict = field(default_factory=dict)

    def score(self, metric: str) -> float:
        v = self.test.get(metric)
        if v is None:
            return float("-inf")
        return -v if not METRICS.get(metric, ("", True))[1] else v

    @property
    def robust(self) -> bool:
        """训练集和验证集方向一致, 才算稳健。"""
        a = self.train.get("total_return", 0.0)
        b = self.test.get("total_return", 0.0)
        return a > 0 and b > 0


def build_grid(strategy_key: str, points: int = 5, overrides: dict | None = None) -> list[dict]:
    cls = REGISTRY[strategy_key]
    specs = cls.param_specs()
    if not specs:
        return [{}]
    overrides = overrides or {}
    axes, keys = [], []
    for p in specs:
        keys.append(p.key)
        if p.key in overrides:
            axes.append([p.cast(overrides[p.key])])
        else:
            axes.append(p.grid(points))
    return [dict(zip(keys, combo)) for combo in itertools.product(*axes)]


def _valid(strategy_key: str, params: dict) -> bool:
    """剔除没有意义的参数组合 (如快线 >= 慢线)。"""
    if strategy_key in ("ma_cross", "macd"):
        if params.get("fast", 0) >= params.get("slow", 1):
            return False
    if strategy_key == "rsi_reversion":
        if params.get("oversold", 0) >= params.get("exit_level", 100):
            return False
    return True


def grid_search(candles: list, strategy_key: str, settings: Settings,
                cfg: bt.BacktestConfig, metric: str = "sharpe",
                points: int = 5, split: float = 0.7, max_combos: int = 600,
                overrides: dict | None = None, progress=None,
                should_stop=None) -> tuple:
    """返回 (按样本外表现排序的 OptRow 列表, 提示信息)。"""
    grid = [g for g in build_grid(strategy_key, points, overrides) if _valid(strategy_key, g)]
    note = ""
    if len(grid) > max_combos:
        step = len(grid) / max_combos
        grid = [grid[int(i * step)] for i in range(max_combos)]
        note = _tr("组合数超过上限, 已均匀抽样到 {} 组").format(len(grid))

    cut = int(len(candles) * split)
    train_c, test_c = candles[:cut], candles[cut:]
    if len(train_c) < 60 or len(test_c) < 30:
        return [], _tr("K 线太少, 无法做训练/验证切分 (至少需要约 300 根)")

    rows = []
    for n, params in enumerate(grid):
        if should_stop and should_stop():
            note = _tr("已中止 (完成 {}/{} 组)").format(n, len(grid))
            break
        try:
            r_tr = bt.run(train_c, create(strategy_key, **params), settings, cfg)
            r_te = bt.run(test_c, create(strategy_key, **params), settings, cfg)
            r_fu = bt.run(candles, create(strategy_key, **params), settings, cfg)
        except Exception:
            continue
        if not (r_tr.ok and r_te.ok):
            continue
        rows.append(OptRow(params=params, train=r_tr.metrics,
                           test=r_te.metrics, full=r_fu.metrics if r_fu.ok else {}))
        if progress and n % 5 == 0:
            progress(n + 1, len(grid))
    if progress:
        progress(len(grid), len(grid))

    rows.sort(key=lambda r: r.score(metric), reverse=True)
    if not rows:
        note = note or _tr("没有产生任何有效结果, 试试放宽参数范围或延长回测区间")
    return rows, note
