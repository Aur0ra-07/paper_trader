"""期权链数据源。

抽象成 OptionDataSource 接口, 现在只有 Yahoo 一个实现。
以后要接 Polygon / ORATS 做历史回测, 实现同一个接口即可, 上层不用改。

Yahoo 的期权接口需要 cookie + crumb 鉴权 (直接请求返回 401), 这里自动处理并在
失效时重取。链数据缓存 60 秒, 到期日列表缓存 1 小时 —— 不缓存必被限流。
"""
from __future__ import annotations

import threading
import time
from datetime import date, datetime, timezone

import requests

from .models import OptionQuote, parse_occ
from .pricing import CALL, PUT
from ..i18n import _tr

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_BASE = "https://query1.finance.yahoo.com"
_FALLBACK = "https://query2.finance.yahoo.com"

CHAIN_TTL = 60.0
EXPIRY_TTL = 3600.0


class OptionDataError(Exception):
    pass


class OptionDataSource:
    """数据源接口。要接付费源时实现这几个方法即可。"""

    def expirations(self, underlying: str) -> list:
        raise NotImplementedError

    def chain(self, underlying: str, expiry: date | None = None) -> tuple:
        """返回 (底层现价, [OptionQuote, ...])。"""
        raise NotImplementedError

    def quote(self, occ_symbol: str) -> "OptionQuote | None":
        """单个合约的最新报价。"""
        raise NotImplementedError

    def supports_history(self) -> bool:
        """能否提供历史期权数据 (回测用)。Yahoo 不能。"""
        return False


