"""QThread-воркеры для тяжёлых операций, чтобы не морозить GUI."""
from PySide6.QtCore import QObject, Signal, QRunnable, QThreadPool


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


def run_in_background(fn, *args, on_finished=None, on_error=None, **kwargs):
    """Запускает fn в пуле потоков. Возвращает Worker."""
    worker = Worker(fn, *args, **kwargs)
    if on_finished:
        worker.signals.finished.connect(on_finished)
    if on_error:
        worker.signals.error.connect(on_error)
    QThreadPool.globalInstance().start(worker)
    return worker
