"""市场浏览页: Yahoo 实时榜单 + 板块分组, 覆盖全美股。"""
from __future__ import annotations

import queue

from PyQt6 import QtCore, QtWidgets

from .. import universe
from ..market import MarketData
from . import theme
from .panels import Card, NumItem, make_table, cell, fill_table, LEFT, RIGHT, CENTER
from ..i18n import _tr

SCREENER = "screener"
SECTOR = "sector"


class ListWorker(QtCore.QThread):
    """后台加载榜单/板块, 只回传最后一次请求。"""

    rows_ready = QtCore.pyqtSignal(str, str, list)
    failed = QtCore.pyqtSignal(str, str)

    def __init__(self, market: MarketData, parent=None):
        super().__init__(parent)
        self.market = market
        self._q: queue.Queue = queue.Queue()
        self._stop = False

    def request(self, kind: str, key: str) -> None:
        self._q.put((kind, key))

    def stop(self) -> None:
        self._stop = True
        self._q.put(None)

    def run(self) -> None:
        while not self._stop:
            item = self._q.get()
            if item is None:
                break
            while not self._q.empty():
                nxt = self._q.get_nowait()
                if nxt is None:
                    return
                item = nxt
            kind, key = item
            try:
                if kind == SCREENER:
                    rows = self.market.screener(key, 100)
                else:
                    syms = universe.SECTOR_MAP.get(key, [])
                    quotes = self.market.quotes(syms)
                    rows = []
                    for s in syms:
                        q = quotes.get(s)
                        if not q:
                            continue
                        rows.append({"symbol": q.symbol, "name": q.name,
                                     "price": q.price or q.tradable_price,   # 和涨跌幅同一口径
                                     "change_pct": q.change_pct,
                                     "volume": q.volume, "market_cap": 0})
                    rows.sort(key=lambda r: -r["change_pct"])
                if not self._stop:
                    self.rows_ready.emit(kind, key, rows)
            except Exception as exc:
                if not self._stop:
                    self.failed.emit(key, str(exc))


