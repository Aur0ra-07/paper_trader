"""组合预设 —— 核心-卫星结构的标准配置。

放在策略层而不是 UI 层, 因为自动交易也要用: 让软件真正按这套组合跑起来,
而不是只能在回测页看看。

**这些权重是起点, 不是推荐。** 想改就改, 但改完要自己重跑验证 ——
尤其别只看样本内的夏普变好就当成进步。`strategy/validation.py` 里有
walk_forward() 和 deflated_sharpe(), 用那个判断改动是真的有效还是
只是把噪声调好看了。
"""
from __future__ import annotations

from .portfolio import ASSET, CASH, ROTATION, STRATEGY, Sleeve

ROT_POOL = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB",
            "TLT", "GLD", "EEM", "EFA", "IWM"]
TREND_POOL = ["SPY", "QQQ", "IWM", "EFA", "EEM"]
ROT_CFG = {"lookback": 120, "top_k": 3, "rebalance_bars": 21, "abs_momentum": True}



def _core(w: float) -> list:
    """三支柱核心: 动量轮动 / 趋势跟踪 / 多资产。

    多资产那支拿 50% 而不是等权的 33%, 是因为它跟另外两支的相关性最低 ——
    按风险贡献看, 相关性低的那一支本来就该拿更多钱。想验证这个取舍,
    在组合页看相关性矩阵, 然后自己跑不同权重对比。
    """
    return [
        Sleeve("动量轮动", ROTATION, list(ROT_POOL), w * 0.25, rotation=dict(ROT_CFG)),
        Sleeve("趋势跟踪", STRATEGY, list(TREND_POOL), w * 0.25,
               strategy_key="dual_momentum"),
        Sleeve("多资产", ASSET, ["TLT", "GLD", "IEF"], w * 0.50),
    ]


PRESETS = [
    ("保守 · 纯核心三支柱", lambda: _core(1.0)),
    ("平衡 · 核心75 + QQQ25", lambda: _core(0.75) + [Sleeve("QQQ卫星", ASSET, ["QQQ"], 0.25)]),
    ("进取 · 核心65 + QQQ35", lambda: _core(0.65) + [Sleeve("QQQ卫星", ASSET, ["QQQ"], 0.35)]),
    ("激进 · 核心50 + QQQ50", lambda: _core(0.50) + [Sleeve("QQQ卫星", ASSET, ["QQQ"], 0.50)]),
    ("高波动 · 核心80 + TQQQ20", lambda: _core(0.80) + [Sleeve("TQQQ卫星", ASSET, ["TQQQ"], 0.20)]),
    ("经典 · 60/40 股债", lambda: [Sleeve("股票", ASSET, ["SPY"], 0.60),
                                Sleeve("长债", ASSET, ["TLT"], 0.40)]),
    ("经典 · 永久组合四分法", lambda: [Sleeve("股票", ASSET, ["SPY"], 0.25),
                                Sleeve("长债", ASSET, ["TLT"], 0.25),
                                Sleeve("黄金", ASSET, ["GLD"], 0.25),
                                Sleeve("现金", CASH, [], 0.25)]),
    ("经典 · 全天候近似", lambda: [Sleeve("股票", ASSET, ["SPY"], 0.30),
                              Sleeve("长债", ASSET, ["TLT"], 0.40),
                              Sleeve("中债", ASSET, ["IEF"], 0.15),
                              Sleeve("黄金", ASSET, ["GLD"], 0.075),
                              Sleeve("商品", ASSET, ["DBC"], 0.075)]),
    ("对照 · 全仓 SPY", lambda: [Sleeve("SPY", ASSET, ["SPY"], 1.0)]),
]


def preset_names() -> list:
    return [name for name, _ in PRESETS]


def by_name(name: str) -> list:
    """按名字取出一份全新的支柱列表 (每次都重新构造, 调用方可以随意改权重)。"""
    for label, build in PRESETS:
        if label == name:
            return build()
    return []