class YahooOptionSource(OptionDataSource):
    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": _UA, "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9"})
        self._crumb = ""
        self._auth_at = 0.0
        self._lock = threading.Lock()
        self._chain_cache: dict = {}      # (sym, expiry_ts) -> (ts, spot, quotes)
        self._exp_cache: dict = {}        # sym -> (ts, [dates])
        self.last_error = ""

    # ------------------------------------------------------------------
    def _authenticate(self, force: bool = False) -> None:
        with self._lock:
            if not force and self._crumb and time.time() - self._auth_at < 1800:
                return
            try:
                self._session.get("https://fc.yahoo.com/", timeout=self.timeout)
            except Exception:
                pass
            try:
                self._session.get("https://finance.yahoo.com/quote/AAPL",
                                  timeout=self.timeout)
                r = self._session.get(_BASE + "/v1/test/getcrumb", timeout=self.timeout)
                crumb = (r.text or "").strip()
                if r.status_code == 200 and crumb and len(crumb) < 32:
                    self._crumb = crumb
                    self._auth_at = time.time()
                else:
                    raise OptionDataError(_tr("拿不到 crumb (HTTP {})").format(r.status_code))
            except OptionDataError:
                raise
            except Exception as exc:
                raise OptionDataError(_tr("期权接口鉴权失败: {}").format(exc))

    def _get_chain_raw(self, underlying: str, expiry_ts: int | None) -> dict:
        self._authenticate()
        params = {"crumb": self._crumb}
        if expiry_ts:
            params["date"] = int(expiry_ts)
        path = "/v7/finance/options/" + underlying.upper()

        last = None
        for attempt in range(3):
            for base in (_BASE, _FALLBACK):
                try:
                    r = self._session.get(base + path, params=params, timeout=self.timeout)
                except Exception as exc:
                    last = exc
                    continue
                if r.status_code == 200:
                    try:
                        data = r.json()
                    except ValueError:
                        last = _tr("响应不是 JSON")
                        continue
                    chain = data.get("optionChain") or {}
                    if chain.get("error"):
                        raise OptionDataError(
                            (chain["error"] or {}).get("description") or _tr("未知错误"))
                    results = chain.get("result") or []
                    if results:
                        return results[0]
                    raise OptionDataError(_tr("{} 没有期权链 (可能这只票没有期权)").format(underlying))
                if r.status_code == 401:
                    self._authenticate(force=True)
                    params["crumb"] = self._crumb
                    last = _tr("401 鉴权失效")
                elif r.status_code == 404:
                    raise OptionDataError(_tr("{} 没有期权").format(underlying))
                else:
                    last = "HTTP {}".format(r.status_code)
            time.sleep(1.5 * (attempt + 1))
        raise OptionDataError(_tr("期权链请求失败: {}").format(last))

    # ------------------------------------------------------------------
    def expirations(self, underlying: str) -> list:
        sym = underlying.upper()
        hit = self._exp_cache.get(sym)
        if hit and time.time() - hit[0] < EXPIRY_TTL:
            return hit[1]
        res = self._get_chain_raw(sym, None)
        out = []
        for ts in res.get("expirationDates") or []:
            try:
                out.append(datetime.fromtimestamp(int(ts), timezone.utc).date())
            except (ValueError, OSError):
                continue
        self._exp_cache[sym] = (time.time(), out)
        # 顺手把第一个到期日的链也缓存了, 省一次请求
        self._store_chain(sym, res)
        return out

    def _expiry_ts(self, expiry: date) -> int:
        return int(datetime(expiry.year, expiry.month, expiry.day,
                            tzinfo=timezone.utc).timestamp())

    def _store_chain(self, sym: str, res: dict) -> tuple:
        quote = res.get("quote") or {}
        spot = float(quote.get("regularMarketPrice") or 0.0)
        opts = (res.get("options") or [{}])[0]
        expiry_ts = int(opts.get("expirationDate") or 0)
        quotes = []
        for right, rows in ((CALL, opts.get("calls") or []), (PUT, opts.get("puts") or [])):
            for row in rows:
                q = _row_to_quote(row, sym, right)
                if q:
                    quotes.append(q)
        quotes.sort(key=lambda q: (q.expiry, q.strike, q.right))
        key = (sym, expiry_ts)
        self._chain_cache[key] = (time.time(), spot, quotes)
        self._chain_cache[(sym, None)] = (time.time(), spot, quotes)
        return spot, quotes

    def chain(self, underlying: str, expiry: date | None = None) -> tuple:
        sym = underlying.upper()
        key = (sym, self._expiry_ts(expiry) if expiry else None)
        hit = self._chain_cache.get(key)
        if hit and time.time() - hit[0] < CHAIN_TTL:
            return hit[1], hit[2]
        res = self._get_chain_raw(sym, key[1])
        return self._store_chain(sym, res)

    def quote(self, occ_symbol: str) -> "OptionQuote | None":
        und, expiry, right, strike = parse_occ(occ_symbol)
        if not und:
            return None
        try:
            _, quotes = self.chain(und, expiry)
        except OptionDataError as exc:
            self.last_error = str(exc)
            return None
        target = occ_symbol.upper()
        for q in quotes:
            if q.symbol.upper() == target:
                return q
        # 有些合约代码根部带后缀, 退而用到期/行权/方向匹配
        for q in quotes:
            if q.right == right and abs(q.strike - strike) < 1e-6 and q.expiry == expiry:
                return q
        return None

    def quotes(self, occ_symbols) -> dict:
        """批量取报价, 按 (底层, 到期) 分组, 每组只拉一次链。"""
        groups: dict = {}
        for s in occ_symbols:
            und, expiry, right, strike = parse_occ(s)
            if und:
                groups.setdefault((und, expiry), []).append(s.upper())
        out = {}
        for (und, expiry), syms in groups.items():
            try:
                _, quotes = self.chain(und, expiry)
            except OptionDataError as exc:
                self.last_error = str(exc)
                continue
            by_sym = {q.symbol.upper(): q for q in quotes}
            for s in syms:
                if s in by_sym:
                    out[s] = by_sym[s]
        return out

    def spot(self, underlying: str) -> float:
        try:
            s, _ = self.chain(underlying)
            return s
        except OptionDataError:
            return 0.0

    def supports_history(self) -> bool:
        return False       # 已到期合约 Yahoo 全部 404, 没法做期权回测

    def close(self) -> None:
        self._session.close()


def _row_to_quote(row: dict, underlying: str, right: str) -> "OptionQuote | None":
    sym = row.get("contractSymbol")
    if not sym:
        return None
    exp_ts = row.get("expiration")
    try:
        expiry = datetime.fromtimestamp(int(exp_ts), timezone.utc).date()
    except (TypeError, ValueError, OSError):
        _, expiry, _, _ = parse_occ(sym)
        if expiry is None:
            return None
    return OptionQuote(
        symbol=sym,
        underlying=underlying,
        right=right,
        strike=float(row.get("strike") or 0.0),
        expiry=expiry,
        bid=float(row.get("bid") or 0.0),
        ask=float(row.get("ask") or 0.0),
        last=float(row.get("lastPrice") or 0.0),
        volume=int(row.get("volume") or 0),
        open_interest=int(row.get("openInterest") or 0),
        iv=float(row.get("impliedVolatility") or 0.0),
        in_the_money=bool(row.get("inTheMoney")),
        multiplier=100 if str(row.get("contractSize") or "REGULAR") == "REGULAR" else 100,
    )