class MarketBrowser(QtWidgets.QWidget):
    """左侧分类, 右侧行情列表。双击一行即可交易。"""

    symbol_chosen = QtCore.pyqtSignal(str)          # 双击 -> 加自选并跳到交易页
    symbols_added = QtCore.pyqtSignal(list)         # 批量加入自选

    def __init__(self, market: MarketData, parent=None):
        super().__init__(parent)
        self.market = market
        self.rows: list[dict] = []
        self.current_kind = SCREENER
        self.current_key = universe.SCREENERS[0][1]
        self.current_title = universe.SCREENERS[0][0]

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        # -- 左侧分类 --
        left = Card(_tr("市场"))
        left.setMaximumWidth(210)
        left.setMinimumWidth(180)
        self.cat_list = QtWidgets.QListWidget()
        self.cat_list.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.cat_list.itemClicked.connect(self._on_category)
        self._build_categories()
        left.vbox.addWidget(self.cat_list, 1)
        lay.addWidget(left)

        # -- 右侧列表 --
        right = Card()
        head = QtWidgets.QHBoxLayout()
        self.lab_title = QtWidgets.QLabel(self.current_title)
        self.lab_title.setObjectName("Title")
        head.addWidget(self.lab_title)
        self.lab_count = QtWidgets.QLabel("")
        self.lab_count.setObjectName("Dim")
        head.addWidget(self.lab_count)
        head.addStretch(1)
        b_refresh = QtWidgets.QPushButton(_tr("刷新"))
        b_refresh.clicked.connect(lambda: self.load(self.current_kind, self.current_key,
                                                   self.current_title, force=True))
        head.addWidget(b_refresh)
        b_add = QtWidgets.QPushButton(_tr("整组加入自选股"))
        b_add.clicked.connect(self._add_all)
        head.addWidget(b_add)
        right.vbox.addLayout(head)

        self.table = make_table([_tr("代码"), _tr("名称"), _tr("最新价"), _tr("涨跌幅"), _tr("成交量"), _tr("市值")], stretch_col=1)
        self.table.setSortingEnabled(True)
        self.table.doubleClicked.connect(self._on_double_click)
        right.vbox.addWidget(self.table, 1)

        hint = QtWidgets.QLabel(
            _tr("双击任意一行即可加入自选股并跳转到交易页  ·  点表头可按价格/涨跌幅/成交量排序  "
            "·  榜单数据缓存 90 秒"))
        hint.setObjectName("Dim")
        right.vbox.addWidget(hint)
        lay.addWidget(right, 1)

        self.worker = ListWorker(market)
        self.worker.rows_ready.connect(self._on_rows)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    # ------------------------------------------------------------------
    def _build_categories(self) -> None:
        def header(text: str) -> None:
            it = QtWidgets.QListWidgetItem(text)
            it.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
            it.setForeground(QtCore.Qt.GlobalColor.gray)
            f = it.font()
            f.setBold(True)
            it.setFont(f)
            self.cat_list.addItem(it)

        header(_tr("实时榜单"))
        for title, sid in universe.SCREENERS:
            it = QtWidgets.QListWidgetItem("  " + title)
            it.setData(QtCore.Qt.ItemDataRole.UserRole, (SCREENER, sid, title))
            self.cat_list.addItem(it)

        header(_tr("板块分组"))
        for title, syms in universe.SECTORS:
            it = QtWidgets.QListWidgetItem("  {} ({})".format(title, len(syms)))
            it.setData(QtCore.Qt.ItemDataRole.UserRole, (SECTOR, title, title))
            self.cat_list.addItem(it)

        self.cat_list.setCurrentRow(1)

    def _on_category(self, item: QtWidgets.QListWidgetItem) -> None:
        data = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, key, title = data
        self.load(kind, key, title)

    # ------------------------------------------------------------------
    def load(self, kind: str, key: str, title: str, force: bool = False) -> None:
        self.current_kind, self.current_key, self.current_title = kind, key, title
        self.lab_title.setText(title)
        self.lab_count.setText(_tr("加载中…"))
        if force and kind == SCREENER:
            self.market._screener_cache.pop(key, None)
        self.worker.request(kind, key)

    def load_default(self) -> None:
        if not self.rows:
            self.load(self.current_kind, self.current_key, self.current_title)

    def _on_rows(self, kind: str, key: str, rows: list) -> None:
        if kind != self.current_kind or key != self.current_key:
            return
        self.rows = rows
        self.lab_count.setText(_tr("{} 只").format(len(rows)))

        self.table.setSortingEnabled(False)
        items = []
        for r in rows:
            col = theme.pnl_color(r["change_pct"])
            items.append([
                cell(r["symbol"], theme.TEXT, LEFT, bold=True),
                cell((r["name"] or "")[:38], theme.TEXT_DIM),
                NumItem("{:.2f}".format(r["price"]), r["price"], col),
                NumItem(theme.signed_pct(r["change_pct"]), r["change_pct"], col, bold=True),
                NumItem(_human(r["volume"]), r["volume"], theme.TEXT_DIM),
                NumItem(_human(r["market_cap"]) if r["market_cap"] else "—",
                        r["market_cap"], theme.TEXT_DIM),
            ])
        fill_table(self.table, items)
        self.table.setSortingEnabled(True)
        col, order = self._default_sort()
        self.table.sortItems(col, order)

    def _default_sort(self):
        """每个列表的自然排序: 跌幅榜升序, 成交活跃按量, 其余按涨跌幅降序。"""
        asc = QtCore.Qt.SortOrder.AscendingOrder
        desc = QtCore.Qt.SortOrder.DescendingOrder
        if self.current_kind == SCREENER:
            if self.current_key == "day_losers":
                return 3, asc
            if self.current_key == "most_actives":
                return 4, desc
        return 3, desc

    def _on_failed(self, key: str, msg: str) -> None:
        if key != self.current_key:
            return
        self.lab_count.setText(_tr("加载失败"))
        self.table.setRowCount(0)
        QtWidgets.QMessageBox.warning(
            self, _tr("榜单加载失败"),
            _tr("{}\n\nYahoo 对榜单接口有频率限制, 稍等十几秒再点刷新即可。").format(msg))

    # ------------------------------------------------------------------
    def _selected_symbol(self) -> str:
        r = self.table.currentRow()
        if r < 0:
            return ""
        it = self.table.item(r, 0)
        return it.text() if it else ""

    def _on_double_click(self) -> None:
        sym = self._selected_symbol()
        if sym:
            self.symbol_chosen.emit(sym)

    def _add_all(self) -> None:
        syms = [r["symbol"] for r in self.rows]
        if not syms:
            return
        if len(syms) > 40 and QtWidgets.QMessageBox.question(
                self, _tr("确认"),
                _tr("把「{}」的 {} 只全部加入自选股?\n自选股太多会拖慢行情刷新, 建议控制在 60 只以内。").format(
                    self.current_title, len(syms))
        ) != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.symbols_added.emit(syms)

    def stop(self) -> None:
        self.worker.stop()
        self.worker.wait(2000)


def _human(v: float) -> str:
    v = float(v or 0)
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(v) >= div:
            return "{:.2f}{}".format(v / div, unit)
    return "{:,.0f}".format(v)
