"""期权页: 期权链 T 型报价 / 持仓 / 多腿组合构建。"""
from __future__ import annotations

import time
from datetime import date, datetime

from PyQt6 import QtCore, QtGui, QtWidgets

from ..options import pricing as pr
from ..options.chain import OptionDataError, YahooOptionSource
from ..options.engine import OptionsEngine, position_margin, total_option_margin
from ..options.models import (
    OptionOrder, OptionQuote, BUY_OPEN, SELL_OPEN, SELL_CLOSE, BUY_CLOSE,
    OPT_SIDE_CN, RIGHT_CN, build_occ,
)
from ..options.pricing import CALL, PUT
from . import theme
from .panels import Card, NumItem, make_table, cell, fill_table, LEFT, RIGHT, CENTER
from .payoff import PayoffChart
from ..i18n import _tr

MARKET, LIMIT = "MARKET", "LIMIT"

# 期权链表格列
# 双边对照 (券商常见的 T 型链): 认购在左、行权价居中、认沽在右
CHAIN_COLS = [_tr("未平仓"), _tr("成交量"), "Delta", _tr("隐波"), _tr("买价"), _tr("卖价"),
              _tr("行权价"),
              _tr("买价"), _tr("卖价"), _tr("隐波"), "Delta", _tr("成交量"), _tr("未平仓")]
STRIKE_COL = 6

# 单边模式: 行权价打头, 从左往右自然阅读, 点整行都不会有歧义
SINGLE_COLS = [_tr("行权价"), _tr("价内/价外"), _tr("买价"), _tr("卖价"), _tr("价差"), _tr("隐波"),
               "Delta", _tr("未平仓"), _tr("成交量")]
SINGLE_STRETCH = 1

MODE_CALL, MODE_PUT, MODE_BOTH = "call", "put", "both"

PRESETS = [
    (_tr("单腿 · 买入认购 (看涨)"), "long_call"),
    (_tr("单腿 · 买入认沽 (看跌)"), "long_put"),
    (_tr("单腿 · 卖出认沽 (现金担保)"), "short_put"),
    (_tr("单腿 · 备兑开仓 (持股卖call)"), "covered_call"),
    (_tr("价差 · 牛市认购价差"), "bull_call"),
    (_tr("价差 · 熊市认沽价差"), "bear_put"),
    (_tr("波动 · 跨式 (赌大涨大跌)"), "straddle"),
    (_tr("波动 · 宽跨式 (更便宜)"), "strangle"),
    (_tr("收租 · 铁鹰 (赌不动)"), "iron_condor"),
]


# ======================================================================
class ChainWorker(QtCore.QThread):
    expirations_ready = QtCore.pyqtSignal(str, list)
    chain_ready = QtCore.pyqtSignal(str, object, float, list)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.source = source
        self.job = None

    def start_job(self, underlying: str, expiry, want_expirations: bool):
        if self.isRunning():
            return False
        self.job = (underlying.upper(), expiry, want_expirations)
        self.start()
        return True

    def run(self):
        und, expiry, want_exp = self.job
        try:
            if want_exp:
                exps = self.source.expirations(und)
                if not exps:
                    self.failed.emit(_tr("{} 没有期权").format(und))
                    return
                self.expirations_ready.emit(und, exps)
                expiry = expiry if expiry in exps else exps[0]
            spot, quotes = self.source.chain(und, expiry)
            self.chain_ready.emit(und, expiry, spot, quotes)
        except OptionDataError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(_tr("期权链加载失败: {}").format(exc))


class PositionQuoteWorker(QtCore.QThread):
    """轮询持仓合约的报价, 用于标记盈亏和到期处理。"""
    ready = QtCore.pyqtSignal(dict, dict)

    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.source = source
        self.symbols: list = []
        self.underlyings: list = []

    def start_job(self, symbols, underlyings):
        if self.isRunning() or not symbols:
            return False
        self.symbols = list(symbols)
        self.underlyings = list(underlyings)
        self.start()
        return True

    def run(self):
        try:
            quotes = self.source.quotes(self.symbols)
        except Exception:
            quotes = {}
        spots = {}
        for u in self.underlyings:
            try:
                spots[u] = self.source.spot(u)
            except Exception:
                pass
        self.ready.emit(quotes, spots)


