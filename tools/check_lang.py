# -*- coding: utf-8 -*-
"""英文翻译表校验。加了界面文字之后跑一遍:

    python tools/check_lang.py

任何一条 FAIL 都意味着运行时会崩或者显示错:
  1. 漏翻: 代码里 _tr("...") / N_("...") 用到了, 但 pt/lang/ 里没有译文
  2. 占位符不一致: {} / {:.2f} / {name} 的字段、%s / %d 的转换符, 数量、格式、
     顺序必须和原文一致 (译文用 {0}{1} 显式编号调序是允许的, 但一条里不能混用)
  3. 真跑一遍: 用假参数分别 .format() 原文和译文, 译文必须不崩
  4. 译文里残留中文
  5. 期权结算 note 必须带 options/engine.py 用来识别的关键词
另外列出 HTML 标签数、换行数不一致的条目作为警告。
"""
from __future__ import annotations

import ast
import collections
import io
import os
import re
import string
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CJK = re.compile("[一-鿿]")
PCT = re.compile(r"%[-+ #0]*\d*(?:\.\d+)?[sdifeEgGxXrc%]")
TAG = re.compile(r"</?[a-zA-Z]+[^>]*>")


def collect_keys() -> dict:
    """代码里所有 _tr / N_ 的字面量 key -> 首次出现的位置。"""
    out = {}
    base = os.path.join(ROOT, "pt")
    for dp, dn, fn in os.walk(base):
        if "__pycache__" in dp or os.path.join("pt", "lang") in dp:
            continue
        for f in sorted(fn):
            if not f.endswith(".py"):
                continue
            p = os.path.join(dp, f)
            tree = ast.parse(io.open(p, encoding="utf-8").read())
            for n in ast.walk(tree):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                        and n.func.id in ("_tr", "N_") and n.args
                        and isinstance(n.args[0], ast.Constant)
                        and isinstance(n.args[0].value, str)):
                    out.setdefault(n.args[0].value,
                                   "%s:%d" % (os.path.relpath(p, ROOT), n.lineno))
    return out


def brace_fields(s):
    try:
        return [(f, spec, conv) for _, f, spec, conv in string.Formatter().parse(s)
                if f is not None]
    except ValueError:
        return None


def pct_fields(s):
    return [m for m in PCT.findall(s) if m != "%%"]


def dummy_args(fields):
    args = []
    for _, spec, _c in fields:
        spec = spec or ""
        if spec[-1:] in tuple("fFeEgG%") or "," in spec:
            args.append(1234.5)
        elif spec[-1:] in tuple("dxXob"):
            args.append(12)
        else:
            args.append("X")
    return args


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    from pt.lang import EN

    fails, warns = [], []
    for k, v in EN.items():
        if not isinstance(v, str):
            fails.append(("译文不是字符串", k, repr(v)))
            continue
        bk, bv = brace_fields(k), brace_fields(v)
        if bk is not None:
            if bv is None:
                fails.append(("译文花括号语法错", k, v))
            else:
                explicit = any(f[0].isdigit() for f in bv if f[0])
                if explicit:
                    if sorted((f[1], f[2]) for f in bk) != sorted((f[1], f[2]) for f in bv):
                        fails.append(("{} 字段不一致 (调序)", k, v))
                elif [f[1:] for f in bk] != [f[1:] for f in bv] or \
                        [f[0] for f in bk] != [f[0] for f in bv]:
                    fails.append(("{} 字段不一致", k, v))
                if bk:
                    args = dummy_args(bk)
                    try:
                        k.format(*args)
                        try:
                            v.format(*args)
                        except (IndexError, KeyError, ValueError) as e:
                            fails.append(("译文 .format() 会崩: %s" % e, k, v))
                    except (IndexError, KeyError, ValueError):
                        pass
        # .format 字符串里的 "50% in" 不是转换符, 会被正则误认成 "% i", 所以只在
        # 原文本身带 % 转换符时才比
        if pct_fields(k) and pct_fields(k) != pct_fields(v):
            fails.append(("% 转换符不一致", k, v))
        if CJK.search(v):
            fails.append(("译文残留中文", k, v))
        if len(TAG.findall(k)) != len(TAG.findall(v)):
            warns.append(("HTML 标签数量不同", k, v))
        if k.count("\n") != v.count("\n"):
            warns.append(("换行数不同", k, v))
        if "到期作废" in k and "expired worthless" not in v.lower():
            fails.append(("缺关键词 expired worthless (options/engine.py 靠它识别)", k, v))
        if "到期实值" in k and "交割" in k and "deliver" not in v.lower():
            fails.append(("缺关键词 deliver (options/engine.py 靠它识别)", k, v))

    used = collect_keys()
    missing = {k: where for k, where in used.items() if k not in EN}
    stale = [k for k in EN if k not in used]

    print("译文 %d 条 | 代码用到 %d 条 | 未翻译 %d | 多余 %d"
          % (len(EN), len(used), len(missing), len(stale)))
    for k, where in list(missing.items())[:40]:
        print("   未翻译  %-40s %r" % (where, k[:70]))
    for k in stale[:20]:
        print("   多余    %r" % k[:80])
    for w in warns[:30]:
        print("   警告 [%s] %r" % (w[0], w[1][:70]))
    if missing:
        fails.append(("有 %d 条未翻译" % len(missing), "", ""))
    if fails:
        print("\n=== FAIL %d 条 ===" % len(fails))
        for f in fails:
            print("   [%s]\n     原: %r\n     译: %r" % f)
        return 1
    print("\n=== 翻译表校验通过 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
