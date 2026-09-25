"""技术指标 (纯 Python, 无 pandas 依赖)。

约定: 所有函数返回与输入等长的列表, 前面数据不足的位置为 None。
这样 indicator[i] 永远对应 bar[i], 不会出现错位导致的未来函数。
"""
from __future__ import annotations

import math


def sma(values: list, period: int) -> list:
    out: list = [None] * len(values)
    if period <= 0:
        return out
    run = 0.0
    for i, v in enumerate(values):
        run += v
        if i >= period:
            run -= values[i - period]
        if i >= period - 1:
            out[i] = run / period
    return out


def ema(values: list, period: int) -> list:
    out: list = [None] * len(values)
    if period <= 0 or len(values) < period:
        return out
    k = 2.0 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(values: list, period: int = 14) -> list:
    out: list = [None] * len(values)
    if len(values) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = values[i] - values[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    ag, al = gains / period, losses / period
    out[period] = 100.0 if al == 0 else 100.0 - 100.0 / (1 + ag / al)
    for i in range(period + 1, len(values)):
        d = values[i] - values[i - 1]
        ag = (ag * (period - 1) + max(d, 0.0)) / period
        al = (al * (period - 1) + max(-d, 0.0)) / period
        out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1 + ag / al)
    return out


def macd(values: list, fast: int = 12, slow: int = 26, signal: int = 9):
    """返回 (dif, dea, hist)。"""
    ef, es = ema(values, fast), ema(values, slow)
    dif = [None if (ef[i] is None or es[i] is None) else ef[i] - es[i] for i in range(len(values))]
    valid = [d for d in dif if d is not None]
    offset = len(dif) - len(valid)
    dea_valid = ema(valid, signal)
    dea = [None] * offset + dea_valid
    hist = [None if (dif[i] is None or dea[i] is None) else (dif[i] - dea[i]) * 2
            for i in range(len(values))]
    return dif, dea, hist


def stdev(values: list, period: int) -> list:
    out: list = [None] * len(values)
    if period < 2:
        return out
    for i in range(period - 1, len(values)):
        window = values[i - period + 1:i + 1]
        m = sum(window) / period
        var = sum((x - m) ** 2 for x in window) / (period - 1)
        out[i] = math.sqrt(var)
    return out


def bollinger(values: list, period: int = 20, mult: float = 2.0):
    """返回 (中轨, 上轨, 下轨)。"""
    mid = sma(values, period)
    sd = stdev(values, period)
    up = [None if (mid[i] is None or sd[i] is None) else mid[i] + mult * sd[i]
          for i in range(len(values))]
    dn = [None if (mid[i] is None or sd[i] is None) else mid[i] - mult * sd[i]
          for i in range(len(values))]
    return mid, up, dn


def atr(highs: list, lows: list, closes: list, period: int = 14) -> list:
    n = len(closes)
    out: list = [None] * n
    if n <= period:
        return out
    tr = [highs[0] - lows[0]]
    for i in range(1, n):
        tr.append(max(highs[i] - lows[i],
                      abs(highs[i] - closes[i - 1]),
                      abs(lows[i] - closes[i - 1])))
    prev = sum(tr[1:period + 1]) / period
    out[period] = prev
    for i in range(period + 1, n):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


def donchian(highs: list, lows: list, period: int = 20):
    """返回 (period 根内最高, period 根内最低) —— 不含当根, 用于突破判断。"""
    n = len(highs)
    hi: list = [None] * n
    lo: list = [None] * n
    for i in range(period, n):
        hi[i] = max(highs[i - period:i])
        lo[i] = min(lows[i - period:i])
    return hi, lo


def roc(values: list, period: int = 12) -> list:
    """变动率 %。"""
    out: list = [None] * len(values)
    for i in range(period, len(values)):
        base = values[i - period]
        if base:
            out[i] = (values[i] / base - 1.0) * 100.0
    return out


def adx(highs: list, lows: list, closes: list, period: int = 14) -> list:
    """趋势强度 ADX, 用于过滤震荡市。"""
    n = len(closes)
    out: list = [None] * n
    if n < period * 2 + 1:
        return out
    plus_dm, minus_dm, tr = [0.0], [0.0], [highs[0] - lows[0]]
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        plus_dm.append(up if (up > dn and up > 0) else 0.0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0.0)
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]),
                      abs(lows[i] - closes[i - 1])))

    atr_s = sum(tr[1:period + 1])
    pdm_s = sum(plus_dm[1:period + 1])
    mdm_s = sum(minus_dm[1:period + 1])
    dx_list = []
    for i in range(period + 1, n):
        atr_s = atr_s - atr_s / period + tr[i]
        pdm_s = pdm_s - pdm_s / period + plus_dm[i]
        mdm_s = mdm_s - mdm_s / period + minus_dm[i]
        if atr_s == 0:
            continue
        pdi = 100.0 * pdm_s / atr_s
        mdi = 100.0 * mdm_s / atr_s
        s = pdi + mdi
        dx = 100.0 * abs(pdi - mdi) / s if s else 0.0
        dx_list.append((i, dx))
        if len(dx_list) == period:
            out[i] = sum(d for _, d in dx_list) / period
        elif len(dx_list) > period:
            prev = out[dx_list[-2][0]]
            if prev is not None:
                out[i] = (prev * (period - 1) + dx) / period
    return out
