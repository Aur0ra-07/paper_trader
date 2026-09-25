# -*- coding: utf-8 -*-
"""东方财富数据源全面验证 —— 需要挂回国加速器运行。

背景: 东财的 K 线接口 (push2his) 拦境外 IP, 报价接口 (push2) 不拦。
开发机在美国, 所以这一轮必须在国内线路上跑。

跑完生成两个文件 (和本程序同目录):
    东财验证报告.txt    人看的摘要
    东财验证数据.json   完整明细, 给 Claude 分析用

全程只读, 不改任何东西, 不碰账户数据。大概 3-8 分钟。
"""
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(
    sys.executable if getattr(sys, "frozen", False) else __file__))
ROOT = os.path.dirname(HERE)
if os.path.isdir(os.path.join(ROOT, "pt")):
    sys.path.insert(0, ROOT)

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
PUSH = "https://push2.eastmoney.com/api/qt/stock/get"
HIS = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{}"

# 软件实际会用到的全部标的
UNIVERSE = [
    "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB",
    "SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "SHY", "GLD", "DBC",
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "AVGO", "NFLX",
    "TQQQ", "SOXL", "SOXX", "SMH", "VNQ", "TIP", "UPRO", "TNA",
]
MARKETS = (105, 106, 107)

S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*"})

REPORT = []
DATA = {"generated_at": datetime.now().isoformat(), "sections": {}}
STATS = {"requests": 0, "failures": 0}


# Windows 控制台默认是 GBK, 打印 ✗ 之类的字符会直接抛 UnicodeEncodeError
# 把整个程序搞崩。这里统一改成 UTF-8 且遇到不认识的字符就替换, 不中断。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def say(s=""):
    # flush=True: 跑起来要几分钟, 不刷新的话用户盯着空白屏幕不知道死没死
    try:
        print(s, flush=True)
    except Exception:                 # 再兜一层, 打印失败也不能影响取数
        try:
            print(s.encode("ascii", "replace").decode("ascii"), flush=True)
        except Exception:
            pass
    REPORT.append(s)


def get(url, params, tries=5, pace=0.35):
    """东财限流凶, 退避重试, 并统计失败率。"""
    last = None
    for i in range(tries):
        STATS["requests"] += 1
        try:
            r = S.get(url, params=params, timeout=20)
            r.raise_for_status()
            time.sleep(pace)
            return r.json(), i
        except Exception as exc:
            last = exc
            STATS["failures"] += 1
            if i < tries - 1:
                time.sleep(0.7 * (i + 1))
    raise RuntimeError(str(last)[:120])


