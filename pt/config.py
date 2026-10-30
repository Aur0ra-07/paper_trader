"""全局配置与佣金/费用模型。"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict, field

import sys


def _app_dir() -> str:
    """账户数据该放哪。

    **绝不能放在 exe 旁边。** 那样有两条必丢数据的路径:
      1. 解压新版本覆盖旧文件夹 -> data/ 被覆盖
      2. 重新打包 (PyInstaller --clean 会整个删掉 dist/<名字>/) -> data/ 没了
    第 2 条真实发生过, 2026-09-14 弄丢了一个账户的全部成交记录。

    所以冻结运行时一律用 %LOCALAPPDATA%\\模拟炒股\\, 换版本、重装、
    重新打包都不影响。旧位置有数据的话首次启动自动搬过来。
    """
    if not getattr(sys, "frozen", False):
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    home = os.path.join(local, "模拟炒股")
    try:
        os.makedirs(home, exist_ok=True)
    except OSError:                       # 极端情况退回 exe 旁边, 总比不能用强
        return os.path.dirname(os.path.abspath(sys.executable))

    # 从旧位置 (exe 旁边) 迁移
    old = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "data")
    new = os.path.join(home, "data")
    if os.path.isdir(old):
        try:
            _migrate(old, new)
        except OSError:
            pass
    return home


def _migrate(old: str, new: str) -> None:
    """把 exe 旁边的旧数据搬到新位置。新位置已经有数据时按文件**合并**, 不是跳过。

    以前只在新位置不存在时才搬。2026-10-29 踩坑: 用户 9/17 试过一次新版,
    在新位置留下一个空账户; 之后一直用老版 exe, 真账户 (17 笔成交) 只在
    exe 旁边。直接换新版会打开那个空账户 —— 看上去就是数据全没了。

    规则: 旧位置的账户文件比新位置的新 (或新位置没有) 才拷过去, 被覆盖的那份
    先存进 backups/。用新版之后新位置一直比旧的新, 以后启动就什么都不做。
    """
    import shutil
    acc_old, acc_new = os.path.join(old, "accounts"), os.path.join(new, "accounts")
    if not os.path.exists(new):
        shutil.copytree(old, new, ignore=shutil.ignore_patterns("cache", "已搬家.txt"))
        moved = True
    else:
        moved = False
        os.makedirs(acc_new, exist_ok=True)
        for fn in sorted(os.listdir(acc_old)) if os.path.isdir(acc_old) else []:
            if not fn.endswith(".json"):
                continue
            src, dst = os.path.join(acc_old, fn), os.path.join(acc_new, fn)
            if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
                continue
            if os.path.exists(dst):
                bk = os.path.join(new, "backups")
                os.makedirs(bk, exist_ok=True)
                shutil.copy2(dst, os.path.join(bk, "%s_%s_before-migrate.json" % (
                    fn[:-5], time.strftime("%Y%m%d-%H%M%S"))))
            shutil.copy2(src, dst)
            moved = True
        if moved:
            # 旧版正在用的那个账户, 换新版后也应该还是它; 设置以用户真正在用的那份为准
            for fn in ("active.txt", "settings.json"):
                src = os.path.join(old, fn)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(new, fn))
            bo = os.path.join(old, "backups")
            if os.path.isdir(bo):
                bn = os.path.join(new, "backups")
                os.makedirs(bn, exist_ok=True)
                for fn in os.listdir(bo):
                    if not os.path.exists(os.path.join(bn, fn)):
                        shutil.copy2(os.path.join(bo, fn), os.path.join(bn, fn))
    if moved:
        with open(os.path.join(old, "已搬家.txt"), "w", encoding="utf-8") as f:
            f.write("账户数据已搬到:\n%s\n\n"
                    "放在这里是为了让它不会被新版本覆盖掉。\n"
                    "这个文件夹先别删 —— 留着当一份备份。\n" % new)


APP_DIR = _app_dir()
DATA_DIR = os.path.join(APP_DIR, "data")
ACCOUNTS_DIR = os.path.join(DATA_DIR, "accounts")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")


@dataclass
class Settings:
    # --- 行情 ---
    refresh_seconds: int = 5              # 行情轮询间隔
    include_prepost: bool = True          # 盘前盘后价格
    data_source: str = "auto"       # auto | yahoo | eastmoney
    language: str = "en"            # en | zh —— 界面语言, 由 pt/i18n.py 在启动时读取

    # --- 成交模型 ---
    slippage_bps: float = 2.0             # 市价单滑点(基点, 1bp = 0.01%)
    allow_closed_market_fill: bool = True  # 休市时市价单按最新收盘价成交(否则挂起)

    # --- 佣金模型 (IBKR Pro 风格) ---
    commission_mode: str = "per_share"    # per_share | flat | zero
    commission_per_share: float = 0.005
    commission_min: float = 1.00
    commission_max_pct: float = 0.01      # 不超过成交金额的 1%
    commission_flat: float = 0.0

    # --- 期权佣金 (按张收, IBKR/多数券商口径) ---
    option_commission_per_contract: float = 0.65
    option_commission_min: float = 1.00

    # --- 卖出侧监管费 (美股版"印花税") ---
    sec_fee_rate: float = 0.0000278       # SEC Section 31 费, 按卖出金额
    taf_per_share: float = 0.000166       # FINRA TAF, 按卖出股数
    taf_max: float = 8.30

    # --- 融资 ---
    margin_rate_annual: float = 0.06      # 融资年化利率 (杠杆回测按日计息)
    maintenance_margin: float = 0.25      # 维持保证金率, 净值低于持仓市值的这个比例就被强平

    # --- 风控规则 ---
    enforce_pdt: bool = True              # 日内交易者规则 (<$25k 限 3 次/5日)
    pdt_equity_threshold: float = 25000.0
    pdt_max_day_trades: int = 3

    # --- 界面 ---
    default_initial_cash: float = 100000.0
    color_up_is_green: bool = True         # True 绿涨红跌(美股习惯) / False 红涨绿跌(A股习惯)

    def save(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls) -> "Settings":
        if not os.path.exists(SETTINGS_PATH):
            s = cls()
            s.save()
            return s
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError):
            return cls()
        known = {f.name for f in cls.__dataclass_fields__.values()}
        s = cls(**{k: v for k, v in raw.items() if k in known})
        if "language" not in raw:
            # 没有这一项 = 英文界面出现之前的老版本存的, 那时只有中文。
            # 按默认值 en 存回去的话, 老用户换新版会突然变成看不懂的英文
            s.language = "zh"
        return s

    # ------------------------------------------------------------------
    def commission(self, shares: int, notional: float) -> float:
        """单边佣金。"""
        if self.commission_mode == "zero":
            return 0.0
        if self.commission_mode == "flat":
            return round(self.commission_flat, 2)
        c = shares * self.commission_per_share
        c = max(c, self.commission_min)
        c = min(c, notional * self.commission_max_pct)
        return round(c, 2)

    def sell_fees(self, shares: int, notional: float) -> float:
        """卖出侧监管规费 (买入为 0)。"""
        sec = notional * self.sec_fee_rate
        taf = min(shares * self.taf_per_share, self.taf_max)
        return round(sec + taf, 2)
