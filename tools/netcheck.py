# -*- coding: utf-8 -*-
"""行情连通性自检 —— 在目标电脑上双击运行, 看哪些行情源能用。

只用 Python 标准库, 不依赖任何第三方包, 所以打包出来只有几 MB。

为什么需要它: 这个软件的行情全部来自 Yahoo Finance。国内网络能不能访问
Yahoo 无法在开发机上验证, 反过来国内的备用源也会拒绝境外 IP。与其闭着眼睛
写一个没法验证的备用数据源, 不如先在真机上测一遍。

结果会同时打印到屏幕和写进同目录的 行情连通性报告.txt。
"""
import json
import os
import platform
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT = 12

# (分类, 名称, URL, 额外请求头, 判定函数)
def _yahoo_ok(body):
    d = json.loads(body)
    res = ((d.get("chart") or {}).get("result") or [])
    if not res:
        return False, "返回里没有数据"
    ts = (res[0].get("timestamp") or [])
    meta = res[0].get("meta") or {}
    return True, "{} 最新价 {}, {} 根K线".format(
        meta.get("symbol", "?"), meta.get("regularMarketPrice", "?"), len(ts))


def _tencent_ok(body):
    if "v_usAAPL=" not in body:
        return False, "格式不对"
    parts = body.split('"')[1].split("~")
    return True, "{} 最新价 {}".format(parts[1] if len(parts) > 1 else "?",
                                     parts[3] if len(parts) > 3 else "?")


def _sina_ok(body):
    if "hq_str_gb_aapl" not in body:
        return False, "格式不对"
    parts = body.split('"')[1].split(",")
    return True, "{} 最新价 {}".format(parts[0] if parts else "?",
                                     parts[1] if len(parts) > 1 else "?")


def _em_quote_ok(body):
    d = json.loads(body).get("data") or {}
    if not d:
        return False, "返回里没有数据"
    return True, "{} 最新价 {}".format(d.get("f58", "?"), d.get("f43", "?") / 1000.0
                                     if isinstance(d.get("f43"), (int, float)) else "?")


def _em_kline_ok(body):
    d = json.loads(body).get("data") or {}
    k = d.get("klines") or []
    if not k:
        return False, "返回里没有K线"
    return True, "{} 根, 最早 {}, 最新 {}".format(
        len(k), k[0].split(",")[0], k[-1].split(",")[0])


TESTS = [
    ("主数据源 (软件现在用的)", "Yahoo 报价",
     "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1m&range=1d",
     {}, _yahoo_ok),
    ("主数据源 (软件现在用的)", "Yahoo 日K (10年)",
     "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1d&range=10y",
     {}, _yahoo_ok),
    ("主数据源 (软件现在用的)", "Yahoo 备用域名",
     "https://query2.finance.yahoo.com/v8/finance/chart/SPY?interval=1d&range=1mo",
     {}, _yahoo_ok),
    ("备用源候选", "腾讯 报价",
     "https://qt.gtimg.cn/q=usAAPL", {}, _tencent_ok),
    ("备用源候选", "新浪 报价",
     "https://hq.sinajs.cn/list=gb_aapl",
     {"Referer": "https://finance.sina.com.cn"}, _sina_ok),
    ("备用源候选", "东方财富 报价",
     "https://push2.eastmoney.com/api/qt/stock/get?secid=105.AAPL&fields=f43,f57,f58",
     {}, _em_quote_ok),
    ("备用源候选", "东方财富 日K (最关键)",
     "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=105.AAPL"
     "&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56&klt=101&fqt=2"
     "&beg=0&end=20500101&lmt=20", {}, _em_kline_ok),
]


def fetch(url, headers):
    req = urllib.request.Request(url, headers=dict({"User-Agent": UA}, **headers))
    ctx = ssl.create_default_context()
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as r:
        raw = r.read()
    ms = (time.time() - t0) * 1000
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(enc), ms
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), ms


def run_one(url, headers, check, tries=3):
    """同一个地址试几次 —— 一次失败可能只是网络抖动。"""
    best_ms, last_err, oks = None, "", 0
    detail = ""
    for _ in range(tries):
        try:
            body, ms = fetch(url, headers)
            ok, info = check(body)
            if ok:
                oks += 1
                detail = info
                best_ms = ms if best_ms is None else min(best_ms, ms)
            else:
                last_err = info
        except urllib.error.HTTPError as e:
            last_err = "HTTP {}".format(e.code)
        except urllib.error.URLError as e:
            last_err = "连不上: {}".format(getattr(e, "reason", e))
        except socket.timeout:
            last_err = "超时 (>{}秒)".format(TIMEOUT)
        except Exception as e:
            last_err = "{}: {}".format(type(e).__name__, e)
        time.sleep(0.4)
    return oks, tries, best_ms, detail, last_err


def main():
    lines = []

    def out(s=""):
        print(s)
        lines.append(s)

    out("=" * 66)
    out("  行情连通性自检")
    out("=" * 66)
    out("时间: {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    out("系统: {} {}".format(platform.system(), platform.release()))
    try:
        out("主机: {}".format(socket.gethostname()))
    except Exception:
        pass
    out()

    results = {}
    group = None
    for cat, name, url, headers, check in TESTS:
        if cat != group:
            group = cat
            out("-" * 66)
            out(cat)
            out("-" * 66)
        sys.stdout.write("  测试 {} …\r".format(name))
        sys.stdout.flush()
        oks, tries, ms, detail, err = run_one(url, headers, check)
        results[name] = oks > 0
        if oks:
            out("  [通] {:<22} {:>6.0f}ms  {}/{} 次成功".format(name, ms, oks, tries))
            if detail:
                out("       {}".format(detail))
        else:
            out("  [×]  {:<22} 全部失败 —— {}".format(name, err))
        out()

    out("=" * 66)
    out("  结论")
    out("=" * 66)
    yahoo = any(v for k, v in results.items() if k.startswith("Yahoo"))
    backups = [k for k, v in results.items() if v and not k.startswith("Yahoo")]
    if yahoo:
        out("  Yahoo 可以访问 —— 软件能直接用, 不需要备用数据源。")
    else:
        out("  Yahoo 访问不了 —— 软件现在的状态是打不开行情的。")
        if backups:
            out("  但下面这些备用源是通的, 可以改造软件去用它们:")
            for b in backups:
                out("    · {}".format(b))
            if not results.get("东方财富 日K (最关键)"):
                out("  注意: 报价通了但**历史K线没通**, 那么回测和策略都用不了,")
                out("        只能看实时价格。需要另找K线源。")
        else:
            out("  而且所有备用源也都不通 —— 可能是整体网络问题, 或者有代理/防火墙。")
            out("  建议: 换个网络环境再测一次。")
    out()
    out("把这份报告发回去, 就能决定下一步怎么做。")

    path = os.path.join(os.path.dirname(os.path.abspath(
        sys.executable if getattr(sys, "frozen", False) else __file__)),
        "行情连通性报告.txt")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        out()
        out("报告已保存: {}".format(path))
    except Exception as e:
        out("(报告没能写进文件: {})".format(e))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
    print()
    try:
        input("按回车键关闭…")
    except (EOFError, KeyboardInterrupt):
        pass
