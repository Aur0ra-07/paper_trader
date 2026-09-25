"""K 线本地缓存。

回测会把同一批 K 线反复拉很多遍, 不缓存必被 Yahoo 限流。
- 固定历史区间 (period1/period2 都在过去): 永久有效, 历史不会变
- 滚动区间 (range=10y 这种): 日线缓存到下一个交易日, 分钟线缓存 5 分钟
"""
from __future__ import annotations

import hashlib
import json
import os
import time

from .config import DATA_DIR

CACHE_DIR = os.path.join(DATA_DIR, "cache")

TTL = {"1m": 300, "5m": 600, "15m": 900, "60m": 3600, "1d": 6 * 3600, "1wk": 12 * 3600}


def _key(symbol: str, interval: str, tag: str) -> str:
    raw = "{}|{}|{}".format(symbol.upper(), interval, tag)
    h = hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]
    safe = "".join(ch for ch in symbol.upper() if ch.isalnum() or ch in "-_")[:12]
    return os.path.join(CACHE_DIR, "{}_{}_{}.json".format(safe, interval, h))


def load(symbol: str, interval: str, tag: str, permanent: bool = False):
    path = _key(symbol, interval, tag)
    if not os.path.exists(path):
        return None
    if not permanent:
        age = time.time() - os.path.getmtime(path)
        if age > TTL.get(interval, 3600):
            return None
    try:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    from .market import Candle
    return [Candle(ts=r[0], open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5])
            for r in rows]


def store(symbol: str, interval: str, tag: str, candles: list) -> None:
    if not candles:
        return
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _key(symbol, interval, tag)
    rows = [[c.ts, c.open, c.high, c.low, c.close, c.volume] for c in candles]
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rows, f, separators=(",", ":"))
        os.replace(tmp, path)
    except OSError:
        pass


def clear() -> int:
    if not os.path.isdir(CACHE_DIR):
        return 0
    n = 0
    for fn in os.listdir(CACHE_DIR):
        try:
            os.remove(os.path.join(CACHE_DIR, fn))
            n += 1
        except OSError:
            pass
    return n


def size_mb() -> float:
    if not os.path.isdir(CACHE_DIR):
        return 0.0
    total = 0
    for fn in os.listdir(CACHE_DIR):
        try:
            total += os.path.getsize(os.path.join(CACHE_DIR, fn))
        except OSError:
            pass
    return total / 1024 / 1024
