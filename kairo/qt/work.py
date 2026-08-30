"""Running backend calls off the UI thread.

The backend already has cancellation - ``kairo.tasks.CancelToken`` - and it is
toolkit-agnostic, so it carries straight over. What changes is only how results
get back: Qt signals rather than ``after(0, ...)``, which removes a whole class
of mistake, since a signal delivered to a destroyed object is simply dropped
instead of raising.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot


# A private pool makes Kairo's lifetime explicit. The global pool can still be
# running while QApplication and Shiboken tear down, which is exactly where the
# live crash occurred.
_POOL: QThreadPool | None = None
_LIVE_JOBS: set["Job"] = set()


def _pool() -> QThreadPool:
    global _POOL
    if _POOL is None:
        _POOL = QThreadPool()
    return _POOL


class Signals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(object)
    finished = Signal()


class Streamer(QObject):
    """Posts items from a pool thread to the UI thread, one at a time.

    Qt queues a signal emitted across threads, so a worker can hand over each
    preview as it arrives without any marshalling helper - and a signal
    delivered to a destroyed receiver is dropped rather than raising, which is
    the failure mode the Tk build kept hitting with after().
    """

    item = Signal(int, object, str)


class Job(QRunnable):
    """Call ``function`` on a pool thread and report back on the main one."""

    def __init__(self, function, *args, **kwargs):
        super().__init__()
        self.signals = Signals()
        self._function = function
        self._args = args
        self._kwargs = kwargs
        self._release_callback = None
        # A Job owns a PySide QObject. Auto-delete would destroy that QObject
        # on the pool thread and race Shiboken's GUI-thread reference handling.
        self.setAutoDelete(False)

    @Slot()
    def run(self):
        try:
            result = self._function(*self._args, **self._kwargs)
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        else:
            self.signals.done.emit(result)
        finally:
            self.signals.finished.emit()


def _release(job: Job) -> None:
    """Drop the runnable and its QObject on the GUI thread only."""
    callback = job._release_callback
    if callback is not None:
        try:
            job.signals.finished.disconnect(callback)
        except (RuntimeError, TypeError):
            pass
    job._release_callback = None
    job._function = None
    job._args = ()
    job._kwargs = {}
    _LIVE_JOBS.discard(job)


def submit(function, *args, on_done=None, on_failed=None, on_progress=None,
           **kwargs) -> Job:
    job = Job(function, *args, **kwargs)
    if on_done is not None:
        job.signals.done.connect(on_done, Qt.QueuedConnection)
    if on_failed is not None:
        job.signals.failed.connect(on_failed, Qt.QueuedConnection)
    if on_progress is not None:
        job.signals.progress.connect(on_progress, Qt.QueuedConnection)

    callback = lambda current=job: _release(current)
    job._release_callback = callback
    job.signals.finished.connect(callback, Qt.QueuedConnection)
    _LIVE_JOBS.add(job)
    _pool().start(job)
    return job


def is_idle() -> bool:
    """True only after workers and their queued GUI cleanup have finished."""
    return (_POOL is None or _POOL.activeThreadCount() == 0) and not _LIVE_JOBS
