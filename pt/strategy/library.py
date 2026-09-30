"""策略库。

每个策略只回答一个问题: **在第 i 根 K 线收盘时, 我想持有什么方向?**
返回 +1 做多 / 0 空仓 / -1 做空。仓位大小、成本、止损由回测/执行框架统一处理,
这样同一份策略代码既能跑历史回测, 也能直接接实盘。

铁律: target(i) 只能使用 <= i 的数据。所有指标都是按下标对齐预计算的,
不会出现未来函数。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import indicators as ind
from ..i18n import _tr


@dataclass
class Param:
    key: str
    label: str
    default: float
    lo: float
    hi: float
    step: float = 1
    kind: str = "int"          # int | float | bool

    def cast(self, v):
        if self.kind == "int":
            return int(round(float(v)))
        if self.kind == "bool":
            return bool(v)
        return float(v)

    def grid(self, n: int = 6) -> list:
        """参数优化用的候选值。"""
        if self.kind == "bool":
            return [False, True]
        vals, v = [], self.lo
        while v <= self.hi + 1e-9:
            vals.append(self.cast(v))
            v += self.step
        if len(vals) <= n:
            return vals
        idx = [round(k * (len(vals) - 1) / (n - 1)) for k in range(n)]
        return sorted({vals[i] for i in idx})


class Strategy:
    key = "base"
    name = _tr("基础策略")
    desc = ""
    params: list = []

    def __init__(self, **kw):
        self.p = {p.key: p.default for p in self.params}
        for k, v in kw.items():
            if k in self.p:
                spec = next(p for p in self.params if p.key == k)
                self.p[k] = spec.cast(v)
        self.closes: list = []
        self.highs: list = []
        self.lows: list = []

    # -- 子类实现 -------------------------------------------------------
    def warmup(self) -> int:
        """开头需要跳过的 K 线根数。"""
        return 1

    def prepare(self, candles: list) -> None:
        """一次性预计算指标。"""
        self.closes = [c.close for c in candles]
        self.highs = [c.high for c in candles]
        self.lows = [c.low for c in candles]

    def target(self, i: int) -> int:
        raise NotImplementedError

    # -- 工具 -----------------------------------------------------------
    def label(self) -> str:
        bits = ["{}={}".format(k, v) for k, v in self.p.items() if not isinstance(v, bool)]
        return "{} ({})".format(self.name, ", ".join(bits)) if bits else self.name

    def explain(self, i: int) -> str:
        """当前这根 K 线的指标读数, 用于 AI 简报和运行日志。"""
        return ""

    @classmethod
    def param_specs(cls) -> list:
        return cls.params


# ======================================================================
class MACross(Strategy):
    key = "ma_cross"
    name = _tr("双均线交叉")
    desc = _tr("快线上穿慢线做多, 下穿则空仓(或反手做空)。经典趋势跟踪, 震荡市会反复挨打。")
    params = [
        Param("fast", _tr("快线周期"), 10, 3, 60, 1),
        Param("slow", _tr("慢线周期"), 30, 10, 250, 5),
        Param("allow_short", _tr("下穿时反手做空"), False, 0, 1, 1, "bool"),
    ]

    def warmup(self) -> int:
        return int(self.p["slow"]) + 1

    def prepare(self, candles):
        super().prepare(candles)
        self.f = ind.sma(self.closes, int(self.p["fast"]))
        self.s = ind.sma(self.closes, int(self.p["slow"]))

    def target(self, i):
        f, s = self.f[i], self.s[i]
        if f is None or s is None:
            return 0
        if f > s:
            return 1
        return -1 if self.p["allow_short"] else 0

    def explain(self, i):
        f, s = self.f[i], self.s[i]
        if f is None or s is None:
            return _tr("均线未就绪")
        return "MA{}={:.2f} {} MA{}={:.2f}".format(
            int(self.p["fast"]), f, ">" if f > s else "<", int(self.p["slow"]), s)


class EMATrend(Strategy):
    key = "ema_trend"
    name = _tr("EMA 趋势 + ADX 过滤")
    desc = _tr("价格站上 EMA 且 ADX 高于阈值(确认有趋势)才做多, 避免在震荡市里被来回扫。")
    params = [
        Param("period", _tr("EMA 周期"), 20, 5, 120, 5),
        Param("adx_period", _tr("ADX 周期"), 14, 7, 30, 1),
        Param("adx_min", _tr("ADX 下限"), 20, 0, 40, 5),
        Param("allow_short", _tr("跌破时做空"), False, 0, 1, 1, "bool"),
    ]

    def warmup(self):
        return max(int(self.p["period"]), int(self.p["adx_period"]) * 2) + 2

    def prepare(self, candles):
        super().prepare(candles)
        self.e = ind.ema(self.closes, int(self.p["period"]))
        self.a = ind.adx(self.highs, self.lows, self.closes, int(self.p["adx_period"]))

    def target(self, i):
        e, a = self.e[i], self.a[i]
        if e is None or a is None or a < self.p["adx_min"]:
            return 0
        if self.closes[i] > e:
            return 1
        return -1 if self.p["allow_short"] else 0

    def explain(self, i):
        e, a = self.e[i], self.a[i]
        if e is None or a is None:
            return _tr("指标未就绪")
        return _tr("价 {:.2f} vs EMA{} {:.2f}, ADX={:.1f}").format(
            self.closes[i], int(self.p["period"]), e, a)


class RSIReversion(Strategy):
    key = "rsi_reversion"
    name = _tr("RSI 均值回归")
    desc = _tr("RSI 跌破超卖线买入, 回到中位线卖出。适合震荡市, 单边下跌行情会一路加仓挨套。")
    params = [
        Param("period", _tr("RSI 周期"), 14, 5, 30, 1),
        Param("oversold", _tr("超卖买入线"), 30, 10, 45, 5),
        Param("exit_level", _tr("平仓线"), 55, 45, 80, 5),
    ]

    def warmup(self):
        return int(self.p["period"]) + 2

    def prepare(self, candles):
        super().prepare(candles)
        self.r = ind.rsi(self.closes, int(self.p["period"]))
        self._state = 0

    def target(self, i):
        r = self.r[i]
        if r is None:
            return 0
        if self._state == 0 and r < self.p["oversold"]:
            self._state = 1
        elif self._state == 1 and r > self.p["exit_level"]:
            self._state = 0
        return self._state

    def explain(self, i):
        r = self.r[i]
        return "RSI({})={:.1f}".format(int(self.p["period"]), r) if r is not None else _tr("RSI 未就绪")


class BollingerReversion(Strategy):
    key = "boll_reversion"
    name = _tr("布林带回归")
    desc = _tr("触及下轨买入, 回到中轨卖出。和 RSI 回归类似, 但阈值随波动率自适应。")
    params = [
        Param("period", _tr("周期"), 20, 5, 60, 1),
        Param("mult", _tr("标准差倍数"), 2.0, 1.0, 3.5, 0.25, "float"),
    ]

    def warmup(self):
        return int(self.p["period"]) + 2

    def prepare(self, candles):
        super().prepare(candles)
        self.mid, self.up, self.dn = ind.bollinger(self.closes, int(self.p["period"]),
                                                   float(self.p["mult"]))
        self._state = 0

    def target(self, i):
        m, d = self.mid[i], self.dn[i]
        if m is None or d is None:
            return 0
        c = self.closes[i]
        if self._state == 0 and c <= d:
            self._state = 1
        elif self._state == 1 and c >= m:
            self._state = 0
        return self._state

    def explain(self, i):
        m, u, d = self.mid[i], self.up[i], self.dn[i]
        if m is None:
            return _tr("布林带未就绪")
        return _tr("价 {:.2f}  下轨 {:.2f} / 中轨 {:.2f} / 上轨 {:.2f}").format(self.closes[i], d, m, u)


class DonchianBreakout(Strategy):
    key = "donchian"
    name = _tr("唐奇安通道突破 (海龟)")
    desc = _tr("突破 N 日新高做多, 跌破 M 日新低离场。趋势策略的老祖宗, 胜率低但吃得住大行情。")
    params = [
        Param("entry", _tr("入场周期(新高)"), 20, 5, 120, 5),
        Param("exit", _tr("离场周期(新低)"), 10, 3, 60, 1),
        Param("allow_short", _tr("破新低反手做空"), False, 0, 1, 1, "bool"),
    ]

    def warmup(self):
        return max(int(self.p["entry"]), int(self.p["exit"])) + 2

    def prepare(self, candles):
        super().prepare(candles)
        self.hi_in, _ = ind.donchian(self.highs, self.lows, int(self.p["entry"]))
        _, self.lo_out = ind.donchian(self.highs, self.lows, int(self.p["exit"]))
        _, self.lo_in = ind.donchian(self.highs, self.lows, int(self.p["entry"]))
        self.hi_out, _ = ind.donchian(self.highs, self.lows, int(self.p["exit"]))
        self._state = 0

    def target(self, i):
        c = self.closes[i]
        hin, lout = self.hi_in[i], self.lo_out[i]
        lin, hout = self.lo_in[i], self.hi_out[i]
        if hin is None or lout is None:
            return 0
        if self._state <= 0 and c > hin:
            self._state = 1
        elif self._state == 1 and c < lout:
            self._state = 0
        if self.p["allow_short"] and lin is not None and hout is not None:
            if self._state >= 0 and c < lin:
                self._state = -1
            elif self._state == -1 and c > hout:
                self._state = 0
        return self._state

    def explain(self, i):
        hin, lout = self.hi_in[i], self.lo_out[i]
        if hin is None:
            return _tr("通道未就绪")
        return _tr("价 {:.2f}  {}日高 {:.2f}  {}日低 {:.2f}").format(
            self.closes[i], int(self.p["entry"]), hin, int(self.p["exit"]), lout)


class MACDTrend(Strategy):
    key = "macd"
    name = _tr("MACD 金叉死叉")
    desc = _tr("DIF 上穿 DEA 做多, 下穿离场。比双均线更灵敏, 假信号也更多。")
    params = [
        Param("fast", _tr("快线"), 12, 5, 30, 1),
        Param("slow", _tr("慢线"), 26, 10, 60, 2),
        Param("signal", _tr("信号线"), 9, 3, 20, 1),
        Param("allow_short", _tr("死叉反手做空"), False, 0, 1, 1, "bool"),
    ]

    def warmup(self):
        return int(self.p["slow"]) + int(self.p["signal"]) + 2

    def prepare(self, candles):
        super().prepare(candles)
        self.dif, self.dea, self.hist = ind.macd(
            self.closes, int(self.p["fast"]), int(self.p["slow"]), int(self.p["signal"]))

    def target(self, i):
        d, e = self.dif[i], self.dea[i]
        if d is None or e is None:
            return 0
        if d > e:
            return 1
        return -1 if self.p["allow_short"] else 0

    def explain(self, i):
        d, e = self.dif[i], self.dea[i]
        if d is None or e is None:
            return _tr("MACD 未就绪")
        return "DIF={:.3f} {} DEA={:.3f}".format(d, ">" if d > e else "<", e)


class DualMomentum(Strategy):
    key = "dual_momentum"
    name = _tr("动量 + 长期均线过滤")
    desc = _tr("N 日涨幅为正、且站上长期均线才持有。牛市吃肉、熊市空仓, 换手率低。")
    params = [
        Param("roc_period", _tr("动量周期"), 60, 10, 250, 10),
        Param("ma_period", _tr("长期均线"), 200, 50, 250, 10),
        Param("roc_min", _tr("动量下限 %"), 0, -20, 20, 2, "float"),
    ]

    def warmup(self):
        return max(int(self.p["roc_period"]), int(self.p["ma_period"])) + 2

    def prepare(self, candles):
        super().prepare(candles)
        self.r = ind.roc(self.closes, int(self.p["roc_period"]))
        self.m = ind.sma(self.closes, int(self.p["ma_period"]))

    def target(self, i):
        r, m = self.r[i], self.m[i]
        if r is None or m is None:
            return 0
        return 1 if (r > self.p["roc_min"] and self.closes[i] > m) else 0

    def explain(self, i):
        r, m = self.r[i], self.m[i]
        if r is None or m is None:
            return _tr("指标未就绪")
        return _tr("{}日动量 {:+.1f}%, 价 {:.2f} vs MA{} {:.2f}").format(
            int(self.p["roc_period"]), r, self.closes[i], int(self.p["ma_period"]), m)


class RSI2Connors(Strategy):
    key = "rsi2_connors"
    name = _tr("RSI2 短线抄底 (Connors)")
    desc = (_tr("只在长期均线之上抄短线的底: 价格站上 MA200 (确认大趋势向上) 且 RSI(2) 极低时买入, "
            "反弹到短期均线上方就走。持仓通常只有几天, 换手高但单笔风险小。"))
    params = [
        Param("rsi_period", _tr("RSI 周期"), 2, 2, 10, 1),
        Param("entry", _tr("买入阈值"), 5, 1, 30, 1),
        Param("trend_ma", _tr("趋势过滤均线"), 200, 50, 250, 10),
        Param("exit_ma", _tr("离场均线"), 5, 3, 20, 1),
    ]

    def warmup(self):
        return int(self.p["trend_ma"]) + 5

    def prepare(self, candles):
        super().prepare(candles)
        self.r = ind.rsi(self.closes, int(self.p["rsi_period"]))
        self.trend = ind.sma(self.closes, int(self.p["trend_ma"]))
        self.exit_ma = ind.sma(self.closes, int(self.p["exit_ma"]))
        self._state = 0

    def target(self, i):
        r, t, e = self.r[i], self.trend[i], self.exit_ma[i]
        if r is None or t is None or e is None:
            return 0
        c = self.closes[i]
        if self._state == 0:
            if c > t and r < self.p["entry"]:
                self._state = 1
        elif c > e or c < t:
            self._state = 0
        return self._state

    def explain(self, i):
        r, t = self.r[i], self.trend[i]
        if r is None or t is None:
            return _tr("指标未就绪")
        return _tr("RSI({})={:.1f}, 价 {:.2f} {} MA{} {:.2f}").format(
            int(self.p["rsi_period"]), r, self.closes[i],
            ">" if self.closes[i] > t else "<", int(self.p["trend_ma"]), t)


class ChandelierTrend(Strategy):
    key = "chandelier"
    name = _tr("吊灯止损趋势跟踪")
    desc = (_tr("突破 N 日新高进场, 之后用「入场以来最高价 - K倍ATR」作为移动止损。"
            "止损随波动率自适应: 波动大时给足空间, 波动小时收紧, 尽量让利润跑完。"))
    params = [
        Param("entry", _tr("入场周期(新高)"), 20, 5, 120, 5),
        Param("atr_period", _tr("ATR 周期"), 22, 5, 50, 1),
        Param("atr_mult", _tr("ATR 倍数"), 3.0, 1.0, 6.0, 0.5, "float"),
        Param("trend_ma", _tr("趋势过滤均线"), 100, 0, 250, 25),
    ]

    def warmup(self):
        return max(int(self.p["entry"]), int(self.p["atr_period"]),
                   int(self.p["trend_ma"])) + 3

    def prepare(self, candles):
        super().prepare(candles)
        self.hi_in, _ = ind.donchian(self.highs, self.lows, int(self.p["entry"]))
        self.a = ind.atr(self.highs, self.lows, self.closes, int(self.p["atr_period"]))
        mp = int(self.p["trend_ma"])
        self.trend = ind.sma(self.closes, mp) if mp >= 2 else [None] * len(self.closes)
        self._use_trend = mp >= 2
        self._state = 0
        self._peak = 0.0

    def target(self, i):
        hin, a = self.hi_in[i], self.a[i]
        if hin is None or a is None:
            return 0
        c = self.closes[i]
        if self._state == 0:
            ok_trend = True
            if self._use_trend:
                t = self.trend[i]
                ok_trend = t is not None and c > t
            if c > hin and ok_trend:
                self._state = 1
                self._peak = self.highs[i]
        else:
            self._peak = max(self._peak, self.highs[i])
            if c < self._peak - self.p["atr_mult"] * a:
                self._state = 0
                self._peak = 0.0
        return self._state

    def explain(self, i):
        a = self.a[i]
        if a is None:
            return _tr("ATR 未就绪")
        if self._state:
            stop = self._peak - self.p["atr_mult"] * a
            return _tr("持多, 峰值 {:.2f}, 吊灯止损 {:.2f} (现价 {:.2f})").format(
                self._peak, stop, self.closes[i])
        hin = self.hi_in[i]
        return _tr("空仓, 需突破 {:.2f} (现价 {:.2f})").format(hin if hin else 0, self.closes[i])


class SqueezeBreakout(Strategy):
    key = "squeeze"
    name = _tr("波动率挤压突破")
    desc = (_tr("布林带宽收窄到近期极低水平 = 市场在蓄力, 随后向上突破上轨时跟进。"
            "低波动之后常跟着大行情, 这个策略专门埋伏这种转换。"))
    params = [
        Param("period", _tr("布林周期"), 20, 10, 60, 5),
        Param("lookback", _tr("带宽分位回看"), 120, 40, 250, 10),
        Param("pct", _tr("带宽分位阈值 %"), 25, 5, 60, 5),
        Param("exit_ma", _tr("离场均线"), 20, 5, 60, 5),
    ]

    def warmup(self):
        return int(self.p["period"]) + int(self.p["lookback"]) + 3

    def prepare(self, candles):
        super().prepare(candles)
        per = int(self.p["period"])
        self.mid, self.up, self.dn = ind.bollinger(self.closes, per, 2.0)
        self.width = [None if (self.mid[i] is None or not self.mid[i])
                      else (self.up[i] - self.dn[i]) / self.mid[i] * 100
                      for i in range(len(self.closes))]
        self.exit_ma = ind.sma(self.closes, int(self.p["exit_ma"]))
        self._state = 0

    def target(self, i):
        w, u, e = self.width[i], self.up[i], self.exit_ma[i]
        if w is None or u is None or e is None:
            return 0
        lb = int(self.p["lookback"])
        window = [x for x in self.width[max(0, i - lb):i] if x is not None]
        if len(window) < lb // 2:
            return self._state
        idx = min(int(len(window) * self.p["pct"] / 100.0), len(window) - 1)
        thresh = sorted(window)[idx]
        c = self.closes[i]
        if self._state == 0:
            if w <= thresh and c > u:
                self._state = 1
        elif c < e:
            self._state = 0
        return self._state

    def explain(self, i):
        w, u = self.width[i], self.up[i]
        if w is None or u is None:
            return _tr("布林带未就绪")
        return _tr("带宽 {:.2f}%, 上轨 {:.2f}, 现价 {:.2f}").format(w, u, self.closes[i])


class TrendVolFilter(Strategy):
    key = "trend_vol"
    name = _tr("趋势 + 低波动过滤")
    desc = (_tr("同时要求: 价格在长期均线上方(趋势向上) 且 近期波动率不在高位(市场不恐慌)。"
            "高波动期往往对应下跌, 避开它能明显压低回撤。"))
    params = [
        Param("ma_period", _tr("趋势均线"), 200, 50, 250, 10),
        Param("atr_period", _tr("ATR 周期"), 20, 10, 60, 5),
        Param("vol_lookback", _tr("波动率回看"), 250, 60, 500, 10),
        Param("vol_max_pct", _tr("波动率分位上限 %"), 80, 40, 100, 5),
    ]

    def warmup(self):
        return max(int(self.p["ma_period"]),
                   int(self.p["vol_lookback"]) + int(self.p["atr_period"])) + 3

    def prepare(self, candles):
        super().prepare(candles)
        self.ma = ind.sma(self.closes, int(self.p["ma_period"]))
        a = ind.atr(self.highs, self.lows, self.closes, int(self.p["atr_period"]))
        self.volp = [None if (a[i] is None or not self.closes[i])
                     else a[i] / self.closes[i] * 100 for i in range(len(self.closes))]

    def target(self, i):
        m, v = self.ma[i], self.volp[i]
        if m is None or v is None:
            return 0
        if self.closes[i] <= m:
            return 0
        lb = int(self.p["vol_lookback"])
        window = [x for x in self.volp[max(0, i - lb):i] if x is not None]
        if len(window) < lb // 2:
            return 0
        idx = min(int(len(window) * self.p["vol_max_pct"] / 100.0), len(window) - 1)
        return 1 if v <= sorted(window)[idx] else 0

    def explain(self, i):
        m, v = self.ma[i], self.volp[i]
        if m is None or v is None:
            return _tr("指标未就绪")
        return _tr("价 {:.2f} vs MA{} {:.2f}, ATR% {:.2f}").format(
            self.closes[i], int(self.p["ma_period"]), m, v)


class BuyHold(Strategy):
    key = "buy_hold"
    name = _tr("买入持有 (基准)")
    desc = _tr("第一根就满仓拿到底。所有策略都该跟它比 —— 跑不赢它的策略没有存在意义。")
    params = []

    def warmup(self):
        return 1

    def target(self, i):
        return 1

    def explain(self, i):
        return _tr("始终满仓")


REGISTRY = {c.key: c for c in (
    MACross, EMATrend, RSIReversion, BollingerReversion,
    DonchianBreakout, MACDTrend, DualMomentum,
    RSI2Connors, ChandelierTrend, SqueezeBreakout, TrendVolFilter, BuyHold)}

STRATEGY_ORDER = ["ma_cross", "ema_trend", "donchian", "chandelier", "macd",
                  "dual_momentum", "trend_vol", "squeeze",
                  "rsi_reversion", "rsi2_connors", "boll_reversion", "buy_hold"]


def create(key: str, **params) -> Strategy:
    cls = REGISTRY.get(key)
    if cls is None:
        raise KeyError(_tr("未知策略: {}").format(key))
    return cls(**params)
