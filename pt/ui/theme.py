"""深色主题与涨跌配色。"""
from __future__ import annotations

BG = "#101418"
BG_ALT = "#161b22"
PANEL = "#1a2029"
BORDER = "#2a323d"
TEXT = "#d8dee9"
TEXT_DIM = "#8b97a8"
ACCENT = "#3b82f6"

GREEN = "#22c55e"
RED = "#ef4444"
FLAT = "#8b97a8"
GOLD = "#f0b429"

# 运行期由设置覆盖: True=欧美习惯(绿涨红跌), False=中国习惯(红涨绿跌)
_UP_IS_GREEN = True


def set_color_scheme(up_is_green: bool) -> None:
    global _UP_IS_GREEN
    _UP_IS_GREEN = bool(up_is_green)


def up_color() -> str:
    return GREEN if _UP_IS_GREEN else RED


def down_color() -> str:
    return RED if _UP_IS_GREEN else GREEN


def pnl_color(value: float) -> str:
    if value > 1e-9:
        return up_color()
    if value < -1e-9:
        return down_color()
    return FLAT


def money(v: float, dp: int = 2) -> str:
    return "${:,.{}f}".format(v, dp)


def signed_money(v: float, dp: int = 2) -> str:
    return "{}${:,.{}f}".format("+" if v > 0 else "-" if v < 0 else "", abs(v), dp)


def signed_pct(v: float, dp: int = 2) -> str:
    return "{}{:.{}f}%".format("+" if v > 0 else "", v, dp)


def _check_icon() -> str:
    """生成一个白色对勾的 PNG, 返回给 QSS 用的路径。

    为什么要自己画: QSS 一旦覆盖了 QCheckBox::indicator, Qt 就不再画原生的对勾,
    勾选与否只剩"框是深色还是蓝色"的区别 —— 一排都勾上时根本看不出状态。
    用 QImage 画 (不需要 QApplication 实例), 存到临时目录, 不额外带资源文件。
    """
    import os
    import tempfile
    path = os.path.join(tempfile.gettempdir(), "pt_check_v1.png")
    if os.path.exists(path):
        return path.replace("\\", "/")
    try:
        from PyQt6 import QtCore, QtGui
        n = 28                                   # 2 倍图, 高 DPI 下不糊
        img = QtGui.QImage(n, n, QtGui.QImage.Format.Format_ARGB32)
        img.fill(QtCore.Qt.GlobalColor.transparent)
        p = QtGui.QPainter(img)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        pen = QtGui.QPen(QtGui.QColor("#ffffff"), 3.6)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolyline(QtGui.QPolygonF([
            QtCore.QPointF(n * 0.22, n * 0.52),
            QtCore.QPointF(n * 0.42, n * 0.72),
            QtCore.QPointF(n * 0.78, n * 0.28)]))
        p.end()
        img.save(path, "PNG")
        return path.replace("\\", "/")
    except Exception:
        return ""


CHECK_ICON = _check_icon()

QSS = """
QWidget {{
    background: {bg};
    color: {text};
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 12px;
}}
QMainWindow, QDialog {{ background: {bg}; }}

QFrame#Card {{
    background: {panel};
    border: 1px solid {border};
    border-radius: 8px;
}}
QLabel#Title {{ font-size: 13px; font-weight: 600; color: {text}; }}
QLabel#Dim {{ color: {dim}; }}
QLabel#BigPrice {{ font-size: 30px; font-weight: 700; }}
QLabel#SubPrice {{ font-size: 15px; font-weight: 600; }}
QLabel#StatValue {{ font-size: 15px; font-weight: 600; }}

QTabWidget::pane {{ border: 1px solid {border}; border-radius: 6px; top: -1px; }}
QTabBar::tab {{
    background: {bgalt}; color: {dim};
    padding: 7px 18px; border: 1px solid {border};
    border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{ background: {panel}; color: {text}; border-bottom: 2px solid {accent}; }}
QTabBar::tab:hover {{ color: {text}; }}

QPushButton {{
    background: {bgalt}; border: 1px solid {border};
    border-radius: 5px; padding: 6px 12px; color: {text};
}}
QPushButton:hover {{ background: #222b36; border-color: #3b4657; }}
QPushButton:pressed {{ background: #0d1117; }}
QPushButton:disabled {{ color: #55606f; background: #141920; }}
QPushButton:checked {{ background: {accent}; border-color: {accent}; color: #fff; }}
QPushButton#Primary {{ background: {accent}; border: none; color: #fff; font-weight: 600; padding: 9px; }}
QPushButton#Primary:hover {{ background: #2f6fdc; }}
QPushButton#Danger {{ background: #b91c1c; border: none; color: #fff; font-weight: 600; }}
QPushButton#Danger:hover {{ background: #dc2626; }}
QPushButton#Link {{ background: transparent; border: none; color: {accent}; padding: 2px 6px; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {bgalt}; border: 1px solid {border};
    border-radius: 5px; padding: 6px 8px; color: {text};
    selection-background-color: {accent};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {accent}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {panel}; border: 1px solid {border};
    selection-background-color: {accent}; outline: none;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 16px; background: {panel}; border: none; }}

QTableWidget {{
    background: {bgalt}; alternate-background-color: #12171d;
    gridline-color: {border}; border: 1px solid {border}; border-radius: 6px;
    selection-background-color: #1e3a5f; selection-color: {text};
    outline: none;
}}
QTableWidget::item {{ padding: 3px 6px; }}
QHeaderView::section {{
    background: {panel}; color: {dim}; border: none;
    border-bottom: 1px solid {border}; border-right: 1px solid {border};
    padding: 6px; font-weight: 600;
}}
QTableCornerButton::section {{ background: {panel}; border: none; }}

QScrollBar:vertical {{ background: {bg}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #37414f; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: #4a5768; }}
QScrollBar:horizontal {{ background: {bg}; height: 10px; }}
QScrollBar::handle:horizontal {{ background: #37414f; border-radius: 5px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QToolBar {{ background: {bgalt}; border-bottom: 1px solid {border}; spacing: 8px; padding: 6px; }}
QStatusBar {{ background: {bgalt}; border-top: 1px solid {border}; color: {dim}; }}
QSplitter::handle {{ background: {border}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QGroupBox {{
    border: 1px solid {border}; border-radius: 6px;
    margin-top: 10px; padding-top: 10px; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {dim}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {border};
    border-radius: 3px; background: {bg}; }}
QCheckBox::indicator:hover {{ border-color: {accent}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent};
    image: url({check}); }}
QCheckBox::indicator:checked:hover {{ background: {accent}; }}
QCheckBox::indicator:disabled {{ background: {bgalt}; border-color: {border}; }}
QCheckBox::indicator:checked:disabled {{ background: {dim}; border-color: {dim};
    image: url({check}); }}
QMenu {{ background: {panel}; border: 1px solid {border}; }}
QMenu::item {{ padding: 6px 24px; }}
QMenu::item:selected {{ background: {accent}; }}
QToolTip {{ background: {panel}; color: {text}; border: 1px solid {border}; padding: 4px; }}
""".format(bg=BG, bgalt=BG_ALT, panel=PANEL, border=BORDER,
           text=TEXT, dim=TEXT_DIM, accent=ACCENT, check=CHECK_ICON)
