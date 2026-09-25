"""账户管理对话框。

危险操作 (重置 / 删除) 全部挪到这里, 不再放在工具栏上一点就中;
并且要求手动输入账户名确认, 默认按钮是取消, 执行前自动备份。
"""
from __future__ import annotations

import os
import time
from datetime import datetime

from PyQt6 import QtCore, QtGui, QtWidgets

from .. import storage
from ..models import Account
from . import theme
from .panels import Card, NumItem, make_table, cell, fill_table, LEFT, RIGHT, CENTER


class ConfirmTypeDialog(QtWidgets.QDialog):
    """要求原样输入某段文字才能确认的对话框 —— 防手滑。"""

    def __init__(self, title: str, message: str, phrase: str,
                 danger_label: str = "确认执行", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(430)
        self.phrase = phrase

        lay = QtWidgets.QVBoxLayout(self)
        lay.setSpacing(12)

        msg = QtWidgets.QLabel(message)
        msg.setWordWrap(True)
        lay.addWidget(msg)

        hint = QtWidgets.QLabel(
            "请输入 <b style='color:{}'>{}</b> 以确认：".format(theme.GOLD, phrase))
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.edit = QtWidgets.QLineEdit()
        self.edit.setPlaceholderText(phrase)
        self.edit.textChanged.connect(self._check)
        lay.addWidget(self.edit)

        note = QtWidgets.QLabel("执行前会自动备份一份快照，在【账户管理 → 备份】里可以找回。")
        note.setObjectName("Dim")
        note.setWordWrap(True)
        lay.addWidget(note)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        cancel = QtWidgets.QPushButton("取消")
        cancel.setDefault(True)
        cancel.setAutoDefault(True)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        self.ok = QtWidgets.QPushButton(danger_label)
        self.ok.setObjectName("Danger")
        self.ok.setEnabled(False)
        self.ok.setAutoDefault(False)
        self.ok.clicked.connect(self.accept)
        row.addWidget(self.ok)
        lay.addLayout(row)

    def _check(self, text: str):
        self.ok.setEnabled(text.strip() == self.phrase)


class AccountEditDialog(QtWidgets.QDialog):
    """新建 / 编辑账户。"""

    def __init__(self, acc: Account | None, default_cash: float, parent=None):
        super().__init__(parent)
        self.acc = acc
        self.setWindowTitle("编辑账户" if acc else "新建模拟账户")
        self.setMinimumWidth(400)

        form = QtWidgets.QFormLayout(self)
        form.setSpacing(10)

        self.name = QtWidgets.QLineEdit(acc.name if acc else "模拟账户")
        form.addRow("账户名称", self.name)

        self.cash = QtWidgets.QDoubleSpinBox()
        self.cash.setRange(1000, 100_000_000)
        self.cash.setDecimals(0)
        self.cash.setSingleStep(10000)
        self.cash.setPrefix("$ ")
        self.cash.setGroupSeparatorShown(True)
        self.cash.setValue(acc.initial_cash if acc else default_cash)
        form.addRow("初始资金", self.cash)

        self.type = QtWidgets.QComboBox()
        self.type.addItem("保证金账户 (2倍购买力, 可做空)", "MARGIN")
        self.type.addItem("现金账户 (无杠杆, 不可做空)", "CASH")
        if acc:
            i = self.type.findData(acc.account_type)
            self.type.setCurrentIndex(max(i, 0))
        form.addRow("账户类型", self.type)

        if acc:
            note = QtWidgets.QLabel(
                "改「初始资金」只会改变收益率的计算基准，不会往账户里打钱，也不会动持仓。")
            note.setObjectName("Dim")
            note.setWordWrap(True)
            form.addRow("", note)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def values(self) -> tuple:
        return (self.name.text().strip() or "模拟账户",
                float(self.cash.value()),
                self.type.currentData())


class AccountManagerDialog(QtWidgets.QDialog):
    """账户总览 + 所有账户操作。"""

    def __init__(self, current_id: str, prices: dict, default_cash: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle("账户管理")
        self.resize(920, 560)
        self.prices = prices or {}
        self.default_cash = default_cash
        self.current_id = current_id
        self.switch_to: str | None = None      # 关闭后主窗口要切到哪个账户
        self.changed = False

        lay = QtWidgets.QVBoxLayout(self)
        lay.setSpacing(10)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._build_accounts(), "账户")
        self.tabs.addTab(self._build_backups(), "备份")
        lay.addWidget(self.tabs, 1)

        close = QtWidgets.QPushButton("关闭")
        close.clicked.connect(self.accept)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)

        self._refresh()

    # ------------------------------------------------------------------
    def _build_accounts(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(8)

        self.table = make_table(
            ["", "账户名称", "类型", "初始资金", "总资产", "总盈亏", "收益率",
             "持仓", "成交", "创建于"], stretch_col=1)
        self.table.doubleClicked.connect(self._switch)
        lay.addWidget(self.table, 1)

        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(6)
        for label, slot, obj in (
                ("切换到选中账户", self._switch, "Primary"),
                ("新建账户", self._new, None),
                ("重命名 / 修改", self._edit, None),
                ("复制一份", self._duplicate, None),
                ("导出 JSON", self._export, None)):
            b = QtWidgets.QPushButton(label)
            if obj:
                b.setObjectName(obj)
            b.clicked.connect(slot)
            row1.addWidget(b)
        row1.addStretch(1)
        lay.addLayout(row1)

        danger = Card("危险操作")
        danger.setStyleSheet("QFrame#Card { border-color: #7f1d1d; }")
        drow = QtWidgets.QHBoxLayout()
        d1 = QtWidgets.QPushButton("重置选中账户…")
        d1.setObjectName("Danger")
        d1.clicked.connect(self._reset)
        drow.addWidget(d1)
        d2 = QtWidgets.QPushButton("删除选中账户…")
        d2.setObjectName("Danger")
        d2.clicked.connect(self._delete)
        drow.addWidget(d2)
        drow.addStretch(1)
        note = QtWidgets.QLabel("两个操作都需要手动输入账户名确认，并会先自动备份。")
        note.setObjectName("Dim")
        drow.addWidget(note)
        danger.vbox.addLayout(drow)
        lay.addWidget(danger)
        return w

    def _build_backups(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(8)

        tip = QtWidgets.QLabel(
            "每次重置或删除账户前都会自动存一份快照到这里（最多保留 60 份）。"
            "选中一份可以恢复成一个<b>新账户</b>，不会覆盖现有账户。")
        tip.setObjectName("Dim")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        self.bk_table = make_table(["备份时间", "账户名称", "内容", "文件"], stretch_col=2)
        lay.addWidget(self.bk_table, 1)

        row = QtWidgets.QHBoxLayout()
        b1 = QtWidgets.QPushButton("恢复为新账户")
        b1.setObjectName("Primary")
        b1.clicked.connect(self._restore)
        row.addWidget(b1)
        b2 = QtWidgets.QPushButton("打开备份文件夹")
        b2.clicked.connect(self._open_backup_dir)
        row.addWidget(b2)
        b3 = QtWidgets.QPushButton("刷新")
        b3.clicked.connect(self._refresh_backups)
        row.addWidget(b3)
        row.addStretch(1)
        lay.addLayout(row)
        return w

    # ------------------------------------------------------------------
    def _refresh(self):
        self.accounts = storage.list_accounts()
        rows = []
        for a in self.accounts:
            eq = a.equity(self.prices)
            pnl = eq - a.initial_cash
            ret = (pnl / a.initial_cash * 100.0) if a.initial_cash else 0.0
            is_cur = a.id == self.current_id
            rows.append([
                cell("●" if is_cur else "", theme.ACCENT, CENTER),
                cell(a.name + ("  (当前)" if is_cur else ""),
                     theme.ACCENT if is_cur else theme.TEXT, LEFT, bold=is_cur),
                cell("保证金" if a.account_type == "MARGIN" else "现金",
                     theme.TEXT_DIM, CENTER),
                cell(theme.money(a.initial_cash, 0), None, RIGHT),
                cell(theme.money(eq), None, RIGHT),
                cell(theme.signed_money(pnl), theme.pnl_color(pnl), RIGHT),
                cell(theme.signed_pct(ret), theme.pnl_color(ret), RIGHT, bold=True),
                cell(str(len(a.open_positions())), None, RIGHT),
                cell(str(len(a.trades)), None, RIGHT),
                cell(datetime.fromtimestamp(a.created_at).strftime("%Y-%m-%d"),
                     theme.TEXT_DIM, CENTER),
            ])
        fill_table(self.table, rows)
        for i, a in enumerate(self.accounts):
            if a.id == self.current_id:
                self.table.selectRow(i)
                break
        self._refresh_backups()

    def _refresh_backups(self):
        rows = []
        self.backups = storage.list_backups()
        for path, name, aid, mtime, summary in self.backups:
            rows.append([
                cell(datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
                     theme.TEXT_DIM),
                cell(name, theme.TEXT, LEFT, bold=True),
                cell(summary, theme.TEXT_DIM),
                cell(os.path.basename(path), theme.TEXT_DIM),
            ])
        fill_table(self.bk_table, rows)

    def _selected(self) -> Account | None:
        r = self.table.currentRow()
        if 0 <= r < len(self.accounts):
            return self.accounts[r]
        QtWidgets.QMessageBox.information(self, "提示", "请先在上面选中一个账户。")
        return None

    # ------------------------------------------------------------------
    def _switch(self):
        a = self._selected()
        if not a or a.id == self.current_id:
            return
        self.switch_to = a.id
        self.changed = True
        self.accept()

    def _new(self):
        dlg = AccountEditDialog(None, self.default_cash, self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        name, cash, atype = dlg.values()
        acc = Account(name=name, initial_cash=cash, cash=cash, account_type=atype)
        acc.equity_curve.append([time.time(), cash])
        storage.save_account(acc)
        self.changed = True
        self.current_id = acc.id
        self.switch_to = acc.id
        self._refresh()

    def _edit(self):
        a = self._selected()
        if not a:
            return
        dlg = AccountEditDialog(a, self.default_cash, self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        name, cash, atype = dlg.values()
        a.name, a.initial_cash, a.account_type = name, cash, atype
        storage.save_account(a)
        self.changed = True
        self._refresh()

    def _duplicate(self):
        a = self._selected()
        if not a:
            return
        import uuid
        copy = Account.from_dict(a.to_dict())
        copy.id = uuid.uuid4().hex[:10]
        copy.name = a.name + " 副本"
        copy.created_at = time.time()
        storage.save_account(copy)
        self.changed = True
        self._refresh()

    def _export(self):
        a = self._selected()
        if not a:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出账户", "{}.json".format(a.name), "JSON (*.json)")
        if not path:
            return
        try:
            storage.export_account(a, path)
            QtWidgets.QMessageBox.information(self, "已导出", path)
        except OSError as exc:
            QtWidgets.QMessageBox.warning(self, "导出失败", str(exc))

    # ------------------------------------------------------------------
    def _reset(self):
        a = self._selected()
        if not a:
            return
        dlg = ConfirmTypeDialog(
            "重置账户",
            "将清空「<b>{}</b>」的全部持仓、挂单、成交记录和净值曲线，"
            "资金恢复到 {}。<br>当前该账户有 <b>{}</b> 个持仓、<b>{}</b> 笔成交。".format(
                a.name, theme.money(a.initial_cash, 0),
                len(a.open_positions()), len(a.trades)),
            a.name, "重置账户", self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        path = storage.backup_account(a, "before-reset")
        a.cash = a.initial_cash
        a.positions.clear()
        a.orders.clear()
        a.trades.clear()
        a.equity_curve = [[time.time(), a.initial_cash]]
        storage.save_account(a)
        self.changed = True
        self._refresh()
        QtWidgets.QMessageBox.information(
            self, "已重置", "账户已重置。\n\n重置前的快照已保存：\n{}".format(os.path.basename(path)))

    def _delete(self):
        a = self._selected()
        if not a:
            return
        if len(self.accounts) <= 1:
            QtWidgets.QMessageBox.information(self, "提示", "至少要保留一个账户。")
            return
        dlg = ConfirmTypeDialog(
            "删除账户",
            "将<b>永久删除</b>账户「<b>{}</b>」及其全部记录"
            "（{} 个持仓、{} 笔成交）。".format(
                a.name, len(a.open_positions()), len(a.trades)),
            a.name, "永久删除", self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        path = storage.backup_account(a, "before-delete")
        storage.delete_account(a.id)
        self.changed = True
        if a.id == self.current_id:
            remaining = storage.list_accounts()
            if remaining:
                self.current_id = remaining[0].id
                self.switch_to = remaining[0].id
        self._refresh()
        QtWidgets.QMessageBox.information(
            self, "已删除", "账户已删除。\n\n删除前的快照已保存：\n{}".format(os.path.basename(path)))

    def _restore(self):
        r = self.bk_table.currentRow()
        if not (0 <= r < len(self.backups)):
            QtWidgets.QMessageBox.information(self, "提示", "请先选中一份备份。")
            return
        path, name, aid, mtime, summary = self.backups[r]
        acc = storage.load_backup(path)
        if not acc:
            QtWidgets.QMessageBox.warning(self, "恢复失败", "这份备份读不出来。")
            return
        import uuid
        acc.id = uuid.uuid4().hex[:10]
        acc.name = "{} (恢复 {})".format(
            name, datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M"))
        storage.save_account(acc)
        self.changed = True
        self.switch_to = acc.id
        self.current_id = acc.id
        self._refresh()
        self.tabs.setCurrentIndex(0)
        QtWidgets.QMessageBox.information(
            self, "已恢复", "已恢复为新账户「{}」，原有账户没有被动过。".format(acc.name))

    def _open_backup_dir(self):
        os.makedirs(storage.BACKUP_DIR, exist_ok=True)
        try:
            os.startfile(storage.BACKUP_DIR)      # noqa: S606 (Windows)
        except Exception:
            import subprocess
            subprocess.Popen(["explorer", storage.BACKUP_DIR])
