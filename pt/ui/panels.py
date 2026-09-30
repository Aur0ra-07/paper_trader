"""复用的小组件与对话框。"""
from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets

from . import theme
from ..i18n import _tr

RIGHT = QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
CENTER = QtCore.Qt.AlignmentFlag.AlignCenter
LEFT = QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter


class Card(QtWidgets.QFrame):
    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.vbox = QtWidgets.QVBoxLayout(self)
        self.vbox.setContentsMargins(12, 10, 12, 12)
        self.vbox.setSpacing(8)
        if title:
            lab = QtWidgets.QLabel(title)
            lab.setObjectName("Title")
            self.vbox.addWidget(lab)


class StatTile(QtWidgets.QWidget):
    """顶部账户摘要的一个小格子。"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(1)
        self.title = QtWidgets.QLabel(title)
        self.title.setObjectName("Dim")
        self.value = QtWidgets.QLabel("—")
        self.value.setObjectName("StatValue")
        self.sub = QtWidgets.QLabel("")
        self.sub.setObjectName("Dim")
        lay.addWidget(self.title)
        lay.addWidget(self.value)
        lay.addWidget(self.sub)

    def set_value(self, text: str, color: str | None = None, sub: str = "") -> None:
        self.value.setText(text)
        self.value.setStyleSheet("color: {};".format(color) if color else "")
        self.sub.setText(sub)


def make_table(headers: list[str], stretch_col: int = 0) -> QtWidgets.QTableWidget:
    t = QtWidgets.QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setAlternatingRowColors(True)
    t.setShowGrid(False)
    t.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
    t.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setWordWrap(False)
    hh = t.horizontalHeader()
    hh.setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
    hh.setSectionResizeMode(stretch_col, QtWidgets.QHeaderView.ResizeMode.Stretch)
    hh.setHighlightSections(False)
    t.verticalHeader().setDefaultSectionSize(26)
    return t


def cell(text: str, color: str | None = None, align=LEFT, bold: bool = False,
         sort_key=None) -> QtWidgets.QTableWidgetItem:
    it = QtWidgets.QTableWidgetItem(text)
    it.setTextAlignment(align)
    if color:
        it.setForeground(QtGui.QColor(color))
    if bold:
        f = it.font()
        f.setBold(True)
        it.setFont(f)
    if sort_key is not None:
        it.setData(QtCore.Qt.ItemDataRole.UserRole + 1, sort_key)
    return it


class NumItem(QtWidgets.QTableWidgetItem):
    """按数值排序的单元格 (显示文本可以带 $ / % / 千分位)。"""

    def __init__(self, text: str, value: float, color: str | None = None,
                 align=RIGHT, bold: bool = False):
        super().__init__(text)
        self._value = value
        self.setTextAlignment(align)
        if color:
            self.setForeground(QtGui.QColor(color))
        if bold:
            f = self.font()
            f.setBold(True)
            self.setFont(f)

    def __lt__(self, other):
        if isinstance(other, NumItem):
            return self._value < other._value
        return super().__lt__(other)


def fill_table(table: QtWidgets.QTableWidget, rows: list[list]) -> None:
    """rows: list of list[QTableWidgetItem]。保持选中行。"""
    sel = table.currentRow()
    table.setRowCount(len(rows))
    for r, items in enumerate(rows):
        for c, it in enumerate(items):
            table.setItem(r, c, it)
    if 0 <= sel < len(rows):
        table.selectRow(sel)


class EquityCurveWidget(QtWidgets.QWidget):
    """账户净值曲线。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        import pyqtgraph as pg
        self.pg = pg
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        axis = pg.DateAxisItem(orientation="bottom")
        self.plot = pg.PlotWidget(axisItems={"bottom": axis})
        self.plot.showGrid(x=True, y=True, alpha=0.12)
        self.plot.getAxis("left").setWidth(70)
        self.plot.setMouseEnabled(x=True, y=False)
        lay.addWidget(self.plot)

        self.curve = self.plot.plot([], [], pen=pg.mkPen(theme.ACCENT, width=1.8))
        self.fill = None
        self.base_line = pg.InfiniteLine(angle=0, movable=False,
                                         pen=pg.mkPen(theme.TEXT_DIM, width=1,
                                                      style=QtCore.Qt.PenStyle.DashLine))
        self.plot.addItem(self.base_line)
        self.empty = pg.TextItem(_tr("暂无净值记录 — 运行一段时间后自动生成"),
                                 color=theme.TEXT_DIM, anchor=(0.5, 0.5))
        self.plot.addItem(self.empty)

    def set_data(self, points: list, baseline: float) -> None:
        pg = self.pg
        if not points:
            self.curve.setData([], [])
            self.empty.setVisible(True)
            return
        self.empty.setVisible(False)
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        color = theme.up_color() if ys[-1] >= baseline else theme.down_color()
        self.curve.setPen(pg.mkPen(color, width=1.8))
        self.curve.setData(xs, ys)
        self.base_line.setPos(baseline)
        lo, hi = min(ys + [baseline]), max(ys + [baseline])
        pad = (hi - lo) * 0.1 or max(hi * 0.01, 1)
        self.plot.setYRange(lo - pad, hi + pad, padding=0)
        self.plot.setXRange(xs[0], xs[-1] + max((xs[-1] - xs[0]) * 0.02, 60), padding=0)
