"""策略页: 回测 / 参数优化 / 自动交易 / AI 建议。"""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import asdict
from datetime import datetime

import pyqtgraph as pg
from PyQt6 import QtCore, QtGui, QtWidgets

from .. import universe
from ..market import ALL_RANGE, MarketData
from ..models import SIDE_CN, BUY, SELL, SHORT, COVER, MARKET, LIMIT, Order
from ..strategy import backtest as bt
from ..strategy import autotrader as auto
from ..strategy import briefing, library, optimizer, presets
from ..strategy.autotrader import AutoConfig, AutoTrader, RiskLimits, HOLD
from ..strategy.backtest import BacktestConfig
from . import theme
from .panels import Card, NumItem, make_table, cell, fill_table, LEFT, RIGHT, CENTER
from .chart import MoneyAxis
from .portfolio_tab import PortfolioTab
from .rotation_tab import RotationPanel, RobustnessPanel, WindowDistWidget
from ..i18n import _tr

# (显示名, range 码) —— 从短到长, 下面的封顶逻辑依赖这个顺序
RANGES = [(_tr("1 年"), "1y"), (_tr("2 年"), "2y"), (_tr("5 年"), "5y"), (_tr("10 年"), "10y"),
          (_tr("20 年"), "20y"), (_tr("全部历史"), ALL_RANGE)]
RANGE_CODES = [c for _, c in RANGES]
INTERVALS = [(_tr("日线"), "1d"), (_tr("周线"), "1wk"), (_tr("60分"), "60m")]
# 各周期实测能拉到的上限 (日线/周线可以到上市当天)
INTERVAL_RANGE_LIMIT = {"60m": "2y", "1wk": ALL_RANGE, "1d": ALL_RANGE}


# ======================================================================
class ParamEditor(QtWidgets.QWidget):
    """按策略的参数表动态生成输入控件。"""

    changed = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.form = QtWidgets.QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setSpacing(6)
        self.widgets: dict = {}

    def set_strategy(self, key: str, values: dict | None = None) -> None:
        while self.form.count():
            it = self.form.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.widgets.clear()
        values = values or {}
        for p in library.REGISTRY[key].param_specs():
            v = values.get(p.key, p.default)
            if p.kind == "bool":
                w = QtWidgets.QCheckBox()
                w.setChecked(bool(v))
                w.stateChanged.connect(self.changed)
            elif p.kind == "float":
                w = QtWidgets.QDoubleSpinBox()
                w.setRange(p.lo, p.hi)
                w.setSingleStep(p.step)
                w.setDecimals(2)
                w.setValue(float(v))
                w.valueChanged.connect(self.changed)
            else:
                w = QtWidgets.QSpinBox()
                w.setRange(int(p.lo), int(p.hi))
                w.setSingleStep(max(int(p.step), 1))
                w.setValue(int(v))
                w.valueChanged.connect(self.changed)
            self.widgets[p.key] = w
            self.form.addRow(p.label, w)

    def values(self) -> dict:
        out = {}
        for k, w in self.widgets.items():
            if isinstance(w, QtWidgets.QCheckBox):
                out[k] = w.isChecked()
            else:
                out[k] = w.value()
        return out

    def set_values(self, values: dict) -> None:
        for k, v in (values or {}).items():
            w = self.widgets.get(k)
            if w is None:
                continue
            if isinstance(w, QtWidgets.QCheckBox):
                w.setChecked(bool(v))
            else:
                w.setValue(v)


# ======================================================================
class BacktestWorker(QtCore.QThread):
    done = QtCore.pyqtSignal(object, dict)
    failed = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(str)

    def __init__(self, market, settings, parent=None):
        super().__init__(parent)
        self.market = market
        self.settings = settings
        self.job = None

    def start_job(self, symbols, strategy_key, params, interval, rng, cfg):
        self.job = (symbols, strategy_key, params, interval, rng, cfg)
        self.start()

    def run(self):
        if not self.job:
            return
        symbols, key, params, interval, rng, cfg = self.job
        try:
            data = {}
            for n, s in enumerate(symbols, 1):
                self.progress.emit(_tr("拉取 {} 的 K 线… ({}/{})").format(s, n, len(symbols)))
                try:
                    c = self.market.candles(s, interval, rng)
                    if c:
                        data[s] = c
                except Exception:
                    continue
                time.sleep(0.2)
            if not data:
                self.failed.emit(_tr("没有拿到任何 K 线数据"))
                return
            self.progress.emit(_tr("回测中…"))
            if len(data) == 1:
                sym = next(iter(data))
                res = bt.run(data[sym], library.create(key, **params),
                             self.settings, cfg, sym)
                self.done.emit(res, {sym: res})
            else:
                combo, singles = bt.run_portfolio(data, key, params, self.settings, cfg)
                self.done.emit(combo, singles)
        except Exception as exc:
            self.failed.emit(_tr("回测失败: {}").format(exc))


class OptimizeWorker(QtCore.QThread):
    done = QtCore.pyqtSignal(list, str)
    failed = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(int, int)

    def __init__(self, market, settings, parent=None):
        super().__init__(parent)
        self.market = market
        self.settings = settings
        self.job = None
        self._stop = False

    def start_job(self, symbol, key, interval, rng, cfg, metric, points):
        self.job = (symbol, key, interval, rng, cfg, metric, points)
        self._stop = False
        self.start()

    def stop(self):
        self._stop = True

    def run(self):
        if not self.job:
            return
        symbol, key, interval, rng, cfg, metric, points = self.job
        try:
            candles = self.market.candles(symbol, interval, rng)
            if len(candles) < 300:
                self.failed.emit(
                    _tr("{} 只有 {} 根 K 线, 做训练/验证切分至少需要约 300 根 —— "
                    "换更长的区间或更短的周期").format(symbol, len(candles)))
                return
            rows, note = optimizer.grid_search(
                candles, key, self.settings, cfg, metric=metric, points=points,
                progress=lambda a, b: self.progress.emit(a, b),
                should_stop=lambda: self._stop)
            self.done.emit(rows, note)
        except Exception as exc:
            self.failed.emit(_tr("优化失败: {}").format(exc))


class AutoEvalWorker(QtCore.QThread):
    """自动交易: 后台拉 K 线**和报价**, 主线程做决策与下单。

    报价必须自己拉 —— 主窗口只轮询自选股, 而组合模式要盯十几只 ETF,
    光有 K 线没有报价, 决策全会卡在"拿不到价格"上。
    """
    ready = QtCore.pyqtSignal(dict, dict)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, market, parent=None):
        super().__init__(parent)
        self.market = market
        self.job = None

    def start_job(self, symbols, interval, rng):
        if self.isRunning():
            return False
        self.job = (symbols, interval, rng)
        self.start()
        return True

    def run(self):
        symbols, interval, rng = self.job
        data = {}
        for s in symbols:
            try:
                c = self.market.candles(s, interval, rng)
                if c:
                    data[s] = c
            except Exception:
                continue
            time.sleep(0.15)
        quotes = {}
        try:
            quotes = self.market.quotes(list(data)) or {}
        except Exception:
            pass
        if data:
            self.ready.emit(data, quotes)
        else:
            self.failed.emit(_tr("没拿到 K 线, 本轮跳过"))


# ======================================================================
# 回测结果区的版式。上面两块 (图表 / 绩效指标) 固定, 下面两块可互相挤压。
_STACK_GAP = 8          # 各块之间的间距
_TRADES_FLOOR = 96      # 交易明细至少这么高, 否则连表头带一行都看不全
_DIST_FLOOR = 110       # 收益分布至少这么高 (表头 + 一行 + 脚注)
_CHART_FLOOR = 160      # 净值曲线至少这么高
_CHART_SHARE = 5        # 图表 : 下方分割器 = 5 : 6, 窗口变大按这个比例一起长
_SPLIT_SHARE = 6


