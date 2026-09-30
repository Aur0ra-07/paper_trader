"""组合页: 把多个收益来源按权重拼起来, 看分散到底有没有用。"""
from __future__ import annotations

import time
from datetime import date

import pyqtgraph as pg
from PyQt6 import QtCore, QtWidgets

from .. import universe
from ..strategy import library
from ..strategy.backtest import rolling_windows
from ..strategy.portfolio import (
    ASSET, CASH, ROTATION, STRATEGY, MixConfig, Sleeve,
    risk_parity_weights, run_mix,
)
from . import theme
from .panels import Card, NumItem, make_table, cell, fill_table, LEFT, RIGHT, CENTER
from .chart import MoneyAxis
from ..strategy.presets import PRESETS, ROT_CFG, ROT_POOL, TREND_POOL, _core
from .rotation_tab import PeriodPicker, WindowDistWidget
from ..i18n import _tr

KIND_CN = {ASSET: _tr("买入持有"), STRATEGY: _tr("择时策略"), ROTATION: _tr("动量轮动"), CASH: _tr("现金")}

class MixWorker(QtCore.QThread):
    done = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(str)

    def __init__(self, market, settings, parent=None):
        super().__init__(parent)
        self.market = market
        self.settings = settings
        self.job = None

    def start_job(self, sleeves, start, end, cfg, risk_parity):
        if self.isRunning():
            return False
        self.job = (sleeves, start, end, cfg, risk_parity)
        self.start()
        return True

    def run(self):
        sleeves, start, end, cfg, rp = self.job
        syms = sorted({s for sl in sleeves for s in sl.symbols} | {"SPY"})
        data = {}
        for n, s in enumerate(syms, 1):
            self.progress.emit(_tr("拉取 {} ({}/{})").format(s, n, len(syms)))
            try:
                c = self.market.candles_between(s, start, end)
                if len(c) > 60:
                    data[s] = c
            except Exception:
                pass
            time.sleep(0.08)
        if not data:
            self.failed.emit(_tr("没有拿到任何数据"))
            return
        try:
            if rp:
                w = risk_parity_weights(sleeves, data, self.settings, cfg)
                for sl in sleeves:
                    sl.weight = w.get(sl.name, 0.0)
            self.progress.emit(_tr("组合回测中…"))
            self.done.emit(run_mix(sleeves, data, self.settings, cfg))
        except Exception as exc:
            self.failed.emit(_tr("组合回测失败: {}").format(exc))


class SleeveDialog(QtWidgets.QDialog):
    def __init__(self, sleeve: "Sleeve | None", parent=None):
        super().__init__(parent)
        self.setWindowTitle(_tr("编辑组成部分"))
        self.setMinimumWidth(420)
        form = QtWidgets.QFormLayout(self)
        form.setSpacing(9)

        self.name = QtWidgets.QLineEdit(sleeve.name if sleeve else _tr("新的一块"))
        form.addRow(_tr("名称"), self.name)

        self.kind = QtWidgets.QComboBox()
        for k in (ASSET, STRATEGY, ROTATION, CASH):
            self.kind.addItem(KIND_CN[k], k)
        if sleeve:
            i = self.kind.findData(sleeve.kind)
            self.kind.setCurrentIndex(max(i, 0))
        self.kind.currentIndexChanged.connect(self._on_kind)
        form.addRow(_tr("类型"), self.kind)

        self.symbols = QtWidgets.QLineEdit(",".join(sleeve.symbols) if sleeve else "SPY")
        self.symbols.setPlaceholderText(_tr("代码用逗号分隔"))
        form.addRow(_tr("标的"), self.symbols)

        self.strategy = QtWidgets.QComboBox()
        for k in library.STRATEGY_ORDER:
            self.strategy.addItem(library.REGISTRY[k].name, k)
        if sleeve and sleeve.strategy_key:
            i = self.strategy.findData(sleeve.strategy_key)
            self.strategy.setCurrentIndex(max(i, 0))
        form.addRow(_tr("策略"), self.strategy)

        self.lookback = QtWidgets.QSpinBox(); self.lookback.setRange(10, 750)
        self.lookback.setValue((sleeve.rotation or {}).get("lookback", 120) if sleeve else 120)
        form.addRow(_tr("轮动回看(根)"), self.lookback)
        self.topk = QtWidgets.QSpinBox(); self.topk.setRange(1, 20)
        self.topk.setValue((sleeve.rotation or {}).get("top_k", 3) if sleeve else 3)
        form.addRow(_tr("轮动持有前几名"), self.topk)

        self.weight = QtWidgets.QDoubleSpinBox()
        self.weight.setRange(0, 100); self.weight.setSuffix(" %")
        self.weight.setValue((sleeve.weight * 100) if sleeve else 25.0)
        form.addRow(_tr("权重"), self.weight)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)
        self._on_kind()

    def _on_kind(self):
        k = self.kind.currentData()
        self.symbols.setEnabled(k != CASH)
        self.strategy.setEnabled(k == STRATEGY)
        self.lookback.setEnabled(k == ROTATION)
        self.topk.setEnabled(k == ROTATION)

    def sleeve(self) -> Sleeve:
        k = self.kind.currentData()
        syms = [s.strip().upper() for s in self.symbols.text().split(",") if s.strip()]
        return Sleeve(
            name=self.name.text().strip() or _tr("未命名"),
            kind=k, symbols=[] if k == CASH else syms,
            weight=self.weight.value() / 100.0,
            strategy_key=self.strategy.currentData() if k == STRATEGY else "buy_hold",
            rotation={"lookback": self.lookback.value(), "top_k": self.topk.value(),
                      "rebalance_bars": 21, "abs_momentum": True} if k == ROTATION else {})


