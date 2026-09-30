"""轮动回测 + 稳健性批量测试两个面板。"""
from __future__ import annotations

import calendar
import datetime
import time

import pyqtgraph as pg
from PyQt6 import QtCore, QtWidgets

from .. import universe
from ..market import MarketData
from ..strategy import backtest as bt, library, rotation
from ..strategy.backtest import BacktestConfig
from ..strategy.rotation import RotationConfig
from . import theme
from .panels import Card, NumItem, make_table, cell, fill_table, LEFT, RIGHT, CENTER
from .chart import MoneyAxis
from ..i18n import _tr


def _ep(y: int, mo: int = 1, d: int = 1) -> int:
    return int(calendar.timegm(datetime.date(y, mo, d).timetuple()))


def _year(ts: float) -> str:
    return datetime.date.fromtimestamp(ts).strftime("%Y-%m-%d")


def window_presets(interval: str) -> list:
    bpy = bt.BARS_PER_YEAR.get(interval, 252)
    return [(_tr("1 个月"), max(int(bpy / 12), 2)),
            (_tr("3 个月"), max(int(bpy / 4), 3)),
            (_tr("6 个月"), max(int(bpy / 2), 5)),
            (_tr("1 年"), max(int(bpy), 10))]


class WindowDistWidget(Card):
    """滚动窗口收益分布 —— 回答「几个月能赚多少」唯一诚实的方式。"""

    def __init__(self, parent=None):
        super().__init__(_tr("持有 N 个月的收益分布 (任意一天入场, 历史上所有可能的结果)"), parent)
        self.table = make_table(
            [_tr("持有时长"), _tr("最差"), _tr("较差(10%)"), _tr("中位"), _tr("较好(90%)"), _tr("最好"),
             _tr("赚钱概率"), _tr("赚超50%概率"), _tr("亏超20%概率"), _tr("样本数")], stretch_col=0)
        self.table.setMaximumHeight(170)
        self.vbox.addWidget(self.table)
        self.note = QtWidgets.QLabel(
            _tr("「中位」才是你该预期的那个数, 「最好」那一列是历史上最幸运的一次入场, 不是你能复制的。"
            "重点看最左边那两列 —— 那是你真的会遇到的坏情况。"))
        self.note.setObjectName("Dim")
        self.note.setWordWrap(True)
        self.vbox.addWidget(self.note)

    def set_equity(self, equity: list, interval: str = "1d") -> None:
        rows = []
        for label, bars in window_presets(interval):
            w = bt.rolling_windows(equity, bars)
            if not w:
                continue
            rows.append([
                cell(label, theme.TEXT, LEFT, bold=True),
                NumItem(theme.signed_pct(w["worst"]), w["worst"], theme.down_color(), bold=True),
                NumItem(theme.signed_pct(w["p10"]), w["p10"], theme.pnl_color(w["p10"])),
                NumItem(theme.signed_pct(w["median"]), w["median"],
                        theme.pnl_color(w["median"]), bold=True),
                NumItem(theme.signed_pct(w["p90"]), w["p90"], theme.pnl_color(w["p90"])),
                NumItem(theme.signed_pct(w["best"]), w["best"], theme.up_color()),
                NumItem("{:.0f}%".format(w["win_rate"]), w["win_rate"],
                        theme.up_color() if w["win_rate"] >= 60 else theme.GOLD),
                NumItem("{:.0f}%".format(w["gain_50_rate"]), w["gain_50_rate"], theme.up_color()),
                NumItem("{:.0f}%".format(w["loss_20_rate"]), w["loss_20_rate"], theme.down_color()),
                NumItem(str(w["n"]), w["n"], theme.TEXT_DIM),
            ])
        fill_table(self.table, rows)

    def clear(self) -> None:
        fill_table(self.table, [])

