"""Cancellation and bulk-run behaviour."""

import threading

import pytest

from kairo.tasks import (ActivityTokens, BulkSummary, Cancelled, CancelToken,
                         Skip, run_bulk)


# -- CancelToken ------------------------------------------------------------

def test_token_starts_uncancelled():
    assert CancelToken().cancelled is False


def test_cancel_is_visible_and_one_way():
    token = CancelToken()
    token.cancel()
    assert token.cancelled is True
    token.cancel()
    assert token.cancelled is True


def test_check_raises_only_after_cancel():
    token = CancelToken()
    token.check()
    token.cancel()
    with pytest.raises(Cancelled):
        token.check()


def test_token_is_visible_across_threads():
    token = CancelToken()
    seen = []

    def worker():
        while not token.cancelled:
            pass
        seen.append(True)

    thread = threading.Thread(target=worker)
    thread.start()
    token.cancel()
    thread.join(timeout=5)
    assert seen == [True]


# -- ActivityTokens ---------------------------------------------------------

def test_starting_an_activity_cancels_the_previous_run():
    """Clicking through applications must not leave a fetch running per app."""
    tokens = ActivityTokens()
    first = tokens.start("artwork")
    second = tokens.start("artwork")
    assert first.cancelled is True
    assert second.cancelled is False


def test_activities_are_independent():
    tokens = ActivityTokens()
    artwork = tokens.start("artwork")
    tokens.start("bulk")
    assert artwork.cancelled is False


def test_is_current_identifies_the_live_token():
    tokens = ActivityTokens()
    first = tokens.start("artwork")
    assert tokens.is_current("artwork", first) is True
    second = tokens.start("artwork")
    assert tokens.is_current("artwork", first) is False
    assert tokens.is_current("artwork", second) is True


def test_cancel_all_stops_everything():
    tokens = ActivityTokens()
    a = tokens.start("artwork")
    b = tokens.start("bulk")
    tokens.cancel_all()
    assert a.cancelled and b.cancelled


# -- run_bulk ---------------------------------------------------------------

def test_counts_successes():
    summary = run_bulk([1, 2, 3], lambda item: None)
    assert (summary.total, summary.succeeded, summary.failed) == (3, 3, 0)
    assert summary.cancelled is False


def test_one_failure_does_not_stop_the_run():
    def work(item):
        if item == 2:
            raise RuntimeError("boom")

    summary = run_bulk([1, 2, 3, 4], work)
    assert summary.succeeded == 3
    assert summary.failed == 1
    assert summary.processed == 4


def test_failures_name_the_item():
    def work(item):
        raise RuntimeError("network down")

    summary = run_bulk(["Portal 2"], work, label=str)
    assert summary.failures == ["Portal 2: network down"]


def test_skip_is_counted_separately_from_failure():
    def work(item):
        if item == "b":
            raise Skip("no artwork available")

    summary = run_bulk(["a", "b", "c"], work, label=str)
    assert (summary.succeeded, summary.skipped, summary.failed) == (2, 1, 0)
    assert summary.skips == ["b: no artwork available"]


def test_cancellation_stops_before_the_next_item():
    token = CancelToken()
    seen = []

    def work(item):
        seen.append(item)
        if item == 2:
            token.cancel()

    summary = run_bulk([1, 2, 3, 4, 5], work, token=token)
    assert seen == [1, 2]
    assert summary.cancelled is True
    assert summary.succeeded == 2
    assert summary.remaining == 3


def test_cancellation_raised_inside_the_worker_is_honoured():
    token = CancelToken()

    def work(item):
        if item == 3:
            token.cancel()
            token.check()

    summary = run_bulk([1, 2, 3, 4], work, token=token)
    assert summary.cancelled is True
    assert summary.succeeded == 2       # item 3 aborted, not counted


def test_cancelling_before_the_start_does_nothing():
    token = CancelToken()
    token.cancel()
    seen = []
    summary = run_bulk([1, 2, 3], seen.append, token=token)
    assert seen == []
    assert summary.cancelled is True
    assert summary.processed == 0


def test_progress_is_reported_for_each_item():
    seen = []
    run_bulk(["a", "b"], lambda i: None,
             on_progress=lambda index, total, item: seen.append((index, total, item)))
    assert seen == [(0, 2, "a"), (1, 2, "b")]


def test_results_are_reported_with_outcomes():
    def work(item):
        if item == "bad":
            raise RuntimeError("x")
        if item == "meh":
            raise Skip("y")

    seen = []
    run_bulk(["ok", "bad", "meh"], work,
             on_result=lambda item, status, detail: seen.append((item, status)))
    assert seen == [("ok", "ok"), ("bad", "failed"), ("meh", "skipped")]


def test_empty_run_is_a_clean_summary():
    summary = run_bulk([], lambda i: None)
    assert summary == BulkSummary(total=0)


def test_describe_reads_naturally():
    summary = run_bulk([1, 2, 3], lambda i: None)
    assert summary.describe() == "Finished 3 — 3 applied"


def test_describe_reports_cancellation():
    token = CancelToken()

    def work(item):
        token.cancel()

    summary = run_bulk([1, 2, 3], work, token=token)
    assert "Cancelled after 1 of 3" in summary.describe()


def test_a_failing_progress_callback_does_not_abort_the_run():
    """Progress posts to a window the user may have closed. If that exception
    escaped, it would skip the caller's cleanup - which is where the ledger
    gets written."""
    def boom(index, total, item):
        raise RuntimeError("window closed")

    seen = []
    summary = run_bulk([1, 2, 3], seen.append, on_progress=boom)
    assert seen == [1, 2, 3]
    assert summary.succeeded == 3


def test_a_failing_result_callback_does_not_abort_the_run():
    def boom(item, status, detail):
        raise RuntimeError("window closed")

    summary = run_bulk([1, 2, 3], lambda i: None, on_result=boom)
    assert summary.succeeded == 3


def test_a_failing_label_is_still_fatal_for_that_item_only():
    """label() is used to build a failure message, so it runs inside the
    per-item handling rather than the callback shield."""
    def work(item):
        raise RuntimeError("x")

    summary = run_bulk([1], work, label=str)
    assert summary.failed == 1
