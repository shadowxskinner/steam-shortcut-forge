"""Running backend calls off the UI thread.

The backend already has cancellation - ``kairo.tasks.CancelToken`` - and it is
toolkit-agnostic, so it carries straight over. What changes is only how results
get back: Qt signals rather than ``after(0, ...)``, which removes a whole class
of mistake, since a signal delivered to a destroyed object is simply dropped
instead of raising.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class Signals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(object)


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
        self.setAutoDelete(True)

    @Slot()
    def run(self):
        try:
            result = self._function(*self._args, **self._kwargs)
        except Exception as exc:
            self.signals.failed.emit(str(exc))
            return
        self.signals.done.emit(result)


def submit(function, *args, on_done=None, on_failed=None, on_progress=None,
           **kwargs) -> Job:
    job = Job(function, *args, **kwargs)
    if on_done is not None:
        job.signals.done.connect(on_done)
    if on_failed is not None:
        job.signals.failed.connect(on_failed)
    if on_progress is not None:
        job.signals.progress.connect(on_progress)
    QThreadPool.globalInstance().start(job)
    return job