def ymd(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


# ======================================================================
def phase1_resolve():
    say("=" * 74)
    say("【1】代码解析: 每个标的在哪个市场号 (105纳斯达克/106纽交所/107美交所)")
    say("=" * 74)
    out = {}
    for sym in UNIVERSE:
        hit = None
        tried = {}
        for mk in MARKETS:
            try:
                d, _ = get(PUSH, {"secid": "%d.%s" % (mk, sym),
                                  "fields": "f43,f57,f58,f59"})
                data = d.get("data") or {}
                tried[mk] = bool(data and data.get("f57"))
                if tried[mk]:
                    hit = {"market": mk, "name": data.get("f58"),
                           "price": data.get("f43"), "decimals": data.get("f59")}
                    break
            except Exception as e:
                tried[mk] = "ERR:" + str(e)[:40]
        out[sym] = {"resolved": hit, "tried": tried}
        say("  %-6s %s" % (sym, ("%d.%s  %s  价=%s 小数位=%s" % (
            hit["market"], sym, hit["name"], hit["price"], hit["decimals"]))
            if hit else "[失败] 三个市场号都没解析出来"))
    DATA["sections"]["resolve"] = out
    say()
    return {k: v["resolved"]["market"] for k, v in out.items() if v["resolved"]}


def phase2_depth(markets):
    say("=" * 74)
    say("【2】历史深度: 东财能给多少根, 最早到哪天 (对比 Yahoo)")
    say("=" * 74)
    say("  %-6s %9s %12s %9s %12s" % ("代码", "东财根数", "东财最早", "Yahoo根数", "Yahoo最早"))
    out = {}
    for sym, mk in markets.items():
        rec = {}
        try:
            d, _ = get(HIS, {"secid": "%d.%s" % (mk, sym),
                             "fields1": "f1,f2,f3",
                             "fields2": "f51,f52,f53,f54,f55,f56",
                             "klt": 101, "fqt": 2, "beg": "0",
                             "end": "20500101", "lmt": 100000})
            k = ((d.get("data") or {}).get("klines") or [])
            rec["em_bars"] = len(k)
            rec["em_first"] = k[0].split(",")[0] if k else None
            rec["em_last"] = k[-1].split(",")[0] if k else None
        except Exception as e:
            rec["em_error"] = str(e)[:90]
        try:
            d, _ = get(YAHOO.format(sym),
                       {"interval": "1d", "period1": 0,
                        "period2": int(time.time()), "events": "div,split"},
                       tries=3, pace=0.15)
            res = ((d.get("chart") or {}).get("result") or [{}])[0]
            ts = res.get("timestamp") or []
            rec["y_bars"] = len(ts)
            rec["y_first"] = ymd(ts[0]) if ts else None
            rec["y_last"] = ymd(ts[-1]) if ts else None
        except Exception as e:
            rec["y_error"] = str(e)[:90]
        out[sym] = rec
        say("  %-6s %9s %12s %9s %12s" % (
            sym, rec.get("em_bars", "ERR"), rec.get("em_first", "-"),
            rec.get("y_bars", "ERR"), rec.get("y_first", "-")))
    DATA["sections"]["depth"] = out
    say()


def phase3_consistency(markets):
    """最关键: 后复权收益率和 Yahoo 前复权是否等价。不一致的要抓出分歧那天。"""
    say("=" * 74)
    say("【3】收益率一致性 —— 最关键的一项")
    say("=" * 74)
    say("  %-6s %8s %10s %11s %11s  %s" % (
        "代码", "重叠天", "最大日偏差", "东财总收益", "Yahoo总收益", "判定"))
    out = {}
    for sym, mk in markets.items():
        rec = {}
        try:
            d, _ = get(HIS, {"secid": "%d.%s" % (mk, sym),
                             "fields1": "f1,f2,f3",
                             "fields2": "f51,f52,f53,f54,f55,f56",
                             "klt": 101, "fqt": 2, "beg": "0",
                             "end": "20500101", "lmt": 100000})
            k = ((d.get("data") or {}).get("klines") or [])
            em = {}
            for r in k:
                p = r.split(",")
                em[p[0]] = {"o": float(p[1]), "c": float(p[2]),
                            "h": float(p[3]), "l": float(p[4])}
            d, _ = get(YAHOO.format(sym),
                       {"interval": "1d", "period1": 0,
                        "period2": int(time.time()), "events": "div,split"},
                       tries=3, pace=0.15)
            res = ((d.get("chart") or {}).get("result") or [{}])[0]
            ts = res.get("timestamp") or []
            ind = res.get("indicators") or {}
            q = (ind.get("quote") or [{}])[0]
            adj = ((ind.get("adjclose") or [{}])[0] or {}).get("adjclose") or []
            ya = {}
            for i, t in enumerate(ts):
                c = adj[i] if i < len(adj) and adj[i] is not None else (
                    q.get("close") or [None] * len(ts))[i]
                if c:
                    ya[ymd(t)] = float(c)

            common = sorted(set(em) & set(ya))
            rec["overlap"] = len(common)
            if len(common) < 50:
                rec["note"] = "重叠太少"
                say("  %-6s 重叠仅 %d 天, 跳过" % (sym, len(common)))
                out[sym] = rec
                continue
            diffs = []
            for a, b in zip(common, common[1:]):
                re_ = em[b]["c"] / em[a]["c"] - 1
                ry = ya[b] / ya[a] - 1
                diffs.append((abs(ry - re_), b, re_, ry))
            diffs.sort(reverse=True)
            mx = diffs[0][0]
            er = (em[common[-1]]["c"] / em[common[0]]["c"] - 1) * 100
            yr = (ya[common[-1]] / ya[common[0]] - 1) * 100
            ok = mx < 5e-4
            rec.update({"max_dev": mx, "em_total": er, "y_total": yr, "ok": ok,
                        "range": [common[0], common[-1]]})
            # 分歧最大的几天, 连原始数据一起记下来, 好判断是股息还是拆股
            rec["worst_days"] = [{
                "date": dt, "em_ret": r1, "y_ret": r2,
                "em_close": em[dt]["c"], "y_close": ya[dt],
                "em_prev": em[common[common.index(dt) - 1]]["c"],
                "y_prev": ya[common[common.index(dt) - 1]],
            } for _, dt, r1, r2 in diffs[:6]] if not ok else []
            say("  %-6s %8d %10.2e %10.1f%% %10.1f%%  %s" % (
                sym, len(common), mx, er, yr, "一致" if ok else "不一致 <<<"))
        except Exception as e:
            rec["error"] = str(e)[:110]
            say("  %-6s ERR %s" % (sym, str(e)[:52]))
        out[sym] = rec
    DATA["sections"]["consistency"] = out
    say()


def phase4_intraday(markets):
    say("=" * 74)
    say("【4】分钟线支持情况 (klt)")
    say("=" * 74)
    out = {}
    sym = "AAPL" if "AAPL" in markets else next(iter(markets))
    mk = markets[sym]
    for klt, name in ((1, "1分"), (5, "5分"), (15, "15分"), (30, "30分"),
                      (60, "60分"), (101, "日"), (102, "周"), (103, "月")):
        try:
            d, _ = get(HIS, {"secid": "%d.%s" % (mk, sym),
                             "fields1": "f1,f2,f3",
                             "fields2": "f51,f52,f53,f54,f55,f56",
                             "klt": klt, "fqt": 2, "beg": "0",
                             "end": "20500101", "lmt": 100000})
            k = ((d.get("data") or {}).get("klines") or [])
            out[klt] = {"bars": len(k), "first": k[0].split(",")[0] if k else None,
                        "last": k[-1].split(",")[0] if k else None,
                        "sample": k[-1] if k else None}
            say("  klt=%-3d %-4s %6d 根  %s ~ %s" % (
                klt, name, len(k), out[klt]["first"], out[klt]["last"]))
        except Exception as e:
            out[klt] = {"error": str(e)[:90]}
            say("  klt=%-3d %-4s ERR %s" % (klt, name, str(e)[:46]))
    DATA["sections"]["intraday"] = out
    say()


def phase5_search():
    say("=" * 74)
    say("【5】搜索接口 (试几个不同的域名和参数)")
    say("=" * 74)
    cands = [
        ("searchapi", "https://searchapi.eastmoney.com/api/suggest/get",
         {"input": "AAPL", "type": "14", "count": "8",
          "token": "D43BF722C8E33BDC906FB84D85E326E8"}),
        ("searchadapter", "https://searchadapter.eastmoney.com/api/suggest/get",
         {"input": "AAPL", "type": "14", "count": "8",
          "token": "D43BF722C8E33BDC906FB84D85E326E8"}),
        ("search-codetable", "https://searchapi.eastmoney.com/api/suggest/get",
         {"input": "AAPL", "type": "14", "count": "8", "applyTo": "3",
          "token": "D43BF722C8E33BDC906FB84D85E326E8", "_": str(int(time.time() * 1000))}),
        ("clist-us", "https://push2.eastmoney.com/api/qt/clist/get",
         {"pn": "1", "pz": "10", "fs": "m:105,m:106,m:107",
          "fields": "f12,f14,f13", "fid": "f3", "po": "1"}),
    ]
    out = {}
    for name, url, params in cands:
        try:
            r = S.get(url, params=params, timeout=20)
            txt = r.text.strip()
            out[name] = {"status": r.status_code, "head": txt[:400]}
            say("  [%s] %s" % (r.status_code, name))
            say("      %s" % txt[:180].replace("\n", " "))
        except Exception as e:
            out[name] = {"error": str(e)[:110]}
            say("  [ERR] %s -> %s" % (name, str(e)[:60]))
        time.sleep(0.4)
    DATA["sections"]["search"] = out
    say()


def phase6_ratelimit(markets):
    say("=" * 74)
    say("【6】限流摸底: 不同间隔下连打 K 线接口的成功率")
    say("=" * 74)
    out = {}
    syms = [s for s in ("SPY", "QQQ", "XLK", "TLT", "GLD", "IWM", "EFA", "EEM")
            if s in markets][:8]
    for pace in (0.0, 0.2, 0.5, 1.0):
        ok = 0
        t0 = time.time()
        for s in syms:
            try:
                r = S.get(HIS, params={
                    "secid": "%d.%s" % (markets[s], s), "fields1": "f1,f2,f3",
                    "fields2": "f51,f53", "klt": 101, "fqt": 2,
                    "beg": "0", "end": "20500101", "lmt": 300}, timeout=20)
                if r.status_code == 200 and (r.json().get("data") or {}).get("klines"):
                    ok += 1
            except Exception:
                pass
            time.sleep(pace)
        out["pace_%.1f" % pace] = {"ok": ok, "total": len(syms),
                                   "seconds": round(time.time() - t0, 1)}
        say("  间隔 %.1fs -> %d/%d 成功, 用时 %.1fs" % (
            pace, ok, len(syms), time.time() - t0))
        time.sleep(1.5)
    DATA["sections"]["ratelimit"] = out
    say()


def main():
    say("=" * 74)
    say("  东方财富数据源验证")
    say("=" * 74)
    say("时间: %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    try:
        r = S.get(YAHOO.format("AAPL"),
                  params={"interval": "1d", "range": "5d"}, timeout=15)
        say("Yahoo 可达: 是 (%d)" % r.status_code)
    except Exception as e:
        say("Yahoo 可达: 否 —— %s" % str(e)[:70])
    say()

    markets = phase1_resolve()
    if not markets:
        say("一个代码都没解析出来 —— 大概率是没挂上国内线路, 后面不用跑了。")
        return
    phase2_depth(markets)
    phase3_consistency(markets)
    phase4_intraday(markets)
    phase5_search()
    phase6_ratelimit(markets)

    say("=" * 74)
    say("  总计")
    say("=" * 74)
    say("  发出请求 %d 次, 其中失败 %d 次 (失败率 %.0f%%)" % (
        STATS["requests"], STATS["failures"],
        STATS["failures"] / max(STATS["requests"], 1) * 100))
    DATA["stats"] = STATS


if __name__ == "__main__":
    try:
        main()
    except Exception:
        say("\n跑崩了:\n" + traceback.format_exc())
    txt = os.path.join(HERE, "东财验证报告.txt")
    js = os.path.join(HERE, "东财验证数据.json")
    try:
        with open(txt, "w", encoding="utf-8") as f:
            f.write("\n".join(REPORT))
        with open(js, "w", encoding="utf-8") as f:
            json.dump(DATA, f, ensure_ascii=False, indent=1)
        print()
        print("报告: %s" % txt)
        print("明细: %s" % js)
    except Exception as e:
        print("写文件失败: %s" % e)
    print()
    try:
        input("跑完了, 按回车关闭 —— 然后可以关掉加速器回来找 Claude。")
    except (EOFError, KeyboardInterrupt):
        pass
