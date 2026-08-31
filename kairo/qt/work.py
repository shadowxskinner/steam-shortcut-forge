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

    def _emit(self, signal, *args) -> bool:
        """Emit unless the receiving QObject is already gone.

        Qt drops a queued signal whose receiver has been destroyed, but
        emitting from a *deleted sender* raises RuntimeError instead. That
        happens when the application tears down while a lookup is still in
        flight, and it used to escape run() - taking the finished signal with
        it, so the job was never released and is_idle() stayed false forever.
        """
        try:
            signal.emit(*args)
            return True
        except RuntimeError:
            return False

    @Slot()
    def run(self):
        try:
            result = self._function(*self._args, **self._kwargs)
        except Exception as exc:
            self._emit(self.signals.failed, str(exc))
        else:
            self._emit(self.signals.done, result)
        finally:
            if not self._emit(self.signals.finished):
                # No GUI thread left to release this on. Drop it here so a
                # close waiting on is_idle() cannot wait forever.
                _LIVE_JOBS.discard(self)


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


def drain(seconds: float = 4.0) -> bool:
    """Block until no pool thread is still running. True if the pool emptied.

    ``is_idle`` only reports; it cannot make the process wait, and the window's
    own close already drains by polling because the GUI thread must stay
    responsive. Neither helps when the event loop ends without any window
    receiving a close at all — a session logout, a SIGTERM, Ctrl+C from the
    terminal an app was started in. The interpreter then tears down with a
    worker still inside Python, which is an intermittent segfault on exit and
    nothing else. Roughly one run in four here.

    ``waitForDone`` is the only thing that gives the C++ guarantee: it returns
    when every ``run`` has returned, not when a queued signal has been seen.
    """
    if _POOL is None:
        return True
    finished = _POOL.waitForDone(int(seconds * 1000))
    if finished:
        # Their queued release never arrives; there is no loop left to
        # deliver it, and the work itself is over.
        _LIVE_JOBS.clear()
    return finished
