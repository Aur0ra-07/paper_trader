"""K 线图组件 (pyqtgraph): 蜡烛 + 均线 + 成交量 + 十字光标 + 持仓/挂单参考线。"""
from __future__ import annotations

from datetime import datetime

import pyqtgraph as pg
from PyQt6 import QtCore, QtGui, QtWidgets

from . import theme
from ..i18n import _tr

pg.setConfigOptions(antialias=True, background=theme.BG_ALT, foreground=theme.TEXT_DIM)


class CandleItem(pg.GraphicsObject):
    """用 QPicture 一次性绘制所有蜡烛, 保证滚动缩放流畅。"""

    def __init__(self):
        super().__init__()
        self._picture = QtGui.QPicture()
        self._bounds = QtCore.QRectF()
        self.candles: list = []

    def set_data(self, candles: list) -> None:
        self.candles = candles
        self._rebuild()
        self.informViewBoundsChanged()
        self.update()

    def _rebuild(self) -> None:
        self._picture = QtGui.QPicture()
        p = QtGui.QPainter(self._picture)
        if not self.candles:
            p.end()
            self._bounds = QtCore.QRectF()
            return

        up = QtGui.QColor(theme.up_color())
        down = QtGui.QColor(theme.down_color())
        w = 0.34
        lo = min(c.low for c in self.candles)
        hi = max(c.high for c in self.candles)

        for i, c in enumerate(self.candles):
            rising = c.close >= c.open
            col = up if rising else down
            p.setPen(pg.mkPen(col, width=1))
            p.drawLine(QtCore.QPointF(i, c.low), QtCore.QPointF(i, c.high))
            body = QtCore.QRectF(i - w, c.open, w * 2, c.close - c.open)
            if abs(c.close - c.open) < (hi - lo) * 1e-4:
                p.drawLine(QtCore.QPointF(i - w, c.close), QtCore.QPointF(i + w, c.close))
            else:
                p.setBrush(pg.mkBrush(col))
                p.drawRect(body)
        p.end()
        self._bounds = QtCore.QRectF(-1, lo, len(self.candles) + 1, hi - lo)

    def paint(self, p, *args):
        p.drawPicture(0, 0, self._picture)

    def boundingRect(self):
        return self._bounds


class VolumeItem(pg.GraphicsObject):
    def __init__(self):
        super().__init__()
        self._picture = QtGui.QPicture()
        self._bounds = QtCore.QRectF()

    def set_data(self, candles: list) -> None:
        self._picture = QtGui.QPicture()
        p = QtGui.QPainter(self._picture)
        if candles:
            up = QtGui.QColor(theme.up_color()); up.setAlpha(150)
            down = QtGui.QColor(theme.down_color()); down.setAlpha(150)
            mx = max((c.volume for c in candles), default=1) or 1
            for i, c in enumerate(candles):
                col = up if c.close >= c.open else down
                p.setPen(pg.mkPen(col))
                p.setBrush(pg.mkBrush(col))
                p.drawRect(QtCore.QRectF(i - 0.34, 0, 0.68, c.volume))
            self._bounds = QtCore.QRectF(-1, 0, len(candles) + 1, mx * 1.05)
        else:
            self._bounds = QtCore.QRectF()
        p.end()
        self.informViewBoundsChanged()
        self.update()

    def paint(self, p, *args):
        p.drawPicture(0, 0, self._picture)

    def boundingRect(self):
        return self._bounds


class MoneyAxis(pg.AxisItem):
    """净值轴: $4.7M, 不是 4.7e+06。

    pyqtgraph 默认在数值跨度大时直接上科学计数法, 而净值曲线动辄从 10 万涨到
    几千万 (NVDA 20 年买入持有就是 100 倍以上), 满屏 e+07 根本没法读。
    """

    def __init__(self, *a, **kw):
        kw.setdefault("orientation", "left")
        super().__init__(*a, **kw)
        self.enableAutoSIPrefix(False)      # 不开这个它还会自己加 SI 前缀

    PREFIX = "$"

    @classmethod
    def fmt(cls, v: float) -> str:
        p = cls.PREFIX
        sign = "-" if v < 0 else ""          # 负号在 $ 外面, 不是 $-2M
        a = abs(v)
        if a >= 1e9:
            return "{}{}{:g}B".format(sign, p, round(a / 1e9, 2))
        if a >= 1e6:
            return "{}{}{:g}M".format(sign, p, round(a / 1e6, 2))
        if a >= 1e4:
            return "{}{}{:g}K".format(sign, p, round(a / 1e3, 1))
        if a >= 1:
            return "{}{}{:,.0f}".format(sign, p, a)
        return "{}{}{:g}".format(sign, p, round(a, 4))

    def tickStrings(self, values, scale, spacing):
        return [self.fmt(v) for v in values]


