"""Bringing launcher entries Kairo already owns into the change history.

The history is written when a change is made, so anything customised outside
that moment is invisible to it: everything migrated from Steam Shortcut Forge,
and anything at all if the history file is lost. Those applications were still
customised by Kairo, are still restorable, and belong in Changes.

Adoption reconstructs a record from the launcher entry itself. It can recover
what was customised, which provider owns it, what the icon reverts to and when
the file was last written. It cannot recover which artwork source supplied the
icon, so adopted records are flagged rather than presented as if they were
recorded at the time.

**The in-file ownership marker is the only thing that authorises adoption.** A
file without one is never claimed, no matter what it is called or where it
sits - the same rule that governs every destructive operation in Kairo.
"""

from __future__ import annotations

import time
from pathlib import Path

from kairo import paths
from kairo.desktop import entry as de
from kairo.ledger import ChangeRecord, Ledger


def _mtime_iso(path: Path) -> str:
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(path.stat().st_mtime))
    except OSError:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _display_name(path: Path, fallback: str) -> str:
    return de.read_entry_value(path, "Name").strip() or fallback


def identify(path: Path, registry) -> tuple[str, str, dict, str] | None:
    """``(key, action, payload, provider_id)`` for an owned entry, or None."""
    for provider in registry.all():
        claimed = provider.claim(path)
        if claimed is not None:
            key, action, payload = claimed
            return key, action, payload, provider.id
    return None


def adopt_untracked(ledger: Ledger, registry) -> list[ChangeRecord]:
    """Add a record for every owned launcher entry the history is missing.

    Idempotent: an entry already present is skipped, so this is safe to run on
    every scan. Returns the records added.
    """
    applications = paths.applications_dir()
    if not applications.is_dir():
        return []

    known = {record.key for record in ledger.records()}
    added: list[ChangeRecord] = []

    for path in sorted(applications.glob("*.desktop")):
        # Ownership first. Everything below this line assumes it.
        if not de.is_managed(path):
            continue

        identified = identify(path, registry)
        if identified is None:
            continue
        key, action, payload, provider_id = identified
        if key in known:
            continue

        record = ChangeRecord(
            key=key,
            provider_id=provider_id,
            name=_display_name(path, key.partition(":")[2]),
            action=action,
            target=str(path),
            original_icon=de.read_entry_value(path, de.ORIGINAL_ICON_KEYS),
            applied_icon=de.read_entry_icon(path),
            source_id="",
            source_label="",
            applied_at=_mtime_iso(path),
            adopted=True,
            payload=payload,
        )
        ledger.record(record, save=False)
        known.add(key)
        added.append(record)

    if added:
        ledger.save()
    return added
