"""Kairo's record of what it has changed on this machine.

The ledger answers the question a user is entitled to ask of anything that
edits their desktop: *what did this program actually do?* Before it existed,
the only answer was to glob two directories and parse every result, which is
why "Restore Original" could not be a first-class feature.

**The ledger is an index, not a permission.** Ownership lives in the marker key
inside the ``.desktop`` file, and that marker is the only thing authorised to
sanction a destructive operation. If the ledger claims Kairo owns an entry but
the file carries no marker - because the user hand-edited it, or a package
replaced it, or the ledger was restored from a backup - Kairo refuses to touch
it. Belt and braces, because the failure mode is deleting somebody else's work.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from kairo import paths
from kairo.desktop import entry as de

LEDGER_VERSION = 1
LEDGER_NAME = "state.json"

#: Kairo created the launcher entry; restoring means deleting it.
ACTION_CREATED = "created"
#: Kairo shadowed an existing entry; restoring means removing the override.
ACTION_OVERRODE = "overrode"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class ChangeRecord:
    """One change Kairo made, and everything needed to explain or undo it."""

    key: str                        # namespaced: steam:440
    provider_id: str
    name: str                       # display name at the time of the change
    action: str                     # ACTION_CREATED | ACTION_OVERRODE
    target: str                     # the .desktop we wrote
    original_icon: str = ""         # Icon= before we touched it, "" if none
    applied_icon: str = ""          # what we set it to
    source_id: str = ""
    source_label: str = ""
    artwork_id: str = ""
    artwork_name: str = ""
    applied_at: str = field(default_factory=now_iso)
    #: Enough provider payload to rebuild an AppEntry for a restore without
    #: rescanning the whole machine first.
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def target_path(self) -> Path:
        return Path(self.target)

    @property
    def applied_icon_path(self) -> Path | None:
        return Path(self.applied_icon) if self.applied_icon else None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ChangeRecord":
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in allowed})


class Ledger:
    """The change history, persisted as one JSON file."""

    def __init__(self, path: Path | None = None):
        self._path = path
        self._records: dict[str, ChangeRecord] = {}
        self._loaded = False

    # -- persistence -----------------------------------------------------

    @property
    def path(self) -> Path:
        return self._path if self._path is not None else paths.data_dir() / LEDGER_NAME

    def load(self) -> "Ledger":
        self._records = {}
        self._loaded = True
        path = self.path
        if not path.is_file():
            return self
        try:
            blob = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            # A corrupt ledger loses history, never data: the markers in the
            # .desktop files remain the real source of ownership.
            return self
        if blob.get("version") != LEDGER_VERSION:
            return self
        for raw in blob.get("changes") or []:
            try:
                record = ChangeRecord.from_dict(raw)
            except TypeError:
                continue
            if record.key:
                self._records[record.key] = record
        return self

    def _ensure(self) -> None:
        if not self._loaded:
            self.load()

    def save(self) -> None:
        self._ensure()
        payload = {
            "version": LEDGER_VERSION,
            "updated_at": now_iso(),
            "changes": [r.to_dict() for r in self.records()],
        }
        de.atomic_write_text(self.path, json.dumps(payload, indent=2) + "\n")

    # -- reading ---------------------------------------------------------

    def records(self) -> list[ChangeRecord]:
        """Newest first, which is the order a history should be read in."""
        self._ensure()
        return sorted(self._records.values(),
                      key=lambda r: (r.applied_at, r.name), reverse=True)

    def get(self, key: str) -> ChangeRecord | None:
        self._ensure()
        return self._records.get(key)

    def __len__(self) -> int:
        self._ensure()
        return len(self._records)

    def for_provider(self, provider_id: str) -> list[ChangeRecord]:
        return [r for r in self.records() if r.provider_id == provider_id]

    # -- writing ---------------------------------------------------------

    def record(self, record: ChangeRecord, *, save: bool = True) -> ChangeRecord:
        """Add or replace the record for one application.

        Re-applying artwork replaces the record rather than appending, but the
        first-recorded ``original_icon`` is carried forward: it is the only
        value that restores the application to how the user found it.
        """
        self._ensure()
        existing = self._records.get(record.key)
        if existing is not None and existing.original_icon and not record.original_icon:
            record.original_icon = existing.original_icon
        self._records[record.key] = record
        if save:
            self.save()
        return record

    def forget(self, key: str, *, save: bool = True) -> bool:
        self._ensure()
        removed = self._records.pop(key, None) is not None
        if removed and save:
            self.save()
        return removed

    def prune(self, *, save: bool = True) -> int:
        """Drop records whose launcher entry is gone or is no longer ours.

        Covers the user deleting a file by hand, or a package update replacing
        an override. The history is stale; the desktop is the truth.
        """
        self._ensure()
        stale = [key for key, record in self._records.items()
                 if not self.owns(record)]
        for key in stale:
            del self._records[key]
        if stale and save:
            self.save()
        return len(stale)

    # -- authority -------------------------------------------------------

    @staticmethod
    def owns(record: ChangeRecord) -> bool:
        """Whether the file on disk still confirms Kairo's ownership.

        The marker inside the file, never the ledger, decides this.
        """
        target = record.target_path
        return target.is_file() and de.is_managed(target)

    @staticmethod
    def restorable(record: ChangeRecord) -> tuple[bool, str]:
        """``(allowed, reason)`` for a destructive restore."""
        target = record.target_path
        if not target.exists():
            return False, "Already restored — the launcher entry is gone."
        if not de.is_managed(target):
            return False, ("This launcher entry has been changed by something "
                           "other than Kairo, so Kairo will not remove it.")
        return True, ""
