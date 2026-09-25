"""国内可访问的行情源 —— Yahoo 在中国大陆访问不了时的备用。

为什么需要: Yahoo 2021-11-01 起停止在中国大陆提供服务, `query1.finance.yahoo.com`
在国内必须挂代理才能用。软件发给国内的人直接就是打不开行情的空壳。

**以腾讯为主, 东财只补腾讯做不到的。** 实测对比:

    能力            腾讯                东财
    报价批量        1.6s / 12只 全中     时灵时不灵, 逐个拉 22s 只成 2 只
    报价准确度      与 Yahoo 偏差 0.000%  同样准确
    日线深度        约 2000 根 (8 年)    10586 根 (42 年)
    日线价格        **真实价格**         后复权, 要额外换算回真实价
    分钟线          拿不到 (只回 1 根)    支持
    对境外 IP       稳定 3/3            K线接口直接拒, 报价也常被掐

所以: 报价走腾讯; K 线优先腾讯, 只有"超过 8 年的日线"和"分钟线"才回落到东财。

必须知道的几个坑:

1. **腾讯的历史价不含股息再投。** 实测 5 年总收益 (vs Yahoo adjclose):
       GLD (不分红)  137.7% vs 137.7%   完全一致
       SPY (股息1.3%) 71.1% vs  83.1%   少 12 pp
       TLT (股息4%)  -45.8% vs -35.4%   少 10 pp
       EFA (股息3%)   30.4% vs  52.7%   少 22 pp
   `qfq` / `hfq` / 不传参数**三者结果完全相同** —— 腾讯对美股压根不做股息复权。

2. **东财用后复权 (fqt=2), 不能用前复权 (fqt=1)** —— 前复权在长历史上会算出
   负价格 (AAPL 1984 年是 -10.485)。但后复权把近期价格放大了 (AAPL 今天是
   49847 而不是 332), 所以取回来必须按不复权的最新价换算回去。

3. **东财的股息算法和 Yahoo 也不一样**, 方向相反 —— 它比 Yahoo 高:
       XLU +40.9pp | EFA +59.2pp | TIP +24.7pp  (2005-2026)

   综合 1 和 3: **Yahoo 是基准, 国内源只是降级备份。** 本项目 PDF 里的所有
   回测数字都是 Yahoo 口径, 切到国内源后跨多年的回测会得到不同的数,
   界面上必须告诉用户 —— 这个提示不要删。

4. **东财 K 线接口必须至少间隔 1 秒**, 实测 0.5 秒只有 2/7 成功, 1.0 秒才 7/7。

5. **东财 `beg=0` 时会无视 `lmt`** —— 不管要多少根都返回全历史。所以按 range
   取数时必须自己算出起始日期传 `beg`, 并且再按根数截断兜底。
"""
from __future__ import annotations

import calendar
import threading
import time
from datetime import datetime, timezone

import requests

from .market import Candle, MarketError, Quote

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_PUSH = "https://push2.eastmoney.com"
# 腾讯的美股报价, 批量、稳定、不挑 IP。K 线它没有, 所以只用来取报价。
_TENCENT = "https://qt.gtimg.cn/q="
_TENCENT_K = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
# 腾讯 K 线一次最多约 2000 根 (5000 直接返回空), 日线 2000 根约 8 年
_TENCENT_MAX_BARS = 2000
# 本项目周期 -> 腾讯周期。分钟线腾讯只返回 1 根, 用不了, 所以不列
_TENCENT_PERIOD = {"1d": "day", "1wk": "week", "1mo": "month"}
_HIS = "https://push2his.eastmoney.com"

# 美股的三个市场号。105=NASDAQ 106=NYSE 107=AMEX/ARCA
_MARKETS = (105, 107, 106)

# 实测确认过的映射, 省掉逐个试市场号的来回 (每次试错都要 1 秒节流)。
# 没列在这里的代码会在运行时探测并缓存。
_SEED = {
    # NASDAQ
    "QQQ": 105, "TLT": 105, "IEF": 105, "SHY": 105, "SMH": 105, "SOXX": 105,
    "TQQQ": 105, "AAPL": 105, "MSFT": 105, "NVDA": 105, "TSLA": 105,
    "AMZN": 105, "GOOGL": 105, "META": 105, "AVGO": 105, "NFLX": 105,
    # AMEX / ARCA (绝大多数 ETF)
    "SPY": 107, "IWM": 107, "EFA": 107, "EEM": 107, "DBC": 107, "TIP": 107,
    "VNQ": 107, "UPRO": 107, "TNA": 107,
    "XLK": 107, "XLF": 107, "XLE": 107, "XLV": 107, "XLY": 107,
    "XLP": 107, "XLI": 107, "XLU": 107,
}

