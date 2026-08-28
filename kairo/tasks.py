"""Cancellation and bulk-run plumbing.

Kept free of any GUI import so the behaviour that matters - that a cancelled
run stops, that one failure does not abort the rest, that the counts add up -
can be tested without a display.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


class Cancelled(Exception):
    """Raised inside a worker when its token has been cancelled."""


class Skip(Exception):
    """Raised by a worker to record an item as deliberately skipped.

    Distinct from a failure: "this app has no artwork available" is a normal
    outcome and should not be reported as something going wrong.
    """


class CancelToken:
    """A one-way flag a worker polls.

    Threads are never killed - they cooperate. Every long loop checks the
    token between items, so cancelling is immediate at item boundaries and
    never leaves a half-written file behind.
    """

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise Cancelled()


#: A token that is never cancelled, so callers need no None checks.
NULL_TOKEN = CancelToken()


class ActivityTokens:
    """One current token per named activity.

    Starting an activity cancels the previous run of the same activity. This
    is what stops a user clicking through forty applications from leaving
    forty live download loops racing each other: selecting the next app
    cancels the previous app's artwork fetch instead of merely ignoring its
    results when they eventually arrive.
    """

    def __init__(self) -> None:
        self._tokens: dict[str, CancelToken] = {}
        self._lock = threading.Lock()

    def start(self, name: str) -> CancelToken:
        with self._lock:
            previous = self._tokens.get(name)
            if previous is not None:
                previous.cancel()
            token = CancelToken()
            self._tokens[name] = token
            return token

    def current(self, name: str) -> CancelToken | None:
        with self._lock:
            return self._tokens.get(name)

    def is_current(self, name: str, token: CancelToken) -> bool:
        with self._lock:
            return self._tokens.get(name) is token

    def cancel(self, name: str) -> None:
        with self._lock:
            token = self._tokens.get(name)
        if token is not None:
            token.cancel()

    def cancel_all(self) -> None:
        with self._lock:
            tokens = list(self._tokens.values())
        for token in tokens:
            token.cancel()


@dataclass
class BulkSummary:
    total: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    cancelled: bool = False
    processed: int = 0
    failures: list[str] = field(default_factory=list)
    skips: list[str] = field(default_factory=list)

    @property
    def remaining(self) -> int:
        return max(0, self.total - self.processed)

    def describe(self) -> str:
        if self.cancelled:
            head = f"Cancelled after {self.processed} of {self.total}"
        else:
            head = f"Finished {self.total}"
        parts = [f"{self.succeeded} applied"]
        if self.skipped:
            parts.append(f"{self.skipped} skipped")
        if self.failed:
            parts.append(f"{self.failed} failed")
        return f"{head} — " + ", ".join(parts)


def run_bulk(
    items: Iterable[Any],
    work: Callable[[Any], Any],
    *,
    token: CancelToken | None = None,
    label: Callable[[Any], str] | None = None,
    on_progress: Callable[[int, int, Any], None] | None = None,
    on_result: Callable[[Any, str, str], None] | None = None,
) -> BulkSummary:
    """Run ``work`` over ``items``, counting outcomes and honouring ``token``.

    One item failing never stops the run: an unreachable server or a single
    malformed file should not cost the user the other 300 applications. Every
    failure is recorded with the name of the item it belongs to, so the final
    summary is actionable rather than a bare count.
    """
    items = list(items)
    token = token or NULL_TOKEN
    summary = BulkSummary(total=len(items))
    name_of = label or (lambda item: str(item))

    for index, item in enumerate(items):
        if token.cancelled:
            summary.cancelled = True
            break
        if on_progress is not None:
            on_progress(index, summary.total, item)
        try:
            work(item)
        except Cancelled:
            summary.cancelled = True
            break
        except Skip as exc:
            summary.skipped += 1
            summary.processed += 1
            summary.skips.append(f"{name_of(item)}: {exc}" if str(exc) else name_of(item))
            if on_result is not None:
                on_result(item, "skipped", str(exc))
            continue
        except Exception as exc:
            summary.failed += 1
            summary.processed += 1
            summary.failures.append(f"{name_of(item)}: {exc}")
            if on_result is not None:
                on_result(item, "failed", str(exc))
            continue
        summary.succeeded += 1
        summary.processed += 1
        if on_result is not None:
            on_result(item, "ok", "")

    return summary
