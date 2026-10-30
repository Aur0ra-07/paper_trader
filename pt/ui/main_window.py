"""主窗口。"""
from __future__ import annotations

import csv
import math
import os
import sys
import time
from datetime import datetime

from PyQt6 import QtCore, QtGui, QtWidgets

from .. import storage
from ..config import DATA_DIR, Settings
from ..engine import TradingEngine, ET
from ..market import MarketData, Quote
from ..options.chain import YahooOptionSource
from ..options.engine import OptionsEngine
from ..models import (
    Account, Order, BUY, SELL, SHORT, COVER, SIDE_CN, TYPE_CN, STATUS_CN,
    MARKET, LIMIT, STOP, STOP_LIMIT, DAY, GTC, PENDING, FILLED,
    BUY_SIDES, CLOSING_SIDES,
)
from . import theme
from .chart import ChartWidget
from .market_tab import MarketBrowser
from .options_tab import OptionsTab
from .strategy_tab import StrategyTab
from .account_dialog import AccountManagerDialog
from .panels import (Card, StatTile, EquityCurveWidget,
                     make_table, cell, fill_table, LEFT, RIGHT, CENTER)
from .workers import QuoteWorker, CandleWorker, SearchWorker
from .. import i18n
from ..i18n import _tr

MARKET_STATE_CN = {"REGULAR": _tr("● 交易中"), "PRE": _tr("● 盘前"), "POST": _tr("● 盘后"), "CLOSED": _tr("● 休市")}
MARKET_STATE_COLOR = {"REGULAR": theme.GREEN, "PRE": theme.GOLD,
                      "POST": theme.GOLD, "CLOSED": theme.TEXT_DIM}


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        theme.set_color_scheme(self.settings.color_up_is_green)

        self.market = MarketData(include_prepost=self.settings.include_prepost)
        self.market.set_source_mode(getattr(self.settings, "data_source", "auto"))
        self.account: Account = storage.bootstrap(self.settings.default_initial_cash)
        self.engine = TradingEngine(self.account, self.settings)
        self.option_source = YahooOptionSource()
        self.options_engine = OptionsEngine(self.account, self.settings)

        self.quotes: dict[str, Quote] = {}
        self.prices: dict[str, float] = {}
        self.option_prices: dict[str, float] = {}   # OCC 代码 -> 每股期权价 (+ 底层现价)
        self.current_symbol = (self.account.watchlist or ["AAPL"])[0]
        self.current_interval = _tr("日线")
        self._preferred_range: dict = {}   # 周期代码 -> 用户选过的 range
        self._search_mode = False
        self._search_rows: list = []
        self._dirty = False

        self.setWindowTitle(_tr("Paper Trader — 美股模拟交易终端"))
        self.resize(1560, 950)
        self.setMinimumSize(1180, 760)

        self._build_ui()
        self._start_workers()

        self.autosave = QtCore.QTimer(self)
        self.autosave.timeout.connect(self._save)
        self.autosave.start(20000)

        self.clock = QtCore.QTimer(self)
        self.clock.timeout.connect(self._tick_clock)
        self.clock.start(1000)

        self._refresh_account_combo()
        self.refresh_all()
        self.select_symbol(self.current_symbol)

    # ==================================================================
    # 界面搭建
    # ==================================================================
    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        root.addWidget(self._build_topbar())
        root.addWidget(self._build_header())

        self.tabs = QtWidgets.QTabWidget()
        self.tab_index = {}
        for key, title, builder in (
                ("trade", _tr("交易"), self._build_trade_tab),
                ("market", _tr("市场"), self._build_market_tab),
                ("strategy", _tr("策略"), self._build_strategy_tab),
                ("options", _tr("期权"), self._build_options_tab),
                ("positions", _tr("持仓"), self._build_positions_tab),
                ("orders", _tr("订单"), self._build_orders_tab),
                ("trades", _tr("成交记录"), self._build_trades_tab),
                ("perf", _tr("绩效"), self._build_perf_tab),
                ("leaderboard", _tr("排行榜"), self._build_leaderboard_tab),
                ("settings", _tr("设置"), self._build_settings_tab)):
            self.tab_index[key] = self.tabs.addTab(builder(), title)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, 1)

        self.status = self.statusBar()
        self.status.showMessage(_tr("就绪"))
        # 当前行情来自谁。切到备用源时必须让用户看见 —— 两家的股息复权算法不同,
        # 长周期回测结果会不一样, 不说清楚会让人以为是软件算错了。
        self.lab_source = QtWidgets.QLabel("")
        self.lab_source.setObjectName("Dim")
        self.status.addPermanentWidget(self.lab_source)
        self._last_source = ""
        self._src_timer = QtCore.QTimer(self)
        self._src_timer.timeout.connect(self._refresh_source_badge)
        self._src_timer.start(3000)
        self._refresh_source_badge()

        # 账户文件读坏 / 从备份救回来 —— 必须明说。默默开个新账户是最坏的做法:
        # 用户以为数据还在, 其实已经没了。
        QtCore.QTimer.singleShot(400, self._warn_data_problems)

    def _warn_data_problems(self) -> None:
        msgs = []
        if storage.RECOVERED_FROM:
            msgs.append(_tr("没找到账户文件，已经自动从备份恢复：\n    %s\n\n"
                        "如果这不是你想要的那份，去「账户管理… → 从备份恢复」\n"
                        "里挑别的时间点。") % storage.RECOVERED_FROM)
        for aid, kept, err in storage.LOAD_FAILURES:
            msgs.append(_tr("账户文件读不出来（%s）：\n    %s\n"
                        "坏掉的原文件已改名保留在：\n    %s") % (err, aid, kept))
        if not msgs:
            return
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        box.setWindowTitle(_tr("账户数据有问题"))
        box.setText("\n\n".join(msgs))
        box.setInformativeText(_tr("数据目录：%s") % DATA_DIR)
        box.exec()

    # ------------------------------------------------------------------
    def _build_topbar(self) -> QtWidgets.QWidget:
        bar = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(8)

        lay.addWidget(QtWidgets.QLabel(_tr("账户")))
        self.account_combo = QtWidgets.QComboBox()
        self.account_combo.setMinimumWidth(230)
        self.account_combo.currentIndexChanged.connect(self._on_account_changed)
        lay.addWidget(self.account_combo)

        b_mgr = QtWidgets.QPushButton(_tr("账户管理…"))
        b_mgr.setToolTip(_tr("新建 / 重命名 / 复制 / 导出 / 重置 / 删除 / 从备份恢复"))
        b_mgr.clicked.connect(self._open_account_manager)
        lay.addWidget(b_mgr)

        lay.addStretch(1)

        self.lab_state = QtWidgets.QLabel(_tr("● 连接中"))
        self.lab_state.setStyleSheet("color: {}; font-weight:600;".format(theme.TEXT_DIM))
        lay.addWidget(self.lab_state)

        self.lab_clock = QtWidgets.QLabel("")
        self.lab_clock.setObjectName("Dim")
        lay.addWidget(self.lab_clock)

        b_refresh = QtWidgets.QPushButton(_tr("立即刷新"))
        b_refresh.clicked.connect(self._force_refresh)
        lay.addWidget(b_refresh)
        return bar

    def _build_header(self) -> QtWidgets.QWidget:
        card = QtWidgets.QFrame()
        card.setObjectName("Card")
        lay = QtWidgets.QHBoxLayout(card)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(0)

        self.tiles = {}
        for key, title in (("equity", _tr("总资产")), ("cash", _tr("可用现金")), ("bp", _tr("购买力")),
                           ("mv", _tr("持仓市值")), ("unreal", _tr("浮动盈亏")),
                           ("realized", _tr("已实现盈亏")), ("ret", _tr("总收益率"))):
            t = StatTile(title)
            self.tiles[key] = t
            lay.addWidget(t, 1)
            if key != "ret":
                sep = QtWidgets.QFrame()
                sep.setFrameShape(QtWidgets.QFrame.Shape.VLine)
                sep.setStyleSheet("color: {};".format(theme.BORDER))
                lay.addWidget(sep)
        return card

    # ------------------------------------------------------------------
    def _build_trade_tab(self) -> QtWidgets.QWidget:
        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(self._build_watch_panel())
        split.addWidget(self._build_chart_panel())
        split.addWidget(self._build_ticket_panel())
        split.setSizes([280, 900, 350])
        split.setStretchFactor(1, 1)
        return split

    def _build_watch_panel(self) -> QtWidgets.QWidget:
        card = Card(_tr("自选股"))
        self.search_box = QtWidgets.QLineEdit()
        # 提示文字写死成「代码」, 不跟着行情源变。auto 模式下 active_source 要等
        # 第一次请求真的失败了才翻成国内源 —— 刚启动还没发过请求时它还是 Yahoo,
        # 提示会写着"公司名", 等用户真去搜公司名才触发兜底, 那时字已经打完了。
        # 代码在三家源上都能搜, 按代码提示永远不会把人带沟里。
        self.search_box.setPlaceholderText(_tr("搜索代码, 回车确认 (如 AAPL)"))
        self.search_box.returnPressed.connect(self._do_search)
        card.vbox.addWidget(self.search_box)

        self.watch_stack = QtWidgets.QStackedWidget()
        self.watch_table = make_table([_tr("代码"), _tr("最新价"), _tr("涨跌幅")], stretch_col=0)
        self.watch_table.itemSelectionChanged.connect(self._on_watch_selected)
        self.watch_table.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.watch_table.customContextMenuRequested.connect(self._watch_menu)
        self.watch_stack.addWidget(self.watch_table)

        sr = QtWidgets.QWidget()
        srl = QtWidgets.QVBoxLayout(sr)
        srl.setContentsMargins(0, 0, 0, 0)
        srl.setSpacing(6)
        back = QtWidgets.QPushButton(_tr("← 返回自选股"))
        back.setObjectName("Link")
        back.clicked.connect(self._exit_search)
        srl.addWidget(back)
        self.search_table = make_table([_tr("代码"), _tr("名称"), _tr("交易所")], stretch_col=1)
        self.search_table.doubleClicked.connect(self._add_from_search)
        srl.addWidget(self.search_table, 1)
        hint = QtWidgets.QLabel(_tr("双击添加到自选股"))
        hint.setObjectName("Dim")
        srl.addWidget(hint)
        self.watch_stack.addWidget(sr)

        card.vbox.addWidget(self.watch_stack, 1)
        return card

    def _build_chart_panel(self) -> QtWidgets.QWidget:
        card = Card()
        head = QtWidgets.QHBoxLayout()
        head.setSpacing(12)

        left = QtWidgets.QVBoxLayout()
        left.setSpacing(0)
        self.lab_symbol = QtWidgets.QLabel("—")
        self.lab_symbol.setStyleSheet("font-size:19px; font-weight:700;")
        self.lab_name = QtWidgets.QLabel("")
        self.lab_name.setObjectName("Dim")
        left.addWidget(self.lab_symbol)
        left.addWidget(self.lab_name)
        head.addLayout(left)

        self.lab_price = QtWidgets.QLabel("—")
        self.lab_price.setObjectName("BigPrice")
        head.addWidget(self.lab_price)

        mid = QtWidgets.QVBoxLayout()
        mid.setSpacing(0)
        self.lab_change = QtWidgets.QLabel("")
        self.lab_change.setObjectName("SubPrice")
        self.lab_ext = QtWidgets.QLabel("")
        self.lab_ext.setObjectName("Dim")
        mid.addWidget(self.lab_change)
        mid.addWidget(self.lab_ext)
        head.addLayout(mid)

        head.addStretch(1)
        self.lab_ohlc = QtWidgets.QLabel("")
        self.lab_ohlc.setObjectName("Dim")
        self.lab_ohlc.setAlignment(RIGHT)
        head.addWidget(self.lab_ohlc)
        card.vbox.addLayout(head)

        ivrow = QtWidgets.QHBoxLayout()
        ivrow.setSpacing(4)
        self.interval_group = QtWidgets.QButtonGroup(self)
        self.interval_group.setExclusive(True)
        for label in MarketData.INTERVALS:
            b = QtWidgets.QPushButton(label)
            b.setCheckable(True)
            b.setMinimumWidth(52)        # 不能写死: 英文 "Weekly" 比「周线」宽
            b.setChecked(label == self.current_interval)
            b.clicked.connect(lambda _, lb=label: self._set_interval(lb))
            self.interval_group.addButton(b)
            ivrow.addWidget(b)

        ivrow.addSpacing(10)
        ivrow.addWidget(QtWidgets.QLabel(_tr("范围")))
        self.range_combo = QtWidgets.QComboBox()
        self.range_combo.setFixedWidth(96)
        self.range_combo.setToolTip(
            _tr("要加载多长的历史。各周期能拉多少受接口限制:\n"
            "分钟线最多 1 个月, 60 分钟最多 2 年, 日线/周线可以到上市当天。"))
        self.range_combo.currentIndexChanged.connect(self._on_range_pick)
        ivrow.addWidget(self.range_combo)
        self.bars_label = QtWidgets.QLabel("")
        self.bars_label.setObjectName("Dim")
        ivrow.addWidget(self.bars_label)
        ivrow.addStretch(1)
        legend = QtWidgets.QLabel(
            _tr('<span style="color:#f0b429">MA5</span>  '
            '<span style="color:#3b82f6">MA20</span>  '
            '<span style="color:#a855f7">MA60</span>  '
            '<span style="color:{}">- - 持仓成本</span>').format(theme.GOLD))
        ivrow.addWidget(legend)
        card.vbox.addLayout(ivrow)

        self.chart = ChartWidget()
        card.vbox.addWidget(self.chart, 1)
        return card

    def _build_ticket_panel(self) -> QtWidgets.QWidget:
        wrap = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(wrap)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        card = Card(_tr("下单"))
        self.lab_ticket_symbol = QtWidgets.QLabel("—")
        self.lab_ticket_symbol.setStyleSheet("font-size:16px; font-weight:700;")
        card.vbox.addWidget(self.lab_ticket_symbol)

        self.lab_pos_hint = QtWidgets.QLabel(_tr("当前无持仓"))
        self.lab_pos_hint.setObjectName("Dim")
        self.lab_pos_hint.setWordWrap(True)
        card.vbox.addWidget(self.lab_pos_hint)

        srow = QtWidgets.QHBoxLayout()
        srow.setSpacing(4)
        self.side_group = QtWidgets.QButtonGroup(self)
        self.side_buttons = {}
        for side in (BUY, SELL, SHORT, COVER):
            b = QtWidgets.QPushButton(SIDE_CN[side])
            b.setCheckable(True)
            b.setChecked(side == BUY)
            b.clicked.connect(lambda _, s=side: self._set_side(s))
            self.side_group.addButton(b)
            self.side_buttons[side] = b
            srow.addWidget(b)
        card.vbox.addLayout(srow)
        self.current_side = BUY

        form = QtWidgets.QFormLayout()
        form.setSpacing(7)
        form.setLabelAlignment(RIGHT)

        self.type_combo = QtWidgets.QComboBox()
        for t in (MARKET, LIMIT, STOP, STOP_LIMIT):
            self.type_combo.addItem(TYPE_CN[t], t)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        form.addRow(_tr("订单类型"), self.type_combo)

        self.qty_spin = QtWidgets.QSpinBox()
        self.qty_spin.setRange(1, 10_000_000)
        self.qty_spin.setValue(10)
        self.qty_spin.setGroupSeparatorShown(True)
        self.qty_spin.valueChanged.connect(self._update_estimate)
        form.addRow(_tr("股数"), self.qty_spin)

        self.limit_spin = QtWidgets.QDoubleSpinBox()
        self.limit_spin.setRange(0.0001, 1_000_000)
        self.limit_spin.setDecimals(2)
        self.limit_spin.setPrefix("$ ")
        self.limit_spin.valueChanged.connect(self._update_estimate)
        self.row_limit = self.limit_spin
        form.addRow(_tr("限价"), self.limit_spin)

        self.stop_spin = QtWidgets.QDoubleSpinBox()
        self.stop_spin.setRange(0.0001, 1_000_000)
        self.stop_spin.setDecimals(2)
        self.stop_spin.setPrefix("$ ")
        self.stop_spin.valueChanged.connect(self._update_estimate)
        form.addRow(_tr("触发价"), self.stop_spin)

        self.tif_combo = QtWidgets.QComboBox()
        self.tif_combo.addItem(_tr("当日有效 (DAY)"), DAY)
        self.tif_combo.addItem(_tr("撤销前有效 (GTC)"), GTC)
        form.addRow(_tr("有效期"), self.tif_combo)
        card.vbox.addLayout(form)

        qrow = QtWidgets.QHBoxLayout()
        qrow.setSpacing(4)
        for pct in (25, 50, 75, 100):
            b = QtWidgets.QPushButton("{}%".format(pct))
            b.clicked.connect(lambda _, p=pct: self._set_qty_pct(p))
            qrow.addWidget(b)
        card.vbox.addLayout(qrow)

        self.lab_est = QtWidgets.QLabel("")
        self.lab_est.setObjectName("Dim")
        self.lab_est.setWordWrap(True)
        card.vbox.addWidget(self.lab_est)

        self.btn_submit = QtWidgets.QPushButton(_tr("买入"))
        self.btn_submit.setObjectName("Primary")
        self.btn_submit.setMinimumHeight(38)
        self.btn_submit.clicked.connect(self._submit_order)
        card.vbox.addWidget(self.btn_submit)
        outer.addWidget(card)

        ocard = Card(_tr("当前挂单"))
        self.pending_table = make_table([_tr("代码"), _tr("订单"), _tr("状态")], stretch_col=1)
        self.pending_table.setMinimumHeight(120)
        self.pending_table.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.pending_table.customContextMenuRequested.connect(self._pending_menu)
        ocard.vbox.addWidget(self.pending_table, 1)
        brow = QtWidgets.QHBoxLayout()
        b1 = QtWidgets.QPushButton(_tr("撤选中"))
        b1.clicked.connect(self._cancel_selected_pending)
        b2 = QtWidgets.QPushButton(_tr("全部撤单"))
        b2.clicked.connect(self._cancel_all)
        brow.addWidget(b1)
        brow.addWidget(b2)
        ocard.vbox.addLayout(brow)
        outer.addWidget(ocard, 1)
        self._on_type_changed()
        return wrap

    def _build_strategy_tab(self) -> QtWidgets.QWidget:
        self.strategy_tab = StrategyTab(
            self.market, self.settings,
            lambda: (self.account, self.engine, self.quotes, self.prices))
        self.strategy_tab.trades_executed.connect(self._after_trade)
        self.strategy_tab.status.connect(lambda m: self.status.showMessage(m, 8000))
        return self.strategy_tab

    def _build_options_tab(self) -> QtWidgets.QWidget:
        self.options_tab = OptionsTab(
            self.option_source, self.settings,
            lambda: (self.account, self.options_engine, self.quotes, self.prices))
        self.options_tab.trades_executed.connect(self._after_trade)
        self.options_tab.status.connect(lambda m: self.status.showMessage(m, 8000))
        self.options_tab.prices_updated.connect(self._on_option_prices)
        return self.options_tab

    def _on_option_prices(self, prices: dict) -> None:
        self.option_prices.update(prices)
        self.prices.update(prices)
        self._refresh_header()

    def _build_market_tab(self) -> QtWidgets.QWidget:
        self.market_browser = MarketBrowser(self.market)
        self.market_browser.symbol_chosen.connect(self._on_market_symbol)
        self.market_browser.symbols_added.connect(self._on_market_bulk_add)
        return self.market_browser

    # ------------------------------------------------------------------
    def _build_positions_tab(self) -> QtWidgets.QWidget:
        card = Card()
        self.pos_table = make_table(
            [_tr("代码"), _tr("名称"), _tr("方向"), _tr("股数"), _tr("成本价"), _tr("现价"), _tr("市值"),
             _tr("浮动盈亏"), _tr("盈亏%"), _tr("已实现"), _tr("占比")], stretch_col=1)
        self.pos_table.doubleClicked.connect(self._pos_double_clicked)
        card.vbox.addWidget(self.pos_table, 1)

        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton(_tr("市价平掉选中持仓"))
        b.setObjectName("Danger")
        b.clicked.connect(self._close_selected_position)
        row.addWidget(b)
        b2 = QtWidgets.QPushButton(_tr("一键清仓 (全部市价平掉)"))
        b2.clicked.connect(self._close_all_positions)
        row.addWidget(b2)
        row.addStretch(1)
        self.lab_pos_summary = QtWidgets.QLabel("")
        self.lab_pos_summary.setObjectName("Dim")
        row.addWidget(self.lab_pos_summary)
        card.vbox.addLayout(row)
        return card

    def _build_orders_tab(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        c1 = Card(_tr("未成交挂单"))
        self.open_orders_table = make_table(
            [_tr("时间"), _tr("代码"), _tr("方向"), _tr("类型"), _tr("股数"), _tr("限价"), _tr("触发价"), _tr("有效期"), _tr("状态")], stretch_col=1)
        c1.vbox.addWidget(self.open_orders_table, 1)
        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton(_tr("撤销选中"))
        b.clicked.connect(self._cancel_selected_open_order)
        row.addWidget(b)
        b2 = QtWidgets.QPushButton(_tr("全部撤单"))
        b2.clicked.connect(self._cancel_all)
        row.addWidget(b2)
        row.addStretch(1)
        c1.vbox.addLayout(row)
        lay.addWidget(c1, 1)

        c2 = Card(_tr("历史订单"))
        self.hist_orders_table = make_table(
            [_tr("时间"), _tr("代码"), _tr("方向"), _tr("类型"), _tr("股数"), _tr("成交价"), _tr("费用"), _tr("状态"), _tr("备注")], stretch_col=8)
        c2.vbox.addWidget(self.hist_orders_table, 1)
        lay.addWidget(c2, 2)
        return w

    def _build_trades_tab(self) -> QtWidgets.QWidget:
        card = Card(_tr("成交明细"))
        self.trades_table = make_table(
            [_tr("时间"), _tr("代码"), _tr("方向"), _tr("股数"), _tr("成交价"), _tr("金额"), _tr("佣金"), _tr("规费"), _tr("已实现盈亏")],
            stretch_col=1)
        card.vbox.addWidget(self.trades_table, 1)
        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton(_tr("导出 CSV"))
        b.clicked.connect(self._export_trades)
        row.addWidget(b)
        row.addStretch(1)
        self.lab_trade_summary = QtWidgets.QLabel("")
        self.lab_trade_summary.setObjectName("Dim")
        row.addWidget(self.lab_trade_summary)
        card.vbox.addLayout(row)
        return card

    def _build_perf_tab(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        c1 = Card(_tr("账户净值曲线"))
        self.equity_chart = EquityCurveWidget()
        c1.vbox.addWidget(self.equity_chart, 1)
        lay.addWidget(c1, 3)

        c2 = Card(_tr("绩效指标"))
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        self.perf_labels = {}
        items = [("closed_trades", _tr("平仓次数")), ("win_rate", _tr("胜率")),
                 ("avg_win", _tr("平均盈利")), ("avg_loss", _tr("平均亏损")),
                 ("profit_factor", _tr("盈亏比")), ("max_drawdown", _tr("最大回撤")),
                 ("realized", _tr("累计已实现")), ("unrealized", _tr("当前浮动")),
                 ("fees", _tr("累计费用")), ("day_trades", _tr("近5日日内交易"))]
        for i, (key, title) in enumerate(items):
            r, c = divmod(i, 5)
            box = QtWidgets.QVBoxLayout()
            t = QtWidgets.QLabel(title)
            t.setObjectName("Dim")
            v = QtWidgets.QLabel("—")
            v.setObjectName("StatValue")
            box.addWidget(t)
            box.addWidget(v)
            holder = QtWidgets.QWidget()
            holder.setLayout(box)
            grid.addWidget(holder, r, c)
            self.perf_labels[key] = v
        c2.vbox.addLayout(grid)
        lay.addWidget(c2, 1)
        return w

    def _build_leaderboard_tab(self) -> QtWidgets.QWidget:
        card = Card(_tr("账户排行榜 (按总收益率)"))
        self.lb_table = make_table(
            ["#", _tr("账户"), _tr("类型"), _tr("初始资金"), _tr("总资产"), _tr("总盈亏"), _tr("收益率"), _tr("平仓次数"), _tr("胜率")],
            stretch_col=1)
        card.vbox.addWidget(self.lb_table, 1)
        hint = QtWidgets.QLabel(_tr("提示: 新建多个账户可以并行测试不同策略, 这里横向对比。"))
        hint.setObjectName("Dim")
        card.vbox.addWidget(hint)
        return card

    def _build_settings_tab(self) -> QtWidgets.QWidget:
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        inner = QtWidgets.QWidget()
        scroll.setWidget(inner)
        lay = QtWidgets.QVBoxLayout(inner)
        lay.setSpacing(10)
        s = self.settings

        # 语言放在最上面, 而且这一组**故意不翻译**: 标签写死双语, 选项各用各自的
        # 语言写。否则切到英文后看不懂英文的人找不到怎么切回来, 反之亦然。
        gl = QtWidgets.QGroupBox("Language / 语言")
        fl = QtWidgets.QFormLayout(gl)
        self.set_lang = QtWidgets.QComboBox()
        for code, name in i18n.LANGS:
            self.set_lang.addItem(name, code)
        self.set_lang.setCurrentIndex(max(self.set_lang.findData(i18n.LANG), 0))
        fl.addRow("Language / 语言", self.set_lang)
        lang_tip = QtWidgets.QLabel("Takes effect after restart  ·  重启后生效")
        lang_tip.setObjectName("Dim")
        fl.addRow("", lang_tip)
        lay.addWidget(gl)

        g1 = QtWidgets.QGroupBox(_tr("行情"))
        f1 = QtWidgets.QFormLayout(g1)
        self.set_refresh = QtWidgets.QSpinBox()
        self.set_refresh.setRange(2, 120)
        self.set_refresh.setValue(s.refresh_seconds)
        self.set_refresh.setSuffix(_tr(" 秒"))
        f1.addRow(_tr("行情刷新间隔"), self.set_refresh)
        self.set_prepost = QtWidgets.QCheckBox(_tr("包含盘前/盘后价格"))
        self.set_prepost.setChecked(s.include_prepost)
        f1.addRow("", self.set_prepost)
        self.set_closedfill = QtWidgets.QCheckBox(_tr("休市时市价单按最新价立即成交 (关闭则挂起到开盘)"))
        self.set_closedfill.setChecked(s.allow_closed_market_fill)
        f1.addRow("", self.set_closedfill)
        self.set_green = QtWidgets.QCheckBox(_tr("绿涨红跌 (美股习惯); 取消勾选为红涨绿跌 (A股习惯)"))
        self.set_green.setChecked(s.color_up_is_green)
        f1.addRow("", self.set_green)
        lay.addWidget(g1)

        # 行情源。挂着回国加速器时 Yahoo 往往仍然直连可用(分流模式), 光靠"自动"
        # 根本走不到备用源, 所以必须能手动强制, 否则没法在本地验证备用源好不好使。
        gs = QtWidgets.QGroupBox(_tr("行情源"))
        fs = QtWidgets.QFormLayout(gs)
        self.set_source = QtWidgets.QComboBox()
        self.set_source.addItem(_tr("自动 (优先 Yahoo, 连不上时切国内源)"), "auto")
        self.set_source.addItem(_tr("只用 Yahoo (连不上就报错, 不降级)"), "yahoo")
        self.set_source.addItem(_tr("只用 国内源 腾讯/东财 (国内可用; 用来测试备用源)"), "eastmoney")
        self.set_source.setCurrentIndex(
            {"auto": 0, "yahoo": 1, "eastmoney": 2}.get(
                getattr(s, "data_source", "auto"), 0))
        fs.addRow(_tr("使用哪个"), self.set_source)
        tip = QtWidgets.QLabel(
            _tr("当前实际在用的源显示在窗口右下角状态栏。国内源以<b>腾讯</b>为主，"
            "腾讯覆盖不到的（超过 8 年的日线、分钟线）才用东方财富。<br>"
            "<b>实时报价与 Yahoo 完全一致</b>（实测偏差 0.000%）；"
            "但腾讯的历史价<b>不含股息再投</b>，东财的股息算法也和 Yahoo 不同，"
            "所以<b>跨多年的回测数字会有差异</b>，正常情况下让它保持「自动」。"))
        tip.setObjectName("Dim")
        tip.setWordWrap(True)
        fs.addRow("", tip)
        lay.addWidget(gs)

        g2 = QtWidgets.QGroupBox(_tr("成交与费用"))
        f2 = QtWidgets.QFormLayout(g2)
        self.set_slip = QtWidgets.QDoubleSpinBox()
        self.set_slip.setRange(0, 200)
        self.set_slip.setDecimals(1)
        self.set_slip.setValue(s.slippage_bps)
        self.set_slip.setSuffix(" bp")
        f2.addRow(_tr("市价单滑点"), self.set_slip)

        self.set_commode = QtWidgets.QComboBox()
        self.set_commode.addItem(_tr("按股数 (IBKR 风格)"), "per_share")
        self.set_commode.addItem(_tr("每笔固定"), "flat")
        self.set_commode.addItem(_tr("零佣金 (Robinhood 风格)"), "zero")
        idx = self.set_commode.findData(s.commission_mode)
        self.set_commode.setCurrentIndex(max(idx, 0))
        f2.addRow(_tr("佣金模式"), self.set_commode)

        self.set_cps = QtWidgets.QDoubleSpinBox()
        self.set_cps.setRange(0, 1)
        self.set_cps.setDecimals(4)
        self.set_cps.setValue(s.commission_per_share)
        self.set_cps.setPrefix("$ ")
        f2.addRow(_tr("每股佣金"), self.set_cps)

        self.set_cmin = QtWidgets.QDoubleSpinBox()
        self.set_cmin.setRange(0, 100)
        self.set_cmin.setValue(s.commission_min)
        self.set_cmin.setPrefix("$ ")
        f2.addRow(_tr("每笔最低佣金"), self.set_cmin)

        self.set_cflat = QtWidgets.QDoubleSpinBox()
        self.set_cflat.setRange(0, 100)
        self.set_cflat.setValue(s.commission_flat)
        self.set_cflat.setPrefix("$ ")
        f2.addRow(_tr("固定佣金 (每笔)"), self.set_cflat)
        lay.addWidget(g2)

        g3 = QtWidgets.QGroupBox(_tr("风控"))
        f3 = QtWidgets.QFormLayout(g3)
        self.set_acctype = QtWidgets.QComboBox()
        self.set_acctype.addItem(_tr("保证金账户 (2倍购买力, 可做空)"), "MARGIN")
        self.set_acctype.addItem(_tr("现金账户 (无杠杆, 不可做空)"), "CASH")
        f3.addRow(_tr("当前账户类型"), self.set_acctype)
        self.set_pdt = QtWidgets.QCheckBox(_tr("启用 PDT 日内交易者规则"))
        self.set_pdt.setChecked(s.enforce_pdt)
        f3.addRow("", self.set_pdt)
        lay.addWidget(g3)

        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton(_tr("保存设置"))
        b.setObjectName("Primary")
        b.setMaximumWidth(160)
        b.clicked.connect(self._apply_settings)
        row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        note = QtWidgets.QLabel(
            _tr("数据来源: Yahoo Finance 公开行情接口 (无需 API key)。免费源对部分交易所可能有延迟, "
            "仅供模拟练习, 不构成任何投资建议。\n本软件不接入任何真实券商, 不涉及真实资金。"))
        note.setObjectName("Dim")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch(1)
        return scroll

    # ==================================================================
    # 线程
    # ==================================================================
    def _start_workers(self) -> None:
        self.qworker = QuoteWorker(self.market, self.settings.refresh_seconds)
        self.qworker.quotes_ready.connect(self._on_quotes)
        self.qworker.failed.connect(lambda m: self.status.showMessage(m, 4000))
        self.qworker.set_symbols(self._tracked_symbols())
        self.qworker.start()

        self.cworker = CandleWorker(self.market)
        self.cworker.candles_ready.connect(self._on_candles)
        self.cworker.failed.connect(lambda m: self.status.showMessage(m, 4000))
        self.cworker.start()

        self.sworker = SearchWorker(self.market)
        self.sworker.results_ready.connect(self._on_search_results)
        self.sworker.start()

    def _tracked_symbols(self) -> list[str]:
        syms = list(self.account.watchlist)
        syms += [p.symbol for p in self.account.open_positions()]
        syms += [o.symbol for o in self.account.open_orders()]
        syms.append(self.current_symbol)
        for acc in storage.list_accounts():          # 排行榜需要其它账户的持仓报价
            syms += [p.symbol for p in acc.open_positions()]
        return [s for s in dict.fromkeys(syms) if s]

    def _force_refresh(self) -> None:
        self.qworker.set_symbols(self._tracked_symbols())
        self.qworker.poke()
        self._request_candles()
        self.status.showMessage(_tr("正在刷新…"), 1500)

    # ==================================================================
    # 行情回调
    # ==================================================================
    def _on_quotes(self, data: dict) -> None:
        self.quotes.update(data)
        self.prices = {k: v.tradable_price for k, v in self.quotes.items() if v.tradable_price}
        self.prices.update(self.option_prices)     # 期权价来自期权链, 别被股票行情覆盖掉

        filled = self.engine.on_quotes(self.quotes)
        if filled:
            for o in filled:
                self.status.showMessage(
                    _tr("✔ 成交  {} {} {} 股 @ ${:.2f}").format(
                        o.symbol, SIDE_CN.get(o.side, o.side), o.qty, o.fill_price), 8000)
            self._dirty = True
            self._save()
        self.engine.record_equity(self.prices)
        self.refresh_all()

        q = self.quotes.get(self.current_symbol)
        state = q.market_state if q else "CLOSED"
        self.lab_state.setText(MARKET_STATE_CN.get(state, _tr("● 未知")))
        self.lab_state.setStyleSheet("color: {}; font-weight:600;".format(
            MARKET_STATE_COLOR.get(state, theme.TEXT_DIM)))

    def _on_candles(self, symbol: str, interval: str, candles: list) -> None:
        want = MarketData.INTERVALS[self.current_interval][0]
        if symbol != self.current_symbol or interval != want:
            return
        self.chart.set_candles(candles, intraday=interval.endswith(("m", "h")))
        self._update_chart_refs()
        if candles:
            first = datetime.fromtimestamp(candles[0].ts).strftime("%Y-%m-%d")
            self.bars_label.setText(_tr("{:,} 根 · 自 {}").format(len(candles), first))
        else:
            self.bars_label.setText(_tr("无数据"))

    def _on_search_results(self, query: str, rows: list) -> None:
        self._search_rows = rows
        fill_table(self.search_table, [
            [cell(r["symbol"], theme.TEXT, LEFT, bold=True),
             cell(r["name"]),
             cell(r["exchange"], theme.TEXT_DIM)] for r in rows])
        if not rows:
            self.status.showMessage(_tr("没有找到匹配的标的"), 3000)

    # ==================================================================
    # 刷新
    # ==================================================================
    def refresh_all(self) -> None:
        self._refresh_header()
        self._refresh_watchlist()
        self._refresh_quote_header()
        self._refresh_pending()
        self._refresh_ticket()
        idx = self.tabs.currentIndex()
        T = self.tab_index
        if idx == T["positions"]:
            self._refresh_positions()
        elif idx == T["orders"]:
            self._refresh_orders()
        elif idx == T["trades"]:
            self._refresh_trades()
        elif idx == T["perf"]:
            self._refresh_perf()
        elif idx == T["leaderboard"]:
            self._refresh_leaderboard()

    def _on_tab_changed(self, idx: int) -> None:
        if idx == self.tab_index.get("market"):
            self.market_browser.load_default()
        elif idx == self.tab_index.get("strategy"):
            self.strategy_tab.refresh_symbol_list()
        elif idx == self.tab_index.get("options"):
            self.options_tab.load_default()
            self.options_tab.refresh()
        self.refresh_all()

    # ------------------------------------------------------------------
    def _on_market_symbol(self, symbol: str) -> None:
        symbol = symbol.upper()
        if symbol not in self.account.watchlist:
            self.account.watchlist.append(symbol)
            self._dirty = True
            self._save()
        self.tabs.setCurrentIndex(self.tab_index["trade"])
        self.select_symbol(symbol)
        self._refresh_watchlist()

    def _on_market_bulk_add(self, symbols: list) -> None:
        wl = self.account.watchlist
        added = [s.upper() for s in symbols if s.upper() not in wl]
        wl.extend(added)
        self._dirty = True
        self._save()
        self.qworker.set_symbols(self._tracked_symbols())
        self.qworker.poke()
        self._refresh_watchlist()
        self.status.showMessage(
            _tr("已加入 {} 只新标的, 自选股共 {} 只").format(len(added), len(wl)), 6000)

    def _refresh_header(self) -> None:
        acc = self.account
        p = self.prices
        eq = acc.equity(p)
        unreal = acc.unrealized_total(p)
        realized = acc.realized_total()
        ret = acc.total_return_pct(p)
        mv = acc.positions_value(p)

        self.tiles["equity"].set_value(theme.money(eq), theme.pnl_color(eq - acc.initial_cash))
        self.tiles["cash"].set_value(theme.money(acc.cash),
                                     theme.RED if acc.cash < 0 else None,
                                     _tr("融资中 · 已付利息 ${:,.2f}").format(acc.interest_paid)
                                     if acc.cash < 0 else "")
        self.tiles["bp"].set_value(theme.money(acc.buying_power(p)), None,
                                   _tr("现金账户") if acc.account_type == "CASH" else _tr("保证金 2x"))
        self.tiles["mv"].set_value(theme.money(mv), None,
                                   _tr("{} 个持仓").format(len(acc.open_positions())))
        self.tiles["unreal"].set_value(theme.signed_money(unreal), theme.pnl_color(unreal))
        self.tiles["realized"].set_value(theme.signed_money(realized), theme.pnl_color(realized))
        self.tiles["ret"].set_value(theme.signed_pct(ret), theme.pnl_color(ret),
                                    theme.signed_money(eq - acc.initial_cash))

    def _refresh_watchlist(self) -> None:
        rows = []
        for sym in self.account.watchlist:
            q = self.quotes.get(sym)
            if q:
                # 价格和涨跌幅必须是同一对: 常规价配「较昨收」。以前这里放的是盘后价,
                # 旁边却是常规时段的涨跌幅, 两个数对不上。盘前盘后价看报价页顶部那行。
                col = theme.pnl_color(q.change)
                rows.append([cell(sym, theme.TEXT, LEFT, bold=True),
                             cell("{:.2f}".format(q.price or q.tradable_price), col, RIGHT),
                             cell(theme.signed_pct(q.change_pct), col, RIGHT)])
            else:
                rows.append([cell(sym, theme.TEXT, LEFT, bold=True),
                             cell("—", theme.TEXT_DIM, RIGHT),
                             cell("—", theme.TEXT_DIM, RIGHT)])
        prev = self.watch_table.currentRow()
        self.watch_table.blockSignals(True)
        fill_table(self.watch_table, rows)
        if self.current_symbol in self.account.watchlist:
            self.watch_table.selectRow(self.account.watchlist.index(self.current_symbol))
        elif 0 <= prev < len(rows):
            self.watch_table.selectRow(prev)
        self.watch_table.blockSignals(False)

    def _refresh_quote_header(self) -> None:
        sym = self.current_symbol
        q = self.quotes.get(sym)
        self.lab_symbol.setText(sym)
        self.lab_ticket_symbol.setText(sym)
        if not q:
            self.lab_name.setText(_tr("加载中…"))
            self.lab_price.setText("—")
            self.lab_change.setText("")
            self.lab_ext.setText("")
            self.lab_ohlc.setText("")
            return
        self.lab_name.setText("{}  ·  {}".format(q.name or "", q.exchange))
        col = theme.pnl_color(q.change)
        self.lab_price.setText("{:.2f}".format(q.price))
        self.lab_price.setStyleSheet("color: {};".format(col))
        self.lab_change.setText("{}  {}".format(theme.signed_money(q.change),
                                                theme.signed_pct(q.change_pct)))
        self.lab_change.setStyleSheet("color: {};".format(col))
        if q.market_state in ("PRE", "POST") and abs(q.ext_price - q.price) > 1e-9:
            tag = _tr("盘前") if q.market_state == "PRE" else _tr("盘后")
            ecol = theme.pnl_color(q.ext_price - q.price)
            # 盘前盘后的涨跌幅一律较 16:00 收盘价 (和 Yahoo 页面同一口径), 写明白免得误会
            self.lab_ext.setText(_tr('{} {:.2f} <span style="color:{}">{}</span> (较收盘)').format(
                tag, q.ext_price, ecol, theme.signed_pct(q.ext_change_pct)))
        else:
            self.lab_ext.setText("")
        self.lab_ohlc.setText(_tr("最高 {:.2f}   最低 {:.2f}   昨收 {:.2f}   成交量 {:,}").format(
            q.day_high, q.day_low, q.prev_close, q.volume))

    def _refresh_pending(self) -> None:
        rows = []
        self._pending_ids = []
        for o in sorted(self.account.open_orders(), key=lambda x: -x.created_at):
            self._pending_ids.append(o.id)
            col = theme.up_color() if o.side in BUY_SIDES else theme.down_color()
            state = _tr("已触发") if o.stop_triggered and o.order_type == STOP_LIMIT else _tr("挂单中")
            rows.append([cell(o.symbol, theme.TEXT, LEFT, bold=True),
                         cell(o.describe(), col),
                         cell(state, theme.TEXT_DIM, RIGHT)])
        fill_table(self.pending_table, rows)

    def _refresh_positions(self) -> None:
        acc, p = self.account, self.prices
        total_mv = sum(abs(pos.market_value(p.get(pos.symbol) or pos.avg_cost))
                       for pos in acc.open_positions()) or 1.0
        rows = []
        self._pos_symbols = []
        for pos in sorted(acc.open_positions(), key=lambda x: x.symbol):
            px = p.get(pos.symbol) or pos.avg_cost
            q = self.quotes.get(pos.symbol)
            un = pos.unrealized(px)
            pct = pos.unrealized_pct(px)
            mv = pos.market_value(px)
            col = theme.pnl_color(un)
            self._pos_symbols.append(pos.symbol)
            rows.append([
                cell(pos.symbol, theme.TEXT, LEFT, bold=True),
                cell((q.name if q else "")[:28], theme.TEXT_DIM),
                cell(_tr("空头") if pos.is_short else _tr("多头"),
                     theme.down_color() if pos.is_short else theme.up_color(), CENTER),
                cell("{:,}".format(pos.abs_qty), None, RIGHT),
                cell("{:.3f}".format(pos.avg_cost), None, RIGHT),
                cell("{:.2f}".format(px), None, RIGHT),
                cell(theme.money(mv), None, RIGHT),
                cell(theme.signed_money(un), col, RIGHT, bold=True),
                cell(theme.signed_pct(pct), col, RIGHT),
                cell(theme.signed_money(pos.realized_pnl), theme.pnl_color(pos.realized_pnl), RIGHT),
                cell("{:.1f}%".format(abs(mv) / total_mv * 100), theme.TEXT_DIM, RIGHT),
            ])
        fill_table(self.pos_table, rows)
        un_total = acc.unrealized_total(p)
        self.lab_pos_summary.setText(
            _tr("持仓 {} 个   总市值 {}   浮动盈亏 {}").format(
                len(rows), theme.money(acc.positions_value(p)), theme.signed_money(un_total)))

    def _refresh_orders(self) -> None:
        self._open_order_ids = []
        rows = []
        for o in sorted(self.account.open_orders(), key=lambda x: -x.created_at):
            self._open_order_ids.append(o.id)
            col = theme.up_color() if o.side in BUY_SIDES else theme.down_color()
            rows.append([
                cell(_fmt_time(o.created_at), theme.TEXT_DIM),
                cell(o.symbol, theme.TEXT, LEFT, bold=True),
                cell(SIDE_CN.get(o.side, o.side), col, CENTER),
                cell(TYPE_CN.get(o.order_type, o.order_type), None, CENTER),
                cell("{:,}".format(o.qty), None, RIGHT),
                cell("{:.2f}".format(o.limit_price) if o.limit_price else "—", None, RIGHT),
                cell("{:.2f}".format(o.stop_price) if o.stop_price else "—", None, RIGHT),
                cell(o.tif, theme.TEXT_DIM, CENTER),
                cell(_tr("已触发") if o.stop_triggered else STATUS_CN.get(o.status, o.status),
                     theme.GOLD, CENTER),
            ])
        fill_table(self.open_orders_table, rows)

        hrows = []
        for o in sorted([x for x in self.account.orders if not x.is_open],
                        key=lambda x: -x.updated_at)[:400]:
            col = theme.up_color() if o.side in BUY_SIDES else theme.down_color()
            scol = {FILLED: theme.TEXT, "REJECTED": theme.RED}.get(o.status, theme.TEXT_DIM)
            hrows.append([
                cell(_fmt_time(o.updated_at), theme.TEXT_DIM),
                cell(o.symbol, theme.TEXT, LEFT, bold=True),
                cell(SIDE_CN.get(o.side, o.side), col, CENTER),
                cell(TYPE_CN.get(o.order_type, o.order_type), None, CENTER),
                cell("{:,}".format(o.qty), None, RIGHT),
                cell("{:.2f}".format(o.fill_price) if o.fill_price else "—", None, RIGHT),
                cell("{:.2f}".format(o.commission + o.fees) if o.fill_price else "—",
                     theme.TEXT_DIM, RIGHT),
                cell(STATUS_CN.get(o.status, o.status), scol, CENTER),
                cell(o.note, theme.TEXT_DIM),
            ])
        fill_table(self.hist_orders_table, hrows)

    def _refresh_trades(self) -> None:
        rows = []
        for t in sorted(self.account.trades, key=lambda x: -x.ts)[:800]:
            col = theme.up_color() if t.side in BUY_SIDES else theme.down_color()
            closing = t.side in CLOSING_SIDES
            rows.append([
                cell(_fmt_time(t.ts), theme.TEXT_DIM),
                cell(t.symbol, theme.TEXT, LEFT, bold=True),
                cell(SIDE_CN.get(t.side, t.side), col, CENTER),
                cell("{:,}".format(t.qty), None, RIGHT),
                cell("{:.3f}".format(t.price), None, RIGHT),
                cell(theme.money(t.notional), None, RIGHT),
                cell("{:.2f}".format(t.commission), theme.TEXT_DIM, RIGHT),
                cell("{:.2f}".format(t.fees), theme.TEXT_DIM, RIGHT),
                cell(theme.signed_money(t.realized_pnl) if closing else "—",
                     theme.pnl_color(t.realized_pnl) if closing else theme.TEXT_DIM, RIGHT,
                     bold=closing),
            ])
        fill_table(self.trades_table, rows)
        acc = self.account
        self.lab_trade_summary.setText(
            _tr("共 {} 笔成交   累计费用 {}   累计已实现 {}").format(
                len(acc.trades), theme.money(acc.fees_total()),
                theme.signed_money(acc.realized_total())))

    def _refresh_perf(self) -> None:
        acc = self.account
        self.equity_chart.set_data(acc.equity_curve, acc.initial_cash)
        st = self.engine.stats(self.prices)
        pf = st["profit_factor"]
        vals = {
            "closed_trades": ("{}".format(st["closed_trades"]), None),
            "win_rate": ("{:.1f}%".format(st["win_rate"]),
                         theme.up_color() if st["win_rate"] >= 50 else theme.down_color()),
            "avg_win": (theme.signed_money(st["avg_win"]), theme.up_color()),
            "avg_loss": (theme.signed_money(st["avg_loss"]), theme.down_color()),
            "profit_factor": ("∞" if pf == float("inf") else "{:.2f}".format(pf), None),
            "max_drawdown": ("-{:.2f}%".format(st["max_drawdown"]), theme.down_color()),
            "realized": (theme.signed_money(st["realized"]), theme.pnl_color(st["realized"])),
            "unrealized": (theme.signed_money(st["unrealized"]), theme.pnl_color(st["unrealized"])),
            "fees": (theme.money(st["fees"]), theme.TEXT_DIM),
            "day_trades": ("{} / {}".format(st["day_trades"], self.settings.pdt_max_day_trades),
                           theme.GOLD if st["day_trades"] >= self.settings.pdt_max_day_trades else None),
        }
        for k, (text, col) in vals.items():
            lab = self.perf_labels[k]
            lab.setText(text)
            lab.setStyleSheet("color: {};".format(col) if col else "")

    def _refresh_leaderboard(self) -> None:
        accounts = storage.list_accounts()
        by_id = {a.id: a for a in accounts}
        by_id[self.account.id] = self.account      # 当前账户用内存中的最新状态
        rows_data = []
        for a in by_id.values():
            eq = a.equity(self.prices)
            pnl = eq - a.initial_cash
            ret = (pnl / a.initial_cash * 100.0) if a.initial_cash else 0.0
            closes = [t for t in a.trades if t.side in CLOSING_SIDES]
            wins = sum(1 for t in closes if t.realized_pnl > 0)
            wr = (wins / len(closes) * 100.0) if closes else 0.0
            rows_data.append((ret, a, eq, pnl, len(closes), wr))
        rows_data.sort(key=lambda x: -x[0])

        rows = []
        for i, (ret, a, eq, pnl, nclose, wr) in enumerate(rows_data, 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, str(i))
            is_me = a.id == self.account.id
            name = a.display_name + (_tr("  ← 当前") if is_me else "")
            rows.append([
                cell(medal, theme.GOLD if i <= 3 else theme.TEXT_DIM, CENTER),
                cell(name, theme.ACCENT if is_me else theme.TEXT, LEFT, bold=is_me),
                cell(_tr("保证金") if a.account_type == "MARGIN" else _tr("现金"), theme.TEXT_DIM, CENTER),
                cell(theme.money(a.initial_cash, 0), None, RIGHT),
                cell(theme.money(eq), None, RIGHT),
                cell(theme.signed_money(pnl), theme.pnl_color(pnl), RIGHT),
                cell(theme.signed_pct(ret), theme.pnl_color(ret), RIGHT, bold=True),
                cell(str(nclose), None, RIGHT),
                cell("{:.0f}%".format(wr) if nclose else "—", theme.TEXT_DIM, RIGHT),
            ])
        fill_table(self.lb_table, rows)

    # ==================================================================
    # 下单面板
    # ==================================================================
    def _set_side(self, side: str) -> None:
        self.current_side = side
        self.side_buttons[side].setChecked(True)
        colors = {BUY: theme.up_color(), COVER: theme.up_color(),
                  SELL: theme.down_color(), SHORT: theme.down_color()}
        self.btn_submit.setText("{} {}".format(SIDE_CN[side], self.current_symbol))
        self.btn_submit.setStyleSheet(
            "background: {}; border: none; color: #fff; font-weight: 700;".format(colors[side]))
        self._update_estimate()

    def _on_type_changed(self) -> None:
        t = self.type_combo.currentData()
        show_limit = t in (LIMIT, STOP_LIMIT)
        show_stop = t in (STOP, STOP_LIMIT)
        self.limit_spin.setEnabled(show_limit)
        self.stop_spin.setEnabled(show_stop)
        q = self.quotes.get(self.current_symbol)
        if q and q.tradable_price:
            if show_limit and self.limit_spin.value() <= 0.01:
                self.limit_spin.setValue(round(q.tradable_price, 2))
            if show_stop and self.stop_spin.value() <= 0.01:
                self.stop_spin.setValue(round(q.tradable_price, 2))
        self._update_estimate()

    def _max_qty(self) -> int:
        side = self.current_side
        pos = self.engine.position(self.current_symbol)
        if side == SELL:
            pending = sum(o.qty for o in self.account.open_orders()
                          if o.symbol == self.current_symbol and o.side == SELL)
            return max(pos.qty - pending, 0)
        if side == COVER:
            pending = sum(o.qty for o in self.account.open_orders()
                          if o.symbol == self.current_symbol and o.side == COVER)
            return max(pos.abs_qty - pending, 0)
        px = self._ref_price()
        if px <= 0:
            return 0
        avail = self.account.buying_power(self.prices) - self.engine.reserved_buying_power()
        avail -= max(self.settings.commission_min, 1.0)
        return max(int(avail // (px * (1 + self.settings.slippage_bps / 10000.0))), 0)

    def _ref_price(self) -> float:
        t = self.type_combo.currentData()
        if t in (LIMIT, STOP_LIMIT) and self.limit_spin.value() > 0:
            return self.limit_spin.value()
        if t == STOP and self.stop_spin.value() > 0:
            return self.stop_spin.value()
        q = self.quotes.get(self.current_symbol)
        return q.tradable_price if q else 0.0

    def _set_qty_pct(self, pct: int) -> None:
        mx = self._max_qty()
        self.qty_spin.setValue(max(int(mx * pct / 100), 1) if mx else 1)

    def _update_estimate(self) -> None:
        qty = self.qty_spin.value()
        px = self._ref_price()
        side = self.current_side
        notional = qty * px
        comm = self.settings.commission(qty, notional) if notional else 0.0
        fees = self.settings.sell_fees(qty, notional) if side in (SELL, SHORT) else 0.0
        total = notional + comm + fees if side in BUY_SIDES else notional - comm - fees
        word = _tr("预计支出") if side in BUY_SIDES else _tr("预计收入")
        # Qt 只看**第一行**判断是不是富文本; 这段第一行没有标签, 不强制指定的话
        # 整段会按纯文本显示, <b> 原样露出来 (中英文都有这个问题)。换行也要换成 <br>。
        self.lab_est.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lab_est.setText(
            _tr("成交金额 {}   佣金 {}   规费 {}\n{} <b>{}</b>   可下单上限 {:,} 股").format(
                theme.money(notional), theme.money(comm), theme.money(fees),
                word, theme.money(abs(total)), self._max_qty()).replace("\n", "<br>"))

    def _refresh_ticket(self) -> None:
        pos = self.engine.position(self.current_symbol)
        px = self.prices.get(self.current_symbol, 0.0)
        if pos.qty:
            un = pos.unrealized(px or pos.avg_cost)
            self.lab_pos_hint.setText(
                _tr('持有 <b>{}</b> {} 股   成本 {:.3f}   浮动 <span style="color:{}">{}</span> ({})').format(
                    _tr("空头") if pos.is_short else _tr("多头"), "{:,}".format(pos.abs_qty), pos.avg_cost,
                    theme.pnl_color(un), theme.signed_money(un),
                    theme.signed_pct(pos.unrealized_pct(px or pos.avg_cost))))
        else:
            self.lab_pos_hint.setText(_tr("当前无持仓"))
        self.btn_submit.setText("{} {}".format(SIDE_CN[self.current_side], self.current_symbol))
        self._update_estimate()

    def _submit_order(self) -> None:
        sym = self.current_symbol
        q = self.quotes.get(sym)
        if not q:
            QtWidgets.QMessageBox.warning(self, _tr("无行情"), _tr("还没有拿到 {} 的行情, 请稍候。").format(sym))
            return
        t = self.type_combo.currentData()
        order = Order(
            symbol=sym, side=self.current_side, qty=self.qty_spin.value(), order_type=t,
            limit_price=self.limit_spin.value() if t in (LIMIT, STOP_LIMIT) else 0.0,
            stop_price=self.stop_spin.value() if t in (STOP, STOP_LIMIT) else 0.0,
            tif=self.tif_combo.currentData())
        ok, msg = self.engine.submit(order, q, self.prices)
        if not ok:
            QtWidgets.QMessageBox.warning(self, _tr("订单被拒绝"), msg)
        else:
            self.status.showMessage("✔ " + msg, 8000)
        self._dirty = True
        self._save()
        self.qworker.set_symbols(self._tracked_symbols())
        self.refresh_all()
        self._update_chart_refs()

    # ==================================================================
    # 自选股 / 搜索 / 图表
    # ==================================================================
    def select_symbol(self, symbol: str) -> None:
        symbol = symbol.upper()
        if not symbol:
            return
        self.current_symbol = symbol
        self.limit_spin.setValue(0.01)
        self.stop_spin.setValue(0.01)
        self._refresh_quote_header()
        self._refresh_ticket()
        self._on_type_changed()
        self.chart.set_candles([], keep_view=False)
        self.chart.empty_label.setText(_tr("加载中…"))
        self._request_candles()
        self.qworker.set_symbols(self._tracked_symbols())
        self.qworker.poke()

    def _request_candles(self) -> None:
        if self.range_combo.count() == 0:      # 首次加载, 下拉还没填
            self._sync_range_combo()
        interval = MarketData.INTERVALS[self.current_interval][0]
        rng = self.range_combo.currentData()
        if rng is None:
            rng = MarketData.INTERVALS[self.current_interval][1]
        self.bars_label.setText(_tr("加载中…"))
        self.cworker.request(self.current_symbol, interval, rng)

    def _sync_range_combo(self) -> None:
        """不同周期能拉的历史长度不一样 (分钟线最多 1 个月), 所以切周期要重建列表。"""
        interval, default = MarketData.INTERVALS[self.current_interval]
        options = MarketData.RANGES.get(interval) or [(_tr("默认"), default)]
        want = self._preferred_range.get(interval, default)
        self.range_combo.blockSignals(True)
        self.range_combo.clear()
        for label, code in options:
            self.range_combo.addItem(label, code)
        i = self.range_combo.findData(want)
        if i < 0:
            i = self.range_combo.findData(default)
        self.range_combo.setCurrentIndex(max(i, 0))
        self.range_combo.blockSignals(False)

    def _on_range_pick(self) -> None:
        interval = MarketData.INTERVALS[self.current_interval][0]
        code = self.range_combo.currentData()
        if code is not None:
            self._preferred_range[interval] = code
            self._request_candles()

    def _set_interval(self, label: str) -> None:
        self.current_interval = label
        self._sync_range_combo()
        self._request_candles()

    def _update_chart_refs(self) -> None:
        pos = self.engine.position(self.current_symbol)
        orders = [o for o in self.account.open_orders() if o.symbol == self.current_symbol]
        self.chart.set_reference_lines(pos.avg_cost if pos.qty else None, orders)

    def _on_watch_selected(self) -> None:
        r = self.watch_table.currentRow()
        if 0 <= r < len(self.account.watchlist):
            sym = self.account.watchlist[r]
            if sym != self.current_symbol:
                self.select_symbol(sym)

    def _do_search(self) -> None:
        text = self.search_box.text().strip()
        if not text:
            return
        self._search_mode = True
        self.watch_stack.setCurrentIndex(1)
        self.sworker.request(text)

    def _exit_search(self) -> None:
        self._search_mode = False
        self.watch_stack.setCurrentIndex(0)
        self.search_box.clear()

    def _add_from_search(self) -> None:
        r = self.search_table.currentRow()
        if not (0 <= r < len(self._search_rows)):
            return
        sym = self._search_rows[r]["symbol"].upper()
        if sym not in self.account.watchlist:
            self.account.watchlist.append(sym)
        self._exit_search()
        self._dirty = True
        self._save()
        self.select_symbol(sym)
        self._refresh_watchlist()

    def _watch_menu(self, pos) -> None:
        r = self.watch_table.rowAt(pos.y())
        if not (0 <= r < len(self.account.watchlist)):
            return
        sym = self.account.watchlist[r]
        menu = QtWidgets.QMenu(self)
        a_del = menu.addAction(_tr("从自选股移除 {}").format(sym))
        a_up = menu.addAction(_tr("上移"))
        a_down = menu.addAction(_tr("下移"))
        act = menu.exec(self.watch_table.viewport().mapToGlobal(pos))
        wl = self.account.watchlist
        if act == a_del:
            wl.remove(sym)
            if self.current_symbol == sym and wl:
                self.select_symbol(wl[0])
        elif act == a_up and r > 0:
            wl[r - 1], wl[r] = wl[r], wl[r - 1]
        elif act == a_down and r < len(wl) - 1:
            wl[r + 1], wl[r] = wl[r], wl[r + 1]
        self._dirty = True
        self._save()
        self._refresh_watchlist()

    # ==================================================================
    # 持仓 / 订单操作
    # ==================================================================
    def _pos_double_clicked(self) -> None:
        r = self.pos_table.currentRow()
        syms = getattr(self, "_pos_symbols", [])
        if 0 <= r < len(syms):
            sym = syms[r]
            self.tabs.setCurrentIndex(self.tab_index["trade"])
            self.select_symbol(sym)
            pos = self.engine.position(sym)
            self._set_side(COVER if pos.is_short else SELL)
            self.qty_spin.setValue(pos.abs_qty or 1)

    def _close_position(self, symbol: str) -> None:
        pos = self.engine.position(symbol)
        if not pos.qty:
            return
        q = self.quotes.get(symbol)
        if not q:
            self.status.showMessage(_tr("{} 暂无行情, 无法平仓").format(symbol), 4000)
            return
        order = Order(symbol=symbol, side=COVER if pos.is_short else SELL,
                      qty=pos.abs_qty, order_type=MARKET)
        ok, msg = self.engine.submit(order, q, self.prices)
        self.status.showMessage(("✔ " if ok else "✘ ") + msg, 8000)
        if not ok:
            QtWidgets.QMessageBox.warning(self, _tr("平仓失败"), msg)

    def _close_selected_position(self) -> None:
        r = self.pos_table.currentRow()
        syms = getattr(self, "_pos_symbols", [])
        if not (0 <= r < len(syms)):
            QtWidgets.QMessageBox.information(self, _tr("提示"), _tr("请先选中一行持仓。"))
            return
        sym = syms[r]
        if QtWidgets.QMessageBox.question(
                self, _tr("确认平仓"), _tr("按市价平掉 {} 的全部持仓?").format(sym)
        ) != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self._close_position(sym)
        self._after_trade()

    def _close_all_positions(self) -> None:
        open_pos = self.account.open_positions()
        if not open_pos:
            return
        if QtWidgets.QMessageBox.question(
                self, _tr("确认清仓"), _tr("按市价平掉全部 {} 个持仓?").format(len(open_pos))
        ) != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        for pos in list(open_pos):
            self._close_position(pos.symbol)
        self._after_trade()

    def _after_trade(self) -> None:
        self._dirty = True
        self._save()
        self.engine.record_equity(self.prices, force=True)
        self.refresh_all()
        self._update_chart_refs()

    def _cancel_selected_pending(self) -> None:
        r = self.pending_table.currentRow()
        ids = getattr(self, "_pending_ids", [])
        if 0 <= r < len(ids):
            self.engine.cancel(ids[r])
            self._after_trade()

    def _pending_menu(self, pos) -> None:
        r = self.pending_table.rowAt(pos.y())
        ids = getattr(self, "_pending_ids", [])
        if not (0 <= r < len(ids)):
            return
        menu = QtWidgets.QMenu(self)
        a = menu.addAction(_tr("撤销此单"))
        if menu.exec(self.pending_table.viewport().mapToGlobal(pos)) == a:
            self.engine.cancel(ids[r])
            self._after_trade()

    def _cancel_selected_open_order(self) -> None:
        r = self.open_orders_table.currentRow()
        ids = getattr(self, "_open_order_ids", [])
        if 0 <= r < len(ids):
            self.engine.cancel(ids[r])
            self._after_trade()

    def _cancel_all(self) -> None:
        n = self.engine.cancel_all()
        self.status.showMessage(_tr("已撤销 {} 笔挂单").format(n), 4000)
        self._after_trade()

    def _export_trades(self) -> None:
        if not self.account.trades:
            QtWidgets.QMessageBox.information(self, _tr("提示"), _tr("还没有成交记录。"))
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, _tr("导出成交记录"), "trades_{}.csv".format(self.account.display_name), "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow([_tr("时间"), _tr("代码"), _tr("方向"), _tr("股数"), _tr("成交价"), _tr("金额"),
                            _tr("佣金"), _tr("规费"), _tr("已实现盈亏")])
                for t in sorted(self.account.trades, key=lambda x: x.ts):
                    w.writerow([_fmt_time(t.ts, full=True), t.symbol,
                                SIDE_CN.get(t.side, t.side), t.qty, "{:.4f}".format(t.price),
                                "{:.2f}".format(t.notional), "{:.2f}".format(t.commission),
                                "{:.2f}".format(t.fees), "{:.2f}".format(t.realized_pnl)])
            self.status.showMessage(_tr("已导出到 {}").format(path), 6000)
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, _tr("导出失败"), str(exc))

    # ==================================================================
    # 账户管理
    # ==================================================================
    def _refresh_account_combo(self) -> None:
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        accounts = storage.list_accounts()
        if not any(a.id == self.account.id for a in accounts):
            accounts.append(self.account)
        for a in accounts:
            eq = a.equity(self.prices)
            ret = a.total_return_pct(self.prices)
            self.account_combo.addItem("{}  ·  {}  ·  {}".format(
                a.display_name, theme.money(eq, 0), theme.signed_pct(ret)), a.id)
            self.account_combo.setItemData(
                self.account_combo.count() - 1,
                _tr("{}\n类型: {}\n初始资金: {}\n持仓 {} 个 · 成交 {} 笔").format(
                    a.display_name, _tr("保证金账户 (2x)") if a.account_type == "MARGIN" else _tr("现金账户"),
                    theme.money(a.initial_cash, 0), len(a.open_positions()), len(a.trades)),
                QtCore.Qt.ItemDataRole.ToolTipRole)
        idx = self.account_combo.findData(self.account.id)
        self.account_combo.setCurrentIndex(max(idx, 0))
        self.account_combo.blockSignals(False)
        if hasattr(self, "set_acctype"):
            i = self.set_acctype.findData(self.account.account_type)
            self.set_acctype.setCurrentIndex(max(i, 0))

    def _on_account_changed(self, _idx: int) -> None:
        aid = self.account_combo.currentData()
        if not aid or aid == self.account.id:
            return
        self._save()
        acc = storage.load_account(aid)
        if not acc:
            return
        self.account = acc
        self.engine = TradingEngine(acc, self.settings)
        self.options_engine = OptionsEngine(acc, self.settings)
        storage.set_active_account_id(acc.id)
        self.current_symbol = (acc.watchlist or ["AAPL"])[0]
        if hasattr(self, "set_acctype"):
            i = self.set_acctype.findData(acc.account_type)
            self.set_acctype.setCurrentIndex(max(i, 0))
        self.select_symbol(self.current_symbol)
        self.refresh_all()
        self.status.showMessage(_tr("已切换到账户: {}").format(acc.display_name), 4000)

    def _open_account_manager(self) -> None:
        self._save()
        dlg = AccountManagerDialog(self.account.id, self.prices,
                                   self.settings.default_initial_cash, self)
        dlg.exec()
        if not dlg.changed:
            return
        target = dlg.switch_to or self.account.id
        acc = storage.load_account(target)
        if acc is None:
            remaining = storage.list_accounts()
            if not remaining:
                acc = storage.bootstrap(self.settings.default_initial_cash)
            else:
                acc = remaining[0]
        switched = acc.id != self.account.id
        self.account = acc
        self.engine = TradingEngine(acc, self.settings)
        self.options_engine = OptionsEngine(acc, self.settings)
        storage.set_active_account_id(acc.id)
        self._refresh_account_combo()
        if hasattr(self, "set_acctype"):
            i = self.set_acctype.findData(acc.account_type)
            self.set_acctype.setCurrentIndex(max(i, 0))
        if switched or self.current_symbol not in acc.watchlist:
            self.current_symbol = (acc.watchlist or ["AAPL"])[0]
            self.select_symbol(self.current_symbol)
        if getattr(self, "strategy_tab", None):
            self.strategy_tab.refresh_symbol_list()
        self.qworker.set_symbols(self._tracked_symbols())
        self.qworker.poke()
        self.refresh_all()
        self.status.showMessage(_tr("当前账户: {}").format(acc.display_name), 5000)

    # ==================================================================
    def _apply_settings(self) -> None:
        s = self.settings
        s.refresh_seconds = self.set_refresh.value()
        s.include_prepost = self.set_prepost.isChecked()
        s.data_source = self.set_source.currentData()
        lang_changed = self.set_lang.currentData() != i18n.LANG
        s.language = self.set_lang.currentData()
        s.allow_closed_market_fill = self.set_closedfill.isChecked()
        s.color_up_is_green = self.set_green.isChecked()
        s.slippage_bps = self.set_slip.value()
        s.commission_mode = self.set_commode.currentData()
        s.commission_per_share = self.set_cps.value()
        s.commission_min = self.set_cmin.value()
        s.commission_flat = self.set_cflat.value()
        s.enforce_pdt = self.set_pdt.isChecked()
        s.save()

        theme.set_color_scheme(s.color_up_is_green)
        self.market.include_prepost = s.include_prepost
        self.market.set_source_mode(s.data_source)
        self._last_source = ""          # 逼状态栏立刻重刷
        self._refresh_source_badge()
        self.qworker.set_interval(s.refresh_seconds)
        self.account.account_type = self.set_acctype.currentData()

        self._save()
        self._refresh_account_combo()
        self._request_candles()
        self._set_side(self.current_side)
        self.refresh_all()
        self.status.showMessage(_tr("设置已保存"), 4000)
        if lang_changed:
            self._offer_restart()

    def _offer_restart(self) -> None:
        """语言切换要重启才生效。提示同样写成双语 —— 这时候界面还是旧语言。"""
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Language / 语言")
        box.setText("Restart now to switch the language?" + chr(10) + "现在重启以切换语言？")
        box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Yes
                               | QtWidgets.QMessageBox.StandardButton.No)
        if box.exec() != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        # 冻结的 exe: sys.executable 就是程序本身; 源码运行: python + main.py
        if getattr(sys, "frozen", False):
            prog, args = sys.executable, sys.argv[1:]
        else:
            prog, args = sys.executable, [os.path.abspath(sys.argv[0])] + sys.argv[1:]
        QtCore.QProcess.startDetached(prog, args, os.getcwd())
        self.close()          # 走 closeEvent, 账户照常落盘

    def _refresh_source_badge(self) -> None:
        src = getattr(self.market, "active_source", "yahoo")
        if src == self._last_source:
            return
        self._last_source = src
        # 搜索框的提示文字不在这里改 —— 见 _build_watch_panel。只有悬停说明跟着源变。
        if src == "yahoo":
            self.search_box.setToolTip(
                _tr("当前是 Yahoo 源，除了代码也能搜公司名。\n"
                "Yahoo 连不上时会自动切到国内源，那时只能按代码搜。"))
            self.lab_source.setText(_tr("行情源 Yahoo"))
            self.lab_source.setToolTip("")
            self.lab_source.setStyleSheet("")
            return
        self.search_box.setToolTip(
            _tr("当前用的是国内行情源，它的搜索接口不返回证券数据，\n"
            "所以只能按代码查，搜公司名查不到。\n"
            "换回 Yahoo（设置 → 行情源）就能按公司名搜。"))
        self.lab_source.setText(_tr("行情源 腾讯/东财（备用）"))
        self.lab_source.setStyleSheet("color:{}; font-weight:600;".format(theme.GOLD))
        self.lab_source.setToolTip(
            _tr("Yahoo 连不上，已自动切换到国内源。\n"
            "报价走腾讯，与 Yahoo 完全一致（实测偏差 0.000%）；\n"
            "K 线也以腾讯为主，超过 8 年或分钟线才用东方财富。\n\n"
            "注意：腾讯的历史价不含股息再投，东财的股息算法\n"
            "也和 Yahoo 不同，跨多年的回测数字会有差异。"))
        self.status.showMessage(
            _tr("Yahoo 行情连不上，已切换到国内源 腾讯/东财（长周期回测数字会有差异）"), 12000)

    def _tick_clock(self) -> None:
        now_et = datetime.now(ET)
        self.lab_clock.setText(_tr("纽约 {}").format(now_et.strftime("%m-%d %H:%M:%S")))

    def _save(self) -> None:
        try:
            storage.save_account(self.account)
            self._dirty = False
        except OSError as exc:
            self.status.showMessage(_tr("保存失败: {}").format(exc), 6000)

    def closeEvent(self, event) -> None:
        self.engine.record_equity(self.prices, force=True)
        self._save()
        if getattr(self, "options_tab", None):
            self.options_tab.stop()
        if getattr(self, "strategy_tab", None):
            self.strategy_tab.stop()
        if getattr(self, "market_browser", None):
            self.market_browser.stop()
        for w in (getattr(self, "qworker", None), getattr(self, "cworker", None),
                  getattr(self, "sworker", None)):
            if w:
                w.stop()
                w.wait(2000)
        self.market.close()
        try:
            self.option_source.close()
        except Exception:
            pass
        super().closeEvent(event)


def _fmt_time(ts: float, full: bool = False) -> str:
    dt = datetime.fromtimestamp(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S" if full else "%m-%d %H:%M:%S")