class UniversePicker(QtWidgets.QWidget):
    """标的池选择: 板块 / 自选股 / 手输。"""

    def __init__(self, get_watchlist, parent=None):
        super().__init__(parent)
        self.get_watchlist = get_watchlist
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)
        self.combo = QtWidgets.QComboBox()
        self.combo.addItem(_tr("自选股"), "watchlist")
        for name, syms in universe.SECTORS:
            self.combo.addItem(_tr("板块: {} ({})").format(name, len(syms)), "sector:" + name)
        self.combo.addItem(_tr("自定义 (手动输入)"), "custom")
        self.combo.currentIndexChanged.connect(self._on_change)
        lay.addWidget(self.combo)
        self.custom = QtWidgets.QLineEdit(
            "XLK,XLF,XLE,XLV,XLY,XLP,XLI,XLU,XLB,SMH,IWM,EFA,EEM,TLT,GLD")
        self.custom.setPlaceholderText(_tr("代码用逗号分隔"))
        self.custom.setVisible(False)
        lay.addWidget(self.custom)

    def _on_change(self):
        self.custom.setVisible(self.combo.currentData() == "custom")

    def symbols(self) -> list:
        mode = self.combo.currentData()
        if mode == "watchlist":
            return list(self.get_watchlist())
        if mode == "custom":
            return [s.strip().upper() for s in self.custom.text().split(",") if s.strip()]
        return list(universe.SECTOR_MAP.get(mode.split(":", 1)[1], []))

    def label(self) -> str:
        return self.combo.currentText()


class PeriodPicker(QtWidgets.QWidget):
    """回测区间: 起止年份 (可以一直拉到 1998, 用来测熊市)。"""

    PRESETS = [
        (_tr("最近 10 年"), 2016, 2027),
        (_tr("最近 5 年"), 2021, 2027),
        (_tr("2004-至今 (含2008)"), 2004, 2027),
        (_tr("1998-2012 (两次崩盘)"), 1998, 2012),
        (_tr("2000-2003 互联网泡沫"), 2000, 2003),
        (_tr("2007-2009 金融危机"), 2007, 2009),
        (_tr("2020 疫情"), 2019, 2021),
        (_tr("2022 加息熊市"), 2021, 2023),
        (_tr("自定义"), 0, 0),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)
        self.combo = QtWidgets.QComboBox()
        for label, a, b in self.PRESETS:
            self.combo.addItem(label, (a, b))
        self.combo.currentIndexChanged.connect(self._on_change)
        lay.addWidget(self.combo)
        row = QtWidgets.QHBoxLayout()
        self.y1 = QtWidgets.QSpinBox(); self.y1.setRange(1980, 2027); self.y1.setValue(2016)
        self.y2 = QtWidgets.QSpinBox(); self.y2.setRange(1981, 2027); self.y2.setValue(2027)
        row.addWidget(self.y1); row.addWidget(QtWidgets.QLabel("→")); row.addWidget(self.y2)
        self.row_widget = QtWidgets.QWidget(); self.row_widget.setLayout(row)
        self.row_widget.setVisible(False)
        lay.addWidget(self.row_widget)

    def _on_change(self):
        a, b = self.combo.currentData()
        custom = (a == 0)
        self.row_widget.setVisible(custom)
        if not custom:
            self.y1.setValue(a); self.y2.setValue(b)

    def range(self) -> tuple:
        y1, y2 = self.y1.value(), self.y2.value()
        if y2 <= y1:
            y2 = y1 + 1
        return _ep(y1), min(_ep(y2), int(time.time()))

    def label(self) -> str:
        return self.combo.currentText()


# ======================================================================
class RotationWorker(QtCore.QThread):
    done = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(str)

    def __init__(self, market, settings, parent=None):
        super().__init__(parent)
        self.market = market
        self.settings = settings
        self.job = None

    def start_job(self, symbols, start, end, interval, cfg):
        self.job = (symbols, start, end, interval, cfg)
        self.start()

    def run(self):
        symbols, start, end, interval, cfg = self.job
        data = {}
        for n, s in enumerate(symbols, 1):
            self.progress.emit(_tr("拉取 {} ({}/{})").format(s, n, len(symbols)))
            try:
                c = self.market.candles_between(s, start, end, interval)
                if len(c) > 50:
                    data[s] = c
            except Exception:
                pass
            time.sleep(0.1)
        if len(data) < 2:
            self.failed.emit(_tr("只拿到 {} 个标的的数据, 轮动至少需要 2 个").format(len(data)))
            return
        self.progress.emit(_tr("轮动回测中… ({} 只)").format(len(data)))
        try:
            self.done.emit(rotation.run(data, self.settings, cfg))
        except Exception as exc:
            self.failed.emit(_tr("回测失败: {}").format(exc))


