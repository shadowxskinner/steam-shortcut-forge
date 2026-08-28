"""Applying and restoring artwork, with the change history kept in step.

The writers stay pure - they know how to edit a launcher entry and nothing
else. This module is the one place that decides *when* the ledger is written
and *when* the desktop database is re-indexed, so a bulk run records 300
changes and refreshes once rather than 300 times.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

from kairo.desktop import database
from kairo.desktop import entry as de
from kairo.ledger import ChangeRecord, Ledger
from kairo.models import AppEntry, Artwork
from kairo.tasks import BulkSummary, CancelToken, Skip, run_bulk


def entry_from_record(record: ChangeRecord) -> AppEntry:
    """Rebuild just enough of an AppEntry to restore one change.

    Restore All has to work from history alone. Requiring a full rescan first
    would mean an application uninstalled since the change was made could never
    have its override removed.
    """
    return AppEntry(
        key=record.key,
        provider_id=record.provider_id,
        name=record.name,
        subtitle=record.payload.get("basename", "") or record.key.partition(":")[2],
        customized=True,
        current_icon=record.applied_icon_path,
        payload=dict(record.payload),
    )


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def apply_icon(
    entry: AppEntry,
    provider,
    icon_src: Path,
    *,
    art: Artwork | None = None,
    source_label: str = "",
    ledger: Ledger | None = None,
    refresh: bool = True,
    save_ledger: bool = True,
) -> Path:
    """Apply artwork and record the change. Returns the stored icon path."""
    writer = provider.writer()
    stored = writer.apply(entry, icon_src)
    target = writer.target(entry)

    if ledger is not None:
        # Read the original back out of the file rather than tracking it
        # separately: the writer is what decides the true pre-change value,
        # and it already preserves the first one across repeat applies.
        original = de.read_entry_value(target, de.ORIGINAL_ICON_KEYS)
        ledger.record(ChangeRecord(
            key=entry.key,
            provider_id=entry.provider_id,
            name=entry.name,
            action=getattr(writer, "action", ""),
            target=str(target),
            original_icon=original,
            applied_icon=str(stored),
            source_id=(art.source_id if art else ""),
            source_label=source_label or (art.label if art else ""),
            artwork_id=(art.id if art else ""),
            artwork_name=(art.name if art else ""),
            payload=dict(entry.payload),
        ), save=save_ledger)

    if refresh:
        database.refresh()
    return stored


def fetch_and_apply(
    entry: AppEntry,
    provider,
    source,
    art: Artwork,
    *,
    ledger: Ledger | None = None,
    token: CancelToken | None = None,
    refresh: bool = True,
    save_ledger: bool = True,
) -> Path:
    """Download the artwork, then apply it. Cancellation is checked between."""
    if token is not None:
        token.check()
    from kairo import paths
    # art.id comes from a remote service and ends up in a filename, and the
    # sources create missing parent directories, so it is sanitised rather
    # than trusted.
    stem = paths.icon_stem(entry.provider_id, entry.local_id, art.id)
    icon_path = source.fetch(art, paths.icon_store(), stem)
    if token is not None:
        token.check()
    return apply_icon(entry, provider, icon_path, art=art,
                      source_label=source.label, ledger=ledger,
                      refresh=refresh, save_ledger=save_ledger)


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

def restore_entry(entry: AppEntry, provider, *, ledger: Ledger | None = None,
                  refresh: bool = True) -> None:
    """Undo Kairo's change to one application.

    The writer decides what restoring means for its kind of entry, and its
    ``can_restore`` consults the marker in the file. The ledger is never asked
    for permission.
    """
    writer = provider.writer()
    allowed, reason = writer.can_restore(entry)
    if not allowed:
        raise ValueError(reason)
    writer.restore(entry)
    provider.refresh(entry)
    if ledger is not None:
        ledger.forget(entry.key)
    if refresh:
        database.refresh()


def restore_record(record: ChangeRecord, registry, *, ledger: Ledger | None = None,
                   refresh: bool = False) -> None:
    """Restore from a history entry rather than a live scan."""
    provider = registry.get(record.provider_id)
    if provider is None:
        raise ValueError(f"No provider named '{record.provider_id}' in this build.")

    allowed, reason = Ledger.restorable(record)
    if not allowed:
        raise Skip(reason)

    restore_entry(entry_from_record(record), provider, ledger=ledger, refresh=refresh)


def restore_all(
    ledger: Ledger,
    registry,
    *,
    token: CancelToken | None = None,
    on_progress: Callable[[int, int, Any], None] | None = None,
) -> BulkSummary:
    """Undo every recorded change.

    One application refusing - because its entry was hand-edited, or its
    provider is not in this build - is a skip, not a stop. The user gets a
    summary at the end rather than the operation dying on the third of two
    hundred.
    """
    records = ledger.records()

    def work(record: ChangeRecord) -> None:
        restore_record(record, registry, ledger=ledger, refresh=False)

    try:
        summary = run_bulk(records, work, token=token,
                           label=lambda r: r.name, on_progress=on_progress)
    finally:
        # Whatever happened, what was already undone must be recorded. Losing
        # the ledger here would leave restored entries still listed as
        # changed, and unrestored ones invisible.
        ledger.save()
        database.refresh()
    return summary


# ---------------------------------------------------------------------------
# Bulk apply
# ---------------------------------------------------------------------------

def apply_many(
    plans: Iterable[tuple[AppEntry, Any, Artwork]],
    registry,
    *,
    ledger: Ledger | None = None,
    token: CancelToken | None = None,
    on_progress: Callable[[int, int, Any], None] | None = None,
) -> BulkSummary:
    """Apply a reviewed set of ``(entry, source, artwork)`` plans."""
    plans = list(plans)

    def work(plan) -> None:
        entry, source, art = plan
        provider = registry.get(entry.provider_id)
        if provider is None:
            raise Skip(f"no provider '{entry.provider_id}'")
        # One ledger write at the end of the run, not one per application.
        fetch_and_apply(entry, provider, source, art, ledger=ledger,
                        token=token, refresh=False, save_ledger=False)

    try:
        summary = run_bulk(plans, work, token=token,
                           label=lambda plan: plan[0].name, on_progress=on_progress)
    finally:
        # The .desktop files are already written. If the ledger is not saved
        # here those applications are customised with no record of it, so
        # Changes cannot list them and Restore All cannot undo them.
        if ledger is not None:
            ledger.save()
        database.refresh()
    return summary