class StrategyTab(QtWidgets.QWidget):
    trades_executed = QtCore.pyqtSignal()
    status = QtCore.pyqtSignal(str)

    def __init__(self, market: MarketData, settings, get_context, parent=None):
        super().__init__(parent)
        self.market = market
        self.settings = settings
        self.get_context = get_context      # () -> (account, engine, quotes, prices)

        self.auto_config = AutoConfig.load()
        self.autotrader = AutoTrader(self.auto_config)
        self.last_result = None
        self.last_singles = {}
        self.opt_rows = []
        self.decisions = []
        self.ai_decisions = []

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        wl = lambda: self.get_context()[0].watchlist
        self.rotation_panel = RotationPanel(market, settings, wl)
        self.rotation_panel.status.connect(self.status)
        self.robust_panel = RobustnessPanel(market, settings, wl)
        self.robust_panel.status.connect(self.status)

        self.inner = QtWidgets.QTabWidget()
        self.inner.addTab(self._build_backtest(), _tr("单标的回测"))
        self.inner.addTab(self.rotation_panel, _tr("动量轮动"))
        self.portfolio_panel = PortfolioTab(market, settings)
        self.portfolio_panel.status.connect(self.status)
        self.inner.addTab(self.portfolio_panel, _tr("组合"))
        self.inner.addTab(self.robust_panel, _tr("稳健性测试"))
        self.inner.addTab(self._build_optimize(), _tr("参数优化"))
        self.inner.addTab(self._build_auto(), _tr("自动交易"))
        self.inner.addTab(self._build_ai(), _tr("AI 建议 (Claude Code)"))
        lay.addWidget(self.inner)

        self.bt_worker = BacktestWorker(market, settings)
        self.bt_worker.done.connect(self._on_bt_done)
        self.bt_worker.failed.connect(self._on_bt_failed)
        self.bt_worker.progress.connect(lambda m: self.bt_status.setText(m))

        self.opt_worker = OptimizeWorker(market, settings)
        self.opt_worker.done.connect(self._on_opt_done)
        self.opt_worker.failed.connect(self._on_opt_failed)
        self.opt_worker.progress.connect(self._on_opt_progress)

        self.auto_worker = AutoEvalWorker(market)
        self.auto_worker.ready.connect(self._on_auto_data)
        self.auto_worker.failed.connect(lambda m: self.auto_status.setText(m))

        self.auto_timer = QtCore.QTimer(self)
        self.auto_timer.timeout.connect(self._auto_tick)

        self._load_auto_ui()

    # ==================================================================
    # 回测
    # ==================================================================
    def _build_backtest(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        root = QtWidgets.QHBoxLayout(w)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        side = Card(_tr("回测设置"))
        side.setMaximumWidth(320)
        side.setMinimumWidth(290)

        self.bt_strategy = QtWidgets.QComboBox()
        for k in library.STRATEGY_ORDER:
            self.bt_strategy.addItem(library.REGISTRY[k].name, k)
        self.bt_strategy.currentIndexChanged.connect(self._on_bt_strategy)
        side.vbox.addWidget(QtWidgets.QLabel(_tr("策略")))
        side.vbox.addWidget(self.bt_strategy)

        self.bt_desc = QtWidgets.QLabel("")
        self.bt_desc.setObjectName("Dim")
        self.bt_desc.setWordWrap(True)
        side.vbox.addWidget(self.bt_desc)

        self.bt_params = ParamEditor()
        side.vbox.addWidget(self.bt_params)

        side.vbox.addWidget(_hline())
        self.bt_universe = QtWidgets.QComboBox()
        self.bt_universe.addItem(_tr("单只标的"), "single")
        self.bt_universe.addItem(_tr("当前自选股"), "watchlist")
        for name, _ in universe.SECTORS:
            self.bt_universe.addItem(_tr("板块: ") + name, "sector:" + name)
        self.bt_universe.currentIndexChanged.connect(self._on_bt_universe)
        side.vbox.addWidget(QtWidgets.QLabel(_tr("回测标的")))
        side.vbox.addWidget(self.bt_universe)

        self.bt_symbol = QtWidgets.QLineEdit("AAPL")
        self.bt_symbol.setPlaceholderText(_tr("股票代码"))
        side.vbox.addWidget(self.bt_symbol)

        form = QtWidgets.QFormLayout()
        form.setSpacing(6)
        self.bt_interval = QtWidgets.QComboBox()
        for label, code in INTERVALS:
            self.bt_interval.addItem(label, code)
        form.addRow(_tr("周期"), self.bt_interval)
        self.bt_range = QtWidgets.QComboBox()
        for _lab, _code in RANGES:
            self.bt_range.addItem(_lab, _code)
        self.bt_range.setCurrentIndex(RANGE_CODES.index("10y"))
        form.addRow(_tr("区间"), self.bt_range)

        self.bt_cash = QtWidgets.QDoubleSpinBox()
        self.bt_cash.setRange(1000, 10_000_000)
        self.bt_cash.setDecimals(0)
        self.bt_cash.setSingleStep(10000)
        self.bt_cash.setValue(100000)
        self.bt_cash.setPrefix("$ ")
        self.bt_cash.setGroupSeparatorShown(True)
        form.addRow(_tr("初始资金"), self.bt_cash)

        self.bt_pos = QtWidgets.QDoubleSpinBox()
        self.bt_pos.setRange(1, 100)
        self.bt_pos.setValue(95)
        self.bt_pos.setSuffix(" %")
        form.addRow(_tr("每次仓位"), self.bt_pos)

        self.bt_sl = QtWidgets.QDoubleSpinBox()
        self.bt_sl.setRange(0, 50)
        self.bt_sl.setValue(0)
        self.bt_sl.setSuffix(" %")
        self.bt_sl.setToolTip(_tr("0 表示不启用"))
        form.addRow(_tr("止损"), self.bt_sl)

        self.bt_tp = QtWidgets.QDoubleSpinBox()
        self.bt_tp.setRange(0, 200)
        self.bt_tp.setValue(0)
        self.bt_tp.setSuffix(" %")
        self.bt_tp.setToolTip(_tr("0 表示不启用"))
        form.addRow(_tr("止盈"), self.bt_tp)

        self.bt_lev = QtWidgets.QDoubleSpinBox()
        self.bt_lev.setRange(1.0, 4.0)
        self.bt_lev.setSingleStep(0.5)
        self.bt_lev.setValue(1.0)
        self.bt_lev.setSuffix(_tr(" 倍"))
        self.bt_lev.setToolTip(_tr("1 = 不融资。>1 会计息, 净值击穿维持保证金会被强制平仓"))
        form.addRow(_tr("融资杠杆"), self.bt_lev)
        side.vbox.addLayout(form)

        self.bt_run = QtWidgets.QPushButton(_tr("运行回测"))
        self.bt_run.setObjectName("Primary")
        self.bt_run.setMinimumHeight(34)
        self.bt_run.clicked.connect(self._run_backtest)
        side.vbox.addWidget(self.bt_run)

        self.bt_status = QtWidgets.QLabel("")
        self.bt_status.setObjectName("Dim")
        self.bt_status.setWordWrap(True)
        side.vbox.addWidget(self.bt_status)
        side.vbox.addStretch(1)
        root.addWidget(side)

        # ---- 结果区 ----
        # 上面两块 (图表 / 绩效指标) 位置和比例固定, 不参与拖拽 ——
        # 打开回测第一眼要看的就是它俩, 不该被拖没也不该自己消失。
        # 只有下面两块 (收益分布 / 交易明细) 能互相挤压, 用分割器隔开。
        right = QtWidgets.QWidget()
        rv = QtWidgets.QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(_STACK_GAP)

        chart_card = Card()
        self.bt_title = QtWidgets.QLabel(_tr("选择策略后点「运行回测」"))
        self.bt_title.setObjectName("Title")
        chart_card.vbox.addWidget(self.bt_title)

        self.bt_plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(orientation="bottom"),
                                              "left": MoneyAxis()})
        self.bt_plot.showGrid(x=True, y=True, alpha=0.12)
        self.bt_plot.getAxis("left").setWidth(88)
        self.bt_plot.addLegend(offset=(10, 10))
        self.bt_curve = self.bt_plot.plot([], [], pen=pg.mkPen(theme.ACCENT, width=2), name=_tr("策略"))
        self.bt_bench = self.bt_plot.plot([], [], pen=pg.mkPen(theme.TEXT_DIM, width=1.4,
                                          style=QtCore.Qt.PenStyle.DashLine), name=_tr("买入持有"))
        chart_card.vbox.addWidget(self.bt_plot, 1)
        chart_card.setMinimumHeight(_CHART_FLOOR)
        rv.addWidget(chart_card, _CHART_SHARE)

        metric_card = Card(_tr("绩效指标"))
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(18)
        self.bt_metrics = {}
        items = [("total_return", _tr("总收益")), ("cagr", _tr("年化")), ("sharpe", _tr("夏普")),
                 ("sortino", _tr("索提诺")), ("max_drawdown", _tr("最大回撤")), ("calmar", _tr("卡玛")),
                 ("n_trades", _tr("交易次数")), ("win_rate", _tr("胜率")),
                 ("profit_factor", _tr("盈亏比")), ("exposure", _tr("持仓时间占比")),
                 ("total_costs", _tr("累计费用")), ("benchmark_return", _tr("买入持有")),
                 ("alpha", _tr("超额收益"))]
        for i, (k, t) in enumerate(items):
            r, c = divmod(i, 7)
            box = QtWidgets.QVBoxLayout()
            lt = QtWidgets.QLabel(t)
            lt.setObjectName("Dim")
            lv = QtWidgets.QLabel("—")
            lv.setObjectName("StatValue")
            box.addWidget(lt)
            box.addWidget(lv)
            holder = QtWidgets.QWidget()
            holder.setLayout(box)
            grid.addWidget(holder, r, c)
            self.bt_metrics[k] = lv
        metric_card.vbox.addLayout(grid)
        self.bt_verdict = QtWidgets.QLabel("")
        self.bt_verdict.setWordWrap(True)
        metric_card.vbox.addWidget(self.bt_verdict)
        # 高度交给控件自己算, 不要写死数字 —— 我拍的 150 比实际需要的 177 小,
        # 结果每个数值标签只剩 7px (需要 15px), 正好被切掉一半。
        # 字体、DPI、指标条数变了都会影响, 所以只能问控件要。
        self.bt_metric_card = metric_card
        # 宽度一变就重新量: 窗口拖窄后结论可能换成两行, 高度不跟着变就会切字
        metric_card.installEventFilter(self)
        self._h_metric = self._fit_height(metric_card)
        rv.addWidget(metric_card, 0)

        # 收益分布不锁死高度 —— 它要能被交易明细挤。里面是张表, 挤窄了自己出
        # 滚动条, 不像绩效指标那样会把数字切掉半截。
        self.bt_windows = WindowDistWidget()
        self._h_windows = self.bt_windows.sizeHint().height()   # 表头 + 4 行 + 脚注
        self.bt_windows.setMinimumHeight(_DIST_FLOOR)

        tabs = QtWidgets.QTabWidget()
        self.bt_trades = make_table(
            [_tr("入场时间"), _tr("代码"), _tr("方向"), _tr("股数"), _tr("入场价"), _tr("出场时间"), _tr("出场价"),
             _tr("盈亏"), _tr("盈亏%"), _tr("持仓K线"), _tr("离场原因")], stretch_col=1)
        tabs.addTab(self.bt_trades, _tr("交易明细"))
        self.bt_singles = make_table(
            [_tr("代码"), _tr("总收益"), _tr("买入持有"), _tr("超额"), _tr("年化"), _tr("夏普"), _tr("最大回撤"), _tr("交易"), _tr("胜率")],
            stretch_col=0)
        self.bt_singles.setSortingEnabled(True)
        tabs.addTab(self.bt_singles, _tr("单只拆解"))
        tabs.setMinimumHeight(_TRADES_FLOOR)

        # 只有这两块能拖。一个把手、两个 pane —— 拖上去再拖回来必然回到原位,
        # 不存在多 pane 那种级联挤压 (往上拖挤图表、往回拖还给邻居, 不对称)。
        # 两个 pane 都不锁死高度, 否则整条分隔条会拖不动。
        self.bt_split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.bt_split.setChildrenCollapsible(False)
        self.bt_split.setHandleWidth(6)
        self.bt_split.addWidget(self.bt_windows)
        self.bt_split.addWidget(tabs)
        # 收益分布默认就它需要的高度, 多出来的空间全给交易明细。
        self.bt_split.setSizes([self._h_windows, _TRADES_FLOOR * 2])
        self.bt_split.setStretchFactor(0, 0)
        self.bt_split.setStretchFactor(1, 1)
        rv.addWidget(self.bt_split, _SPLIT_SHARE)
        root.addWidget(right, 1)

        self._on_bt_strategy()
        self._on_bt_universe()
        return w

    @staticmethod
    def _fit_height(widget) -> int:
        """把控件锁到它自己需要的高度 —— 要么完整显示, 绝不半截。返回该高度。

        控件已经有真实宽度时, **只认 heightForWidth(实际宽度)**。不能再和
        sizeHint 取 max: 自动换行的 QLabel 的 sizeHint 是按一个很窄的默认宽度
        算的 (结论那行在 1600px 宽下只要 16px, sizeHint 却报 64~80px 好几行),
        取 max 会让卡片凭空高出 50~66px, 把下面的空间挤掉。英文句子更长, 更明显。
        还没显示出来 (宽度为 0) 时才退回 sizeHint。留 2px 余量防止四舍五入切边。
        """
        lay = widget.layout()
        wpx = widget.width()
        if lay is not None and lay.hasHeightForWidth() and wpx > 0:
            h = lay.heightForWidth(wpx)
        else:
            h = widget.sizeHint().height()
            if lay is not None:
                h = max(h, lay.sizeHint().height())
        h = max(h + 2, 80)
        widget.setFixedHeight(h)
        return h

    def eventFilter(self, obj, ev):
        if (obj is getattr(self, "bt_metric_card", None)
                and ev.type() == QtCore.QEvent.Type.Resize
                and ev.size().width() != ev.oldSize().width()):
            # 只看宽度: setFixedHeight 本身也会触发 Resize, 看高度会死循环
            QtCore.QTimer.singleShot(0, self._refit_metric)
        return super().eventFilter(obj, ev)

    def _refit_metric(self) -> None:
        """结论那行字填进去之后重新量高 —— 长度不定、可能换行。

        绩效指标是唯一锁死高度的一块: 它是一格一格的数字, 挤窄了就是把字切掉
        半截, 不像表格能出滚动条。所以它只会变高, 不会被挤。
        """
        self._h_metric = self._fit_height(self.bt_metric_card)

    def _on_bt_strategy(self):
        key = self.bt_strategy.currentData()
        self.bt_desc.setText(library.REGISTRY[key].desc)
        self.bt_params.set_strategy(key)

    def _on_bt_universe(self):
        self.bt_symbol.setVisible(self.bt_universe.currentData() == "single")

    def _symbols_for(self, mode: str) -> list:
        if mode == "single":
            s = self.bt_symbol.text().strip().upper()
            return [s] if s else []
        if mode == "watchlist":
            acc, _, _, _ = self.get_context()
            return list(acc.watchlist)
        if mode.startswith("sector:"):
            return list(universe.SECTOR_MAP.get(mode.split(":", 1)[1], []))
        return []

    def _run_backtest(self):
        if self.bt_worker.isRunning():
            return
        mode = self.bt_universe.currentData()
        symbols = self._symbols_for(mode)
        if not symbols:
            QtWidgets.QMessageBox.information(self, _tr("提示"), _tr("请先指定回测标的。"))
            return
        interval = self.bt_interval.currentData()
        rng = self.bt_range.currentData()
        limit = INTERVAL_RANGE_LIMIT.get(interval)
        if limit and RANGE_CODES.index(rng) > RANGE_CODES.index(limit):
            rng = limit
            self.bt_range.setCurrentIndex(RANGE_CODES.index(limit))
        cfg = BacktestConfig(initial_cash=self.bt_cash.value(),
                             position_pct=self.bt_pos.value(),
                             stop_loss_pct=self.bt_sl.value(),
                             take_profit_pct=self.bt_tp.value(),
                             interval=interval,
                             leverage=self.bt_lev.value())
        self.bt_run.setEnabled(False)
        self.bt_status.setText(_tr("准备中…"))
        self.bt_worker.start_job(symbols, self.bt_strategy.currentData(),
                                 self.bt_params.values(), interval, rng, cfg)

    def _on_bt_failed(self, msg: str):
        self.bt_run.setEnabled(True)
        self.bt_status.setText(msg)
        QtWidgets.QMessageBox.warning(self, _tr("回测失败"), msg)

    def _on_bt_done(self, res, singles):
        self.bt_run.setEnabled(True)
        self.last_result, self.last_singles = res, singles
        if not res.ok:
            self.bt_status.setText(res.error)
            QtWidgets.QMessageBox.warning(self, _tr("回测失败"), res.error)
            return
        self.bt_status.setText(_tr("完成 · {} 根 K 线").format(res.metrics.get("bars", 0)))
        # 结论那行字是现在才填进去的, 长度不定、可能换行 —— 重新量一次高度,
        # 否则文字会被卡片切掉 (宁可卡片变高, 也不能只显示半行)。
        QtCore.QTimer.singleShot(0, self._refit_metric)
        self.bt_title.setText("{} — {}".format(res.symbol or _tr("回测"), res.strategy_label))

        xs = [p[0] for p in res.equity]
        ys = [p[1] for p in res.equity]
        up = ys[-1] >= ys[0]
        self.bt_curve.setPen(pg.mkPen(theme.up_color() if up else theme.down_color(), width=2))
        self.bt_curve.setData(xs, ys)
        if res.benchmark:
            self.bt_bench.setData([p[0] for p in res.benchmark], [p[1] for p in res.benchmark])
        else:
            self.bt_bench.setData([], [])
        # 兜底: 视图卡在默认的 (0,1) 就会画出一张空图 (X 轴显示 1970-01-01 那个
        # 时刻, Y 轴 0.2/0.4/0.6)。正常情况 setData 会自动 autoRange, 这行只是
        # 保证万一没触发时不会把人晾在空白图表前面。
        self.bt_plot.enableAutoRange()

        m = res.metrics
        pf = m.get("profit_factor", 0)
        fmt = {
            "total_return": (theme.signed_pct(m.get("total_return", 0)),
                             theme.pnl_color(m.get("total_return", 0))),
            "cagr": (theme.signed_pct(m.get("cagr", 0)), theme.pnl_color(m.get("cagr", 0))),
            "sharpe": ("{:.2f}".format(m.get("sharpe", 0)),
                       theme.up_color() if m.get("sharpe", 0) >= 1 else None),
            "sortino": ("{:.2f}".format(m.get("sortino", 0)), None),
            "max_drawdown": ("-{:.2f}%".format(m.get("max_drawdown", 0)), theme.down_color()),
            "calmar": ("{:.2f}".format(m.get("calmar", 0)), None),
            "n_trades": ("{}".format(m.get("n_trades", 0)), None),
            "win_rate": ("{:.1f}%".format(m.get("win_rate", 0)), None),
            "profit_factor": ("∞" if pf == float("inf") else "{:.2f}".format(pf), None),
            "exposure": ("{:.0f}%".format(m.get("exposure", 0)), theme.TEXT_DIM),
            "total_costs": (theme.money(m.get("total_costs", 0), 0), theme.TEXT_DIM),
            "benchmark_return": (theme.signed_pct(m.get("benchmark_return", 0)),
                                 theme.TEXT_DIM),
            "alpha": (theme.signed_pct(m.get("alpha", 0)), theme.pnl_color(m.get("alpha", 0))),
        }
        for k, (text, col) in fmt.items():
            lab = self.bt_metrics[k]
            lab.setText(text)
            lab.setStyleSheet("color: {};".format(col) if col else "")

        alpha = m.get("alpha", 0)
        if alpha > 0:
            v = (_tr('<span style="color:{}">跑赢买入持有 {:.1f} 个百分点</span>'
                 " —— 但请务必去【参数优化】做样本外验证, 单次回测很容易是运气。").format(
                     theme.up_color(), alpha))
        else:
            v = (_tr('<span style="color:{}">跑输买入持有 {:.1f} 个百分点</span>'
                 " —— 扣掉佣金和滑点后, 多数择时策略都是这个结果。").format(
                     theme.down_color(), abs(alpha)))
        mc = m.get("margin_calls", 0)
        if mc:
            v += (_tr('<br><span style="color:{}">期间被追加保证金强制平仓 {} 次</span>').format(
                theme.RED, mc))
        self.bt_verdict.setText(v)

        self.bt_windows.set_equity(res.equity, self.bt_interval.currentData())

        rows = []
        for t in res.trades[-500:]:
            col = theme.pnl_color(t.pnl)
            rows.append([
                cell(_ts(t.entry_ts), theme.TEXT_DIM),
                cell(t.symbol, theme.TEXT, LEFT, bold=True),
                cell(_tr("多") if t.direction > 0 else _tr("空"),
                     theme.up_color() if t.direction > 0 else theme.down_color(), CENTER),
                cell("{:,}".format(t.qty), None, RIGHT),
                cell("{:.2f}".format(t.entry_price), None, RIGHT),
                cell(_ts(t.exit_ts), theme.TEXT_DIM),
                cell("{:.2f}".format(t.exit_price), None, RIGHT),
                cell(theme.signed_money(t.pnl), col, RIGHT, bold=True),
                cell(theme.signed_pct(t.pnl_pct), col, RIGHT),
                cell(str(t.bars_held), theme.TEXT_DIM, RIGHT),
                cell(t.exit_reason, theme.TEXT_DIM, CENTER),
            ])
        fill_table(self.bt_trades, rows)

        self.bt_singles.setSortingEnabled(False)
        srows = []
        for sym, r in singles.items():
            if not r.ok:
                continue
            mm = r.metrics
            a = mm.get("alpha", 0)
            srows.append([
                cell(sym, theme.TEXT, LEFT, bold=True),
                NumItem(theme.signed_pct(mm["total_return"]), mm["total_return"],
                        theme.pnl_color(mm["total_return"])),
                NumItem(theme.signed_pct(mm["benchmark_return"]), mm["benchmark_return"],
                        theme.TEXT_DIM),
                NumItem(theme.signed_pct(a), a, theme.pnl_color(a), bold=True),
                NumItem(theme.signed_pct(mm["cagr"]), mm["cagr"]),
                NumItem("{:.2f}".format(mm["sharpe"]), mm["sharpe"]),
                NumItem("-{:.1f}%".format(mm["max_drawdown"]), -mm["max_drawdown"],
                        theme.down_color()),
                NumItem(str(mm["n_trades"]), mm["n_trades"]),
                NumItem("{:.0f}%".format(mm["win_rate"]), mm["win_rate"]),
            ])
        fill_table(self.bt_singles, srows)
        self.bt_singles.setSortingEnabled(True)
        self.bt_singles.sortItems(3, QtCore.Qt.SortOrder.DescendingOrder)

    # ==================================================================
    # 参数优化
    # ==================================================================
    def _build_optimize(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        top = Card(_tr("网格搜索 + 样本外验证"))
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(10)

        self.opt_strategy = QtWidgets.QComboBox()
        for k in library.STRATEGY_ORDER:
            if library.REGISTRY[k].param_specs():
                self.opt_strategy.addItem(library.REGISTRY[k].name, k)
        row.addWidget(QtWidgets.QLabel(_tr("策略")))
        row.addWidget(self.opt_strategy)

        self.opt_symbol = QtWidgets.QLineEdit("AAPL")
        self.opt_symbol.setMaximumWidth(110)
        row.addWidget(QtWidgets.QLabel(_tr("标的")))
        row.addWidget(self.opt_symbol)

        self.opt_interval = QtWidgets.QComboBox()
        for label, code in INTERVALS:
            self.opt_interval.addItem(label, code)
        row.addWidget(QtWidgets.QLabel(_tr("周期")))
        row.addWidget(self.opt_interval)

        self.opt_range = QtWidgets.QComboBox()
        for _lab, _code in RANGES:
            self.opt_range.addItem(_lab, _code)
        self.opt_range.setCurrentIndex(RANGE_CODES.index("10y"))
        row.addWidget(QtWidgets.QLabel(_tr("区间")))
        row.addWidget(self.opt_range)

        self.opt_metric = QtWidgets.QComboBox()
        for k, (label, _) in optimizer.METRICS.items():
            self.opt_metric.addItem(label, k)
        row.addWidget(QtWidgets.QLabel(_tr("优化目标")))
        row.addWidget(self.opt_metric)

        self.opt_points = QtWidgets.QSpinBox()
        self.opt_points.setRange(3, 10)
        self.opt_points.setValue(6)
        self.opt_points.setToolTip(_tr("每个参数取几个候选值, 越大越慢"))
        row.addWidget(QtWidgets.QLabel(_tr("每参数取样")))
        row.addWidget(self.opt_points)

        self.opt_run = QtWidgets.QPushButton(_tr("开始优化"))
        self.opt_run.setObjectName("Primary")
        self.opt_run.clicked.connect(self._run_optimize)
        row.addWidget(self.opt_run)
        self.opt_stop = QtWidgets.QPushButton(_tr("停止"))
        self.opt_stop.setEnabled(False)
        self.opt_stop.clicked.connect(lambda: self.opt_worker.stop())
        row.addWidget(self.opt_stop)
        row.addStretch(1)
        top.vbox.addLayout(row)

        self.opt_bar = QtWidgets.QProgressBar()
        self.opt_bar.setTextVisible(True)
        self.opt_bar.setVisible(False)
        top.vbox.addWidget(self.opt_bar)

        warn = QtWidgets.QLabel(
            _tr("只在前 70% 的历史上搜参数, 用后 30% 验证。<b>请按「验证集」列挑参数, 不要按「训练集」挑</b> —— "
            "训练集最漂亮的那组, 往往就是过拟合最严重的那组。"))
        warn.setObjectName("Dim")
        warn.setWordWrap(True)
        top.vbox.addWidget(warn)
        lay.addWidget(top)

        res = Card(_tr("优化结果 (按验证集表现排序)"))
        self.opt_table = make_table(
            [_tr("参数"), _tr("训练集收益"), _tr("验证集收益"), _tr("验证夏普"), _tr("验证回撤"),
             _tr("验证交易数"), _tr("全样本收益"), _tr("稳健")], stretch_col=0)
        self.opt_table.setSortingEnabled(True)
        self.opt_table.doubleClicked.connect(self._apply_opt_params)
        res.vbox.addWidget(self.opt_table, 1)
        brow = QtWidgets.QHBoxLayout()
        b1 = QtWidgets.QPushButton(_tr("把选中参数用到【回测】"))
        b1.clicked.connect(lambda: self._apply_opt_params(target="backtest"))
        brow.addWidget(b1)
        b2 = QtWidgets.QPushButton(_tr("把选中参数用到【自动交易】"))
        b2.clicked.connect(lambda: self._apply_opt_params(target="auto"))
        brow.addWidget(b2)
        brow.addStretch(1)
        self.opt_note = QtWidgets.QLabel("")
        self.opt_note.setObjectName("Dim")
        brow.addWidget(self.opt_note)
        res.vbox.addLayout(brow)
        lay.addWidget(res, 1)
        return w

    def _run_optimize(self):
        if self.opt_worker.isRunning():
            return
        sym = self.opt_symbol.text().strip().upper()
        if not sym:
            return
        interval = self.opt_interval.currentData()
        rng = self.opt_range.currentData()
        limit = INTERVAL_RANGE_LIMIT.get(interval)
        if limit and RANGE_CODES.index(rng) > RANGE_CODES.index(limit):
            rng = limit
            self.opt_range.setCurrentIndex(RANGE_CODES.index(limit))
        cfg = BacktestConfig(initial_cash=100000, position_pct=95, interval=interval)
        self.opt_run.setEnabled(False)
        self.opt_stop.setEnabled(True)
        self.opt_bar.setVisible(True)
        self.opt_bar.setValue(0)
        self.opt_note.setText(_tr("搜索中…"))
        self.opt_worker.start_job(sym, self.opt_strategy.currentData(), interval, rng,
                                  cfg, self.opt_metric.currentData(), self.opt_points.value())

    def _on_opt_progress(self, cur: int, total: int):
        self.opt_bar.setMaximum(max(total, 1))
        self.opt_bar.setValue(cur)
        self.opt_bar.setFormat(_tr("%v / %m 组"))

    def _on_opt_failed(self, msg: str):
        self.opt_run.setEnabled(True)
        self.opt_stop.setEnabled(False)
        self.opt_bar.setVisible(False)
        self.opt_note.setText(msg)
        QtWidgets.QMessageBox.warning(self, _tr("优化失败"), msg)

    def _on_opt_done(self, rows: list, note: str):
        self.opt_run.setEnabled(True)
        self.opt_stop.setEnabled(False)
        self.opt_bar.setVisible(False)
        self.opt_rows = rows
        self.opt_note.setText(note or _tr("共 {} 组有效结果 · 双击一行应用参数").format(len(rows)))

        self.opt_table.setSortingEnabled(False)
        items = []
        for r in rows:
            tr = r.train.get("total_return", 0)
            te = r.test.get("total_return", 0)
            label = ", ".join("{}={}".format(k, v) for k, v in r.params.items()
                              if not isinstance(v, bool)) or _tr("(无参数)")
            if r.params.get("allow_short"):
                label += _tr(", 做空")
            items.append([
                cell(label, theme.TEXT, LEFT),
                NumItem(theme.signed_pct(tr), tr, theme.pnl_color(tr)),
                NumItem(theme.signed_pct(te), te, theme.pnl_color(te), bold=True),
                NumItem("{:.2f}".format(r.test.get("sharpe", 0)), r.test.get("sharpe", 0)),
                NumItem("-{:.1f}%".format(r.test.get("max_drawdown", 0)),
                        -r.test.get("max_drawdown", 0), theme.down_color()),
                NumItem(str(r.test.get("n_trades", 0)), r.test.get("n_trades", 0)),
                NumItem(theme.signed_pct(r.full.get("total_return", 0)),
                        r.full.get("total_return", 0), theme.TEXT_DIM),
                cell(_tr("稳健") if r.robust else "—",
                     theme.up_color() if r.robust else theme.TEXT_DIM, CENTER),
            ])
        fill_table(self.opt_table, items)
        self.opt_table.setSortingEnabled(True)

    def _apply_opt_params(self, target: str = "backtest"):
        r = self.opt_table.currentRow()
        if not (0 <= r < len(self.opt_rows)):
            QtWidgets.QMessageBox.information(self, _tr("提示"), _tr("请先选中一行结果。"))
            return
        row = self.opt_rows[r] if self.opt_table.isSortingEnabled() is False else None
        # 表格可能被重排, 用参数文本反查
        label_item = self.opt_table.item(r, 0)
        if row is None and label_item:
            for cand in self.opt_rows:
                lab = ", ".join("{}={}".format(k, v) for k, v in cand.params.items()
                                if not isinstance(v, bool)) or _tr("(无参数)")
                if cand.params.get("allow_short"):
                    lab += _tr(", 做空")
                if lab == label_item.text():
                    row = cand
                    break
        if row is None:
            return
        key = self.opt_strategy.currentData()
        if target == "auto":
            idx = self.auto_strategy.findData(key)
            if idx >= 0:
                self.auto_strategy.setCurrentIndex(idx)
            self.auto_params.set_strategy(key, row.params)
            self.inner.setCurrentIndex(5)
            self.status.emit(_tr("参数已应用到自动交易: {}").format(row.params))
        else:
            idx = self.bt_strategy.findData(key)
            if idx >= 0:
                self.bt_strategy.setCurrentIndex(idx)
            self.bt_params.set_strategy(key, row.params)
            self.bt_symbol.setText(self.opt_symbol.text().strip().upper())
            self.inner.setCurrentIndex(0)
            self.status.emit(_tr("参数已应用到回测: {}").format(row.params))

    # ==================================================================
    # 自动交易
    # ==================================================================
    def _build_auto(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        root = QtWidgets.QHBoxLayout(w)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        side = Card(_tr("自动交易设置"))
        side.setMaximumWidth(330)
        side.setMinimumWidth(300)

        side.vbox.addWidget(QtWidgets.QLabel(_tr("交易模式")))
        self.auto_mode = QtWidgets.QComboBox()
        self.auto_mode.addItem(_tr("单标的择时 (一个策略跑多只股票)"), auto.SINGLE)
        self.auto_mode.addItem(_tr("核心-卫星组合 (按目标权重再平衡)"), auto.PORTFOLIO)
        self.auto_mode.currentIndexChanged.connect(self._on_auto_mode)
        side.vbox.addWidget(self.auto_mode)

        # ---- 组合模式专用 ----
        self.auto_pf_box = QtWidgets.QWidget()
        pf = QtWidgets.QVBoxLayout(self.auto_pf_box)
        pf.setContentsMargins(0, 0, 0, 0)
        pf.setSpacing(4)
        self.auto_preset = QtWidgets.QComboBox()
        for name in presets.preset_names():
            self.auto_preset.addItem(_tr(name), name)     # 显示译名, 数据存原文
        self.auto_preset.currentIndexChanged.connect(self._preview_portfolio)
        pf.addWidget(self.auto_preset)
        brow2 = QtWidgets.QHBoxLayout()
        brow2.addWidget(QtWidgets.QLabel(_tr("再平衡容忍带")))
        self.auto_band = QtWidgets.QDoubleSpinBox()
        self.auto_band.setRange(0.0, 20.0)
        self.auto_band.setSingleStep(0.5)
        self.auto_band.setValue(2.0)
        self.auto_band.setSuffix(" pp")
        self.auto_band.setToolTip(
            _tr("权重偏离目标超过这么多个百分点才动手。\n"
            "设 0 会每天产生碎单; 太大则长期偏离目标。2pp 是个合理起点。"))
        brow2.addWidget(self.auto_band)
        pf.addLayout(brow2)
        brow3 = QtWidgets.QHBoxLayout()
        brow3.addWidget(QtWidgets.QLabel(_tr("融资杠杆")))
        self.auto_lev = QtWidgets.QDoubleSpinBox()
        self.auto_lev.setRange(1.0, auto.MAX_LEVERAGE)
        self.auto_lev.setSingleStep(0.25)
        self.auto_lev.setValue(1.0)
        self.auto_lev.setSuffix(_tr(" 倍"))
        self.auto_lev.setToolTip(
            _tr("所有目标权重乘这个倍数, 多出来的钱向券商借, 按设置里的融资年化利率每天计息。\n"
            "上限 2 倍 (Reg T); 现金账户不能融资, 会按 1 倍执行。\n"
            "实盘不模拟强平: 回撤熔断只会停止交易, 不会自动降杠杆。先在【组合】页回测同样的倍数。"))
        self.auto_lev.valueChanged.connect(self._preview_portfolio)
        brow3.addWidget(self.auto_lev)
        pf.addLayout(brow3)
        self.auto_pf_note = QtWidgets.QLabel("")
        self.auto_pf_note.setObjectName("Dim")
        self.auto_pf_note.setWordWrap(True)
        pf.addWidget(self.auto_pf_note)
        side.vbox.addWidget(self.auto_pf_box)

        # ---- 单标的模式专用 ----
        self.auto_single_box = QtWidgets.QWidget()
        sb = QtWidgets.QVBoxLayout(self.auto_single_box)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(4)
        self.auto_strategy = QtWidgets.QComboBox()
        for k in library.STRATEGY_ORDER:
            self.auto_strategy.addItem(library.REGISTRY[k].name, k)
        self.auto_strategy.currentIndexChanged.connect(
            lambda: self.auto_params.set_strategy(self.auto_strategy.currentData()))
        sb.addWidget(QtWidgets.QLabel(_tr("策略")))
        sb.addWidget(self.auto_strategy)
        self.auto_params = ParamEditor()
        sb.addWidget(self.auto_params)
        side.vbox.addWidget(self.auto_single_box)

        side.vbox.addWidget(_hline())
        self.auto_sym_label = QtWidgets.QLabel(_tr("交易标的 (来自自选股)"))
        side.vbox.addWidget(self.auto_sym_label)
        self.auto_symbols = QtWidgets.QListWidget()
        self.auto_symbols.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.auto_symbols.setMaximumHeight(150)
        side.vbox.addWidget(self.auto_symbols)
        brow = QtWidgets.QHBoxLayout()
        ba = QtWidgets.QPushButton(_tr("全选"))
        ba.clicked.connect(lambda: self._check_all_symbols(True))
        bn = QtWidgets.QPushButton(_tr("全不选"))
        bn.clicked.connect(lambda: self._check_all_symbols(False))
        brow.addWidget(ba)
        brow.addWidget(bn)
        side.vbox.addLayout(brow)

        form = QtWidgets.QFormLayout()
        form.setSpacing(6)
        self.auto_interval = QtWidgets.QComboBox()
        for label, code in INTERVALS:
            self.auto_interval.addItem(label, code)
        form.addRow(_tr("信号周期"), self.auto_interval)
        self.auto_check = QtWidgets.QSpinBox()
        self.auto_check.setRange(30, 7200)
        self.auto_check.setValue(300)
        self.auto_check.setSuffix(_tr(" 秒"))
        form.addRow(_tr("评估间隔"), self.auto_check)

        self.rl_pos = QtWidgets.QDoubleSpinBox(); self.rl_pos.setRange(1, 100); self.rl_pos.setSuffix(" %")
        form.addRow(_tr("单票最大仓位"), self.rl_pos)
        self.rl_max = QtWidgets.QSpinBox(); self.rl_max.setRange(1, 30)
        form.addRow(_tr("最多持仓数"), self.rl_max)
        self.rl_sl = QtWidgets.QDoubleSpinBox(); self.rl_sl.setRange(0, 50); self.rl_sl.setSuffix(" %")
        form.addRow(_tr("单笔止损"), self.rl_sl)
        self.rl_tp = QtWidgets.QDoubleSpinBox(); self.rl_tp.setRange(0, 200); self.rl_tp.setSuffix(" %")
        form.addRow(_tr("单笔止盈"), self.rl_tp)
        self.rl_trades = QtWidgets.QSpinBox(); self.rl_trades.setRange(1, 100)
        form.addRow(_tr("每日最多交易"), self.rl_trades)
        self.rl_halt = QtWidgets.QDoubleSpinBox(); self.rl_halt.setRange(0, 90); self.rl_halt.setSuffix(" %")
        form.addRow(_tr("回撤熔断"), self.rl_halt)
        self.rl_short = QtWidgets.QCheckBox(_tr("允许做空"))
        form.addRow("", self.rl_short)
        side.vbox.addLayout(form)

        self.auto_dry = QtWidgets.QCheckBox(_tr("仅给建议, 不自动下单 (推荐先这样跑)"))
        self.auto_dry.setChecked(True)
        side.vbox.addWidget(self.auto_dry)

        self.auto_toggle = QtWidgets.QPushButton(_tr("启动自动交易"))
        self.auto_toggle.setObjectName("Primary")
        self.auto_toggle.setCheckable(True)
        self.auto_toggle.setMinimumHeight(36)
        self.auto_toggle.clicked.connect(self._toggle_auto)
        side.vbox.addWidget(self.auto_toggle)
        side.vbox.addStretch(1)
        root.addWidget(side)

        right = QtWidgets.QVBoxLayout()
        right.setSpacing(8)

        dcard = Card()
        hrow = QtWidgets.QHBoxLayout()
        t = QtWidgets.QLabel(_tr("本轮决策"))
        t.setObjectName("Title")
        hrow.addWidget(t)
        self.auto_status = QtWidgets.QLabel(_tr("未启动"))
        self.auto_status.setObjectName("Dim")
        hrow.addWidget(self.auto_status)
        hrow.addStretch(1)
        b0 = QtWidgets.QPushButton(_tr("立即评估一次"))
        b0.clicked.connect(lambda: self._auto_tick(force=True))
        hrow.addWidget(b0)
        self.auto_exec_btn = QtWidgets.QPushButton(_tr("执行全部可执行决策"))
        self.auto_exec_btn.clicked.connect(self._execute_decisions)
        hrow.addWidget(self.auto_exec_btn)
        b2 = QtWidgets.QPushButton(_tr("解除熔断"))
        b2.clicked.connect(self._reset_halt)
        hrow.addWidget(b2)
        dcard.vbox.addLayout(hrow)

        self.auto_table = make_table(
            [_tr("代码"), _tr("现状"), _tr("目标"), _tr("动作"), _tr("股数"), _tr("现价"), _tr("理由 / 指标"), _tr("风控")], stretch_col=6)
        dcard.vbox.addWidget(self.auto_table, 1)
        right.addWidget(dcard, 1)

        lcard = Card(_tr("执行日志"))
        self.auto_log = make_table([_tr("时间"), _tr("代码"), _tr("动作"), _tr("股数"), _tr("结果"), _tr("理由")], stretch_col=5)
        lcard.vbox.addWidget(self.auto_log, 1)
        right.addWidget(lcard, 1)
        root.addLayout(right, 1)
        return w

    def _check_all_symbols(self, on: bool):
        for i in range(self.auto_symbols.count()):
            self.auto_symbols.item(i).setCheckState(
                QtCore.Qt.CheckState.Checked if on else QtCore.Qt.CheckState.Unchecked)

    def refresh_symbol_list(self):
        acc, _, _, _ = self.get_context()
        chosen = set(self.auto_config.symbols or [])
        self.auto_symbols.clear()
        for s in acc.watchlist:
            it = QtWidgets.QListWidgetItem(s)
            it.setFlags(it.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.CheckState.Checked if s in chosen
                             else QtCore.Qt.CheckState.Unchecked)
            self.auto_symbols.addItem(it)

    def _on_auto_mode(self):
        """组合模式下标的由预设决定, 策略/自选股那套不适用。"""
        pf = self.auto_mode.currentData() == auto.PORTFOLIO
        self.auto_pf_box.setVisible(pf)
        self.auto_single_box.setVisible(not pf)
        self.auto_symbols.setVisible(not pf)
        self.auto_sym_label.setVisible(not pf)
        # 组合的仓位由权重决定, 单票上限/持仓数/止损在这个模式下不适用
        for wdg, tip in ((self.rl_pos, _tr("组合模式下仓位由权重决定")),
                         (self.rl_max, _tr("组合模式下持仓数由组合结构决定")),
                         (self.rl_sl, _tr("组合模式不挂单笔止损 —— 止损卖掉后再平衡会买回来")),
                         (self.rl_tp, _tr("组合模式不挂单笔止盈"))):
            wdg.setEnabled(not pf)
            wdg.setToolTip(tip if pf else "")
        if pf:
            self._preview_portfolio()

    def _preview_portfolio(self):
        sleeves = presets.by_name(self.auto_preset.currentData())
        if not sleeves:
            self.auto_pf_note.setText("")
            return
        syms = sorted({x for sl in sleeves for x in sl.symbols})
        lev = self.auto_lev.value() if hasattr(self, "auto_lev") else 1.0
        extra = ""
        if lev > 1.0:
            extra = _tr("<br><b>{:.2f} 倍杠杆</b>：总仓位 {:.0f}% 净值，借 {:.0f}% 要付利息。").format(
                lev, lev * 100, (lev - 1) * 100)
        self.auto_pf_note.setText(
            _tr("{} 个支柱 · 需要盯 {} 只标的<br>{}<br>"
            "<b>仓位由权重决定</b>，单票上限 / 持仓数 / 止损在这个模式下不生效；"
            "风控靠分散和回撤熔断。").format(
                len(sleeves), len(syms),
                "　".join("{} {:.0f}%".format(sl.name, sl.weight * 100 * lev) for sl in sleeves))
            + extra)

    def _selected_symbols(self) -> list:
        return [self.auto_symbols.item(i).text() for i in range(self.auto_symbols.count())
                if self.auto_symbols.item(i).checkState() == QtCore.Qt.CheckState.Checked]

    def _load_auto_ui(self):
        c = self.auto_config
        mi = self.auto_mode.findData(c.mode)
        self.auto_mode.setCurrentIndex(max(mi, 0))
        pi = self.auto_preset.findData(c.preset)
        self.auto_preset.setCurrentIndex(max(pi, 0))
        self.auto_band.setValue(c.rebalance_band_pct)
        self.auto_lev.setValue(c.leverage)
        idx = self.auto_strategy.findData(c.strategy_key)
        self.auto_strategy.setCurrentIndex(max(idx, 0))
        self.auto_params.set_strategy(c.strategy_key, c.params)
        i = self.auto_interval.findData(c.interval)
        self.auto_interval.setCurrentIndex(max(i, 0))
        self.auto_check.setValue(c.check_seconds)
        self.auto_dry.setChecked(c.dry_run)
        lim = c.limits()
        self.rl_pos.setValue(lim.max_position_pct)
        self.rl_max.setValue(lim.max_positions)
        self.rl_sl.setValue(lim.stop_loss_pct)
        self.rl_tp.setValue(lim.take_profit_pct)
        self.rl_trades.setValue(lim.max_trades_per_day)
        self.rl_halt.setValue(lim.halt_drawdown_pct)
        self.rl_short.setChecked(lim.allow_short)
        self._on_auto_mode()
        self._refresh_auto_log()

    def _save_auto_ui(self):
        c = self.auto_config
        c.mode = self.auto_mode.currentData()
        c.preset = self.auto_preset.currentData()
        c.rebalance_band_pct = self.auto_band.value()
        c.leverage = self.auto_lev.value()
        c.strategy_key = self.auto_strategy.currentData()
        c.params = self.auto_params.values()
        c.symbols = self._selected_symbols()
        c.interval = self.auto_interval.currentData()
        c.check_seconds = self.auto_check.value()
        c.dry_run = self.auto_dry.isChecked()
        c.risk = asdict(RiskLimits(
            max_position_pct=self.rl_pos.value(), max_positions=self.rl_max.value(),
            stop_loss_pct=self.rl_sl.value(), take_profit_pct=self.rl_tp.value(),
            max_trades_per_day=self.rl_trades.value(),
            halt_drawdown_pct=self.rl_halt.value(), allow_short=self.rl_short.isChecked()))
        c.save()

    def _toggle_auto(self):
        on = self.auto_toggle.isChecked()
        pf = self.auto_mode.currentData() == auto.PORTFOLIO
        if on and not pf and not self._selected_symbols():
            self.auto_toggle.setChecked(False)
            QtWidgets.QMessageBox.information(self, _tr("提示"), _tr("请先勾选至少一个交易标的。"))
            return
        if on and pf and not presets.by_name(self.auto_preset.currentData()):
            self.auto_toggle.setChecked(False)
            QtWidgets.QMessageBox.warning(self, _tr("提示"), _tr("这个组合预设读不出来。"))
            return
        self._save_auto_ui()
        self.auto_config.enabled = on
        self.auto_config.save()
        if on:
            mode = _tr("仅建议") if self.auto_dry.isChecked() else _tr("自动下单")
            self.auto_toggle.setText(_tr("停止自动交易"))
            self.auto_status.setText(_tr("运行中 · {} · 每 {} 秒评估").format(
                mode, self.auto_check.value()))
            self.auto_timer.start(self.auto_check.value() * 1000)
            self._auto_tick(force=True)
        else:
            self.auto_toggle.setText(_tr("启动自动交易"))
            self.auto_status.setText(_tr("已停止"))
            self.auto_timer.stop()

    def _auto_tick(self, force: bool = False):
        if not force and not self.auto_config.enabled:
            return
        self._save_auto_ui()
        # 组合模式的标的由预设决定, 不看自选股的勾选
        syms = self.auto_config.watch_symbols()
        if not syms:
            self.auto_status.setText(
                _tr("组合预设里没有标的") if self.auto_config.mode == auto.PORTFOLIO
                else _tr("没有勾选标的"))
            return
        interval = self.auto_interval.currentData()
        rng = {"1d": "2y", "1wk": "10y", "60m": "2y"}.get(interval, "2y")
        if not self.auto_worker.start_job(syms, interval, rng):
            self.auto_status.setText(_tr("上一轮还在跑, 跳过本轮"))

    def _on_auto_data(self, candles: dict, extra_quotes: dict):
        acc, engine, quotes, prices = self.get_context()
        # 主窗口只轮询自选股; 组合模式的标的靠 worker 自己补报价
        quotes = dict(quotes)
        prices = dict(prices)
        for sym, q in (extra_quotes or {}).items():
            if q and q.price > 0:
                quotes.setdefault(sym, q)
                prices.setdefault(sym, q.price)
        self.autotrader.config = self.auto_config
        decisions = self.autotrader.evaluate(candles, quotes, engine, prices)
        self.decisions = decisions
        self._render_decisions()
        n = sum(1 for d in decisions if d.actionable)
        stamp = datetime.now().strftime("%H:%M:%S")
        if self.autotrader.halted:
            self.auto_status.setText(_tr("⛔ 已熔断: {}").format(self.autotrader.halt_reason))
        elif self.auto_config.enabled and not self.auto_config.dry_run and n:
            logs = self.autotrader.execute(decisions, engine, quotes, prices)
            self.auto_status.setText(_tr("{} 已执行 {} 笔").format(stamp, len(logs)))
            self._refresh_auto_log()
            self.trades_executed.emit()
        else:
            self.auto_status.setText(_tr("{} 评估完成 · {} 条可执行{}").format(
                stamp, n, _tr(" (仅建议模式)") if self.auto_config.dry_run else ""))

    def _render_decisions(self):
        rows = []
        dirs = {1: _tr("多"), 0: _tr("空仓"), -1: _tr("空")}
        for d in self.decisions:
            act_col = (theme.up_color() if d.action in (BUY, COVER)
                       else theme.down_color() if d.action in (SELL, SHORT)
                       else theme.TEXT_DIM)
            rows.append([
                cell(d.symbol, theme.TEXT, LEFT, bold=True),
                cell(dirs.get(d.current_dir, "?"), theme.TEXT_DIM, CENTER),
                cell(dirs.get(d.target_dir, "?"), theme.TEXT_DIM, CENTER),
                cell(SIDE_CN.get(d.action, d.action), act_col, CENTER, bold=d.action != HOLD),
                cell("{:,}".format(d.qty) if d.qty else "—", None, RIGHT),
                cell("{:.2f}".format(d.price) if d.price else "—", None, RIGHT),
                cell(d.reason or d.indicator, theme.TEXT_DIM),
                cell(d.blocked or "—", theme.GOLD if d.blocked else theme.TEXT_DIM),
            ])
        fill_table(self.auto_table, rows)

    def _execute_decisions(self):
        if not self.decisions:
            return
        n = sum(1 for d in self.decisions if d.actionable)
        if not n:
            QtWidgets.QMessageBox.information(self, _tr("提示"), _tr("本轮没有可执行的决策。"))
            return
        if QtWidgets.QMessageBox.question(
                self, _tr("确认"), _tr("按市价执行 {} 条决策?").format(n)
        ) != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        acc, engine, quotes, prices = self.get_context()
        logs = self.autotrader.execute(self.decisions, engine, quotes, prices)
        self._refresh_auto_log()
        self.trades_executed.emit()
        self.status.emit(_tr("已执行 {} 笔自动交易").format(len(logs)))
        self._auto_tick(force=True)

    def _reset_halt(self):
        self.autotrader.reset_halt()
        self.auto_status.setText(_tr("熔断已解除"))

    def _refresh_auto_log(self):
        from ..strategy.autotrader import read_log
        rows = []
        for e in reversed(read_log(200)):
            ok = e.get("ok")
            rows.append([
                cell(datetime.fromtimestamp(e.get("ts", 0)).strftime("%m-%d %H:%M:%S"),
                     theme.TEXT_DIM),
                cell(e.get("symbol", ""), theme.TEXT, LEFT, bold=True),
                cell(SIDE_CN.get(e.get("action", ""), e.get("action", "")),
                     theme.up_color() if e.get("action") in (BUY, COVER) else theme.down_color(),
                     CENTER),
                cell(str(e.get("qty", "")), None, RIGHT),
                cell(_tr("成功") if ok else _tr("失败"), theme.up_color() if ok else theme.down_color(),
                     CENTER),
                cell(e.get("reason", ""), theme.TEXT_DIM),
            ])
        fill_table(self.auto_log, rows)

    # ==================================================================
    # AI 建议 (Claude Code)
    # ==================================================================
    def _build_ai(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        how = Card(_tr("怎么用 (不需要 API key, 用你的 Claude Code 订阅)"))
        steps = QtWidgets.QLabel(
            _tr("<b>1.</b> 点下面的「导出简报」—— 会把账户、持仓、行情、技术指标、风控约束写成一个 Markdown 文件<br>"
            "<b>2.</b> 在 Claude Code 里对着这个项目说: <code>读一下 data/ai/briefing.md，"
            "按里面的格式把调仓建议写进 data/ai/decisions.json</code><br>"
            "<b>3.</b> 回到这里点「读取 AI 建议」, 每条建议都会做合法性校验 (持仓够不够、购买力够不够)<br>"
            "<b>4.</b> 逐条确认后执行 —— <b>永远是你按下最后那个按钮</b>"))
        steps.setWordWrap(True)
        how.vbox.addWidget(steps)

        row = QtWidgets.QHBoxLayout()
        b1 = QtWidgets.QPushButton(_tr("导出简报"))
        b1.setObjectName("Primary")
        b1.clicked.connect(self._export_briefing)
        row.addWidget(b1)
        b2 = QtWidgets.QPushButton(_tr("打开 data/ai 文件夹"))
        b2.clicked.connect(self._open_ai_dir)
        row.addWidget(b2)
        b3 = QtWidgets.QPushButton(_tr("复制提示词"))
        b3.clicked.connect(self._copy_prompt)
        row.addWidget(b3)
        b4 = QtWidgets.QPushButton(_tr("读取 AI 建议"))
        b4.clicked.connect(self._load_ai)
        row.addWidget(b4)
        row.addStretch(1)
        self.ai_status = QtWidgets.QLabel("")
        self.ai_status.setObjectName("Dim")
        row.addWidget(self.ai_status)
        how.vbox.addLayout(row)
        lay.addWidget(how)

        card = Card(_tr("AI 建议"))
        self.ai_note = QtWidgets.QLabel(_tr("还没有读取到建议"))
        self.ai_note.setWordWrap(True)
        card.vbox.addWidget(self.ai_note)
        self.ai_table = make_table(
            [_tr("代码"), _tr("动作"), _tr("股数"), _tr("类型"), _tr("限价"), _tr("信心"), _tr("理由"), _tr("校验")], stretch_col=6)
        card.vbox.addWidget(self.ai_table, 1)
        brow = QtWidgets.QHBoxLayout()
        e1 = QtWidgets.QPushButton(_tr("执行选中"))
        e1.clicked.connect(lambda: self._execute_ai(selected_only=True))
        brow.addWidget(e1)
        e2 = QtWidgets.QPushButton(_tr("执行全部合法建议"))
        e2.setObjectName("Primary")
        e2.clicked.connect(lambda: self._execute_ai(selected_only=False))
        brow.addWidget(e2)
        brow.addStretch(1)
        note = QtWidgets.QLabel(_tr("这是模拟盘。AI 的建议不是投资建议, 执行与否由你决定。"))
        note.setObjectName("Dim")
        brow.addWidget(note)
        card.vbox.addLayout(brow)
        lay.addWidget(card, 1)
        return w

    def _export_briefing(self):
        acc, engine, quotes, prices = self.get_context()
        syms = list(dict.fromkeys(list(acc.watchlist) +
                                  [p.symbol for p in acc.open_positions()]))
        self.ai_status.setText(_tr("正在拉取 K 线…"))
        QtWidgets.QApplication.processEvents()
        cdata = {}
        for s in syms:
            try:
                cdata[s] = self.market.candles(s, "1d", "2y")
            except Exception:
                continue
            time.sleep(0.12)
        note = ""
        if self.last_result and self.last_result.ok:
            m = self.last_result.metrics
            note = _tr("{} 在 {} 上回测: 总收益 {:+.1f}%, 买入持有 {:+.1f}%, 夏普 {:.2f}, 最大回撤 {:.1f}%").format(
                self.last_result.strategy_label, self.last_result.symbol,
                m.get("total_return", 0), m.get("benchmark_return", 0),
                m.get("sharpe", 0), m.get("max_drawdown", 0))
        try:
            path = briefing.export_briefing(acc, engine, quotes, prices, cdata,
                                            auto_config=self.auto_config,
                                            backtest_note=note)
        except Exception as exc:
            self.ai_status.setText(_tr("导出失败: {}").format(exc))
            QtWidgets.QMessageBox.warning(self, _tr("导出失败"), str(exc))
            return
        self.ai_status.setText(_tr("已导出 {} 只标的 → {}").format(len(cdata), path))
        self.status.emit(_tr("简报已导出: {}").format(path))

    def _open_ai_dir(self):
        os.makedirs(briefing.AI_DIR, exist_ok=True)
        try:
            os.startfile(briefing.AI_DIR)               # noqa: S606 (Windows)
        except Exception:
            subprocess.Popen(["explorer", briefing.AI_DIR])

    def _copy_prompt(self):
        text = (_tr("读一下 data/ai/briefing.md，按文件末尾的格式把调仓建议写进 "
                "data/ai/decisions.json。这是模拟盘，只用文件里给出的数据做判断，"
                "每条建议的 reason 要引用具体指标数值。"))
        QtWidgets.QApplication.clipboard().setText(text)
        self.ai_status.setText(_tr("提示词已复制到剪贴板"))

    def _load_ai(self):
        acc, engine, quotes, prices = self.get_context()
        ds, note, err = briefing.load_decisions(acc, engine, prices)
        if err:
            self.ai_status.setText(err)
            self.ai_note.setText(err)
            fill_table(self.ai_table, [])
            self.ai_decisions = []
            return
        self.ai_decisions = ds
        age = briefing.decisions_age()
        self.ai_note.setText(_tr("<b>AI 备注:</b> {}  <span style='color:{}'>"
                             "(文件更新于 {:.0f} 分钟前)</span>").format(
                                 note or _tr("(无)"), theme.TEXT_DIM, max(age, 0) / 60))
        rows = []
        for d in ds:
            col = (theme.up_color() if d.action in (BUY, COVER) else theme.down_color())
            rows.append([
                cell(d.symbol, theme.TEXT, LEFT, bold=True),
                cell(SIDE_CN.get(d.action, d.action), col, CENTER, bold=True),
                cell("{:,}".format(d.qty), None, RIGHT),
                cell(d.order_type, theme.TEXT_DIM, CENTER),
                cell("{:.2f}".format(d.limit_price) if d.limit_price else "—", None, RIGHT),
                cell("{:.0%}".format(d.confidence) if d.confidence else "—",
                     theme.TEXT_DIM, RIGHT),
                cell(d.reason, theme.TEXT_DIM),
                cell(_tr("✓ 可执行") if d.ok else "✗ " + d.error,
                     theme.up_color() if d.ok else theme.down_color()),
            ])
        fill_table(self.ai_table, rows)
        good = sum(1 for d in ds if d.ok)
        self.ai_status.setText(_tr("读取 {} 条, {} 条通过校验").format(len(ds), good))

    def _execute_ai(self, selected_only: bool):
        if not self.ai_decisions:
            return
        if selected_only:
            r = self.ai_table.currentRow()
            if not (0 <= r < len(self.ai_decisions)):
                QtWidgets.QMessageBox.information(self, _tr("提示"), _tr("请先选中一行。"))
                return
            targets = [self.ai_decisions[r]]
        else:
            targets = [d for d in self.ai_decisions if d.ok]
        targets = [d for d in targets if d.ok]
        if not targets:
            QtWidgets.QMessageBox.information(self, _tr("提示"), _tr("没有通过校验的建议可执行。"))
            return

        lines = [_tr("{} {} {} 股{}").format(
            SIDE_CN.get(d.action, d.action), d.symbol, d.qty,
            _tr(" @ 限价 {:.2f}").format(d.limit_price) if d.order_type == LIMIT else _tr(" (市价)"))
            for d in targets]
        if QtWidgets.QMessageBox.question(
                self, _tr("确认执行 AI 建议"), _tr("即将下单:\n\n") + "\n".join(lines)
        ) != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        acc, engine, quotes, prices = self.get_context()
        done = 0
        errs = []
        for d in targets:
            q = quotes.get(d.symbol)
            if not q:
                errs.append(_tr("{}: 无行情").format(d.symbol))
                continue
            order = Order(symbol=d.symbol, side=d.action, qty=d.qty,
                          order_type=LIMIT if d.order_type == LIMIT else MARKET,
                          limit_price=d.limit_price if d.order_type == LIMIT else 0.0)
            ok, msg = engine.submit(order, q, prices)
            if ok:
                done += 1
            else:
                errs.append("{}: {}".format(d.symbol, msg))
        self.trades_executed.emit()
        self.status.emit(_tr("AI 建议已执行 {} 条").format(done))
        self._load_ai()
        if errs:
            QtWidgets.QMessageBox.warning(self, _tr("部分未成功"), "\n".join(errs[:8]))

    # ==================================================================
    def stop(self):
        self.auto_timer.stop()
        self.rotation_panel.stop()
        self.robust_panel.stop()
        self.portfolio_panel.stop()
        for w in (self.bt_worker, self.opt_worker, self.auto_worker):
            if w.isRunning():
                if hasattr(w, "stop"):
                    w.stop()
                w.wait(1500)


def _hline() -> QtWidgets.QFrame:
    f = QtWidgets.QFrame()
    f.setFrameShape(QtWidgets.QFrame.Shape.HLine)
    f.setStyleSheet("color: {};".format(theme.BORDER))
    return f


def _ts(ts: float) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