# K 线接口的最小请求间隔 (秒)。实测 1.0 才能 7/7 成功, 0.5 只有 2/7。
_KLINE_PACE = 1.05
# 报价接口也会限流 —— 开发中连续压测之后整个 IP 被 502 掉了很久。
# 自选股轮询会反复打这个接口, 宁可慢也不要被封。
_QUOTE_PACE = 0.35

# 本项目的周期代码 -> 东财 klt
_KLT = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60, "1h": 60,
        "1d": 101, "1wk": 102, "1mo": 103}

# 每个**日历日**平均有多少根 (不是每个交易日!)。美股一年约 252 个交易日,
# 所以日线是 252/365 ≈ 0.69, 不是 1 —— 按 1 算会让"5 年"的上限放到 7.3 年。
# 这组数只用来做截断兜底, 留了一点余量, 宁可多一点也不要切掉有效数据。
_BARS_PER = {"1m": 270, "5m": 54, "15m": 18, "30m": 9, "60m": 4.8,
             "1d": 0.72, "1wk": 0.15, "1mo": 0.035}
_RANGE_DAYS = {"1d": 1, "5d": 5, "1mo": 31, "3mo": 92, "6mo": 183,
               "1y": 366, "2y": 731, "5y": 1827, "10y": 3653, "20y": 7305}


def _daily_ts(date_str: str) -> int:
    """把 '2026-09-11' 转成和 Yahoo 日线对齐的时间戳。

    统一取当天 13:30 UTC (夏令时的美股开盘)。这样无论用户在美国还是中国,
    `datetime.fromtimestamp(ts)` 得到的日期都和东财给的那一天相同。
    """
    y, m, d = (int(x) for x in date_str[:10].split("-"))
    return calendar.timegm((y, m, d, 13, 30, 0, 0, 0, 0))


def _minute_ts(s: str) -> int:
    """'2026-09-12 04:00' -> 时间戳。东财分钟线给的是北京时间。"""
    dt = datetime.strptime(s[:16], "%Y-%m-%d %H:%M")
    # 北京时间 = UTC+8
    return calendar.timegm(dt.timetuple()) - 8 * 3600


