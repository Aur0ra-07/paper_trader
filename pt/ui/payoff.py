"""期权损益图: 到期损益 + 当前理论损益。"""
from __future__ import annotations

import pyqtgraph as pg
from PyQt6 import QtCore, QtGui, QtWidgets

from ..options import pricing as pr
from . import theme
from .chart import MoneyAxis
from ..i18n import _tr


class PayoffChart(QtWidgets.QWidget):
    """横轴=到期时底层价格, 纵轴=这笔组合的盈亏 (美元)。

    实线是到期损益 (只剩内在价值), 虚线是"现在平掉"的理论损益 —— 两条线之间的
    垂直距离就是还没耗完的时间价值。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self.readout = QtWidgets.QLabel("")
        self.readout.setObjectName("Dim")
        self.readout.setMinimumHeight(18)
        lay.addWidget(self.readout)

        self.plot = pg.PlotWidget(axisItems={"left": MoneyAxis()})
        self.plot.showGrid(x=True, y=True, alpha=0.12)
        self.plot.getAxis("left").setWidth(70)
        self.plot.setLabel("bottom", _tr("到期时底层价格"))
        lay.addWidget(self.plot, 1)

        self.zero = pg.InfiniteLine(pos=0, angle=0, movable=False,
                                    pen=pg.mkPen(theme.TEXT_DIM, width=1))
        self.plot.addItem(self.zero)
        self.spot_line = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen(theme.ACCENT, width=1.2, style=QtCore.Qt.PenStyle.DashLine),
            label=_tr("现价 {value:.2f}"),
            labelOpts={"position": 0.95, "color": theme.ACCENT,
                       "fill": (20, 24, 30, 200)})
        self.plot.addItem(self.spot_line)

        self.curve_exp = self.plot.plot([], [], pen=pg.mkPen(theme.TEXT, width=2.2),
                                        name=_tr("到期损益"))
        self.curve_now = self.plot.plot(
            [], [], pen=pg.mkPen(theme.GOLD, width=1.4,
                                 style=QtCore.Qt.PenStyle.DashLine), name=_tr("当前损益"))
        self.fill_up = None
        self.fill_dn = None
        self._be_lines: list = []

        self.empty = pg.TextItem(_tr("选好合约后这里会画出损益图"), color=theme.TEXT_DIM,
                                 anchor=(0.5, 0.5))
        self.plot.addItem(self.empty)

        self.vline = pg.InfiniteLine(angle=90, movable=False,
                                     pen=pg.mkPen("#55606f",
                                                  style=QtCore.Qt.PenStyle.DashLine))
        self.plot.addItem(self.vline, ignoreBounds=True)
        self._proxy = pg.SignalProxy(self.plot.scene().sigMouseMoved,
                                     rateLimit=40, slot=self._on_mouse)
        self._xs: list = []
        self._ys: list = []
        self._now: list = []
        self._show_empty(True)

    def _show_empty(self, on: bool) -> None:
        """空状态: 固定视野、藏掉刻度数字、提示文字居中。

        不这么做的话零线和现价线都在 0, 视野塌缩到一个极小区间,
        坐标轴会显示 -1e-112 / 5e-124 这种乱码, 提示文字也会被切掉半截。
        """
        self.empty.setVisible(on)
        self.spot_line.setVisible(not on)
        for ax in ("left", "bottom"):
            self.plot.getAxis(ax).setStyle(showValues=not on)
        if on:
            self.empty.setPos(0, 0)
            self.plot.setXRange(-1, 1, padding=0)
            self.plot.setYRange(-1, 1, padding=0)

    # ------------------------------------------------------------------
    def clear(self):
        self.curve_exp.setData([], [])
        self.curve_now.setData([], [])
        self._clear_fills()
        self._clear_be()
        self._show_empty(True)
        self.readout.setText("")
        self._xs, self._ys, self._now = [], [], []

    def _clear_fills(self):
        for f in (self.fill_up, self.fill_dn):
            if f is not None:
                self.plot.removeItem(f)
        self.fill_up = self.fill_dn = None

    def _clear_be(self):
        for ln in self._be_lines:
            self.plot.removeItem(ln)
        self._be_lines.clear()

    # ------------------------------------------------------------------
    def set_legs(self, legs: list, spot: float, iv: float = 0.0,
                 days_left: float = 0.0) -> dict:
        """legs 见 pricing.payoff_at_expiry。返回关键指标字典。"""
        if not legs or spot <= 0:
            self.clear()
            return {}
        self._show_empty(False)
        self._clear_fills()
        self._clear_be()

        strikes = [l.get("strike", spot) for l in legs if l.get("right") != "S"] or [spot]
        lo = min(min(strikes), spot) * 0.75
        hi = max(max(strikes), spot) * 1.25
        n = 260
        step = (hi - lo) / (n - 1)
        xs = [lo + i * step for i in range(n)]
        ys = [pr.payoff_at_expiry(legs, x) for x in xs]

        # 当前理论损益 (还有时间价值)
        T = max(days_left, 0.0) / 365.0
        now_ys = []
        if T > 0 and iv > 0:
            for x in xs:
                total = 0.0
                for leg in legs:
                    qty = leg.get("qty", 0)
                    mult = leg.get("multiplier", 100)
                    prem = leg.get("premium", 0.0)
                    right = leg.get("right", pr.CALL)
                    K = leg.get("strike", 0.0)
                    if right == "S":
                        total += qty * (x - K)
                        continue
                    v = pr.bs_price(x, K, T, leg.get("iv", iv) or iv, right)
                    total += qty * (v - prem) * mult
                now_ys.append(total)

        self.curve_exp.setData(xs, ys)
        self.curve_now.setData(xs, now_ys) if now_ys else self.curve_now.setData([], [])
        self._xs, self._ys, self._now = xs, ys, now_ys

        # 盈亏区域填色
        zero = pg.PlotCurveItem(xs, [0.0] * len(xs))
        up_col = QtGui.QColor(theme.up_color()); up_col.setAlpha(45)
        dn_col = QtGui.QColor(theme.down_color()); dn_col.setAlpha(45)
        pos_curve = pg.PlotCurveItem(xs, [max(v, 0.0) for v in ys])
        neg_curve = pg.PlotCurveItem(xs, [min(v, 0.0) for v in ys])
        self.fill_up = pg.FillBetweenItem(zero, pos_curve, brush=pg.mkBrush(up_col))
        self.fill_dn = pg.FillBetweenItem(zero, neg_curve, brush=pg.mkBrush(dn_col))
        self.plot.addItem(self.fill_up)
        self.plot.addItem(self.fill_dn)

        self.spot_line.setPos(spot)

        # 盈亏平衡点 = 曲线穿越 0 的地方
        bes = []
        for i in range(1, len(xs)):
            a, b = ys[i - 1], ys[i]
            if a == 0:
                bes.append(xs[i - 1])
            elif (a < 0 < b) or (a > 0 > b):
                t = abs(a) / (abs(a) + abs(b))
                bes.append(xs[i - 1] + t * (xs[i] - xs[i - 1]))
        for x in bes[:4]:
            ln = pg.InfiniteLine(pos=x, angle=90, movable=False,
                                 pen=pg.mkPen(theme.TEXT_DIM, width=1,
                                              style=QtCore.Qt.PenStyle.DotLine),
                                 label=_tr("平衡 {:.2f}").format(x),
                                 labelOpts={"position": 0.08, "color": theme.TEXT_DIM,
                                            "fill": (20, 24, 30, 190)})
            self.plot.addItem(ln)
            self._be_lines.append(ln)

        pad = (max(ys) - min(ys)) * 0.15 or 100
        self.plot.setYRange(min(ys) - pad, max(ys) + pad, padding=0)
        self.plot.setXRange(lo, hi, padding=0)

        return {
            "breakevens": bes,
            "max_profit": max(ys),
            "max_loss": min(ys),
            "payoff_at_spot": pr.payoff_at_expiry(legs, spot),
            "unlimited_up": ys[-1] >= max(ys) - 1e-6 and ys[-1] > ys[len(ys) // 2],
            "unlimited_down": ys[0] >= max(ys) - 1e-6 and ys[0] > ys[len(ys) // 2],
        }

    # ------------------------------------------------------------------
    def _on_mouse(self, evt):
        pos = evt[0]
        if not self._xs or not self.plot.sceneBoundingRect().contains(pos):
            return
        mp = self.plot.getPlotItem().vb.mapSceneToView(pos)
        x = mp.x()
        self.vline.setPos(x)
        lo, hi = self._xs[0], self._xs[-1]
        if not (lo <= x <= hi):
            return
        i = min(int((x - lo) / (hi - lo) * (len(self._xs) - 1)), len(self._xs) - 1)
        y = self._ys[i]
        txt = (_tr('底层 <b>{:.2f}</b> 时  到期损益 <b style="color:{}">{}</b>').format(
            self._xs[i], theme.pnl_color(y), theme.signed_money(y)))
        if self._now:
            yn = self._now[i]
            txt += _tr('   现在平掉 <span style="color:{}">{}</span>').format(
                theme.pnl_color(yn), theme.signed_money(yn))
        self.readout.setText(txt)