class RobustWorker(QtCore.QThread):
    done = QtCore.pyqtSignal(list, dict)
    failed = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(str)

    def __init__(self, market, settings, parent=None):
        super().__init__(parent)
        self.market = market
        self.settings = settings
        self.job = None
        self._stop = False

    def start_job(self, symbols, start, end, interval, keys, cfg):
        self.job = (symbols, start, end, interval, keys, cfg)
        self._stop = False
        self.start()

    def stop(self):
        self._stop = True

    def run(self):
        symbols, start, end, interval, keys, cfg = self.job
        data = {}
        for n, s in enumerate(symbols, 1):
            if self._stop:
                break
            self.progress.emit(_tr("拉取 {} ({}/{})").format(s, n, len(symbols)))
            try:
                c = self.market.candles_between(s, start, end, interval)
                if len(c) > 260:
                    data[s] = c
            except Exception:
                pass
            time.sleep(0.1)
        if not data:
            self.failed.emit(_tr("没有拿到足够长的 K 线"))
            return

        rows, detail = [], {}
        for n, key in enumerate(keys, 1):
            if self._stop:
                break
            self.progress.emit(_tr("回测 {} ({}/{})").format(
                library.REGISTRY[key].name, n, len(keys)))
            alphas, sharpes, dds, rets, per_symbol = [], [], [], [], []
            for sym, c in data.items():
                try:
                    r = bt.run(c, library.create(key), self.settings, cfg, sym)
                except Exception:
                    continue
                if not r.ok:
                    continue
                mm = r.metrics
                alphas.append(mm["alpha"]); sharpes.append(mm["sharpe"])
                dds.append(mm["max_drawdown"]); rets.append(mm["total_return"])
                per_symbol.append((sym, mm["total_return"], mm["benchmark_return"],
                                   mm["alpha"], mm["sharpe"], mm["max_drawdown"]))
            if not alphas:
                continue
            srt = sorted(alphas)
            rows.append({
                "key": key, "name": library.REGISTRY[key].name,
                "n": len(alphas), "win": sum(1 for a in alphas if a > 0),
                "median_alpha": srt[len(srt) // 2],
                "mean_alpha": sum(alphas) / len(alphas),
                "mean_sharpe": sum(sharpes) / len(sharpes),
                "mean_dd": sum(dds) / len(dds),
                "median_return": sorted(rets)[len(rets) // 2],
            })
            detail[key] = per_symbol
        self.done.emit(rows, detail)


# ======================================================================
class RotationPanel(QtWidgets.QWidget):
    status = QtCore.pyqtSignal(str)

    def __init__(self, market: MarketData, settings, get_watchlist, parent=None):
        super().__init__(parent)
        self.market = market
        self.settings = settings
        self.result = None

        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        side = Card(_tr("动量轮动设置"))
        side.setMaximumWidth(330)
        side.setMinimumWidth(300)

        intro = QtWidgets.QLabel(
            _tr("不再问「这只股票该不该买」, 而是问「这一篮子里哪几只最强」。<br>"
            "永远满仓最强的几只, 定期换马; 开了绝对动量的话, 全都在跌时退回现金。"))
        intro.setObjectName("Dim")
        intro.setWordWrap(True)
        side.vbox.addWidget(intro)

        side.vbox.addWidget(QtWidgets.QLabel(_tr("标的池")))
        self.picker = UniversePicker(get_watchlist)
        side.vbox.addWidget(self.picker)

        side.vbox.addWidget(QtWidgets.QLabel(_tr("回测区间")))
        self.period = PeriodPicker()
        side.vbox.addWidget(self.period)

        form = QtWidgets.QFormLayout()
        form.setSpacing(6)
        self.f_interval = QtWidgets.QComboBox()
        self.f_interval.addItem(_tr("日线"), "1d")
        self.f_interval.addItem(_tr("周线"), "1wk")
        form.addRow(_tr("周期"), self.f_interval)

        self.f_lookback = QtWidgets.QSpinBox(); self.f_lookback.setRange(10, 750)
        self.f_lookback.setValue(120)
        self.f_lookback.setToolTip(_tr("日线 120 根 ≈ 半年动量"))
        form.addRow(_tr("动量回看(根)"), self.f_lookback)

        self.f_lookback2 = QtWidgets.QSpinBox(); self.f_lookback2.setRange(0, 750)
        self.f_lookback2.setValue(0)
        self.f_lookback2.setToolTip(_tr("0 = 不用。设了就和主窗口取平均, 更稳一些"))
        form.addRow(_tr("第二回看窗口"), self.f_lookback2)

        self.f_skip = QtWidgets.QSpinBox(); self.f_skip.setRange(0, 60); self.f_skip.setValue(0)
        self.f_skip.setToolTip(_tr("跳过最近 N 根 —— 学术上短期有反转效应"))
        form.addRow(_tr("跳过最近(根)"), self.f_skip)

        self.f_topk = QtWidgets.QSpinBox(); self.f_topk.setRange(1, 20); self.f_topk.setValue(3)
        form.addRow(_tr("持有前几名"), self.f_topk)

        self.f_rebal = QtWidgets.QSpinBox(); self.f_rebal.setRange(1, 250)
        self.f_rebal.setValue(21)
        self.f_rebal.setToolTip(_tr("日线 21 根 ≈ 每月调仓; 太频繁会被手续费吃掉"))
        form.addRow(_tr("调仓间隔(根)"), self.f_rebal)

        self.f_trend = QtWidgets.QSpinBox(); self.f_trend.setRange(0, 250); self.f_trend.setValue(0)
        self.f_trend.setToolTip(_tr("0 = 不用。要求价格在该均线之上才买"))
        form.addRow(_tr("趋势均线过滤"), self.f_trend)

        self.f_cash = QtWidgets.QDoubleSpinBox()
        self.f_cash.setRange(1000, 10_000_000); self.f_cash.setDecimals(0)
        self.f_cash.setSingleStep(10000); self.f_cash.setValue(100000)
        self.f_cash.setPrefix("$ "); self.f_cash.setGroupSeparatorShown(True)
        form.addRow(_tr("初始资金"), self.f_cash)
        side.vbox.addLayout(form)

        self.f_lev = QtWidgets.QDoubleSpinBox()
        self.f_lev.setRange(1.0, 4.0); self.f_lev.setSingleStep(0.5)
        self.f_lev.setValue(1.0); self.f_lev.setSuffix(_tr(" 倍"))
        self.f_lev.setToolTip(_tr("1 = 不融资。>1 会按年化利率计息, 且净值击穿维持保证金会被强平"))
        form.addRow(_tr("融资杠杆"), self.f_lev)

        self.f_abs = QtWidgets.QCheckBox(_tr("绝对动量 (全都在跌时退回现金)"))
        self.f_abs.setChecked(True)
        side.vbox.addWidget(self.f_abs)

        self.run_btn = QtWidgets.QPushButton(_tr("运行轮动回测"))
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
        self.title = QtWidgets.QLabel(_tr("选好标的池后点「运行轮动回测」"))
        self.title.setObjectName("Title")
        chart.vbox.addWidget(self.title)
        self.plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(orientation="bottom"),
                                          "left": MoneyAxis()})
        self.plot.showGrid(x=True, y=True, alpha=0.12)
        self.plot.getAxis("left").setWidth(88)
        self.plot.addLegend(offset=(10, 10))
        self.curve = self.plot.plot([], [], pen=pg.mkPen(theme.ACCENT, width=2), name=_tr("轮动策略"))
        self.bench = self.plot.plot([], [], pen=pg.mkPen(theme.TEXT_DIM, width=1.4,
                                    style=QtCore.Qt.PenStyle.DashLine), name=_tr("等权买入持有"))
        chart.vbox.addWidget(self.plot, 1)
        right.addWidget(chart, 3)

        mcard = Card(_tr("绩效指标"))
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(18)
        self.metrics = {}
        items = [("total_return", _tr("总收益")), ("cagr", _tr("年化")), ("sharpe", _tr("夏普")),
                 ("max_drawdown", _tr("最大回撤")), ("calmar", _tr("卡玛")),
                 ("benchmark_return", _tr("等权买入持有")), ("alpha", _tr("超额收益")),
                 ("n_trades", _tr("换手次数")), ("rebalances", _tr("调仓次数")),
                 ("total_costs", _tr("累计费用")), ("win_rate", _tr("胜率"))]
        for i, (k, t) in enumerate(items):
            r, c = divmod(i, 6)
            box = QtWidgets.QVBoxLayout()
            lt = QtWidgets.QLabel(t); lt.setObjectName("Dim")
            lv = QtWidgets.QLabel("—"); lv.setObjectName("StatValue")
            box.addWidget(lt); box.addWidget(lv)
            h = QtWidgets.QWidget(); h.setLayout(box)
            grid.addWidget(h, r, c)
            self.metrics[k] = lv
        mcard.vbox.addLayout(grid)
        self.verdict = QtWidgets.QLabel("")
        self.verdict.setWordWrap(True)
        mcard.vbox.addWidget(self.verdict)
        right.addWidget(mcard)

        self.windows = WindowDistWidget()
        right.addWidget(self.windows)

        tabs = QtWidgets.QTabWidget()
        self.hold_table = make_table([_tr("调仓日期"), _tr("持有标的")], stretch_col=1)
        tabs.addTab(self.hold_table, _tr("持仓变迁"))
        self.trade_table = make_table(
            [_tr("买入"), _tr("代码"), _tr("股数"), _tr("买入价"), _tr("卖出"), _tr("卖出价"), _tr("盈亏"), _tr("盈亏%"), _tr("持有K线"), _tr("原因")],
            stretch_col=1)
        tabs.addTab(self.trade_table, _tr("换仓明细"))
        right.addWidget(tabs, 2)
        root.addLayout(right, 1)

        self.worker = RotationWorker(market, settings)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.progress.connect(lambda m: self.status_lab.setText(m))

    def _run(self):
        if self.worker.isRunning():
            return
        syms = self.picker.symbols()
        if len(syms) < 2:
            QtWidgets.QMessageBox.information(self, _tr("提示"), _tr("轮动至少需要 2 个标的。"))
            return
        start, end = self.period.range()
        cfg = RotationConfig(
            lookback=self.f_lookback.value(), lookback2=self.f_lookback2.value(),
            skip_recent=self.f_skip.value(), top_k=self.f_topk.value(),
            rebalance_bars=self.f_rebal.value(), abs_momentum=self.f_abs.isChecked(),
            trend_ma=self.f_trend.value(), initial_cash=self.f_cash.value(),
            interval=self.f_interval.currentData(), leverage=self.f_lev.value())
        self.run_btn.setEnabled(False)
        self.status_lab.setText(_tr("准备中…"))
        self.worker.start_job(syms, start, end, self.f_interval.currentData(), cfg)

    def _on_failed(self, msg):
        self.run_btn.setEnabled(True)
        self.status_lab.setText(msg)
        QtWidgets.QMessageBox.warning(self, _tr("轮动回测失败"), msg)

    def _on_done(self, res):
        self.run_btn.setEnabled(True)
        self.result = res
        if not res.ok:
            self.status_lab.setText(res.error)
            QtWidgets.QMessageBox.warning(self, _tr("轮动回测失败"), res.error)
            return
        self.status_lab.setText(_tr("完成 · {} 只标的 · {} 根 K 线").format(
            len(res.symbols), res.metrics.get("bars", 0)))
        self.title.setText("{}  —  {} ({} ~ {})".format(
            self.picker.label(), res.strategy_label,
            _year(res.equity[0][0]), _year(res.equity[-1][0])))

        xs = [p[0] for p in res.equity]; ys = [p[1] for p in res.equity]
        up = ys[-1] >= ys[0]
        self.curve.setPen(pg.mkPen(theme.up_color() if up else theme.down_color(), width=2))
        self.curve.setData(xs, ys)
        self.bench.setData([p[0] for p in res.benchmark], [p[1] for p in res.benchmark])

        m = res.metrics
        vals = {
            "total_return": (theme.signed_pct(m.get("total_return", 0)),
                             theme.pnl_color(m.get("total_return", 0))),
            "cagr": (theme.signed_pct(m.get("cagr", 0)), theme.pnl_color(m.get("cagr", 0))),
            "sharpe": ("{:.2f}".format(m.get("sharpe", 0)),
                       theme.up_color() if m.get("sharpe", 0) >= 1 else None),
            "max_drawdown": ("-{:.1f}%".format(m.get("max_drawdown", 0)), theme.down_color()),
            "calmar": ("{:.2f}".format(m.get("calmar", 0)), None),
            "benchmark_return": (theme.signed_pct(m.get("benchmark_return", 0)), theme.TEXT_DIM),
            "alpha": (theme.signed_pct(m.get("alpha", 0)), theme.pnl_color(m.get("alpha", 0))),
            "n_trades": (str(m.get("n_trades", 0)), None),
            "rebalances": (str(m.get("rebalances", 0)), theme.TEXT_DIM),
            "total_costs": (theme.money(m.get("total_costs", 0), 0), theme.TEXT_DIM),
            "win_rate": ("{:.0f}%".format(m.get("win_rate", 0)), None),
        }
        for k, (t, col) in vals.items():
            lab = self.metrics[k]
            lab.setText(t)
            lab.setStyleSheet("color: {};".format(col) if col else "")

        alpha = m.get("alpha", 0)
        bench_dd = _max_dd(res.benchmark)
        if alpha > 0:
            head = _tr('<span style="color:{}">跑赢等权买入持有 {:.1f} 个百分点</span>').format(
                theme.up_color(), alpha)
        else:
            head = _tr('<span style="color:{}">跑输等权买入持有 {:.1f} 个百分点</span>').format(
                theme.down_color(), abs(alpha))
        mc = m.get("margin_calls", 0)
        mc_txt = (_tr("<br><span style='color:{}'>期间被追加保证金强制平仓 {} 次 —— "
                  "杠杆在高波动标的上会把你在最低点扫出局。</span>").format(theme.RED, mc)) if mc else ""
        self.verdict.setText(
            _tr("{}；最大回撤 {:.1f}% vs 基准 {:.1f}%。<br>"
            "<span style='color:{}'>注意选择偏差: 如果标的池是你按今天的认知挑出来的赢家"
            "(比如「现在最强的科技股」), 回测结果会严重虚高。板块 ETF 这类固定名单最可信。</span>").format(
                head, m.get("max_drawdown", 0), bench_dd, theme.GOLD) + mc_txt)

        self.windows.set_equity(res.equity, self.f_interval.currentData())

        fill_table(self.hold_table, [
            [cell(_year(ts), theme.TEXT_DIM),
             cell("  ".join(syms) if syms else _tr("空仓 (全都在跌)"),
                  theme.TEXT if syms else theme.GOLD)]
            for ts, syms in res.holdings[-400:]])

        rows = []
        for t in res.trades[-500:]:
            col = theme.pnl_color(t.pnl)
            rows.append([
                cell(_year(t.entry_ts), theme.TEXT_DIM),
                cell(t.symbol, theme.TEXT, LEFT, bold=True),
                cell("{:,}".format(t.qty), None, RIGHT),
                cell("{:.2f}".format(t.entry_price), None, RIGHT),
                cell(_year(t.exit_ts), theme.TEXT_DIM),
                cell("{:.2f}".format(t.exit_price), None, RIGHT),
                cell(theme.signed_money(t.pnl), col, RIGHT, bold=True),
                cell(theme.signed_pct(t.pnl_pct), col, RIGHT),
                cell(str(t.bars_held), theme.TEXT_DIM, RIGHT),
                cell(t.exit_reason, theme.TEXT_DIM, CENTER),
            ])
        fill_table(self.trade_table, rows)

    def stop(self):
        if self.worker.isRunning():
            self.worker.wait(1500)