# ======================================================================
class PortfolioTab(QtWidgets.QWidget):
    status = QtCore.pyqtSignal(str)

    def __init__(self, market, settings, parent=None):
        super().__init__(parent)
        self.market = market
        self.settings = settings
        self.sleeves: list = PRESETS[1][1]()
        self.result = None

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        side = Card(_tr("组合构成"))
        side.setMaximumWidth(360)
        side.setMinimumWidth(330)
        intro = QtWidgets.QLabel(
            _tr("金融里唯一免费的午餐是<b>分散</b>：几个相关性低的收益来源拼起来，"
            "夏普会高于其中任何一个，回撤还更小。<br>"
            "要更高收益，正确做法是调「卫星」的比例，不是去梭哈更疯的标的。"))
        intro.setObjectName("Dim")
        intro.setWordWrap(True)
        side.vbox.addWidget(intro)

        side.vbox.addWidget(QtWidgets.QLabel(_tr("预设组合")))
        self.preset = QtWidgets.QComboBox()
        for label, _ in PRESETS:
            self.preset.addItem(_tr(label))     # PRESETS 里存的是原文
        self.preset.setCurrentIndex(1)
        self.preset.currentIndexChanged.connect(self._load_preset)
        side.vbox.addWidget(self.preset)

        self.sleeve_table = make_table([_tr("名称"), _tr("类型"), _tr("内容"), _tr("权重")], stretch_col=2)
        self.sleeve_table.setMaximumHeight(190)
        self.sleeve_table.doubleClicked.connect(self._edit_sleeve)
        side.vbox.addWidget(self.sleeve_table)

        brow = QtWidgets.QHBoxLayout()
        for label, slot in ((_tr("添加"), self._add_sleeve), (_tr("编辑"), self._edit_sleeve),
                            (_tr("删除"), self._del_sleeve)):
            b = QtWidgets.QPushButton(label)
            b.clicked.connect(slot)
            brow.addWidget(b)
        side.vbox.addLayout(brow)

        form = QtWidgets.QFormLayout()
        form.setSpacing(6)
        self.period = PeriodPicker()
        form.addRow(_tr("回测区间"), self.period)
        self.rebal = QtWidgets.QComboBox()
        for label, bars in ((_tr("每月"), 21), (_tr("每季度"), 63), (_tr("每半年"), 126),
                            (_tr("每年"), 252), (_tr("从不"), 0)):
            self.rebal.addItem(label, bars)
        self.rebal.setCurrentIndex(1)
        form.addRow(_tr("再平衡"), self.rebal)
        self.cash = QtWidgets.QDoubleSpinBox()
        self.cash.setRange(1000, 10_000_000); self.cash.setDecimals(0)
        self.cash.setSingleStep(10000); self.cash.setValue(100000)
        self.cash.setPrefix("$ "); self.cash.setGroupSeparatorShown(True)
        form.addRow(_tr("初始资金"), self.cash)
        self.lev = QtWidgets.QDoubleSpinBox()
        self.lev.setRange(1.0, 3.0); self.lev.setSingleStep(0.25)
        self.lev.setValue(1.0); self.lev.setSuffix(_tr(" 倍"))
        self.lev.setToolTip(_tr("散户融资利率 6%，对年化 8% 左右的组合加杠杆通常得不偿失"))
        form.addRow(_tr("融资杠杆"), self.lev)
        self.vol_target = QtWidgets.QDoubleSpinBox()
        self.vol_target.setRange(0, 40); self.vol_target.setSuffix(" %")
        self.vol_target.setValue(0)
        self.vol_target.setToolTip(_tr("0 = 关闭。开启后按实际波动率动态调整总仓位"))
        form.addRow(_tr("目标年化波动率"), self.vol_target)
        side.vbox.addLayout(form)

        self.rp_check = QtWidgets.QCheckBox(_tr("用风险平价自动分配权重（按波动率倒数）"))
        side.vbox.addWidget(self.rp_check)

        self.run_btn = QtWidgets.QPushButton(_tr("运行组合回测"))
        self.run_btn.setObjectName("Primary")
        self.run_btn.setMinimumHeight(34)
        self.run_btn.clicked.connect(self._run)
        side.vbox.addWidget(self.run_btn)
        self.status_lab = QtWidgets.QLabel("")
        self.status_lab.setObjectName("Dim")
        self.status_lab.setWordWrap(True)
        side.vbox.addWidget(self.status_lab)
        side.vbox.addStretch(1)
        root.addWidget(side)

        right = QtWidgets.QVBoxLayout()
        right.setSpacing(8)

        chart = Card()
        self.title = QtWidgets.QLabel(_tr("选好组合后点「运行组合回测」"))
        self.title.setObjectName("Title")
        chart.vbox.addWidget(self.title)
        self.plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(orientation="bottom"),
                                          "left": MoneyAxis()})
        self.plot.showGrid(x=True, y=True, alpha=0.12)
        self.plot.getAxis("left").setWidth(88)
        self.plot.addLegend(offset=(10, 10))
        self.curve = self.plot.plot([], [], pen=pg.mkPen(theme.ACCENT, width=2.2), name=_tr("组合"))
        self.bench = self.plot.plot([], [], pen=pg.mkPen(theme.TEXT_DIM, width=1.4,
                                    style=QtCore.Qt.PenStyle.DashLine), name=_tr("全仓 SPY"))
        self.sleeve_curves: list = []
        chart.vbox.addWidget(self.plot, 1)
        self.show_sleeves = QtWidgets.QCheckBox(_tr("同时画出每一块单独的净值"))
        self.show_sleeves.stateChanged.connect(self._redraw_sleeves)
        chart.vbox.addWidget(self.show_sleeves)
        right.addWidget(chart, 3)

        mc = Card(_tr("绩效指标"))
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(16)
        self.metrics = {}
        items = [("total_return", _tr("总收益")), ("cagr", _tr("年化")), ("sharpe", _tr("夏普")),
                 ("max_drawdown", _tr("最大回撤")), ("calmar", _tr("卡玛")),
                 ("benchmark_return", _tr("全仓SPY")), ("alpha", _tr("超额")),
                 ("avg_correlation", _tr("平均相关性")), ("avg_exposure", _tr("平均仓位")),
                 ("rebalances", _tr("再平衡次数"))]
        for i, (k, t) in enumerate(items):
            box = QtWidgets.QVBoxLayout()
            lt = QtWidgets.QLabel(t); lt.setObjectName("Dim")
            lv = QtWidgets.QLabel("—"); lv.setObjectName("StatValue")
            box.addWidget(lt); box.addWidget(lv)
            h = QtWidgets.QWidget(); h.setLayout(box)
            grid.addWidget(h, 0, i)
            self.metrics[k] = lv
        mc.vbox.addLayout(grid)
        self.verdict = QtWidgets.QLabel("")
        self.verdict.setWordWrap(True)
        mc.vbox.addWidget(self.verdict)
        right.addWidget(mc)

        self.windows = WindowDistWidget()
        right.addWidget(self.windows)

        tabs = QtWidgets.QTabWidget()
        self.corr_table = make_table(["A", "B", _tr("相关性"), _tr("说明")], stretch_col=3)
        tabs.addTab(self.corr_table, _tr("相关性矩阵"))
        self.sleeve_metric_table = make_table(
            [_tr("组成部分"), _tr("权重"), _tr("总收益"), _tr("年化"), _tr("夏普"), _tr("最大回撤")], stretch_col=0)
        tabs.addTab(self.sleeve_metric_table, _tr("各部分单独表现"))
        right.addWidget(tabs, 2)
        root.addLayout(right, 1)

        self.worker = MixWorker(market, settings)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.progress.connect(lambda m: self.status_lab.setText(m))
        self._render_sleeves()

    # ------------------------------------------------------------------
    def _load_preset(self):
        self.sleeves = PRESETS[self.preset.currentIndex()][1]()
        self._render_sleeves()

    def _render_sleeves(self):
        rows = []
        total = sum(s.weight for s in self.sleeves) or 1.0
        for s in self.sleeves:
            rows.append([
                cell(s.name, theme.TEXT, LEFT, bold=True),
                cell(KIND_CN.get(s.kind, s.kind), theme.TEXT_DIM, CENTER),
                cell(s.describe(), theme.TEXT_DIM),
                cell("{:.1f}%".format(s.weight / total * 100), None, RIGHT)])
        fill_table(self.sleeve_table, rows)

    def _add_sleeve(self):
        dlg = SleeveDialog(None, self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.sleeves.append(dlg.sleeve())
            self._render_sleeves()

    def _edit_sleeve(self):
        r = self.sleeve_table.currentRow()
        if not (0 <= r < len(self.sleeves)):
            return
        dlg = SleeveDialog(self.sleeves[r], self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.sleeves[r] = dlg.sleeve()
            self._render_sleeves()

    def _del_sleeve(self):
        r = self.sleeve_table.currentRow()
        if 0 <= r < len(self.sleeves):
            del self.sleeves[r]
            self._render_sleeves()

    # ------------------------------------------------------------------
    def _run(self):
        if not self.sleeves:
            QtWidgets.QMessageBox.information(self, _tr("提示"), _tr("组合里至少要有一块。"))
            return
        start, end = self.period.range()
        cfg = MixConfig(initial_cash=self.cash.value(),
                        rebalance_bars=self.rebal.currentData(),
                        leverage=self.lev.value(),
                        vol_target=self.vol_target.value() / 100.0,
                        interval="1d")
        import copy
        self.run_btn.setEnabled(False)
        self.status_lab.setText(_tr("准备中…"))
        if not self.worker.start_job(copy.deepcopy(self.sleeves), start, end, cfg,
                                     self.rp_check.isChecked()):
            self.run_btn.setEnabled(True)
            self.status_lab.setText(_tr("上一次还在跑"))

    def _on_failed(self, msg):
        self.run_btn.setEnabled(True)
        self.status_lab.setText(msg)
        QtWidgets.QMessageBox.warning(self, _tr("组合回测失败"), msg)

    def _on_done(self, r):
        self.run_btn.setEnabled(True)
        self.result = r
        if not r.ok:
            self.status_lab.setText(r.error)
            QtWidgets.QMessageBox.warning(self, _tr("组合回测失败"), r.error)
            return
        self.status_lab.setText(_tr("完成 · {} 根 K 线").format(r.metrics.get("bars", 0)))
        self.title.setText("{}　·　{}".format(self.preset.currentText(), r.strategy_label))

        xs = [p[0] for p in r.equity]; ys = [p[1] for p in r.equity]
        self.curve.setPen(pg.mkPen(theme.up_color() if ys[-1] >= ys[0]
                                   else theme.down_color(), width=2.2))
        self.curve.setData(xs, ys)
        if r.benchmark:
            self.bench.setData([p[0] for p in r.benchmark], [p[1] for p in r.benchmark])
        self._redraw_sleeves()

        m = r.metrics
        vals = {
            "total_return": (theme.signed_pct(m["total_return"]), theme.pnl_color(m["total_return"])),
            "cagr": (theme.signed_pct(m["cagr"]), theme.pnl_color(m["cagr"])),
            "sharpe": ("{:.2f}".format(m["sharpe"]),
                       theme.up_color() if m["sharpe"] >= 0.8 else None),
            "max_drawdown": ("-{:.1f}%".format(m["max_drawdown"]), theme.down_color()),
            "calmar": ("{:.2f}".format(m["calmar"]),
                       theme.up_color() if m["calmar"] >= 0.4 else None),
            "benchmark_return": (theme.signed_pct(m["benchmark_return"]), theme.TEXT_DIM),
            "alpha": (theme.signed_pct(m["alpha"]), theme.pnl_color(m["alpha"])),
            "avg_correlation": ("{:.2f}".format(m.get("avg_correlation", 0)),
                                theme.up_color() if m.get("avg_correlation", 1) < 0.5 else theme.GOLD),
            "avg_exposure": ("{:.2f}x".format(m.get("avg_exposure", 1)), theme.TEXT_DIM),
            "rebalances": (str(m.get("rebalances", 0)), theme.TEXT_DIM),
        }
        for k, (t, c) in vals.items():
            lab = self.metrics[k]
            lab.setText(t)
            lab.setStyleSheet("color: {};".format(c) if c else "")

        bench_dd = _max_dd(r.benchmark)
        self.verdict.setText(
            _tr("最大回撤 <b>{:.1f}%</b> vs 全仓 SPY <b>{:.1f}%</b>；"
            "年化 {:.1f}% vs {:.1f}%。<br>"
            "<span style='color:{}'>看卡玛比率（年化÷回撤）而不是只看总收益——"
            "回撤才是你真正要承受的东西。平均相关性越低，分散越有效。</span>").format(
                m["max_drawdown"], bench_dd, m["cagr"],
                _cagr(r.benchmark, m.get("years", 1)), theme.TEXT_DIM))

        self.windows.set_equity(r.equity, "1d")

        crows = []
        for (a, b), c in sorted(r.correlation.items(), key=lambda kv: kv[1]):
            note = (_tr("几乎不相关，分散效果好") if abs(c) < 0.3 else
                    _tr("中度相关") if abs(c) < 0.6 else _tr("高度相关，分散作用有限"))
            crows.append([
                cell(a, theme.TEXT, LEFT), cell(b, theme.TEXT, LEFT),
                NumItem("{:+.2f}".format(c), c,
                        theme.up_color() if abs(c) < 0.3 else
                        (theme.GOLD if abs(c) < 0.6 else theme.down_color()), bold=True),
                cell(note, theme.TEXT_DIM)])
        fill_table(self.corr_table, crows)

        srows = []
        for name, mm in r.sleeve_metrics.items():
            srows.append([
                cell(name, theme.TEXT, LEFT, bold=True),
                cell("{:.1f}%".format(r.weights_used.get(name, 0) * 100), None, RIGHT),
                cell(theme.signed_pct(mm["total_return"]), theme.pnl_color(mm["total_return"]), RIGHT),
                cell(theme.signed_pct(mm["cagr"]), None, RIGHT),
                cell("{:.2f}".format(mm["sharpe"]), None, RIGHT),
                cell("-{:.1f}%".format(mm["max_drawdown"]), theme.down_color(), RIGHT)])
        fill_table(self.sleeve_metric_table, srows)

    def _redraw_sleeves(self):
        for c in self.sleeve_curves:
            self.plot.removeItem(c)
        self.sleeve_curves.clear()
        if not (self.result and self.result.ok and self.show_sleeves.isChecked()):
            return
        colors = ["#f0b429", "#a855f7", "#22d3ee", "#f472b6", "#84cc16"]
        base = self.result.equity[0][1] if self.result.equity else 100000.0
        for i, (name, curve) in enumerate(self.result.sleeve_curves.items()):
            if not curve:
                continue
            scale = base / curve[0][1]
            c = self.plot.plot([p[0] for p in curve], [p[1] * scale for p in curve],
                               pen=pg.mkPen(colors[i % len(colors)], width=1.1), name=name)
            self.sleeve_curves.append(c)

    def stop(self):
        if self.worker.isRunning():
            self.worker.wait(1500)


def _max_dd(curve: list) -> float:
    if not curve:
        return 0.0
    peak, mdd = curve[0][1], 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak * 100.0)
    return mdd


def _cagr(curve: list, years: float) -> float:
    if not curve or years <= 0 or curve[0][1] <= 0:
        return 0.0
    return ((curve[-1][1] / curve[0][1]) ** (1 / years) - 1) * 100.0
