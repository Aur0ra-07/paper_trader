"""Black-Scholes 定价、隐含波动率反解、希腊字母、概率计算。

重要前提: 这里的 BS 只用来算**希腊字母和概率**, 不用来给期权定价 ——
定价一律用市场真实的 bid/ask。原因是实测过: 用历史波动率合成的 BS 价格
和真实成交价的中位误差 24%, 虚值期权 51%, 拿来当价格用是自欺欺人。
但反过来, 用**市场 IV** 算希腊字母是准确的, 因为那正是市场自己的定价参数。
"""
from __future__ import annotations

import math
from datetime import date, datetime

CALL = "C"
PUT = "P"

DEFAULT_RATE = 0.04          # 无风险利率近似
SECONDS_PER_YEAR = 365.0 * 86400


def _nd(x: float) -> float:
    """标准正态累积分布。"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def year_fraction(expiry: date, now: datetime | None = None) -> float:
    """到期剩余年数。到期日当天按收盘 16:00 算。"""
    now = now or datetime.now()
    end = datetime(expiry.year, expiry.month, expiry.day, 16, 0, 0)
    secs = (end - now).total_seconds()
    return max(secs, 0.0) / SECONDS_PER_YEAR


def _d1d2(S: float, K: float, T: float, sigma: float, r: float, q: float):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return None, None
    vt = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + sigma * sigma / 2.0) * T) / vt
    return d1, d1 - vt


def bs_price(S: float, K: float, T: float, sigma: float, right: str,
             r: float = DEFAULT_RATE, q: float = 0.0) -> float:
    """理论价。到期或波动率为 0 时退化为内在价值。"""
    d1, d2 = _d1d2(S, K, T, sigma, r, q)
    if d1 is None:
        return intrinsic(S, K, right)
    if right == CALL:
        return S * math.exp(-q * T) * _nd(d1) - K * math.exp(-r * T) * _nd(d2)
    return K * math.exp(-r * T) * _nd(-d2) - S * math.exp(-q * T) * _nd(-d1)


def intrinsic(S: float, K: float, right: str) -> float:
    return max(S - K, 0.0) if right == CALL else max(K - S, 0.0)


def implied_vol(price: float, S: float, K: float, T: float, right: str,
                r: float = DEFAULT_RATE, q: float = 0.0) -> float:
    """从市场价反解隐含波动率 (二分法, 稳定压倒速度)。"""
    if price <= 0 or T <= 0 or S <= 0:
        return 0.0
    intr = intrinsic(S, K, right)
    if price <= intr + 1e-9:
        return 0.0
    lo, hi = 1e-4, 5.0
    if bs_price(S, K, T, hi, right, r, q) < price:
        return hi
    for _ in range(64):
        mid = (lo + hi) / 2.0
        if bs_price(S, K, T, mid, right, r, q) > price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2.0


def greeks(S: float, K: float, T: float, sigma: float, right: str,
           r: float = DEFAULT_RATE, q: float = 0.0) -> dict:
    """希腊字母。theta 已换算成「每天」, vega 换算成「波动率每涨 1 个百分点」。"""
    d1, d2 = _d1d2(S, K, T, sigma, r, q)
    if d1 is None:
        # 到期瞬间: delta 是 0 或 1, 其余为 0
        itm = (S > K) if right == CALL else (S < K)
        return {"delta": (1.0 if right == CALL else -1.0) if itm else 0.0,
                "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

    disc_q = math.exp(-q * T)
    disc_r = math.exp(-r * T)
    pdf = _npdf(d1)
    sqrtT = math.sqrt(T)

    if right == CALL:
        delta = disc_q * _nd(d1)
        theta = (-S * disc_q * pdf * sigma / (2 * sqrtT)
                 - r * K * disc_r * _nd(d2) + q * S * disc_q * _nd(d1))
        rho = K * T * disc_r * _nd(d2) / 100.0
    else:
        delta = -disc_q * _nd(-d1)
        theta = (-S * disc_q * pdf * sigma / (2 * sqrtT)
                 + r * K * disc_r * _nd(-d2) - q * S * disc_q * _nd(-d1))
        rho = -K * T * disc_r * _nd(-d2) / 100.0

    return {
        "delta": delta,
        "gamma": disc_q * pdf / (S * sigma * sqrtT),
        "theta": theta / 365.0,              # 每天
        "vega": S * disc_q * pdf * sqrtT / 100.0,   # 每 1 个波动率百分点
        "rho": rho,
    }


# ----------------------------------------------------------------------
def prob_itm(S: float, K: float, T: float, sigma: float, right: str,
             r: float = DEFAULT_RATE, q: float = 0.0) -> float:
    """到期时变成实值的概率 (风险中性测度下)。"""
    d1, d2 = _d1d2(S, K, T, sigma, r, q)
    if d1 is None:
        itm = (S > K) if right == CALL else (S < K)
        return 1.0 if itm else 0.0
    return _nd(d2) if right == CALL else _nd(-d2)


def prob_above(S: float, target: float, T: float, sigma: float,
               r: float = DEFAULT_RATE, q: float = 0.0) -> float:
    """到期时股价高于 target 的概率。"""
    if T <= 0 or sigma <= 0 or S <= 0 or target <= 0:
        return 1.0 if S > target else 0.0
    vt = sigma * math.sqrt(T)
    d2 = (math.log(S / target) + (r - q - sigma * sigma / 2.0) * T) / vt
    return _nd(d2)


def breakeven(strike: float, premium: float, right: str) -> float:
    """买方的到期盈亏平衡价 (每股权利金)。"""
    return strike + premium if right == CALL else strike - premium


def expected_move(S: float, T: float, sigma: float) -> float:
    """±1 个标准差的价格波动幅度 (美元)。"""
    if T <= 0 or sigma <= 0:
        return 0.0
    return S * sigma * math.sqrt(T)


def analyze(S: float, K: float, T: float, sigma: float, right: str,
            premium: float, qty: int = 1, r: float = DEFAULT_RATE) -> dict:
    """给一笔「买入期权」的完整赔率画像。premium = 每股权利金。"""
    g = greeks(S, K, T, sigma, right, r)
    be = breakeven(K, premium, right)
    p_itm = prob_itm(S, K, T, sigma, right, r)
    p_profit = prob_above(S, be, T, sigma, r) if right == CALL else (
        1.0 - prob_above(S, be, T, sigma, r))
    cost = premium * 100 * max(qty, 1)
    return {
        "greeks": g,
        "breakeven": be,
        "breakeven_move_pct": (be / S - 1.0) * 100.0 if S else 0.0,
        "prob_itm": p_itm * 100.0,
        "prob_profit": p_profit * 100.0,
        "max_loss": cost,                    # 买方最多亏光权利金
        "theta_per_day": g["theta"] * 100 * max(qty, 1),
        "expected_move": expected_move(S, T, sigma),
        "days_left": T * 365.0,
        "cost": cost,
    }


def payoff_at_expiry(legs: list, spot: float) -> float:
    """多腿组合在到期价 spot 时的总损益 (美元)。

    legs: [{"right": "C"/"P"/"S", "strike": K, "qty": 正=买入/负=卖出,
            "premium": 每股权利金, "multiplier": 100}]
    right 为 "S" 表示正股腿 (strike 当作买入成本)。
    """
    total = 0.0
    for leg in legs:
        qty = leg.get("qty", 0)
        mult = leg.get("multiplier", 100)
        prem = leg.get("premium", 0.0)
        right = leg.get("right", CALL)
        K = leg.get("strike", 0.0)
        if right == "S":
            total += qty * (spot - K)
            continue
        value = intrinsic(spot, K, right)
        total += qty * (value - prem) * mult
    return total