# ======================================================================
class OptionsTab(QtWidgets.QWidget):
    trades_executed = QtCore.pyqtSignal()
    status = QtCore.pyqtSignal(str)
    prices_updated = QtCore.pyqtSignal(dict)

    def __init__(self, source, settings, get_context, parent=None):
        super().__init__(parent)
        self.source = source
        self.settings = settings
        self.get_context = get_context      # () -> (account, options_engine, stock_quotes, prices)

        self.underlying = "AAPL"
        self.expiry: date | None = None
        self.expirations: list = []
        self.spot = 0.0
        self.quotes: list = []
        self.by_symbol: dict = {}
        self.selected: OptionQuote | None = None
        self.opt_prices: dict = {}
        self.spots: dict = {}

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.inner = QtWidgets.QTabWidget()
        self.inner.addTab(self._build_chain(), _tr("期权链"))
        self.inner.addTab(self._build_positions(), _tr("我的期权持仓"))
        self.inner.addTab(self._build_combo(), _tr("策略组合"))
        self.inner.currentChanged.connect(self._on_inner_tab)
        lay.addWidget(self.inner)

        self.worker = ChainWorker(source)
        self.worker.expirations_ready.connect(self._on_expirations)
        self.worker.chain_ready.connect(self._on_chain)
        self.worker.failed.connect(self._on_failed)

        self.pos_worker = PositionQuoteWorker(source)
        self.pos_worker.ready.connect(self._on_position_quotes)

        self.pos_timer = QtCore.QTimer(self)
        self.pos_timer.timeout.connect(self.refresh_position_quotes)
        self.pos_timer.start(20000)

        self._loaded = False

    # ==================================================================
    # 期权链
    # ==================================================================
    def _build_chain(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        root = QtWidgets.QHBoxLayout(w)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # ---- 左: 底层 + 到期日 ----
        side = Card(_tr("标的与到期日"))
        side.setMaximumWidth(230)
        side.setMinimumWidth(200)
        row = QtWidgets.QHBoxLayout()
        self.sym_edit = QtWidgets.QLineEdit(self.underlying)
        self.sym_edit.setPlaceholderText(_tr("股票代码"))
        self.sym_edit.returnPressed.connect(self._load_underlying)
        row.addWidget(self.sym_edit)
        b = QtWidgets.QPushButton(_tr("加载"))
        b.clicked.connect(self._load_underlying)
        row.addWidget(b)
        side.vbox.addLayout(row)

        self.lab_spot = QtWidgets.QLabel("—")
        self.lab_spot.setStyleSheet("font-size:20px; font-weight:700;")
        side.vbox.addWidget(self.lab_spot)
        self.lab_spot_sub = QtWidgets.QLabel("")
        self.lab_spot_sub.setObjectName("Dim")
        self.lab_spot_sub.setWordWrap(True)
        side.vbox.addWidget(self.lab_spot_sub)

        side.vbox.addWidget(QtWidgets.QLabel(_tr("到期日")))
        self.exp_list = QtWidgets.QListWidget()
        self.exp_list.itemClicked.connect(self._on_expiry_pick)
        side.vbox.addWidget(self.exp_list, 1)

        self.only_liquid = QtWidgets.QCheckBox(_tr("只看有流动性的"))
        self.only_liquid.setChecked(True)
        self.only_liquid.setToolTip(_tr("过滤掉几乎没人交易、买卖价差极宽的合约"))
        self.only_liquid.stateChanged.connect(self._render_chain)
        side.vbox.addWidget(self.only_liquid)

        self.near_only = QtWidgets.QCheckBox(_tr("只看现价 ±20% 范围"))
        self.near_only.setChecked(True)
        self.near_only.stateChanged.connect(self._render_chain)
        side.vbox.addWidget(self.near_only)
        root.addWidget(side)

        # ---- 中: T 型报价 ----
        mid = Card()
        head = QtWidgets.QHBoxLayout()
        self.lab_chain = QtWidgets.QLabel(_tr("输入代码后点「加载」"))
        self.lab_chain.setObjectName("Title")
        head.addWidget(self.lab_chain)
        head.addStretch(1)

        # 看涨 / 看跌 用明确的按钮切换, 不靠「点表格左半边还是右半边」
        self.chain_mode = MODE_CALL
        self.mode_buttons = {}
        mode_group = QtWidgets.QButtonGroup(self)
        mrow = QtWidgets.QHBoxLayout()
        mrow.setSpacing(4)
        for mode, text, tip in (
                (MODE_CALL, _tr("看涨 Call"), _tr("只看认购合约——赌股价上涨")),
                (MODE_PUT, _tr("看跌 Put"), _tr("只看认沽合约——赌股价下跌")),
                (MODE_BOTH, _tr("两边对照"), _tr("券商常见的 T 型链: 认购在左, 认沽在右"))):
            b = QtWidgets.QPushButton(text)
            b.setCheckable(True)
            b.setChecked(mode == self.chain_mode)
            b.setToolTip(tip)
            b.clicked.connect(lambda _, m=mode: self._set_chain_mode(m))
            mode_group.addButton(b)
            self.mode_buttons[mode] = b
            mrow.addWidget(b)
        head.addLayout(mrow)
        mid.vbox.addLayout(head)

        self.chain_legend = QtWidgets.QLabel("")
        self.chain_legend.setObjectName("Dim")
        mid.vbox.addWidget(self.chain_legend)

        self.chain_table = make_table(SINGLE_COLS, stretch_col=SINGLE_STRETCH)
        self.chain_table.doubleClicked.connect(self._on_chain_click)
        self.chain_table.clicked.connect(self._on_chain_click)
        mid.vbox.addWidget(self.chain_table, 1)
        self.chain_status = QtWidgets.QLabel("")
        self.chain_status.setObjectName("Dim")
        mid.vbox.addWidget(self.chain_status)
        root.addWidget(mid, 1)

        # ---- 右: 下单 + 赔率 ----
        right = QtWidgets.QVBoxLayout()
        right.setSpacing(8)

        ticket = Card(_tr("下单"))
        ticket.setMaximumWidth(450)      # 380 塞不下英文的 Buy to Open 等四个按钮
        ticket.setMinimumWidth(340)
        self.lab_contract = QtWidgets.QLabel(_tr("还没选合约"))
        self.lab_contract.setStyleSheet("font-size:14px; font-weight:700;")
        self.lab_contract.setWordWrap(True)
        ticket.vbox.addWidget(self.lab_contract)
        self.lab_quote = QtWidgets.QLabel("")
        self.lab_quote.setObjectName("Dim")
        self.lab_quote.setWordWrap(True)
        ticket.vbox.addWidget(self.lab_quote)

        srow = QtWidgets.QHBoxLayout()
        srow.setSpacing(4)
        self.side_group = QtWidgets.QButtonGroup(self)
        self.side_buttons = {}
        for s in (BUY_OPEN, SELL_OPEN, SELL_CLOSE, BUY_CLOSE):
            b = QtWidgets.QPushButton(OPT_SIDE_CN[s])
            b.setCheckable(True)
            b.setChecked(s == BUY_OPEN)
            b.clicked.connect(lambda _, x=s: self._set_side(x))
            self.side_group.addButton(b)
            self.side_buttons[s] = b
            srow.addWidget(b)
        ticket.vbox.addLayout(srow)
        self.side = BUY_OPEN

        form = QtWidgets.QFormLayout()
        form.setSpacing(6)
        self.qty_spin = QtWidgets.QSpinBox()
        self.qty_spin.setRange(1, 10000)
        self.qty_spin.setValue(1)
        self.qty_spin.valueChanged.connect(self._update_ticket)
        form.addRow(_tr("合约张数"), self.qty_spin)
        self.type_combo = QtWidgets.QComboBox()
        self.type_combo.addItem(_tr("市价 (吃对手价)"), MARKET)
        self.type_combo.addItem(_tr("限价"), LIMIT)
        self.type_combo.currentIndexChanged.connect(self._update_ticket)
        form.addRow(_tr("订单类型"), self.type_combo)
        self.limit_spin = QtWidgets.QDoubleSpinBox()
        self.limit_spin.setRange(0.01, 100000)
        self.limit_spin.setDecimals(2)
        self.limit_spin.setPrefix("$ ")
        self.limit_spin.valueChanged.connect(self._update_ticket)
        form.addRow(_tr("限价 (每股)"), self.limit_spin)
        ticket.vbox.addLayout(form)

        self.lab_odds = QtWidgets.QLabel("")
        self.lab_odds.setWordWrap(True)
        self.lab_odds.setTextFormat(QtCore.Qt.TextFormat.RichText)
        ticket.vbox.addWidget(self.lab_odds)

        self.btn_submit = QtWidgets.QPushButton(_tr("买入开仓"))
        self.btn_submit.setObjectName("Primary")
        self.btn_submit.setMinimumHeight(36)
        self.btn_submit.clicked.connect(self._submit)
        ticket.vbox.addWidget(self.btn_submit)
        right.addWidget(ticket)

        pc = Card(_tr("到期损益预览"))
        self.mini_payoff = PayoffChart()
        self.mini_payoff.setMinimumHeight(190)
        pc.vbox.addWidget(self.mini_payoff, 1)
        right.addWidget(pc, 1)
        root.addLayout(right)
        return w

    # ------------------------------------------------------------------
    def _load_underlying(self):
        sym = self.sym_edit.text().strip().upper()
        if not sym:
            return
        self.underlying = sym
        self.chain_status.setText(_tr("加载中…"))
        if not self.worker.start_job(sym, None, True):
            self.chain_status.setText(_tr("上一次还在加载, 请稍候"))

    def load_default(self):
        if not self._loaded:
            self._loaded = True
            self._load_underlying()

    def _on_expirations(self, und: str, exps: list):
        if und != self.underlying:
            return
        self.expirations = exps
        self.exp_list.clear()
        today = date.today()
        for e in exps:
            days = (e - today).days
            it = QtWidgets.QListWidgetItem(_tr("{}  ({} 天)").format(e.isoformat(), max(days, 0)))
            it.setData(QtCore.Qt.ItemDataRole.UserRole, e)
            if days <= 7:
                it.setForeground(QtGui.QColor(theme.GOLD))
            self.exp_list.addItem(it)
        if exps:
            self.exp_list.setCurrentRow(0)

    def _on_expiry_pick(self, item):
        e = item.data(QtCore.Qt.ItemDataRole.UserRole)
        if not e or e == self.expiry:
            return
        self.chain_status.setText(_tr("加载 {} 的链…").format(e))
        if not self.worker.start_job(self.underlying, e, False):
            self.chain_status.setText(_tr("上一次还在加载, 请稍候"))

    def _on_failed(self, msg: str):
        self.chain_status.setText(msg)
        QtWidgets.QMessageBox.warning(self, _tr("期权数据"), msg)

    def _on_chain(self, und: str, expiry, spot: float, quotes: list):
        if und != self.underlying:
            return
        self.expiry = expiry
        self.spot = spot
        self.quotes = quotes
        self.by_symbol = {q.symbol: q for q in quotes}
        for q in quotes:
            self.opt_prices[q.symbol] = q.mid
        self.spots[und] = spot
        self.prices_updated.emit(dict(self.opt_prices, **self.spots))

        self.lab_spot.setText("{:.2f}".format(spot))
        days = (expiry - date.today()).days if expiry else 0
        atm = min((q for q in quotes if q.right == CALL),
                  key=lambda q: abs(q.strike - spot), default=None)
        iv = atm.iv if atm else 0.0
        move = pr.expected_move(spot, max(days, 0) / 365.0, iv)
        self.lab_spot_sub.setText(
            _tr("{}<br>平值隐波 {:.1f}%<br>到期前 1 个标准差波动 ±{:.2f} "
            "({:.1f}%)").format(und, iv * 100, move, move / spot * 100 if spot else 0))
        self.lab_chain.setText(_tr("{} · 到期 {} · 剩 {} 天").format(und, expiry, max(days, 0)))
        self._render_chain()
        self.chain_status.setText(_tr("共 {} 个合约").format(len(quotes)))

    # ------------------------------------------------------------------
    def _set_chain_mode(self, mode: str):
        """在「只看认购 / 只看认沽 / 两边对照」之间切换。

        单边模式下行权价打头、点整行都选中同一个合约, 不存在「左半边还是右半边」
        这种要靠猜的规则。
        """
        if mode == self.chain_mode:
            return
        self.chain_mode = mode
        self.mode_buttons[mode].setChecked(True)
        cols = CHAIN_COLS if mode == MODE_BOTH else SINGLE_COLS
        stretch = STRIKE_COL if mode == MODE_BOTH else SINGLE_STRETCH
        t = self.chain_table
        t.clearContents()
        t.setRowCount(0)
        t.setColumnCount(len(cols))
        t.setHorizontalHeaderLabels(cols)
        hh = t.horizontalHeader()
        for i in range(len(cols)):
            hh.setSectionResizeMode(i, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(stretch, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self._render_chain()

    def _render_chain(self):
        self._update_chain_legend()
        if not self.quotes:
            return
        calls = {q.strike: q for q in self.quotes if q.right == CALL}
        puts = {q.strike: q for q in self.quotes if q.right == PUT}
        both = self.chain_mode == MODE_BOTH
        side = calls if self.chain_mode == MODE_CALL else puts
        strikes = sorted(set(calls) | set(puts)) if both else sorted(side)
        if self.near_only.isChecked() and self.spot > 0:
            strikes = [k for k in strikes if abs(k - self.spot) / self.spot <= 0.20]
        if self.only_liquid.isChecked():
            if both:
                strikes = [k for k in strikes
                           if (calls.get(k) and calls[k].liquid)
                           or (puts.get(k) and puts[k].liquid)]
            else:
                strikes = [k for k in strikes if side[k].liquid]

        days = (self.expiry - date.today()).days if self.expiry else 0
        T = max(days, 0) / 365.0
        self._row_strikes = strikes
        rows = []
        for k in strikes:
            atm = self.spot > 0 and abs(k - self.spot) / self.spot < 0.006
            if both:
                rows.append(
                    self._side_cells(calls.get(k), T, CALL, reverse=True)
                    + [cell("{:g}".format(k), theme.GOLD if atm else theme.TEXT,
                            CENTER, bold=True)]
                    + self._side_cells(puts.get(k), T, PUT, reverse=False))
            else:
                rows.append(self._single_cells(side[k], T, self.chain_mode, atm))
        fill_table(self.chain_table, rows)

    def _update_chain_legend(self):
        if getattr(self, "chain_legend", None) is None:
            return
        if self.chain_mode == MODE_BOTH:
            self.chain_legend.setText(
                _tr('<span style="color:{}">◀ 左边六列 = 认购 Call</span>　'
                '<span style="color:{}">右边六列 = 认沽 Put ▶</span>　·　'
                '点哪一边就选哪一边的合约　·　'
                '觉得绕就切到上面的「看涨」或「看跌」').format(
                    theme.up_color(), theme.down_color()))
        else:
            cn, color = ((_tr("认购 Call"), theme.up_color())
                         if self.chain_mode == MODE_CALL
                         else (_tr("认沽 Put"), theme.down_color()))
            self.chain_legend.setText(
                _tr('当前只显示 <span style="color:{}"><b>{}</b></span>　·　'
                '点任意一行即可选中该合约').format(color, cn))

    def _single_cells(self, q: OptionQuote, T: float, right: str,
                      atm: bool) -> list:
        """单边模式的一行: 行权价打头, 附带「离现价多远」。"""
        edge = 0.0
        if self.spot > 0:
            edge = ((self.spot - q.strike) if right == CALL
                    else (q.strike - self.spot)) / self.spot
        itm = edge > 0
        base = theme.TEXT if itm else theme.TEXT_DIM
        delta = 0.0
        if T > 0 and q.iv > 0 and self.spot > 0:
            delta = pr.greeks(self.spot, q.strike, T, q.iv, right)["delta"]
        money = "{} {:.1f}%".format(_tr("价内") if itm else _tr("价外"), abs(edge) * 100)
        dim = theme.TEXT_DIM
        return [
            cell("{:g}".format(q.strike), theme.GOLD if atm else theme.TEXT,
                 RIGHT, bold=True, sort_key=q.strike),
            cell(_tr("平值") if atm else money, theme.GOLD if atm else base, LEFT),
            cell("{:.2f}".format(q.bid), theme.up_color(), RIGHT, bold=itm),
            cell("{:.2f}".format(q.ask), theme.down_color(), RIGHT, bold=itm),
            cell("{:.1f}%".format(q.spread_pct),
                 dim if q.liquid else theme.GOLD, RIGHT),
            cell("{:.1f}%".format(q.iv * 100), dim, RIGHT),
            cell("{:+.2f}".format(delta), base, RIGHT),
            cell("{:,}".format(q.open_interest), dim, RIGHT),
            cell("{:,}".format(q.volume), dim, RIGHT),
        ]

    def _side_cells(self, q: "OptionQuote | None", T: float, right: str,
                    reverse: bool) -> list:
        if q is None:
            return [cell("—", theme.TEXT_DIM, CENTER) for _ in range(6)]
        itm = (q.strike < self.spot) if right == CALL else (q.strike > self.spot)
        base = theme.TEXT if itm else theme.TEXT_DIM
        delta = 0.0
        if T > 0 and q.iv > 0 and self.spot > 0:
            delta = pr.greeks(self.spot, q.strike, T, q.iv, right)["delta"]
        dim = theme.TEXT_DIM
        cells = [
            cell("{:,}".format(q.open_interest), dim, RIGHT),
            cell("{:,}".format(q.volume), dim, RIGHT),
            cell("{:+.2f}".format(delta), base, RIGHT),
            cell("{:.1f}%".format(q.iv * 100), dim, RIGHT),
            cell("{:.2f}".format(q.bid), theme.up_color(), RIGHT, bold=itm),
            cell("{:.2f}".format(q.ask), theme.down_color(), RIGHT, bold=itm),
        ]
        return list(reversed(cells)) if reverse else cells

    def _on_chain_click(self, index):
        r, c = index.row(), index.column()
        if not (0 <= r < len(getattr(self, "_row_strikes", []))):
            return
        if self.chain_mode == MODE_BOTH:
            if c == STRIKE_COL:      # 行权价那一列不属于任何一边
                return
            right = CALL if c < STRIKE_COL else PUT
        else:
            right = CALL if self.chain_mode == MODE_CALL else PUT
        k = self._row_strikes[r]
        q = next((x for x in self.quotes if x.right == right and abs(x.strike - k) < 1e-9), None)
        if q:
            self.select_contract(q)

    # ------------------------------------------------------------------
    def select_contract(self, q: OptionQuote):
        self.selected = q
        self.limit_spin.blockSignals(True)
        self.limit_spin.setValue(round(q.mid, 2) or 0.01)
        self.limit_spin.blockSignals(False)
        self.lab_contract.setText("{} {} {:g} {}".format(
            q.underlying, q.expiry.isoformat(), q.strike, RIGHT_CN.get(q.right, q.right)))
        self.lab_quote.setText(
            _tr("买价 <b>{:.2f}</b>　卖价 <b>{:.2f}</b>　价差 {:.1f}%<br>"
            "隐波 {:.1f}%　未平仓 {:,}　成交量 {:,}{}").format(
                q.bid, q.ask, q.spread_pct, q.iv * 100, q.open_interest, q.volume,
                "" if q.liquid else
                _tr('<br><span style="color:{}">流动性差, 真实成交可能比这个价还糟</span>').format(
                    theme.GOLD)))
        self._update_ticket()

    def _set_side(self, side: str):
        self.side = side
        self.side_buttons[side].setChecked(True)
        self._update_ticket()

    def _update_ticket(self):
        q = self.selected
        if not q:
            self.lab_odds.setText(_tr("先用上方的「看涨 Call / 看跌 Put」选边，"
                                  "再点报价表里的任意一行来选合约。"))
            self.mini_payoff.clear()
            return
        acc, eng, _, _ = self.get_context()
        qty = self.qty_spin.value()
        is_limit = self.type_combo.currentData() == LIMIT
        self.limit_spin.setEnabled(is_limit)
        px = self.limit_spin.value() if is_limit else q.fill_price(self.side)
        days = (q.expiry - date.today()).days
        T = max(days, 0) / 365.0
        comm = eng.commission(qty)
        notional = px * qty * q.multiplier

        colors = {BUY_OPEN: theme.up_color(), BUY_CLOSE: theme.up_color(),
                  SELL_OPEN: theme.down_color(), SELL_CLOSE: theme.down_color()}
        self.btn_submit.setText(_tr("{}  {} 张").format(OPT_SIDE_CN[self.side], qty))
        self.btn_submit.setStyleSheet(
            "background: {}; border:none; color:#fff; font-weight:700;".format(
                colors[self.side]))

        g = pr.greeks(self.spot, q.strike, T, q.iv, q.right) if (T > 0 and q.iv > 0) else {}
        sign = 1 if self.side in (BUY_OPEN, BUY_CLOSE) else -1
        lines = []
        if self.side in (BUY_OPEN, BUY_CLOSE):
            lines.append(_tr("<b>需要付出 {}</b>（含佣金 {}）").format(
                theme.money(notional + comm), theme.money(comm)))
        else:
            lines.append(_tr("<b>收到权利金 {}</b>（扣佣金后 {}）").format(
                theme.money(notional), theme.money(notional - comm)))

        if self.side == BUY_OPEN and T > 0 and q.iv > 0:
            a = pr.analyze(self.spot, q.strike, T, q.iv, q.right, px, qty)
            need = a["breakeven_move_pct"]
            lines.append(
                _tr("盈亏平衡价 <b>{:.2f}</b>（{}需{} {:.1f}%）").format(
                    a["breakeven"], _tr("股价") , _tr("涨") if need > 0 else _tr("跌"), abs(need)))
            lines.append(
                _tr('到期变实值 <b>{:.0f}%</b>　真正赚钱 <b style="color:{}">{:.0f}%</b>').format(
                    a["prob_itm"], theme.GOLD, a["prob_profit"]))
            lines.append(_tr('每天时间损耗 <span style="color:{}">{}</span>　'
                         '最大亏损 <span style="color:{}">{}</span>（100%）').format(
                             theme.down_color(), theme.money(abs(a["theta_per_day"])),
                             theme.down_color(), theme.money(a["max_loss"])))
        elif self.side == SELL_OPEN:
            probe_margin = self._probe_margin(q, qty, px)
            lines.append(_tr("占用保证金约 <b>{}</b>").format(theme.money(probe_margin)))
            if T > 0 and q.iv > 0:
                p_itm = pr.prob_itm(self.spot, q.strike, T, q.iv, q.right)
                lines.append(_tr("到期被指派概率约 <b>{:.0f}%</b>").format(p_itm * 100))
                if q.right == CALL:
                    lines.append(_tr('<span style="color:{}">裸卖认购理论上亏损无上限</span>').format(
                        theme.down_color()))
                else:
                    lines.append(_tr("最坏情况: 以 {:g} 接货 {} 股, 需 {}").format(
                        q.strike, qty * q.multiplier,
                        theme.money(q.strike * qty * q.multiplier)))
        if g:
            lines.append(
                _tr('<span style="color:{}">Delta {:+.3f}　Gamma {:.4f}　'
                'Theta {:+.2f}/天　Vega {:.3f}</span>').format(
                    theme.TEXT_DIM, g["delta"] * sign, g["gamma"] * sign,
                    g["theta"] * sign * q.multiplier * qty, g["vega"] * sign))
        lines.append(_tr('<span style="color:{}">剩余 {} 天</span>').format(theme.TEXT_DIM, max(days, 0)))
        self.lab_odds.setText("<br>".join(lines))

        legs = [{"right": q.right, "strike": q.strike, "qty": qty * sign,
                 "premium": px, "multiplier": q.multiplier, "iv": q.iv}]
        self.mini_payoff.set_legs(legs, self.spot, q.iv, days)

    def _probe_margin(self, q: OptionQuote, qty: int, px: float) -> float:
        from ..options.models import OptionPosition
        acc, eng, _, _ = self.get_context()
        probe = OptionPosition(symbol=q.symbol, underlying=q.underlying, right=q.right,
                               strike=q.strike, expiry=q.expiry.isoformat(),
                               qty=-qty, avg_cost=px, multiplier=q.multiplier)
        return position_margin(probe, self.spot, acc, px)

    def _submit(self):
        q = self.selected
        if not q:
            return
        acc, eng, _, prices = self.get_context()
        is_limit = self.type_combo.currentData() == LIMIT
        order = OptionOrder(
            symbol=q.symbol, side=self.side, qty=self.qty_spin.value(),
            underlying=q.underlying, right=q.right, strike=q.strike,
            expiry=q.expiry.isoformat(), multiplier=q.multiplier,
            order_type=LIMIT if is_limit else MARKET,
            limit_price=self.limit_spin.value() if is_limit else 0.0)
        merged = dict(prices)
        merged.update(self.opt_prices)
        ok, msg = eng.submit(order, q, merged, dict(self.spots))
        if not ok:
            QtWidgets.QMessageBox.warning(self, _tr("订单被拒绝"), msg)
        else:
            self.status.emit(_tr("期权 ") + msg)
        self.trades_executed.emit()
        self._refresh_positions()
        self.refresh_position_quotes()

    # ==================================================================
    # 持仓
    # ==================================================================
    def _build_positions(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        sc = Card(_tr("组合希腊字母"))
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(20)
        self.greek_labels = {}
        for i, (k, t) in enumerate([
                ("count", _tr("期权持仓")), ("value", _tr("期权市值")), ("unreal", _tr("浮动盈亏")),
                ("realized", _tr("已实现")), ("margin", _tr("占用保证金")),
                ("delta", _tr("总Delta(等效股数)")), ("theta", _tr("总Theta(每天)")),
                ("vega", _tr("总Vega")), ("expiring", _tr("7天内到期"))]):
            box = QtWidgets.QVBoxLayout()
            lt = QtWidgets.QLabel(t); lt.setObjectName("Dim")
            lv = QtWidgets.QLabel("—"); lv.setObjectName("StatValue")
            box.addWidget(lt); box.addWidget(lv)
            h = QtWidgets.QWidget(); h.setLayout(box)
            grid.addWidget(h, 0, i)
            self.greek_labels[k] = lv
        sc.vbox.addLayout(grid)
        lay.addWidget(sc)

        pc = Card(_tr("期权持仓"))
        self.pos_table = make_table(
            [_tr("合约"), _tr("方向"), _tr("张数"), _tr("成本/股"), _tr("现价"), _tr("市值"), _tr("浮动盈亏"), _tr("盈亏%"),
             "Delta", _tr("Theta/天"), _tr("内在价值"), _tr("时间价值"), _tr("剩余天数")], stretch_col=0)
        self.pos_table.itemSelectionChanged.connect(self._on_pos_select)
        pc.vbox.addWidget(self.pos_table, 1)
        row = QtWidgets.QHBoxLayout()
        b1 = QtWidgets.QPushButton(_tr("平掉选中持仓"))
        b1.setObjectName("Danger")
        b1.clicked.connect(self._close_selected)
        row.addWidget(b1)
        b2 = QtWidgets.QPushButton(_tr("刷新报价"))
        b2.clicked.connect(self.refresh_position_quotes)
        row.addWidget(b2)
        b3 = QtWidgets.QPushButton(_tr("立即处理到期合约"))
        b3.setToolTip(_tr("正常情况下会自动处理; 这里可以手动触发一次"))
        b3.clicked.connect(lambda: self.process_expirations(force=True))
        row.addWidget(b3)
        row.addStretch(1)
        self.pos_status = QtWidgets.QLabel("")
        self.pos_status.setObjectName("Dim")
        row.addWidget(self.pos_status)
        pc.vbox.addLayout(row)
        lay.addWidget(pc, 2)

        tc = Card(_tr("期权成交与到期记录"))
        self.trade_table = make_table(
            [_tr("时间"), _tr("合约"), _tr("操作"), _tr("张数"), _tr("价格"), _tr("金额"), _tr("佣金"), _tr("已实现盈亏"), _tr("备注")],
            stretch_col=1)
        tc.vbox.addWidget(self.trade_table, 1)
        lay.addWidget(tc, 1)
        return w

    def _on_pos_select(self):
        r = self.pos_table.currentRow()
        syms = getattr(self, "_pos_symbols", [])
        if not (0 <= r < len(syms)):
            return
        acc, eng, _, _ = self.get_context()
        pos = acc.option_positions.get(syms[r])
        if not pos:
            return
        px = self.opt_prices.get(pos.symbol, pos.avg_cost)
        spot = self.spots.get(pos.underlying, 0.0)
        if spot <= 0:
            return
        legs = [{"right": pos.right, "strike": pos.strike, "qty": pos.qty,
                 "premium": pos.avg_cost, "multiplier": pos.multiplier}]
        self.mini_payoff.set_legs(legs, spot, 0.0, pos.days_left())

    def _refresh_positions(self):
        acc, eng, _, prices = self.get_context()
        merged = dict(prices)
        merged.update(self.opt_prices)
        rows = []
        self._pos_symbols = []
        tot_delta = tot_theta = tot_vega = 0.0
        expiring = 0
        for pos in sorted(acc.open_option_positions(), key=lambda p: (p.expiry, p.strike)):
            px = self.opt_prices.get(pos.symbol, pos.avg_cost)
            spot = self.spots.get(pos.underlying, 0.0)
            days = pos.days_left()
            T = max(days, 0) / 365.0
            un = pos.unrealized(px)
            intr = pos.intrinsic_value(spot) if spot else 0.0
            tv = max(px - intr, 0.0)
            iv = 0.0
            g = {}
            if spot > 0 and T > 0 and px > 0:
                iv = pr.implied_vol(px, spot, pos.strike, T, pos.right)
                if iv > 0:
                    g = pr.greeks(spot, pos.strike, T, iv, pos.right)
                    tot_delta += g["delta"] * pos.qty * pos.multiplier
                    tot_theta += g["theta"] * pos.qty * pos.multiplier
                    tot_vega += g["vega"] * pos.qty * pos.multiplier
            if days <= 7:
                expiring += 1
            col = theme.pnl_color(un)
            self._pos_symbols.append(pos.symbol)
            rows.append([
                cell("{} {} {:g}{}".format(pos.underlying, pos.expiry, pos.strike,
                                           "C" if pos.right == CALL else "P"),
                     theme.TEXT, LEFT, bold=True),
                cell(_tr("买方") if pos.qty > 0 else _tr("卖方"),
                     theme.up_color() if pos.qty > 0 else theme.down_color(), CENTER),
                cell("{:+d}".format(pos.qty), None, RIGHT),
                cell("{:.3f}".format(pos.avg_cost), None, RIGHT),
                cell("{:.2f}".format(px), None, RIGHT),
                cell(theme.money(pos.market_value(px)), None, RIGHT),
                cell(theme.signed_money(un), col, RIGHT, bold=True),
                cell(theme.signed_pct(pos.unrealized_pct(px)), col, RIGHT),
                cell("{:+.3f}".format(g.get("delta", 0) * pos.qty) if g else "—",
                     theme.TEXT_DIM, RIGHT),
                cell("{:+.2f}".format(g.get("theta", 0) * pos.qty * pos.multiplier)
                     if g else "—", theme.TEXT_DIM, RIGHT),
                cell("{:.2f}".format(intr), theme.TEXT_DIM, RIGHT),
                cell("{:.2f}".format(tv), theme.TEXT_DIM, RIGHT),
                cell(str(days), theme.GOLD if days <= 7 else theme.TEXT_DIM, RIGHT),
            ])
        fill_table(self.pos_table, rows)

        st = eng.stats(merged, self.spots)
        vals = {
            "count": (str(st["positions"]), None),
            "value": (theme.money(st["market_value"]), None),
            "unreal": (theme.signed_money(st["unrealized"]), theme.pnl_color(st["unrealized"])),
            "realized": (theme.signed_money(st["realized"]), theme.pnl_color(st["realized"])),
            "margin": (theme.money(st["margin_used"]), theme.GOLD if st["margin_used"] else None),
            "delta": ("{:+,.0f}".format(tot_delta), theme.pnl_color(tot_delta)),
            "theta": (theme.signed_money(tot_theta), theme.pnl_color(tot_theta)),
            "vega": ("{:+,.1f}".format(tot_vega), None),
            "expiring": (str(expiring), theme.GOLD if expiring else None),
        }
        for k, (t, c) in vals.items():
            lab = self.greek_labels[k]
            lab.setText(t)
            lab.setStyleSheet("color: {};".format(c) if c else "")

        trows = []
        for t in sorted(acc.option_trades, key=lambda x: -x.ts)[:300]:
            col = theme.up_color() if t.side in (BUY_OPEN, BUY_CLOSE) else theme.down_color()
            trows.append([
                cell(datetime.fromtimestamp(t.ts).strftime("%m-%d %H:%M:%S"), theme.TEXT_DIM),
                cell("{} {} {:g}{}".format(t.underlying, t.expiry, t.strike,
                                           "C" if t.right == CALL else "P"),
                     theme.TEXT, LEFT, bold=True),
                cell(OPT_SIDE_CN.get(t.side, t.side), col, CENTER),
                cell(str(t.qty), None, RIGHT),
                cell("{:.3f}".format(t.price), None, RIGHT),
                cell(theme.money(t.notional), None, RIGHT),
                cell("{:.2f}".format(t.commission), theme.TEXT_DIM, RIGHT),
                cell(theme.signed_money(t.realized_pnl),
                     theme.pnl_color(t.realized_pnl), RIGHT, bold=True),
                cell(t.note, theme.TEXT_DIM),
            ])
        fill_table(self.trade_table, trows)

    def _close_selected(self):
        r = self.pos_table.currentRow()
        syms = getattr(self, "_pos_symbols", [])
        if not (0 <= r < len(syms)):
            QtWidgets.QMessageBox.information(self, _tr("提示"), _tr("请先选中一行持仓。"))
            return
        acc, eng, _, prices = self.get_context()
        pos = acc.option_positions.get(syms[r])
        if not pos or pos.qty == 0:
            return
        q = self.by_symbol.get(pos.symbol) or self.source.quote(pos.symbol)
        if not q:
            QtWidgets.QMessageBox.warning(self, _tr("无报价"), _tr("拿不到该合约的报价, 无法平仓。"))
            return
        side = SELL_CLOSE if pos.qty > 0 else BUY_CLOSE
        if QtWidgets.QMessageBox.question(
                self, _tr("确认平仓"), _tr("按市价{} {} 张 {}?").format(
                    OPT_SIDE_CN[side], pos.abs_qty, pos.symbol)
        ) != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        order = OptionOrder(symbol=pos.symbol, side=side, qty=pos.abs_qty,
                            underlying=pos.underlying, right=pos.right,
                            strike=pos.strike, expiry=pos.expiry,
                            multiplier=pos.multiplier, order_type=MARKET)
        merged = dict(prices)
        merged.update(self.opt_prices)
        ok, msg = eng.submit(order, q, merged, dict(self.spots))
        self.status.emit(_tr("期权 ") + msg)
        if not ok:
            QtWidgets.QMessageBox.warning(self, _tr("平仓失败"), msg)
        self.trades_executed.emit()
        self._refresh_positions()

    # ------------------------------------------------------------------
    def refresh_position_quotes(self):
        acc, eng, _, _ = self.get_context()
        syms = [p.symbol for p in acc.open_option_positions()]
        unds = sorted({p.underlying for p in acc.open_option_positions()})
        if not syms:
            self._refresh_positions()
            return
        self.pos_worker.start_job(syms, unds)

    def _on_position_quotes(self, quotes: dict, spots: dict):
        for s, q in quotes.items():
            self.opt_prices[s] = q.mid
            self.by_symbol[s] = q
        self.spots.update({k: v for k, v in spots.items() if v > 0})
        self.prices_updated.emit(dict(self.opt_prices, **self.spots))
        self._refresh_positions()
        self.process_expirations()

    def process_expirations(self, force: bool = False):
        acc, eng, _, _ = self.get_context()
        if not acc.open_option_positions():
            return
        logs = eng.process_expirations(dict(self.spots), force=force)
        if logs:
            for l in logs:
                self.status.emit(_tr("期权到期: ") + l)
            QtWidgets.QMessageBox.information(self, _tr("期权到期处理"), "\n".join(logs[:10]))
            self.trades_executed.emit()
            self._refresh_positions()

    # ==================================================================
    # 组合构建
    # ==================================================================
    def _build_combo(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        root = QtWidgets.QHBoxLayout(w)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        side = Card(_tr("策略构建"))
        side.setMaximumWidth(360)
        side.setMinimumWidth(330)
        tip = QtWidgets.QLabel(
            _tr("选一个预设结构, 系统会按当前期权链自动挑行权价; "
            "也可以在下面的腿列表里手动改。"))
        tip.setObjectName("Dim")
        tip.setWordWrap(True)
        side.vbox.addWidget(tip)

        self.preset_combo = QtWidgets.QComboBox()
        for label, key in PRESETS:
            self.preset_combo.addItem(label, key)
        side.vbox.addWidget(self.preset_combo)

        form = QtWidgets.QFormLayout()
        form.setSpacing(6)
        self.combo_qty = QtWidgets.QSpinBox()
        self.combo_qty.setRange(1, 1000)
        self.combo_qty.setValue(1)
        form.addRow(_tr("组数"), self.combo_qty)
        self.combo_width = QtWidgets.QSpinBox()
        self.combo_width.setRange(1, 50)
        self.combo_width.setValue(5)
        self.combo_width.setToolTip(_tr("价差/铁鹰两腿之间隔几档行权价"))
        form.addRow(_tr("价差宽度(档)"), self.combo_width)
        side.vbox.addLayout(form)

        b = QtWidgets.QPushButton(_tr("按当前期权链生成"))
        b.setObjectName("Primary")
        b.clicked.connect(self._build_preset)
        side.vbox.addWidget(b)

        side.vbox.addWidget(QtWidgets.QLabel(_tr("腿")))
        self.leg_table = make_table([_tr("合约"), _tr("方向"), _tr("张数"), _tr("价格")], stretch_col=0)
        self.leg_table.setMaximumHeight(150)
        side.vbox.addWidget(self.leg_table)
        brow = QtWidgets.QHBoxLayout()
        b1 = QtWidgets.QPushButton(_tr("把选中合约加为一腿"))
        b1.clicked.connect(lambda: self._add_leg(+1))
        brow.addWidget(b1)
        b2 = QtWidgets.QPushButton(_tr("加为卖出腿"))
        b2.clicked.connect(lambda: self._add_leg(-1))
        brow.addWidget(b2)
        side.vbox.addLayout(brow)
        brow2 = QtWidgets.QHBoxLayout()
        b3 = QtWidgets.QPushButton(_tr("删除选中腿"))
        b3.clicked.connect(self._remove_leg)
        brow2.addWidget(b3)
        b4 = QtWidgets.QPushButton(_tr("清空"))
        b4.clicked.connect(self._clear_legs)
        brow2.addWidget(b4)
        side.vbox.addLayout(brow2)

        self.combo_metrics = QtWidgets.QLabel("")
        self.combo_metrics.setWordWrap(True)
        side.vbox.addWidget(self.combo_metrics)

        self.btn_combo_submit = QtWidgets.QPushButton(_tr("一次性下单全部腿"))
        self.btn_combo_submit.setObjectName("Primary")
        self.btn_combo_submit.setMinimumHeight(34)
        self.btn_combo_submit.clicked.connect(self._submit_combo)
        side.vbox.addWidget(self.btn_combo_submit)
        side.vbox.addStretch(1)
        root.addWidget(side)

        card = Card(_tr("到期损益图"))
        self.combo_payoff = PayoffChart()
        card.vbox.addWidget(self.combo_payoff, 1)
        root.addWidget(card, 1)

        self.legs: list = []
        return w

    def _leg_quote(self, right: str, strike: float):
        return next((q for q in self.quotes
                     if q.right == right and abs(q.strike - strike) < 1e-9), None)

    def _nearest_strike(self, right: str, target: float):
        cands = [q for q in self.quotes if q.right == right]
        if not cands:
            return None
        return min(cands, key=lambda q: abs(q.strike - target))

    def _build_preset(self):
        if not self.quotes or self.spot <= 0:
            QtWidgets.QMessageBox.information(self, _tr("提示"), _tr("先在【期权链】里加载一个标的。"))
            return
        key = self.preset_combo.currentData()
        n = self.combo_qty.value()
        strikes = sorted({q.strike for q in self.quotes})
        if not strikes:
            return
        atm = min(strikes, key=lambda k: abs(k - self.spot))
        i = strikes.index(atm)
        w = self.combo_width.value()

        def s(off):
            return strikes[max(0, min(len(strikes) - 1, i + off))]

        self.legs = []
        recipe = {
            "long_call":    [(CALL, atm, +n)],
            "long_put":     [(PUT, atm, +n)],
            "short_put":    [(PUT, s(-w), -n)],
            "covered_call": [(CALL, s(w), -n)],
            "bull_call":    [(CALL, atm, +n), (CALL, s(w), -n)],
            "bear_put":     [(PUT, atm, +n), (PUT, s(-w), -n)],
            "straddle":     [(CALL, atm, +n), (PUT, atm, +n)],
            "strangle":     [(CALL, s(w), +n), (PUT, s(-w), +n)],
            "iron_condor":  [(PUT, s(-2 * w), +n), (PUT, s(-w), -n),
                             (CALL, s(w), -n), (CALL, s(2 * w), +n)],
        }.get(key, [])
        for right, strike, qty in recipe:
            q = self._leg_quote(right, strike) or self._nearest_strike(right, strike)
            if q:
                self.legs.append({"quote": q, "qty": qty})
        if key == "covered_call":
            self.legs.append({"quote": None, "qty": n * 100, "stock": True})
        self._render_legs()

    def _add_leg(self, direction: int):
        if not self.selected:
            QtWidgets.QMessageBox.information(self, _tr("提示"), _tr("先在【期权链】里双击选中一个合约。"))
            return
        self.legs.append({"quote": self.selected, "qty": direction * self.combo_qty.value()})
        self._render_legs()

    def _remove_leg(self):
        r = self.leg_table.currentRow()
        if 0 <= r < len(self.legs):
            del self.legs[r]
            self._render_legs()

    def _clear_legs(self):
        self.legs = []
        self._render_legs()

    def _render_legs(self):
        rows = []
        for leg in self.legs:
            q = leg.get("quote")
            qty = leg["qty"]
            if leg.get("stock"):
                rows.append([
                    cell(_tr("{} 正股").format(self.underlying), theme.TEXT, LEFT, bold=True),
                    cell(_tr("买入"), theme.up_color(), CENTER),
                    cell(_tr("{:,} 股").format(qty), None, RIGHT),
                    cell("{:.2f}".format(self.spot), None, RIGHT)])
                continue
            px = q.fill_price(BUY_OPEN if qty > 0 else SELL_OPEN)
            rows.append([
                cell("{} {:g}{}".format(q.expiry, q.strike,
                                        "C" if q.right == CALL else "P"),
                     theme.TEXT, LEFT, bold=True),
                cell(_tr("买入") if qty > 0 else _tr("卖出"),
                     theme.up_color() if qty > 0 else theme.down_color(), CENTER),
                cell("{:+d}".format(qty), None, RIGHT),
                cell("{:.2f}".format(px), None, RIGHT)])
        fill_table(self.leg_table, rows)
        self._update_combo_payoff()

    def _update_combo_payoff(self):
        if not self.legs or self.spot <= 0:
            self.combo_payoff.clear()
            self.combo_metrics.setText("")
            return
        pl = []
        net = 0.0
        days = 0
        iv = 0.0
        for leg in self.legs:
            qty = leg["qty"]
            if leg.get("stock"):
                pl.append({"right": "S", "strike": self.spot, "qty": qty,
                           "premium": 0.0, "multiplier": 1})
                net -= qty * self.spot
                continue
            q = leg["quote"]
            px = q.fill_price(BUY_OPEN if qty > 0 else SELL_OPEN)
            pl.append({"right": q.right, "strike": q.strike, "qty": qty,
                       "premium": px, "multiplier": q.multiplier, "iv": q.iv})
            net -= qty * px * q.multiplier
            days = max(days, (q.expiry - date.today()).days)
            iv = max(iv, q.iv)
        info = self.combo_payoff.set_legs(pl, self.spot, iv, days)
        if not info:
            return
        mx, mn = info["max_profit"], info["max_loss"]
        bes = info["breakevens"]
        self.combo_metrics.setText(
            _tr("{} <b>{}</b><br>"
            '最大盈利 <span style="color:{}">{}</span>{}<br>'
            '最大亏损 <span style="color:{}">{}</span>{}<br>'
            "盈亏平衡 {}<br>剩余 {} 天").format(
                _tr("净支出") if net < 0 else _tr("净收入"), theme.money(abs(net)),
                theme.up_color(), theme.money(mx),
                _tr("（区间外还会继续涨）") if info["unlimited_up"] else "",
                theme.down_color(), theme.money(abs(mn)),
                _tr("（理论无下限）") if info["unlimited_down"] else "",
                " / ".join("{:.2f}".format(b) for b in bes) or "—", max(days, 0)))

    def _submit_combo(self):
        if not self.legs:
            return
        acc, eng, _, prices = self.get_context()
        opts = [l for l in self.legs if not l.get("stock")]
        stock_legs = [l for l in self.legs if l.get("stock")]
        if stock_legs:
            QtWidgets.QMessageBox.information(
                self, _tr("提示"),
                _tr("这个结构包含正股腿。请先到【交易】页买入 {} 股 {}，再回来下期权腿。").format(
                    sum(l["qty"] for l in stock_legs), self.underlying))
        lines = []
        for l in opts:
            q = l["quote"]
            lines.append(_tr("{} {} 张 {} {:g}{}").format(
                _tr("买入") if l["qty"] > 0 else _tr("卖出"), abs(l["qty"]),
                q.expiry, q.strike, "C" if q.right == CALL else "P"))
        if QtWidgets.QMessageBox.question(
                self, _tr("确认下单"), _tr("按市价执行以下 {} 条腿:\n\n{}").format(
                    len(opts), "\n".join(lines))
        ) != QtWidgets.QMessageBox.StandardButton.Yes:
            return

        merged = dict(prices)
        merged.update(self.opt_prices)
        done, errs = 0, []
        # 先建卖方腿会释放保证金空间? 反之买方腿先建更安全: 先买后卖
        for l in sorted(opts, key=lambda x: -x["qty"]):
            q = l["quote"]
            pos = eng.position(q.symbol)
            if l["qty"] > 0:
                side = BUY_CLOSE if pos.qty < 0 else BUY_OPEN
            else:
                side = SELL_CLOSE if pos.qty > 0 else SELL_OPEN
            order = OptionOrder(symbol=q.symbol, side=side, qty=abs(l["qty"]),
                                underlying=q.underlying, right=q.right, strike=q.strike,
                                expiry=q.expiry.isoformat(), multiplier=q.multiplier,
                                order_type=MARKET)
            ok, msg = eng.submit(order, q, merged, dict(self.spots))
            if ok:
                done += 1
            else:
                errs.append("{:g}{}: {}".format(
                    q.strike, "C" if q.right == CALL else "P", msg))
        self.status.emit(_tr("组合下单: 成功 {} 条腿").format(done))
        self.trades_executed.emit()
        self._refresh_positions()
        if errs:
            QtWidgets.QMessageBox.warning(self, _tr("部分腿未成交"), "\n".join(errs[:6]))

    # ==================================================================
    def _on_inner_tab(self, idx: int):
        if idx == 1:
            self.refresh_position_quotes()
        elif idx == 2:
            self._update_combo_payoff()

    def refresh(self):
        self._refresh_positions()

    def stop(self):
        self.pos_timer.stop()
        for w in (self.worker, self.pos_worker):
            if w.isRunning():
                w.wait(1500)