class CountAxis(MoneyAxis):
    """成交量轴: 150M, 不是 1.5e+08。和净值轴同一套缩写, 只是不带 $。"""

    PREFIX = ""


class TimeAxis(pg.AxisItem):
    """把 K 线序号映射回时间标签 (跳过休市空档)。"""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.timestamps: list[int] = []
        self.intraday = True

    def tickStrings(self, values, scale, spacing):
        """只有"今年"才省略年份 —— 往年的 09-12 看不出是哪一年。"""
        out = []
        this_year = datetime.now().year
        # 日线/周线: 刻度跨 20 根以上 ≈ 月级, 给到月即可, 不必精确到日
        coarse = spacing >= 20
        # 分时: 整段跨了不止一天时, 每天的第一个刻度带上日期
        multiday = False
        if self.intraday and len(self.timestamps) > 1:
            multiday = (datetime.fromtimestamp(self.timestamps[0]).date()
                        != datetime.fromtimestamp(self.timestamps[-1]).date())
        prev_day = None
        for v in values:
            i = int(round(v))
            if not (0 <= i < len(self.timestamps)):
                out.append("")
                continue
            dt = datetime.fromtimestamp(self.timestamps[i])
            if self.intraday:
                day = dt.date()
                fmt = "%m-%d %H:%M" if (multiday and day != prev_day) else "%H:%M"
                prev_day = day
            elif dt.year == this_year:
                fmt = "%m-%d"
            else:
                fmt = "%Y-%m" if coarse else "%Y-%m-%d"
            out.append(dt.strftime(fmt))
        return out