# ======================================================================
class RobustnessPanel(QtWidgets.QWidget):
    """把一个策略丢到一整篮子股票上跑, 看它到底是真有效还是撞了大运。"""

    status = QtCore.pyqtSignal(str)

    def __init__(self, market: MarketData, settings, get_watchlist, parent=None):
        super().__init__(parent)
        self.market = market
        self.settings = settings
        self.rows = []
        self.detail = {}

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        top = Card(_tr("稳健性测试 —— 别用一只股票的回测结果骗自己"))
        intro = QtWidgets.QLabel(
            _tr("在单只股票上回测出来的漂亮结果, 很可能只是这只股票恰好适合这个策略。"
            "这里把每个策略丢到<b>整篮子标的</b>上跑一遍, 看它跑赢自身基准的比例、超额收益的<b>中位数</b>"
            "(不是平均数, 平均数会被个别极端值带偏), 以及平均夏普。<br>"
            "<b>判断标准: 跑赢家数要明显过半, 中位超额要为正, 平均夏普要高于买入持有那一行。</b>"))
        intro.setObjectName("Dim")
        intro.setWordWrap(True)
        top.vbox.addWidget(intro)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(QtWidgets.QLabel(_tr("标的池")))
        self.picker = UniversePicker(get_watchlist)
        self.picker.setMaximumWidth(260)
        row.addWidget(self.picker)
        row.addWidget(QtWidgets.QLabel(_tr("区间")))
        self.period = PeriodPicker()
        self.period.setMaximumWidth(200)
        row.addWidget(self.period)
        self.run_btn = QtWidgets.QPushButton(_tr("全策略横评"))
        self.run_btn.setObjectName("Primary")
        self.run_btn.clicked.connect(self._run)
        row.addWidget(self.run_btn)
        self.stop_btn = QtWidgets.QPushButton(_tr("停止"))
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(lambda: self.worker.stop())
        row.addWidget(self.stop_btn)
        row.addStretch(1)
        self.status_lab = QtWidgets.QLabel("")
        self.status_lab.setObjectName("Dim")
        row.addWidget(self.status_lab)
        top.vbox.addLayout(row)
        lay.addWidget(top)

        card = Card(_tr("横评结果 (按平均夏普排序)"))
        self.table = make_table(
            [_tr("策略"), _tr("跑赢/总数"), _tr("跑赢比例"), _tr("中位超额"), _tr("平均超额"), _tr("中位收益"),
             _tr("平均夏普"), _tr("平均回撤")], stretch_col=0)
        self.table.setSortingEnabled(True)
        self.table.itemSelectionChanged.connect(self._show_detail)
        card.vbox.addWidget(self.table, 1)
        lay.addWidget(card, 1)

        dcard = Card(_tr("选中策略的逐只明细"))
        self.detail_table = make_table(
            [_tr("代码"), _tr("策略收益"), _tr("买入持有"), _tr("超额"), _tr("夏普"), _tr("最大回撤")], stretch_col=0)
        self.detail_table.setSortingEnabled(True)
        dcard.vbox.addWidget(self.detail_table, 1)
        lay.addWidget(dcard, 1)

        self.worker = RobustWorker(market, settings)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.progress.connect(lambda m: self.status_lab.setText(m))

    def _run(self):
        if self.worker.isRunning():
            return
        syms = self.picker.symbols()
        if len(syms) < 3:
            QtWidgets.QMessageBox.information(self, _tr("提示"), _tr("稳健性测试至少需要 3 个标的。"))
            return
        start, end = self.period.range()
        cfg = BacktestConfig(initial_cash=100000, position_pct=95, interval="1d")
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_lab.setText(_tr("准备中…"))
        self.worker.start_job(syms, start, end, "1d", list(library.STRATEGY_ORDER), cfg)

    def _on_failed(self, msg):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_lab.setText(msg)
        QtWidgets.QMessageBox.warning(self, _tr("测试失败"), msg)

    def _on_done(self, rows, detail):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.rows, self.detail = rows, detail
        if not rows:
            self.status_lab.setText(_tr("没有产生结果"))
            return
        n = rows[0]["n"]
        self.status_lab.setText(_tr("完成 · {} 只标的 × {} 个策略").format(n, len(rows)))

        self.table.setSortingEnabled(False)
        items = []
        for r in sorted(rows, key=lambda x: -x["mean_sharpe"]):
            ratio = r["win"] / r["n"] * 100 if r["n"] else 0
            is_bh = r["key"] == "buy_hold"
            items.append([
                cell(r["name"], theme.GOLD if is_bh else theme.TEXT, LEFT, bold=is_bh),
                cell("{}/{}".format(r["win"], r["n"]), None, CENTER),
                NumItem("{:.0f}%".format(ratio), ratio,
                        theme.up_color() if ratio > 50 else theme.down_color()),
                NumItem("—" if is_bh else theme.signed_pct(r["median_alpha"]),
                        r["median_alpha"],
                        theme.pnl_color(r["median_alpha"]) if not is_bh else theme.TEXT_DIM,
                        bold=True),
                NumItem("—" if is_bh else theme.signed_pct(r["mean_alpha"]),
                        r["mean_alpha"], theme.TEXT_DIM),
                NumItem(theme.signed_pct(r["median_return"]), r["median_return"],
                        theme.pnl_color(r["median_return"])),
                NumItem("{:.2f}".format(r["mean_sharpe"]), r["mean_sharpe"],
                        theme.GOLD if is_bh else None, bold=True),
                NumItem("-{:.1f}%".format(r["mean_dd"]), -r["mean_dd"], theme.down_color()),
            ])
        fill_table(self.table, items)
        self.table.setSortingEnabled(True)
        self.table.sortItems(6, QtCore.Qt.SortOrder.DescendingOrder)

        bh = next((r for r in rows if r["key"] == "buy_hold"), None)
        if bh:
            better = [r["name"] for r in rows
                      if r["key"] != "buy_hold" and r["mean_sharpe"] > bh["mean_sharpe"]]
            self.status_lab.setText(
                _tr("{} · 平均夏普高于买入持有的策略: {}").format(
                    self.status_lab.text(), "、".join(better) if better else _tr("一个都没有")))

    def _show_detail(self):
        r = self.table.currentRow()
        it = self.table.item(r, 0)
        if not it:
            return
        key = next((x["key"] for x in self.rows if x["name"] == it.text()), None)
        rows = self.detail.get(key) or []
        self.detail_table.setSortingEnabled(False)
        items = []
        for sym, ret, bench, alpha, sharpe, dd in rows:
            items.append([
                cell(sym, theme.TEXT, LEFT, bold=True),
                NumItem(theme.signed_pct(ret), ret, theme.pnl_color(ret)),
                NumItem(theme.signed_pct(bench), bench, theme.TEXT_DIM),
                NumItem(theme.signed_pct(alpha), alpha, theme.pnl_color(alpha), bold=True),
                NumItem("{:.2f}".format(sharpe), sharpe),
                NumItem("-{:.1f}%".format(dd), -dd, theme.down_color()),
            ])
        fill_table(self.detail_table, items)
        self.detail_table.setSortingEnabled(True)
        self.detail_table.sortItems(3, QtCore.Qt.SortOrder.DescendingOrder)

    def stop(self):
        if self.worker.isRunning():
            self.worker.stop()
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
