"""自动交易执行器。

把回测里验证过的同一份策略代码接到模拟账户上。关键设计:

* **只用已收盘的 K 线发信号** —— 盘中那根还在变, 用它等于偷看未来。
* **风控在策略之外** —— 单票上限、最大持仓数、止损、回撤熔断由执行层统一管,
  策略只负责说"我想做多还是空仓"。
* **每个决策都留痕** —— 什么时候、因为什么指标、做了什么, 全部写进日志。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime

from ..config import DATA_DIR
from ..engine import TradingEngine, ET, et_date
from ..models import Order, BUY, SELL, SHORT, COVER, MARKET, SIDE_CN
from . import allocator, presets
from .library import create, REGISTRY
from ..i18n import N_, _tr

CONFIG_PATH = os.path.join(DATA_DIR, "autotrader.json")
LOG_PATH = os.path.join(DATA_DIR, "autotrader_log.jsonl")

HOLD = "HOLD"

SINGLE, PORTFOLIO = "single", "portfolio"
MAX_LEVERAGE = 2.0                  # 组合模式杠杆上限 = Reg T 初始保证金
MODE_CN = {SINGLE: _tr("单标的择时"), PORTFOLIO: _tr("核心-卫星组合")}


@dataclass
class RiskLimits:
    max_position_pct: float = 20.0      # 单只标的最多占净值
    max_positions: int = 5              # 最多同时持有几只
    stop_loss_pct: float = 8.0          # 单笔止损 (0=关闭)
    take_profit_pct: float = 0.0        # 单笔止盈 (0=关闭)
    max_trades_per_day: int = 10
    halt_drawdown_pct: float = 20.0     # 组合回撤超过此值就停机 (0=关闭)
    allow_short: bool = False


@dataclass
class Decision:
    symbol: str
    action: str                 # BUY / SELL / SHORT / COVER / HOLD
    qty: int = 0
    price: float = 0.0
    current_dir: int = 0
    target_dir: int = 0
    reason: str = ""
    indicator: str = ""
    blocked: str = ""           # 非空表示被风控拦下
    signal_ts: int = 0

    @property
    def actionable(self) -> bool:
        return self.action != HOLD and self.qty > 0 and not self.blocked


@dataclass
class AutoConfig:
    enabled: bool = False
    strategy_key: str = "ma_cross"
    params: dict = field(default_factory=dict)
    symbols: list = field(default_factory=list)
    interval: str = "1d"            # 信号周期
    check_seconds: int = 300        # 多久评估一次
    dry_run: bool = True            # True=只给建议不下单
    risk: dict = field(default_factory=lambda: asdict(RiskLimits()))

    # -- 组合模式 --
    mode: str = SINGLE              # SINGLE=单标的择时 / PORTFOLIO=核心-卫星组合
    preset: str = N_("进取 · 核心65 + QQQ35")
    rebalance_band_pct: float = 2.0  # 权重偏离目标超过这么多个百分点才动手
    leverage: float = 1.0           # 目标权重整体乘这个倍数; >1 = 融资, 现金账户强制 1

    def sleeves(self) -> list:
        return presets.by_name(self.preset)

    def watch_symbols(self) -> list:
        """这一轮需要拉 K 线的全部代码。"""
        if self.mode != PORTFOLIO:
            return list(self.symbols)
        out = []
        for sl in self.sleeves():
            for s in sl.symbols:
                if s not in out:
                    out.append(s)
        return out

    def limits(self) -> RiskLimits:
        base = asdict(RiskLimits())
        base.update(self.risk or {})
        return RiskLimits(**{k: v for k, v in base.items() if k in base})

    def save(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls) -> "AutoConfig":
        if not os.path.exists(CONFIG_PATH):
            return cls()
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError):
            return cls()
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in raw.items() if k in known})


# ======================================================================
def signal_index(candles: list, interval: str, market_state: str) -> int:
    """最后一根**已收盘**K线的下标。盘中那根正在形成, 不能用。"""
    n = len(candles)
    if n < 2:
        return -1
    last = candles[-1]
    if interval == "1d":
        forming = (et_date(last.ts) == et_date(time.time())
                   and market_state in ("REGULAR", "PRE"))
    elif interval == "1wk":
        now = datetime.now(ET)
        bar = datetime.fromtimestamp(last.ts, ET)
        forming = bar.isocalendar()[:2] == now.isocalendar()[:2]
    else:
        forming = market_state == "REGULAR"
    return n - 2 if forming else n - 1


class AutoTrader:
    def __init__(self, config: AutoConfig):
        self.config = config
        self.log: list = []
        self.halted = False
        self.halt_reason = ""
        self.peak_equity = 0.0
        self.last_run = 0.0
        self.last_plan = None      # 组合模式最近一次算出的目标权重

    # ------------------------------------------------------------------
    def _check_halt(self, engine: TradingEngine, prices: dict) -> float:
        """更新峰值并判断是否触发回撤熔断, 返回当前权益。"""
        lim = self.config.limits()
        acc = engine.account
        equity = acc.equity(prices)
        self.peak_equity = max(self.peak_equity, equity, acc.initial_cash)
        if lim.halt_drawdown_pct > 0 and self.peak_equity > 0:
            dd = (self.peak_equity - equity) / self.peak_equity * 100.0
            if dd >= lim.halt_drawdown_pct:
                self.halted = True
                self.halt_reason = _tr("组合回撤 {:.1f}% 触及熔断线 {:.0f}%").format(
                    dd, lim.halt_drawdown_pct)
        return equity

    def evaluate_portfolio(self, candles_by_symbol: dict, quotes: dict,
                           engine: TradingEngine, prices: dict) -> list:
        """组合模式: 算出每个标的的目标权重, 和现有持仓比对, 补差额。

        和单标的模式的关键区别 —— 这里的仓位是**比例**而不是有无:

        * 仓位大小由组合权重决定, 所以 `max_position_pct` / `max_positions`
          在这个模式下不适用 (组合本来就要同时拿 8-12 只)。
        * 不挂单笔止损/止盈 —— 止损卖掉之后再平衡又会买回来, 只会来回磨损。
          组合的风控是**分散 + 回撤熔断**, 不是单票止损。
        * 只有偏离目标超过 `rebalance_band_pct` 才动手, 否则每天都会产生碎单。
        """
        cfg = self.config
        lim = cfg.limits()
        acc = engine.account
        equity = self._check_halt(engine, prices)

        sleeves = cfg.sleeves()
        if not sleeves:
            return [Decision(_tr("组合"), HOLD, reason=_tr("找不到预设「{}」").format(cfg.preset),
                             blocked=_tr("预设缺失"))]

        # 只用已收盘的 K 线发信号 (不变量 3)
        idx = {}
        for sym, candles in candles_by_symbol.items():
            if candles:
                q = quotes.get(sym)
                idx[sym] = signal_index(candles, cfg.interval,
                                        q.market_state if q else "CLOSED")
        plan = allocator.plan(sleeves, candles_by_symbol, idx, lim.allow_short)
        if not plan.ok:
            return [Decision(_tr("组合"), HOLD, reason=plan.error, blocked=_tr("组合无法解析"))]
        self.last_plan = plan

        # 杠杆: 权重整体放大, 借的钱按 margin_rate_annual 计息 (engine.accrue_margin_interest)。
        # 上限 2 倍是 Reg T 初始保证金 —— 再高 buying_power 也给不了。
        lev = 1.0 if acc.account_type == "CASH" else min(max(cfg.leverage, 1.0), MAX_LEVERAGE)
        # round: 0.6 * 1.5 = 0.8999999..., 不取整的话 180 股会算成 179 股
        targets = {s: round(w * lev, 9) for s, w in plan.targets.items()}

        band = max(cfg.rebalance_band_pct, 0.0) / 100.0
        today = et_date(time.time())
        trades_today = sum(1 for t in acc.trades if et_date(t.ts) == today)
        avail_bp = acc.buying_power(prices) - engine.reserved_buying_power()

        held = {p.symbol for p in acc.open_positions()}
        decisions = []
        # 先卖后买: 腾出现金再建仓, 否则购买力不够会白白拦掉买单
        rows = []
        for sym in sorted(set(targets) | held):
            q = quotes.get(sym)
            px = q.tradable_price if q else prices.get(sym, 0.0)
            pos = engine.position(sym)
            tgt_w = targets.get(sym, 0.0)
            cur_w = (pos.qty * px / equity) if equity > 0 and px > 0 else 0.0
            rows.append((sym, px, pos, tgt_w, cur_w, tgt_w - cur_w))
        rows.sort(key=lambda r: r[5])          # 差额从负到正 = 先卖后买

        for sym, px, pos, tgt_w, cur_w, diff_w in rows:
            cur_dir = 0 if pos.qty == 0 else (1 if pos.qty > 0 else -1)
            d = Decision(sym, HOLD, price=px, current_dir=cur_dir,
                         target_dir=1 if tgt_w > 0 else 0,
                         indicator=_tr("目标 {:.1f}% / 当前 {:.1f}%").format(
                             tgt_w * 100, cur_w * 100))
            if px <= 0:
                d.reason, d.blocked = _tr("拿不到价格"), _tr("无行情")
                decisions.append(d)
                continue

            if pos.qty < 0:                     # 组合模式不做空, 先平掉
                d.action, d.qty = COVER, pos.abs_qty
                d.reason = _tr("组合模式不持空头, 平仓")
            elif tgt_w <= 0 and pos.qty > 0:
                d.action, d.qty = SELL, pos.abs_qty
                d.reason = _tr("已不在目标持仓里, 清仓")
            elif pos.qty == 0 and tgt_w > 0 and int((tgt_w * equity) // px) >= 1:
                # 容忍带管的是"已有仓位要不要调", 不该拦住建仓 ——
                # 否则目标权重比容忍带还小的支柱(比如 3.2% 配 3.5pp 带)永远建不上。
                d.action, d.qty = BUY, int((tgt_w * equity) // px)
                d.reason = _tr("建仓到目标权重 {:.1f}%").format(tgt_w * 100)
            elif abs(diff_w) < band:
                d.reason = _tr("偏离 {:+.1f}pp, 在 ±{:.1f}pp 容忍带内, 不动").format(
                    diff_w * 100, band * 100)
            else:
                want_qty = int((tgt_w * equity) // px)
                delta = want_qty - pos.qty
                if delta == 0:
                    d.reason = _tr("差额不足 1 股")
                elif delta > 0:
                    d.action, d.qty = BUY, delta
                    d.reason = _tr("权重低了 {:.1f}pp, 补到 {:.1f}%").format(
                        -diff_w * 100 if diff_w < 0 else diff_w * 100, tgt_w * 100)
                else:
                    d.action, d.qty = SELL, -delta
                    d.reason = _tr("权重高了 {:.1f}pp, 减到 {:.1f}%").format(
                        -diff_w * 100, tgt_w * 100)

            if d.action != HOLD:
                if self.halted:
                    d.blocked = self.halt_reason
                elif trades_today >= lim.max_trades_per_day:
                    d.blocked = _tr("今日交易已达上限 {} 笔").format(lim.max_trades_per_day)
                elif d.action == BUY and d.qty * px > avail_bp:
                    d.qty = max(int(avail_bp // px), 0)
                    if d.qty < 1:
                        d.blocked = _tr("购买力不足")
                if d.actionable:                # 额度在批内逐条扣减 (不变量 4)
                    trades_today += 1
                    avail_bp += (-d.qty * px if d.action == BUY else d.qty * px)
            decisions.append(d)
        return decisions

    def evaluate(self, candles_by_symbol: dict, quotes: dict,
                 engine: TradingEngine, prices: dict) -> list:
        """跑一轮策略, 返回决策列表 (不下单)。"""
        if self.config.mode == PORTFOLIO:
            return self.evaluate_portfolio(candles_by_symbol, quotes, engine, prices)
        cfg = self.config
        lim = cfg.limits()
        acc = engine.account
        equity = self._check_halt(engine, prices)

        decisions: list = []
        today = et_date(time.time())
        # 这一批决策是一次性生成、随后一起执行的, 所以额度必须在批内逐条扣减,
        # 否则 5 个标的会各自看到"还没开仓", 一起冲进去把上限撑爆。
        trades_today = sum(1 for t in acc.trades if et_date(t.ts) == today)
        open_count = len(acc.open_positions())
        avail_bp = acc.buying_power(prices) - engine.reserved_buying_power()

        for sym in cfg.symbols:
            candles = candles_by_symbol.get(sym) or []
            q = quotes.get(sym)
            px = q.tradable_price if q else 0.0
            pos = engine.position(sym)
            cur_dir = 0 if pos.qty == 0 else (1 if pos.qty > 0 else -1)

            if len(candles) < 10 or px <= 0:
                decisions.append(Decision(sym, HOLD, current_dir=cur_dir,
                                          reason=_tr("数据不足"), blocked=_tr("无行情/K线")))
                continue

            i = signal_index(candles, cfg.interval, q.market_state if q else "CLOSED")
            strat = create(cfg.strategy_key, **(cfg.params or {}))
            if i < strat.warmup():
                decisions.append(Decision(sym, HOLD, current_dir=cur_dir,
                                          reason=_tr("K线不足以预热该策略"), blocked=_tr("预热不足")))
                continue
            strat.prepare(candles)
            try:
                # 从预热点重放到信号点, 让带状态的策略(如 RSI 回归)状态正确
                tgt = 0
                for k in range(strat.warmup(), i + 1):
                    tgt = strat.target(k)
                note = strat.explain(i)
            except Exception as exc:
                decisions.append(Decision(sym, HOLD, current_dir=cur_dir,
                                          reason=_tr("策略出错: {}").format(exc), blocked=_tr("策略异常")))
                continue

            if not lim.allow_short and tgt < 0:
                tgt = 0

            d = Decision(sym, HOLD, price=px, current_dir=cur_dir, target_dir=tgt,
                         indicator=note, signal_ts=candles[i].ts)

            # -- 先看单笔止损/止盈 (优先于策略信号) --
            forced = self._forced_exit(pos, px, lim)
            if forced and cur_dir != 0:
                d.action = COVER if cur_dir < 0 else SELL
                d.qty = pos.abs_qty
                d.reason = forced
            elif tgt == cur_dir:
                d.reason = _tr("维持现状 ({})").format(
                    {1: _tr("持多"), 0: _tr("空仓"), -1: _tr("持空")}[cur_dir])
            elif cur_dir != 0 and tgt != cur_dir:
                d.action = COVER if cur_dir < 0 else SELL
                d.qty = pos.abs_qty
                d.reason = _tr("策略信号转向: {}").format(note)
            else:
                budget = equity * (lim.max_position_pct / 100.0)
                qty = int(budget // px) if px > 0 else 0
                d.action = BUY if tgt > 0 else SHORT
                d.qty = qty
                d.reason = _tr("策略信号建仓: {}").format(note)

            # -- 风控拦截 (额度在批内逐条扣减) --
            if d.action != HOLD:
                if self.halted:
                    d.blocked = self.halt_reason
                elif trades_today >= lim.max_trades_per_day:
                    d.blocked = _tr("今日交易已达上限 {} 笔").format(lim.max_trades_per_day)
                elif d.action in (BUY, SHORT):
                    if open_count >= lim.max_positions:
                        d.blocked = _tr("持仓数已达上限 {} 只").format(lim.max_positions)
                    elif d.qty < 1:
                        d.blocked = _tr("按 {:.0f}% 仓位上限算出来不足 1 股").format(lim.max_position_pct)
                    elif d.qty * px > avail_bp:
                        d.qty = max(int(avail_bp // px), 0)
                        if d.qty < 1:
                            d.blocked = _tr("购买力不足")

                if d.actionable:
                    trades_today += 1
                    if d.action in (BUY, SHORT):
                        open_count += 1
                        avail_bp -= d.qty * px
                    else:
                        open_count = max(open_count - 1, 0)
                        avail_bp += d.qty * px
            decisions.append(d)

        return decisions

    def _forced_exit(self, pos, px: float, lim: RiskLimits) -> str:
        if pos.qty == 0 or not pos.avg_cost:
            return ""
        pct = pos.unrealized_pct(px)
        if lim.stop_loss_pct > 0 and pct <= -lim.stop_loss_pct:
            return _tr("触发止损 ({:.1f}% ≤ -{:.0f}%)").format(pct, lim.stop_loss_pct)
        if lim.take_profit_pct > 0 and pct >= lim.take_profit_pct:
            return _tr("触发止盈 ({:.1f}% ≥ {:.0f}%)").format(pct, lim.take_profit_pct)
        return ""

    # ------------------------------------------------------------------
    def execute(self, decisions: list, engine: TradingEngine, quotes: dict,
                prices: dict) -> list:
        """把可执行的决策下成市价单。返回日志行。"""
        out = []
        for d in decisions:
            if not d.actionable:
                continue
            q = quotes.get(d.symbol)
            if not q:
                continue
            order = Order(symbol=d.symbol, side=d.action, qty=d.qty, order_type=MARKET)
            ok, msg = engine.submit(order, q, prices)
            entry = {
                "ts": time.time(), "symbol": d.symbol, "action": d.action,
                "qty": d.qty, "ok": ok, "message": msg, "reason": d.reason,
                "indicator": d.indicator, "strategy": self.config.strategy_key,
            }
            out.append(entry)
            self.log.append(entry)
            _append_log(entry)
        self.last_run = time.time()
        return out

    def reset_halt(self) -> None:
        self.halted = False
        self.halt_reason = ""
        self.peak_equity = 0.0


def _append_log(entry: dict) -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def read_log(limit: int = 300) -> list:
    if not os.path.exists(LOG_PATH):
        return []
    try:
        with open(LOG_PATH, encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out
