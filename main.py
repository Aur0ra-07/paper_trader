"""Paper Trader — 美股模拟交易终端。

真实行情 (Yahoo Finance 公开接口) + 虚拟资金, 不接入任何真实券商。
运行: python main.py
"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6 import QtCore, QtGui, QtWidgets   # noqa: E402

from pt.ui import theme                       # noqa: E402
from pt.ui.main_window import MainWindow      # noqa: E402


def _dark_palette() -> QtGui.QPalette:
    p = QtGui.QPalette()
    C = QtGui.QPalette.ColorRole
    p.setColor(C.Window, QtGui.QColor(theme.BG))
    p.setColor(C.WindowText, QtGui.QColor(theme.TEXT))
    p.setColor(C.Base, QtGui.QColor(theme.BG_ALT))
    p.setColor(C.AlternateBase, QtGui.QColor(theme.PANEL))
    p.setColor(C.Text, QtGui.QColor(theme.TEXT))
    p.setColor(C.Button, QtGui.QColor(theme.BG_ALT))
    p.setColor(C.ButtonText, QtGui.QColor(theme.TEXT))
    p.setColor(C.Highlight, QtGui.QColor(theme.ACCENT))
    p.setColor(C.HighlightedText, QtGui.QColor("#ffffff"))
    p.setColor(C.ToolTipBase, QtGui.QColor(theme.PANEL))
    p.setColor(C.ToolTipText, QtGui.QColor(theme.TEXT))
    return p


def _excepthook(etype, value, tb) -> None:
    """未捕获异常的兜底。

    注意 sys.stderr 可能是 None —— pythonw 启动和 PyInstaller --windowed
    打包出来的程序都没有标准错误流。直接 .write() 会让异常处理器自己先崩,
    结果就是用户看到程序无声闪退。所以这里全部包起来, 并额外落一份日志,
    否则打包版出问题就彻底无从查起。
    """
    msg = "".join(traceback.format_exception(etype, value, tb))
    try:
        if sys.stderr is not None:
            sys.stderr.write(msg)
    except Exception:
        pass
    path = ""
    try:
        from pt.config import DATA_DIR
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "错误日志.txt")
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n===== {} =====\n{}".format(
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        path = ""
    try:
        tail = msg[-1800:]
        if path:
            tail += "\n\n（完整记录已保存到 {}）".format(path)
        QtWidgets.QMessageBox.critical(None, "程序错误", tail)
    except Exception:
        pass


def main() -> int:
    QtWidgets.QApplication.setHighDpiScaleFactorRoundingPolicy(
        QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Paper Trader")
    app.setStyle("Fusion")
    app.setPalette(_dark_palette())
    app.setStyleSheet(theme.QSS)

    sys.excepthook = _excepthook

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