class EastMoneySource:
    """只实现 MarketData 里和行情相关的那几个方法, 签名保持一致。"""

    def __init__(self, timeout: int = 20, retries: int = 5):
        self.timeout = timeout
        self.retries = retries
        # 报价要短超时少重试: 自选股每几秒轮询一次, 一只卡住就会拖垮整批。
        # 实测按 K 线那套 (20s x 5 次) 拉 9 只要 58 秒, 界面会一直是空的。
        self.quote_timeout = 6
        self.quote_retries = 2
        self._scale: dict = {}          # (代码,周期) -> (后复权->真实价 系数, 时间)
        self._quote_cache: dict = {}    # 代码 -> (Quote, 时间), 拉失败时兜底
        self._tsuffix: dict = {}        # 代码 -> 腾讯后缀 (AAPL.OQ)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _UA,
                                      "Accept": "application/json, text/plain, */*"})
        self._secid: dict = {s: "{}.{}".format(m, s) for s, m in _SEED.items()}
        self._lock = threading.Lock()
        self._next_ok: dict = {_HIS: 0.0, _PUSH: 0.0}   # 各接口下次可请求的时刻

    # ------------------------------------------------------------------
    def _throttle(self, host: str, pace: float) -> None:
        """全局节流。不加这个 K 线接口会有 32% 的请求被掐断,
        而且失败的样子长得像"代码不存在", 极容易误判。"""
        with self._lock:
            wait = self._next_ok.get(host, 0.0) - time.time()
            self._next_ok[host] = time.time() + max(wait, 0.0) + pace
        if wait > 0:
            time.sleep(wait)

    def _get(self, url: str, params: dict, pace: float = _QUOTE_PACE,
             timeout: float = 0, retries: int = 0) -> dict:
        host = _HIS if url.startswith(_HIS) else _PUSH
        timeout = timeout or self.timeout
        retries = retries or self.retries
        last = None
        for i in range(retries):
            self._throttle(host, pace)
            try:
                r = self._session.get(url, params=params, timeout=timeout)
                r.raise_for_status()
                return r.json()
            except Exception as exc:
                last = exc
                if i < retries - 1:
                    time.sleep(0.5 * (i + 1))       # 退避
        raise MarketError("东方财富请求失败: {}".format(last))

    def _resolve(self, symbol: str) -> str:
        """代码 -> secid。先查缓存/内置表, 再逐个市场号试。"""
        sym = symbol.upper().replace(".", "-")
        with self._lock:
            hit = self._secid.get(sym)
        if hit:
            return hit
        errors = 0
        for mk in _MARKETS:
            secid = "{}.{}".format(mk, sym)
            try:
                d = self._get(_PUSH + "/api/qt/stock/get",
                              {"secid": secid, "fields": "f43,f57,f58"})
                data = d.get("data") or {}
                if data and data.get("f57"):
                    with self._lock:
                        self._secid[sym] = secid
                    return secid
            except MarketError:
                errors += 1
        # 三个市场号全都是网络错误时, 不能说成"代码不存在" —— 那会让调用方
        # 以为标的有问题, 实际上只是被限流了。
        if errors == len(_MARKETS):
            raise MarketError("东方财富连不上, 无法解析 {}".format(symbol))
        raise MarketError("东方财富没有这个代码: {}".format(symbol))

    # ------------------------------------------------------------------
    def quote(self, symbol: str) -> Quote:
        """单只报价。直接复用批量那条路 —— 字段口径一致, 少维护一套解析。"""
        got = self.quotes([symbol])
        q = got.get(symbol.upper())
        if q is None:
            raise MarketError("东方财富无行情数据: {}".format(symbol))
        return q

    def _tencent_quotes(self, syms: list) -> dict:
        """腾讯批量报价。返回 {代码: Quote}, 拿不到的就不在结果里。

        格式: v_usAAPL="200~苹果~AAPL.OQ~现价~昨收~开盘~成交量~...~最高~最低~..."
        字段按 ~ 分隔, 下标见下面的常量。实测 12 只 1.6 秒, 与 Yahoo 全部一致。
        """
        if not syms:
            return {}
        r = self._session.get(_TENCENT + ",".join("us" + x for x in syms),
                              timeout=self.quote_timeout)
        r.raise_for_status()
        r.encoding = "gbk"                       # 腾讯这个接口是 GBK
        now = time.time()
        out = {}
        for line in r.text.split(";"):
            if "=" not in line or '"' not in line:
                continue
            code = line.split("=")[0].replace("v_us", "").strip().split(".")[0].upper()
            f = line.split('"')[1].split("~")
            if len(f) < 35 or code not in syms:
                continue
            px = _f(f[3])
            if px <= 0:
                continue
            out[code] = Quote(
                symbol=code, name=f[1], price=px, ext_price=px,
                prev_close=_f(f[4]), day_high=_f(f[33]), day_low=_f(f[34]),
                volume=int(_f(f[6])), currency="USD",
                exchange=(f[2].split(".")[-1] if "." in f[2] else ""),
                market_state=_market_state(now), ts=now)
        return out

    def quotes(self, symbols) -> dict:
        """批量报价 —— **一次请求拿全部**, 腾讯优先, 东财兜底。

        绝对不要逐个调单只接口: 实测 9 只自选股逐个拉要 22.4 秒而且只成功 2 只
        (东财是突发限流, 连着打几次就开始掐连接), 而界面每 5 秒就要刷一次,
        结果就是自选股永远是一片"—"。

        实测对比 (12 只):
            腾讯 qt.gtimg.cn       1.6 秒  12/12  与 Yahoo 偏差 0.000%
            东财 ulist.np          1.1 秒   9/9   但对境外 IP 时灵时不灵
            东财 逐个 stock/get     22 秒    2/9   完全不能用
        """
        syms = [x.upper() for x in dict.fromkeys(symbols) if x]
        if not syms:
            return {}
        now = time.time()

        out = {}
        # 腾讯不需要 secid, 所以**先打腾讯**再说 —— 之前先对所有标的做 _resolve
        # (要打东财并按 0.35 秒节流), 12 只要 7.4 秒; 直接走腾讯只要 1.6 秒。
        # 东财的 ulist.np 只用来补腾讯没给的那几只。
        try:
            out.update(self._tencent_quotes(syms))
        except Exception:
            pass
        secids = []
        for x in syms:
            if x in out:
                continue
            try:
                secids.append(self._resolve(x))
            except MarketError:
                pass

        if secids:
            try:
                d = self._get(_PUSH + "/api/qt/ulist.np/get", {
                    "secids": ",".join(secids),
                    "fields": "f2,f3,f4,f5,f12,f13,f14,f15,f16,f18",
                    "fltt": "2",
                }, timeout=self.quote_timeout, retries=self.quote_retries)
                diff = ((d.get("data") or {}).get("diff") or [])
                rows = diff.values() if isinstance(diff, dict) else diff
                for x in rows:
                    code = (x.get("f12") or "").upper()
                    if not code:
                        continue
                    px = _f(x.get("f2"))
                    if px <= 0:
                        continue
                    mk = int(x.get("f13") or 0)
                    q = Quote(
                        symbol=code, name=x.get("f14") or "",
                        price=px, ext_price=px,
                        prev_close=_f(x.get("f18")),
                        day_high=_f(x.get("f15")), day_low=_f(x.get("f16")),
                        volume=int(_f(x.get("f5"))),
                        currency="USD",
                        exchange={105: "NASDAQ", 106: "NYSE",
                                  107: "AMEX"}.get(mk, ""),
                        market_state=_market_state(now), ts=now)
                    out[code] = q
                    with self._lock:
                        self._quote_cache[code] = (q, now)
            except MarketError:
                pass

        # 没拿到的用上一次的结果兜底 —— 显示几十秒前的价格远好过一片空白
        for s in syms:
            if s in out:
                continue
            with self._lock:
                hit = self._quote_cache.get(s)
            if hit and now - hit[1] < 600:
                out[s] = hit[0]
        return out

    # ------------------------------------------------------------------
    def _tencent_suffix(self, symbol: str) -> str:
        """腾讯 K 线要带交易所后缀 (AAPL.OQ / SPY.AM)。

        后缀从报价接口的第 3 个字段拿, 顺手缓存 —— 报价本来就要拉, 不多花请求。
        """
        sym = symbol.upper()
        with self._lock:
            hit = self._tsuffix.get(sym)
        if hit:
            return hit
        try:
            r = self._session.get(_TENCENT + "us" + sym, timeout=self.quote_timeout)
            r.raise_for_status()
            r.encoding = "gbk"
            f = r.text.split('"')[1].split("~")
            if len(f) > 2 and "." in f[2]:
                with self._lock:
                    self._tsuffix[sym] = f[2]
                return f[2]
        except Exception:
            pass
        raise MarketError("拿不到 {} 的腾讯代码后缀".format(symbol))

    def _tencent_klines(self, symbol: str, interval: str, limit: int) -> list:
        """腾讯日/周/月线。

        为什么优先用它: 返回的就是**真实价格**(无需后复权换算), 而且对境外 IP
        也很稳 —— 东财的 K 线接口直接拒境外 IP, 报价接口也时灵时不灵。

        两个限制, 超出时调用方要回退到东财:
          * 一次最多约 2000 根 (日线约 8 年)
          * **分钟线拿不到** (只返回 1 根)
        """
        period = _TENCENT_PERIOD.get(interval)
        if not period:
            raise MarketError("腾讯不支持周期 {}".format(interval))
        code = "us" + self._tencent_suffix(symbol)
        n = min(max(int(limit), 1), _TENCENT_MAX_BARS)
        r = self._session.get(_TENCENT_K,
                              params={"param": "%s,%s,,,%d,qfq" % (code, period, n)},
                              timeout=self.timeout)
        r.raise_for_status()
        node = ((r.json().get("data") or {}).get(code) or {})
        rows = None
        for key in (period, "qfq" + period, "hfq" + period):
            v = node.get(key)
            if isinstance(v, list) and v:
                rows = v
                break
        if not rows:
            raise MarketError("腾讯没有 {} 的 K 线".format(symbol))
        out = []
        for x in rows:                      # [日期, 开, 收, 高, 低, 量]
            if len(x) < 6:
                continue
            try:
                out.append(Candle(ts=_daily_ts(x[0]), open=float(x[1]),
                                  close=float(x[2]), high=float(x[3]),
                                  low=float(x[4]), volume=int(float(x[5]))))
            except (ValueError, IndexError):
                continue
        return out

    def _scale_to_real(self, symbol: str, interval: str, adj_last: float) -> float:
        """后复权价 -> 真实价 的换算系数。

        **这是必须做的一步。** 后复权把近期价格往上缩放: AAPL 累计拆股约 148 倍,
        今天的后复权价是 49847 而真实价是 332。收益率没错, 但图表 Y 轴、下单价、
        持仓成本线全都会变成天文数字。

        做法: 额外拉一根**不复权** (fqt=0) 的最新 K 线, 用它和后复权最新价求比值,
        然后整条序列乘上去 —— 这样最后一根等于真实价, 而所有收益率保持不变
        (等价于把后复权转成前复权, 但不会像东财自带的前复权那样算出负数)。

        系数只在发生拆股/分红时变, 所以按标的缓存半天。
        """
        if adj_last <= 0:
            return 1.0
        key = (symbol.upper(), interval)
        now = time.time()
        with self._lock:
            hit = self._scale.get(key)
        if hit and now - hit[1] < 6 * 3600:
            return hit[0]
        try:
            d = self._get(_HIS + "/api/qt/stock/kline/get", {
                "secid": self._resolve(symbol), "fields1": "f1,f2,f3",
                "fields2": "f51,f53", "klt": _KLT.get(interval, 101),
                "fqt": 0, "beg": "0", "end": "20500101", "lmt": 1,
            }, pace=_KLINE_PACE)
            rows = ((d.get("data") or {}).get("klines") or [])
            real = float(rows[-1].split(",")[1]) if rows else 0.0
        except Exception:
            real = 0.0
        factor = (real / adj_last) if real > 0 else 1.0
        with self._lock:
            self._scale[key] = (factor, now)
        return factor

    def _klines(self, symbol: str, interval: str, limit: int,
                beg: str = "0", end: str = "20500101") -> list:
        klt = _KLT.get(interval)
        if klt is None:
            raise MarketError("东方财富不支持周期 {}".format(interval))
        secid = self._resolve(symbol)
        d = self._get(_HIS + "/api/qt/stock/kline/get", {
            "secid": secid,
            "fields1": "f1,f2,f3",
            "fields2": "f51,f52,f53,f54,f55,f56",   # 日期 开 收 高 低 量
            "klt": klt,
            "fqt": 2,                                # 后复权: 绝不能用 1
            "beg": beg, "end": end, "lmt": max(int(limit), 1),
        }, pace=_KLINE_PACE)
        rows = ((d.get("data") or {}).get("klines") or [])
        minute = klt < 100
        out = []
        for r in rows:
            p = r.split(",")
            if len(p) < 6:
                continue
            try:
                ts = _minute_ts(p[0]) if minute else _daily_ts(p[0])
                out.append(Candle(ts=ts, open=float(p[1]), close=float(p[2]),
                                  high=float(p[3]), low=float(p[4]),
                                  volume=int(float(p[5]))))
            except (ValueError, IndexError):
                continue
        # 后复权价要换算回真实价, 否则 AAPL 会显示成 49847 而不是 332
        if out and not minute:
            f = self._scale_to_real(symbol, interval, out[-1].close)
            if f and abs(f - 1.0) > 1e-9:
                out = [Candle(ts=c.ts, open=c.open * f, high=c.high * f,
                              low=c.low * f, close=c.close * f, volume=c.volume)
                       for c in out]
        return out

    def candles(self, symbol: str, interval: str, rng: str,
                adjusted: bool = True) -> list:
        """按 range 取 K 线。

        坑: **`beg=0` 时东财会无视 `lmt`**, 不管你要多少根都把全历史给你 ——
        实测 6mo/1y/2y/5y/10y/20y 一律返回 10586 根、回到 1984 年。所以这里
        不靠 lmt 限制, 而是把起始日期算出来传 `beg`, 并且拿到之后再按根数兜一次底。
        """
        from .market import ALL_RANGE
        if rng != ALL_RANGE:
            days = _RANGE_DAYS.get(rng) or 366
            want = int(days * _BARS_PER.get(interval, 1)) + 10
            # 腾讯优先: 真实价格、不用换算、对境外 IP 也稳。
            # 它拿不下的(超 2000 根 / 分钟线)才退回东财。
            if interval in _TENCENT_PERIOD and want <= _TENCENT_MAX_BARS:
                try:
                    out = self._tencent_klines(symbol, interval, want)
                    if out:
                        return out[-want:] if len(out) > want else out
                except Exception:
                    pass
        if rng == ALL_RANGE:
            return self._klines(symbol, interval, 100000)
        days = _RANGE_DAYS.get(rng) or 366
        start = datetime.fromtimestamp(time.time() - days * 86400, timezone.utc)
        cap = int(days * _BARS_PER.get(interval, 1)) + 10
        try:
            out = self._klines(symbol, interval, 100000,
                               beg=start.strftime("%Y%m%d"))
            # 双保险: 万一 beg 也被忽略, 按预估根数截断, 绝不能把全历史当成"5 年"
            return out[-cap:] if len(out) > cap else out
        except MarketError:
            # 东财也挂了 —— 退而求其次, 把腾讯能给的最多根数拿回来。
            # 回测拿到 8 年数据远好过一根都没有 (界面会显示实际根数)。
            if interval in _TENCENT_PERIOD:
                out = self._tencent_klines(symbol, interval, _TENCENT_MAX_BARS)
                if out:
                    return out
            raise

    def candles_between(self, symbol: str, start: int, end: int,
                        interval: str = "1d", adjusted: bool = True) -> list:
        # 区间不太长时同样先试腾讯
        span_days = max(int((end - max(start, 0)) / 86400), 1)
        want = int(span_days * _BARS_PER.get(interval, 1)) + 10
        if interval in _TENCENT_PERIOD and want <= _TENCENT_MAX_BARS and start > 0:
            try:
                out = [c for c in self._tencent_klines(symbol, interval, want)
                       if start <= c.ts <= end]
                if out:
                    return out
            except Exception:
                pass

        def fmt(t):
            return datetime.fromtimestamp(max(int(t), 0),
                                          timezone.utc).strftime("%Y%m%d")
        return self._klines(symbol, interval, 100000,
                            beg=fmt(start) if start > 0 else "0", end=fmt(end))

    # ------------------------------------------------------------------
    def search(self, query: str, limit: int = 12) -> list:
        """代码搜索 —— 只做"直接把代码解析出来"这一件事。

        东财的 suggest 接口 (type=14) 实测返回的是**用户和帖子**, 不是证券,
        拿不到可用结果; clist 接口能给全量美股, 但每页被限死 100 条,
        13809 只要 138 次请求才拉得完, 不值得为了搜索去打这么多次。

        所以这里退化成: 你输入的如果是个有效代码, 就把它解析出来; 否则返回空。
        对模拟盘的使用场景 (输入已知代码下单/看盘) 足够, 也不会误导用户。
        """
        q = (query or "").strip().upper()
        if not q or len(q) > 8 or not q.replace("-", "").replace(".", "").isalnum():
            return []
        try:
            secid = self._resolve(q)
            d = self._get(_PUSH + "/api/qt/stock/get",
                          {"secid": secid, "fields": "f57,f58"})
            data = d.get("data") or {}
            if not data.get("f57"):
                return []
            mk = int(secid.split(".")[0])
            return [{
                "symbol": (data.get("f57") or q).upper(),
                "name": data.get("f58") or "",
                "exchange": {105: "NASDAQ", 106: "NYSE", 107: "AMEX"}.get(mk, ""),
                "type": "EQUITY",
            }]
        except MarketError:
            return []

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _market_state(ts: float) -> str:
    """东财不给市场状态, 按美东时间粗略判断。"""
    if not ts:
        return "CLOSED"
    et = datetime.fromtimestamp(ts, timezone.utc).timestamp() - 4 * 3600
    h = datetime.fromtimestamp(et, timezone.utc)
    if h.weekday() >= 5:
        return "CLOSED"
    mins = h.hour * 60 + h.minute
    if 4 * 60 <= mins < 9 * 60 + 30:
        return "PRE"
    if 9 * 60 + 30 <= mins < 16 * 60:
        return "REGULAR"
    if 16 * 60 <= mins < 20 * 60:
        return "POST"
    return "CLOSED"
