"""QThread-воркеры для тяжёлых операций, чтобы не морозить GUI."""
from PySide6.QtCore import QObject, Signal, QRunnable, QThreadPool


class Cancelled(Exception):
    """Отмена длительной операции пользователем."""


class WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(str)
    progress = Signal(int)


class Worker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.signals.finished.emit(result)
        except Exception as e:
            self.signals.error.emit(str(e))


# Активные воркеры держим в реестре: выброшенный QRunnable съедается
# сборщиком мусора Python — поток молча умирает (ни finished, ни error),
# UI виснет навсегда и «лечится только перезапуском». Проверено: без ссылки
# bulk на 3000 кейсов не завершается никогда, со ссылкой — 0.01–1 с.
_ACTIVE: set = set()


def _discard(worker) -> None:
    _ACTIVE.discard(worker)


def run_in_background(fn, *args, on_finished=None, on_error=None, **kwargs):
    """Запускает fn в пуле потоков. Возвращает Worker (ссылку держит реестр)."""
    worker = Worker(fn, *args, **kwargs)
    _ACTIVE.add(worker)
    try:
        worker.signals.finished.connect(lambda _r, w=worker: _discard(w))
        worker.signals.error.connect(lambda _m, w=worker: _discard(w))
    except Exception:
        pass
    if on_finished:
        worker.signals.finished.connect(on_finished)
    if on_error:
        worker.signals.error.connect(on_error)
    QThreadPool.globalInstance().start(worker)
    return worker
