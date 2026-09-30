"""后台线程: 行情轮询 / K 线加载 / 代码搜索。UI 线程永不阻塞。"""
from __future__ import annotations

import queue

from PyQt6 import QtCore

from ..market import MarketData
from ..i18n import _tr


class QuoteWorker(QtCore.QThread):
    """按固定间隔批量拉取报价。"""

    quotes_ready = QtCore.pyqtSignal(dict)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, market: MarketData, interval: int = 5, parent=None):
        super().__init__(parent)
        self.market = market
        self.interval = max(2, int(interval))
        self._symbols: list[str] = []
        self._lock = QtCore.QMutex()
        self._wait = QtCore.QWaitCondition()
        self._stop = False

    def set_symbols(self, symbols) -> None:
        with QtCore.QMutexLocker(self._lock):
            self._symbols = [s.upper() for s in dict.fromkeys(symbols) if s]

    def set_interval(self, seconds: int) -> None:
        self.interval = max(2, int(seconds))
        self.poke()

    def poke(self) -> None:
        """立即触发一次拉取。"""
        self._wait.wakeAll()

    def stop(self) -> None:
        self._stop = True
        self._wait.wakeAll()

    def run(self) -> None:
        while not self._stop:
            with QtCore.QMutexLocker(self._lock):
                syms = list(self._symbols)
            if syms:
                try:
                    data = self.market.quotes(syms)
                    if data and not self._stop:
                        self.quotes_ready.emit(data)
                    elif not data:
                        self.failed.emit(_tr("行情拉取失败, 正在重试…"))
                except Exception as exc:            # 网络异常不应杀死线程
                    self.failed.emit(_tr("行情异常: {}").format(exc))
            self._lock.lock()
            self._wait.wait(self._lock, self.interval * 1000)
            self._lock.unlock()


class CandleWorker(QtCore.QThread):
    """按请求加载 K 线, 只回传最后一次请求的结果。"""

    candles_ready = QtCore.pyqtSignal(str, str, list)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, market: MarketData, parent=None):
        super().__init__(parent)
        self.market = market
        self._q: queue.Queue = queue.Queue()
        self._stop = False

    def request(self, symbol: str, interval: str, rng: str) -> None:
        self._q.put((symbol.upper(), interval, rng))

    def stop(self) -> None:
        self._stop = True
        self._q.put(None)

    def run(self) -> None:
        while not self._stop:
            item = self._q.get()
            if item is None:
                break
            # 丢弃过期请求, 只处理最新的
            while not self._q.empty():
                nxt = self._q.get_nowait()
                if nxt is None:
                    return
                item = nxt
            symbol, interval, rng = item
            try:
                data = self.market.candles(symbol, interval, rng)
                if not self._stop:
                    self.candles_ready.emit(symbol, interval, data)
            except Exception as exc:
                self.failed.emit(_tr("K线加载失败 {}: {}").format(symbol, exc))


class SearchWorker(QtCore.QThread):
    results_ready = QtCore.pyqtSignal(str, list)

    def __init__(self, market: MarketData, parent=None):
        super().__init__(parent)
        self.market = market
        self._q: queue.Queue = queue.Queue()
        self._stop = False

    def request(self, text: str) -> None:
        self._q.put(text)

    def stop(self) -> None:
        self._stop = True
        self._q.put(None)

    def run(self) -> None:
        while not self._stop:
            text = self._q.get()
            if text is None:
                break
            while not self._q.empty():
                nxt = self._q.get_nowait()
                if nxt is None:
                    return
                text = nxt
            try:
                rows = self.market.search(text)
            except Exception:
                rows = []
            if not self._stop:
                self.results_ready.emit(text, rows)
