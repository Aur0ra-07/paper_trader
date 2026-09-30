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
from ..i18n import N_, _tr

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
        Sleeve(_tr("动量轮动"), ROTATION, list(ROT_POOL), w * 0.25, rotation=dict(ROT_CFG)),
        Sleeve(_tr("趋势跟踪"), STRATEGY, list(TREND_POOL), w * 0.25,
               strategy_key="dual_momentum"),
        Sleeve(_tr("多资产"), ASSET, ["TLT", "GLD", "IEF"], w * 0.50),
    ]


PRESETS = [
    (N_("保守 · 纯核心三支柱"), lambda: _core(1.0)),
    (N_("平衡 · 核心75 + QQQ25"), lambda: _core(0.75) + [Sleeve(_tr("QQQ卫星"), ASSET, ["QQQ"], 0.25)]),
    (N_("进取 · 核心65 + QQQ35"), lambda: _core(0.65) + [Sleeve(_tr("QQQ卫星"), ASSET, ["QQQ"], 0.35)]),
    (N_("激进 · 核心50 + QQQ50"), lambda: _core(0.50) + [Sleeve(_tr("QQQ卫星"), ASSET, ["QQQ"], 0.50)]),
    (N_("高波动 · 核心80 + TQQQ20"), lambda: _core(0.80) + [Sleeve(_tr("TQQQ卫星"), ASSET, ["TQQQ"], 0.20)]),
    (N_("经典 · 60/40 股债"), lambda: [Sleeve(_tr("股票"), ASSET, ["SPY"], 0.60),
                                Sleeve(_tr("长债"), ASSET, ["TLT"], 0.40)]),
    (N_("经典 · 永久组合四分法"), lambda: [Sleeve(_tr("股票"), ASSET, ["SPY"], 0.25),
                                Sleeve(_tr("长债"), ASSET, ["TLT"], 0.25),
                                Sleeve(_tr("黄金"), ASSET, ["GLD"], 0.25),
                                Sleeve(_tr("现金"), CASH, [], 0.25)]),
    (N_("经典 · 全天候近似"), lambda: [Sleeve(_tr("股票"), ASSET, ["SPY"], 0.30),
                              Sleeve(_tr("长债"), ASSET, ["TLT"], 0.40),
                              Sleeve(_tr("中债"), ASSET, ["IEF"], 0.15),
                              Sleeve(_tr("黄金"), ASSET, ["GLD"], 0.075),
                              Sleeve(_tr("商品"), ASSET, ["DBC"], 0.075)]),
    (N_("对照 · 全仓 SPY"), lambda: [Sleeve("SPY", ASSET, ["SPY"], 1.0)]),
]


def preset_names() -> list:
    """预设的**中文原文**名字 —— 存盘用这个, 显示时再 _tr()。"""
    return [name for name, _ in PRESETS]


def by_name(name: str) -> list:
    """按名字取出一份全新的支柱列表 (每次都重新构造, 调用方可以随意改权重)。

    中文原文和当前语言的译名都认: autotrader.json 里存的是中文原文,
    但万一有旧代码传进来的是显示文字, 也不至于找不到。
    """
    for label, build in PRESETS:
        if name in (label, _tr(label)):
            return build()
    return []
