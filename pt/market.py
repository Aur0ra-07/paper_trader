"""实时行情数据源 (Yahoo Finance 公开接口, 无需 API key)。"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Iterable

import requests

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_BASE = "https://query1.finance.yahoo.com"
_FALLBACK = "https://query2.finance.yahoo.com"


@dataclass
class Quote:
    symbol: str
    name: str = ""
    price: float = 0.0              # 最新价 (常规时段)
    ext_price: float = 0.0          # 含盘前/盘后的最新价
    prev_close: float = 0.0
    day_high: float = 0.0
    day_low: float = 0.0
    volume: int = 0
    currency: str = "USD"
    exchange: str = ""
    market_state: str = "CLOSED"    # PRE | REGULAR | POST | CLOSED
    ts: float = 0.0                 # 行情时间戳 (epoch)
    fetched_at: float = field(default_factory=time.time)

    @property
    def change(self) -> float:
        return self.price - self.prev_close if self.prev_close else 0.0

    @property
    def change_pct(self) -> float:
        return (self.change / self.prev_close * 100.0) if self.prev_close else 0.0

    @property
    def ext_change_pct(self) -> float:
        if not self.price or not self.ext_price:
            return 0.0
        return (self.ext_price - self.price) / self.price * 100.0

    @property
    def tradable_price(self) -> float:
        """撮合用价格: 盘前盘后用延伸价, 否则用常规价。"""
        if self.market_state in ("PRE", "POST") and self.ext_price > 0:
            return self.ext_price
        return self.price or self.ext_price


@dataclass
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: int


class MarketError(Exception):
    pass


# 哨兵: 表示"能拉多少拉多少"。不能用接口的 range="max" ——
# 实测日线传 max 只回 405 根 (被降采样成月线), 真正的全历史要走 period1/period2。
ALL_RANGE = "__all__"


class MarketData:
    """行情客户端 (requests.Session 线程安全复用 + 并发批量报价)。"""

    # (接口周期代码, 默认 range)
    INTERVALS = {
        "1分": ("1m", "5d"),
        "5分": ("5m", "1mo"),
        "15分": ("15m", "1mo"),
        "60分": ("60m", "2y"),
        "日线": ("1d", "5y"),
        "周线": ("1wk", "20y"),
    }

    # 每个周期**实测**可用的 range 档位 (标签, range)。
    # 注意 range="max" 是个陷阱: 日线/周线传 max 只会返回 405 根, 因为接口
    # 会偷偷降采样成月线。要真正的全历史必须走 period1/period2, 见 ALL_RANGE。
    RANGES = {
        "1m":  [("1 天", "1d"), ("5 天", "5d")],
        "5m":  [("5 天", "5d"), ("1 个月", "1mo")],
        "15m": [("1 个月", "1mo")],
        "60m": [("3 个月", "3mo"), ("1 年", "1y"), ("2 年", "2y")],
        "1d":  [("6 个月", "6mo"), ("1 年", "1y"), ("2 年", "2y"), ("5 年", "5y"),
                ("10 年", "10y"), ("20 年", "20y"), ("全部历史", ALL_RANGE)],
        "1wk": [("5 年", "5y"), ("10 年", "10y"), ("20 年", "20y"),
                ("全部历史", ALL_RANGE)],
    }

    def __init__(self, include_prepost: bool = True, timeout: int = 12):
        self.include_prepost = include_prepost
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _UA, "Accept": "application/json"})
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="mkt")
        self._search_cache: dict[str, list[dict]] = {}
        self._screener_cache: dict[str, tuple[float, list[dict]]] = {}
        self._screener_lock = threading.Lock()
        self._last_screener_call = 0.0
        # -- 数据源兜底状态 --
        self.fallback_enabled = True
        self.source_mode = "auto"           # auto | yahoo | eastmoney
        self.active_source = "yahoo"        # 最近一次成功取数用的是谁
        self.last_fallback_reason = ""
        self._fb = None
        self._y_fails = 0
        self._y_cold_until = 0.0

    # ------------------------------------------------------------------
    def _get(self, path: str, params: dict) -> dict:
        last = None
        for base in (_BASE, _FALLBACK):
            try:
                r = self._session.get(base + path, params=params, timeout=self.timeout)
                if r.status_code == 404:
                    raise MarketError("代码不存在")
                r.raise_for_status()
                return r.json()
            except MarketError:
                raise
            except Exception as exc:          # 网络抖动时切备用域名
                last = exc
        raise MarketError("行情请求失败: {}".format(last))

    # ------------------------------------------------------------------
    def _y_quote(self, symbol: str) -> Quote:
        data = self._get(
            "/v8/finance/chart/" + symbol.upper(),
            {"interval": "1m", "range": "1d",
             "includePrePost": "true" if self.include_prepost else "false"},
        )
        chart = data.get("chart") or {}
        if chart.get("error"):
            raise MarketError(chart["error"].get("description") or "未知错误")
        results = chart.get("result") or []
        if not results:
            raise MarketError("无行情数据")
        m = results[0].get("meta") or {}

        price = _f(m.get("regularMarketPrice"))
        prev = _f(m.get("previousClose")) or _f(m.get("chartPreviousClose"))
        ext = _f(m.get("fulldayPrice")) or price

        return Quote(
            symbol=(m.get("symbol") or symbol).upper(),
            name=m.get("longName") or m.get("shortName") or "",
            price=price,
            ext_price=ext,
            prev_close=prev,
            day_high=_f(m.get("regularMarketDayHigh")),
            day_low=_f(m.get("regularMarketDayLow")),
            volume=int(m.get("regularMarketVolume") or 0),
            currency=m.get("currency") or "USD",
            exchange=m.get("fullExchangeName") or m.get("exchangeName") or "",
            market_state=_market_state(m),
            ts=float(m.get("regularMarketTime") or 0),
        )

    def _y_quotes(self, symbols: Iterable[str]) -> dict[str, Quote]:
        syms = [s.upper() for s in dict.fromkeys(symbols) if s]
        if not syms:
            return {}
        out: dict[str, Quote] = {}
        for sym, res in zip(syms, self._pool.map(self._y_safe_quote, syms)):
            if res is not None:
                out[sym] = res
        # 一个都没拿到 = Yahoo 整体不可用, 必须抛出去让 _dispatch 切备用源。
        # 以前这里静默返回空字典, 导致批量报价永远走不到兜底。
        if not out:
            raise MarketError("Yahoo 批量报价全部失败")
        return out

    def _y_safe_quote(self, symbol: str) -> "Quote | None":
        """只走 Yahoo, 不经过兜底 —— 否则线程池里每个标的都会各自去打东财。"""
        try:
            return self._y_quote(symbol)
        except Exception:
            return None


    # ------------------------------------------------------------------
    def _y_candles(self, symbol: str, interval: str, rng: str,
                adjusted: bool = True) -> list[Candle]:
        """adjusted=True 时返回前复权价 (含股息再投), 回测请务必用这个。

        rng 传 ALL_RANGE 时改走 period1/period2 拉全历史 —— 接口的 range="max"
        会降采样成月线 (日线只剩 405 根), 拿不到真正的全部日线。
        """
        from . import cache
        if rng == ALL_RANGE:
            # 1970 会被接口自动收敛到该标的的实际上市日。
            # 终点按 TTL 对齐取整 —— 否则每次调用 end 都不同, 缓存键秒秒在变,
            # 既永远不命中又会无限堆积缓存文件。
            step = max(cache.TTL.get(interval, 3600), 60)
            end = int(time.time()) // step * step
            return self.candles_between(symbol, 0, end,
                                        interval=interval, adjusted=adjusted)
        prepost = self.include_prepost and interval.endswith("m")
        params = {"interval": interval, "range": rng,
                  "includePrePost": "true" if prepost else "false"}
        if adjusted:
            params["events"] = "div,split"
        data = self._get("/v8/finance/chart/" + symbol.upper(), params)
        chart = data.get("chart") or {}
        if chart.get("error"):
            raise MarketError(chart["error"].get("description") or "未知错误")
        results = chart.get("result") or []
        if not results:
            return []
        return _parse_candles(results[0], adjusted)

    # ==================================================================
    # 数据源兜底: Yahoo 打不通时自动切国内源 (腾讯为主, 东财补缺)
    #
    # Yahoo 2021-11-01 起停止对中国大陆服务, query1.finance.yahoo.com 在国内
    # 必须挂代理。软件发给国内的人, 不兜底就是一个打不开行情的空壳。
    #
    # 注意国内源的**股息处理和 Yahoo 都不一样**: 腾讯压根不算股息 (SPY 5 年少 12pp),
    # 东财算但算法不同 (XLU 21 年多 41pp)。所以永远优先 Yahoo, 只在它真的不可用
    # 时才降级, 并且要让界面能告诉用户当前用的是哪家。
    # ==================================================================
    def set_source_mode(self, mode: str) -> None:
        """auto = 优先 Yahoo 失败降级 / yahoo = 只用 Yahoo / eastmoney = 只用东财。

        需要"只用东财"这个选项, 是因为挂回国加速器时 Yahoo 往往还是直连可用
        (分流模式), "自动"根本走不到备用源, 就没法在本地验证备用源好不好使。
        """
        mode = mode if mode in ("auto", "yahoo", "eastmoney") else "auto"
        self.source_mode = mode
        self.fallback_enabled = mode != "yahoo"
        self._y_fails = 0
        # 强制东财 = 让 Yahoo 永远处于冷却期; 其余模式立即解除冷却
        self._y_cold_until = float("inf") if mode == "eastmoney" else 0.0
        # active_source 要立刻跟上, 否则状态栏会在下一次轮询之前一直显示旧的源,
        # 用户刚改完设置看到的还是原来那个, 会以为没生效。
        # auto 模式下一次调用一定先试 Yahoo, 所以乐观地标成 yahoo;
        # 真失败了 _dispatch 会把它改回 eastmoney。
        self.active_source = "eastmoney" if mode == "eastmoney" else "yahoo"

    def _fallback(self):
        if self._fb is None and self.fallback_enabled:
            from .eastmoney import EastMoneySource
            self._fb = EastMoneySource()
        return self._fb

    def _dispatch(self, name: str, *args, **kw):
        now = time.time()
        # Yahoo 连续失败后先记一段"冷却期", 免得每次调用都白等一轮超时
        if not (self._y_cold_until > now):
            try:
                out = getattr(self, "_y_" + name)(*args, **kw)
                self._y_fails = 0
                self.active_source = "yahoo"
                return out
            except MarketError as exc:
                if not self.fallback_enabled:
                    raise
                self._y_fails += 1
                self.last_fallback_reason = str(exc)[:160]
                if self._y_fails >= 3:
                    self._y_cold_until = now + 120.0
        fb = self._fallback()
        if fb is None:
            raise MarketError("Yahoo 不可用, 且备用源已关闭")
        out = getattr(fb, name)(*args, **kw)
        self.active_source = "eastmoney"
        return out

    def quote(self, symbol: str) -> Quote:
        return self._dispatch("quote", symbol)

    def quotes(self, symbols) -> dict:
        return self._dispatch("quotes", symbols)

    def candles(self, symbol: str, interval: str, rng: str,
                adjusted: bool = True) -> list:
        return self._dispatch("candles", symbol, interval, rng, adjusted=adjusted)

    def candles_between(self, symbol: str, start: int, end: int,
                        interval: str = "1d", adjusted: bool = True) -> list:
        return self._dispatch("candles_between", symbol, start, end,
                              interval=interval, adjusted=adjusted)

    def search(self, query: str, limit: int = 12) -> list:
        return self._dispatch("search", query, limit)

    def screener(self, scr_id: str, count: int = 100) -> list:
        # 榜单是 Yahoo 独有的, 东财没有对应接口 —— 降级成空列表而不是报错,
        # 否则整个"市场"页会打不开。
        try:
            return self._dispatch("screener", scr_id, count)
        except (MarketError, AttributeError):
            return []

    def candles_cached(self, symbol: str, interval: str, rng: str,
                       adjusted: bool = True) -> list[Candle]:
        """带本地缓存的滚动区间 K 线 (回测专用, 避免反复拉同一段被限流)。"""
        from . import cache
        tag = "r:{}{}".format(rng, ":adj" if adjusted else "")
        hit = cache.load(symbol, interval, tag)
        if hit:
            return hit
        data = self.candles(symbol, interval, rng, adjusted=adjusted)
        cache.store(symbol, interval, tag, data)
        return data

    def _y_candles_between(self, symbol: str, start: int, end: int,
                        interval: str = "1d", adjusted: bool = True) -> list[Candle]:
        """任意历史区间 (epoch 秒)。可以取到 1998 年, 用来测熊市。

        adjusted=True (默认) 返回前复权价 —— 长期回测必须用复权价, 不然
        高股息标的会被低估几十到几百个百分点。
        """
        from . import cache
        tag = "p:{}-{}{}".format(int(start), int(end), ":adj" if adjusted else "")
        permanent = end < time.time() - 86400          # 已完结的历史区间不会再变
        hit = cache.load(symbol, interval, tag, permanent=permanent)
        if hit:
            return hit

        params = {"interval": interval, "period1": int(start), "period2": int(end)}
        if adjusted:
            params["events"] = "div,split"
        data = self._get("/v8/finance/chart/" + symbol.upper(), params)
        chart = data.get("chart") or {}
        if chart.get("error"):
            raise MarketError(chart["error"].get("description") or "未知错误")
        results = chart.get("result") or []
        if not results:
            return []
        out = _parse_candles(results[0], adjusted)
        cache.store(symbol, interval, tag, out)
        return out

    # ------------------------------------------------------------------
    def _y_search(self, query: str, limit: int = 12) -> list[dict]:
        query = (query or "").strip()
        if not query:
            return []
        key = query.lower()
        if key in self._search_cache:
            return self._search_cache[key]
        try:
            data = self._get("/v1/finance/search",
                             {"q": query, "quotesCount": limit, "newsCount": 0,
                              "enableFuzzyQuery": "false"})
        except MarketError:
            return []
        rows = []
        for it in data.get("quotes", []):
            sym = it.get("symbol")
            if not sym:
                continue
            rows.append({
                "symbol": sym,
                "name": it.get("longname") or it.get("shortname") or "",
                "type": it.get("quoteType") or "",
                "exchange": it.get("exchDisp") or it.get("exchange") or "",
            })
        self._search_cache[key] = rows
        return rows

    def _y_screener(self, scr_id: str, count: int = 100) -> list[dict]:
        """Yahoo 预置榜单 (涨幅榜/成交活跃等)。带 90 秒缓存与节流, 避免 429。"""
        now = time.time()
        hit = self._screener_cache.get(scr_id)
        if hit and now - hit[0] < 90:
            return hit[1]

        with self._screener_lock:
            gap = time.time() - self._last_screener_call
            if gap < 1.2:
                time.sleep(1.2 - gap)
            self._last_screener_call = time.time()
            try:
                data = self._get("/v1/finance/screener/predefined/saved",
                                 {"scrIds": scr_id, "count": count, "start": 0})
            except MarketError:
                if hit:
                    return hit[1]          # 限流时退回旧缓存
                raise

        results = ((data.get("finance") or {}).get("result") or [])
        if not results:
            return []
        rows = []
        for q in results[0].get("quotes", []):
            sym = q.get("symbol")
            if not sym:
                continue
            rows.append({
                "symbol": sym,
                "name": q.get("shortName") or q.get("longName") or "",
                "price": _f(q.get("regularMarketPrice")),
                "change_pct": _f(q.get("regularMarketChangePercent")),
                "volume": int(q.get("regularMarketVolume") or 0),
                "market_cap": int(q.get("marketCap") or 0),
            })
        self._screener_cache[scr_id] = (time.time(), rows)
        return rows

    def close(self) -> None:
        self._pool.shutdown(wait=False)
        self._session.close()


# ----------------------------------------------------------------------
def _parse_candles(res: dict, adjusted: bool = True) -> list:
    """把 Yahoo 的原始响应转成 Candle 列表。

    如果响应里带了 adjclose (前复权收盘价), 就用它, 并按同样的比例缩放 O/H/L ——
    否则像 TLT(年化息 4%)、XLU 这种高股息标的的长期回测会被严重低估:
    实测 TLT 2005-2026 不复权 -9%, 复权后 +85%。
    """
    stamps = res.get("timestamp") or []
    ind = res.get("indicators") or {}
    q = (ind.get("quote") or [{}])[0]
    o = q.get("open") or []
    h = q.get("high") or []
    l = q.get("low") or []
    c = q.get("close") or []
    v = q.get("volume") or []
    adj = (((ind.get("adjclose") or [{}])[0] or {}).get("adjclose") or []) if adjusted else []

    out: list = []
    last_close = None
    for i, t in enumerate(stamps):
        close = _pick(c, i)
        if close is None:
            close = last_close
        if close is None:
            continue
        last_close = close
        op, hi, lo = _pick(o, i), _pick(h, i), _pick(l, i)
        op = op if op is not None else close
        hi = hi if hi is not None else close
        lo = lo if lo is not None else close

        a = _pick(adj, i)
        if a is not None and close > 0:
            f = a / close
            op, hi, lo, close = op * f, hi * f, lo * f, a

        out.append(Candle(
            ts=int(t),
            open=op, high=hi, low=lo, close=close,
            volume=int(_pick(v, i) or 0),
        ))
    return out


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _pick(arr, i):
    if i < len(arr):
        v = arr[i]
        if v is not None:
            return float(v)
    return None


def _market_state(meta: dict) -> str:
    period = ((meta.get("currentTradingPeriod") or {}).get("regular") or {})
    start, end = period.get("start"), period.get("end")
    now = time.time()
    if not start or not end:
        return "CLOSED"
    if start <= now < end:
        return "REGULAR"
    # 盘前: 常规开盘前 5.5 小时内; 盘后: 收盘后 4 小时内
    if start - 5.5 * 3600 <= now < start:
        return "PRE"
    if end <= now < end + 4 * 3600:
        return "POST"
    return "CLOSED"