class ChartWidget(QtWidgets.QWidget):
    """K 线主视图。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.candles: list = []
        self._intraday = True

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self.readout = QtWidgets.QLabel("")
        self.readout.setObjectName("Dim")
        self.readout.setMinimumHeight(18)
        lay.addWidget(self.readout)

        self.glw = pg.GraphicsLayoutWidget()
        lay.addWidget(self.glw, 1)

        self.axis = TimeAxis(orientation="bottom")
        self.p_price = self.glw.addPlot(row=0, col=0)
        self.p_price.showGrid(x=True, y=True, alpha=0.12)
        self.p_price.getAxis("left").setWidth(62)
        self.p_price.hideAxis("bottom")
        self.p_price.setMouseEnabled(x=True, y=False)

        self.glw.nextRow()
        self.p_vol = self.glw.addPlot(row=1, col=0, axisItems={"bottom": self.axis,
                                                              "left": CountAxis()})
        self.p_vol.showGrid(x=True, y=True, alpha=0.12)
        self.p_vol.getAxis("left").setWidth(62)
        self.p_vol.setMaximumHeight(110)
        self.p_vol.setXLink(self.p_price)
        self.p_vol.setMouseEnabled(x=True, y=False)

        self.candle_item = CandleItem()
        self.p_price.addItem(self.candle_item)
        self.vol_item = VolumeItem()
        self.p_vol.addItem(self.vol_item)

        self.ma_lines = {}
        for period, color in ((5, "#f0b429"), (20, "#3b82f6"), (60, "#a855f7")):
            curve = self.p_price.plot([], [], pen=pg.mkPen(color, width=1.2), name="MA{}".format(period))
            self.ma_lines[period] = curve

        # 参考线
        self.cost_line = pg.InfiniteLine(angle=0, movable=False,
                                         pen=pg.mkPen(theme.GOLD, width=1.1,
                                                      style=QtCore.Qt.PenStyle.DashLine))
        self.cost_line.setVisible(False)
        self.p_price.addItem(self.cost_line)
        self._order_lines: list = []

        # 十字光标
        self.vline = pg.InfiniteLine(angle=90, movable=False,
                                     pen=pg.mkPen("#55606f", style=QtCore.Qt.PenStyle.DashLine))
        self.hline = pg.InfiniteLine(angle=0, movable=False,
                                     pen=pg.mkPen("#55606f", style=QtCore.Qt.PenStyle.DashLine))
        self.p_price.addItem(self.vline, ignoreBounds=True)
        self.p_price.addItem(self.hline, ignoreBounds=True)
        self._proxy = pg.SignalProxy(self.p_price.scene().sigMouseMoved,
                                     rateLimit=40, slot=self._on_mouse)

        self.empty_label = pg.TextItem(_tr("加载中…"), color=theme.TEXT_DIM, anchor=(0.5, 0.5))
        self.p_price.addItem(self.empty_label)

        self.p_price.sigXRangeChanged.connect(self._autoscale_y)

    # ------------------------------------------------------------------
    def set_candles(self, candles: list, intraday: bool = True, keep_view: bool = False) -> None:
        self.candles = candles
        self._intraday = intraday
        self.axis.timestamps = [c.ts for c in candles]
        self.axis.intraday = intraday

        self.candle_item.set_data(candles)
        self.vol_item.set_data(candles)
        self.empty_label.setVisible(not candles)
        if not candles:
            (x0, x1), (y0, y1) = self.p_price.viewRange()
            self.empty_label.setPos((x0 + x1) / 2.0, (y0 + y1) / 2.0)
            for c in self.ma_lines.values():
                c.setData([], [])
            return

        closes = [c.close for c in candles]
        xs = list(range(len(candles)))
        for period, curve in self.ma_lines.items():
            if len(closes) >= period:
                ma = _sma(closes, period)
                curve.setData(xs[period - 1:], ma)
            else:
                curve.setData([], [])

        # 把可视范围锁在数据两端 —— 否则一缩放就能拖到 K 线之外, 看起来像"前面断了"
        n = len(candles)
        for plot in (self.p_price, self.p_vol):
            plot.setLimits(xMin=-2, xMax=n + 3, minXRange=5, maxXRange=n + 5)

        if not keep_view:
            show = min(n, 140)
            self.p_price.setXRange(n - show - 0.5, n + 2, padding=0)
        self._autoscale_y()

    def _autoscale_y(self, *_):
        if not self.candles:
            return
        x0, x1 = self.p_price.viewRange()[0]
        i0 = max(0, int(x0))
        i1 = min(len(self.candles), int(x1) + 1)
        window = self.candles[i0:i1]
        if not window:
            return
        lo = min(c.low for c in window)
        hi = max(c.high for c in window)
        pad = (hi - lo) * 0.08 or (hi * 0.01 or 1)
        self.p_price.setYRange(lo - pad, hi + pad, padding=0)
        vmax = max((c.volume for c in window), default=1) or 1
        self.p_vol.setYRange(0, vmax * 1.1, padding=0)

    # ------------------------------------------------------------------
    def set_reference_lines(self, avg_cost: float | None, orders: list) -> None:
        for ln in self._order_lines:
            self.p_price.removeItem(ln)
        self._order_lines.clear()

        if avg_cost and avg_cost > 0:
            self.cost_line.setPos(avg_cost)
            self.cost_line.setVisible(True)
            self.cost_line.setToolTip(_tr("持仓成本 {:.2f}").format(avg_cost))
        else:
            self.cost_line.setVisible(False)

        for o in orders:
            price = o.limit_price or o.stop_price
            if not price:
                continue
            color = theme.up_color() if o.side in ("BUY", "COVER") else theme.down_color()
            ln = pg.InfiniteLine(
                pos=price, angle=0, movable=False,
                pen=pg.mkPen(color, width=1, style=QtCore.Qt.PenStyle.DotLine),
                label="{} {:.2f}".format(o.describe().split(" ")[0], price),
                labelOpts={"position": 0.04, "color": color, "fill": (20, 24, 30, 190)})
            self.p_price.addItem(ln)
            self._order_lines.append(ln)

    # ------------------------------------------------------------------
    def _on_mouse(self, evt):
        pos = evt[0]
        if not self.p_price.sceneBoundingRect().contains(pos) or not self.candles:
            return
        mp = self.p_price.vb.mapSceneToView(pos)
        i = int(round(mp.x()))
        self.vline.setPos(mp.x())
        self.hline.setPos(mp.y())
        if 0 <= i < len(self.candles):
            c = self.candles[i]
            dt = datetime.fromtimestamp(c.ts)
            pct = ((c.close - c.open) / c.open * 100.0) if c.open else 0.0
            col = theme.pnl_color(c.close - c.open)
            self.readout.setText(
                _tr('<span style="color:{dim}">{t}</span>  '
                '开 <b>{o:.2f}</b>  高 <b>{h:.2f}</b>  低 <b>{l:.2f}</b>  '
                '收 <b style="color:{col}">{c:.2f}</b>  '
                '<span style="color:{col}">{p:+.2f}%</span>  '
                '量 <b>{v:,}</b>').format(
                    dim=theme.TEXT_DIM,
                    t=dt.strftime("%Y-%m-%d %H:%M" if self._intraday else "%Y-%m-%d"),
                    o=c.open, h=c.high, l=c.low, c=c.close, p=pct, v=c.volume, col=col))


def _sma(values: list, period: int) -> list:
    out, run = [], 0.0
    for i, v in enumerate(values):
        run += v
        if i >= period:
            run -= values[i - period]
        if i >= period - 1:
            out.append(run / period)
    return out
