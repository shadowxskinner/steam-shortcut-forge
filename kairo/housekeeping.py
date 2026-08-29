"""Cleaning up artwork nothing points at any more.

Kairo copies every icon it applies into its own store so that a launcher entry
never depends on a theme that might be upgraded away. Icons therefore
accumulate: replacing an application's artwork supersedes the old file, and
removing a customisation leaves its artwork behind if anything went wrong
mid-operation.

**Deletion is decided by reference, never by the change history.** An icon is
removable only when no launcher entry in the user's applications directory
points at it. Using the history instead would be unsafe for exactly the reason
migration exposed: entries can be genuinely owned and customised while the
history knows nothing about them, and deleting their artwork would break real
launcher entries.

Every ``.desktop`` in that directory contributes references, including ones
Kairo does not own. If somebody hand-wrote an entry pointing into Kairo's
store, that artwork is in use and stays.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from kairo import paths
from kairo.desktop import entry as de


def referenced_icons() -> set[Path]:
    """Every path in the icon store that some launcher entry points at."""
    referenced: set[Path] = set()
    applications = paths.applications_dir()
    if not applications.is_dir():
        return referenced

    for path in applications.glob("*.desktop"):
        # Deliberately not filtered by ownership: a reference from a file we
        # do not own still means the artwork is in use.
        value = de.read_entry_icon(path)
        if not value.startswith("/"):
            continue
        try:
            referenced.add(Path(value).resolve())
        except OSError:
            continue
    return referenced


def is_referenced(icon: Path) -> bool:
    try:
        return icon.resolve() in referenced_icons()
    except OSError:
        return False


def orphan_icons() -> list[Path]:
    """Files in the icon store that no launcher entry references.

    Only regular files directly inside the store are considered. Anything
    nested is left alone rather than walked, so a stray directory can never
    turn into a recursive delete.
    """
    store = paths.icon_store()
    if not store.is_dir():
        return []
    try:
        store_real = store.resolve()
    except OSError:
        return []

    referenced = referenced_icons()
    orphans: list[Path] = []
    for path in sorted(store.iterdir()):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            resolved = path.resolve()
            if resolved.parent != store_real:
                continue          # escaped the store somehow; do not touch it
        except OSError:
            continue
        if resolved not in referenced:
            orphans.append(path)
    return orphans


@dataclass
class SweepResult:
    removed: int = 0
    freed_bytes: int = 0
    failures: list[str] = field(default_factory=list)

    def describe(self) -> str:
        if not self.removed:
            return "No unused artwork to clean up."
        megabytes = self.freed_bytes / (1024 * 1024)
        return f"Removed {self.removed} unused icon(s), freeing {megabytes:.1f} MB."


def sweep(dry_run: bool = False) -> SweepResult:
    """Delete unreferenced artwork from Kairo's own store."""
    result = SweepResult()
    for path in orphan_icons():
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        if dry_run:
            result.removed += 1
            result.freed_bytes += size
            continue
        try:
            path.unlink()
        except OSError as exc:
            result.failures.append(f"{path.name}: {exc}")
            continue
        result.removed += 1
        result.freed_bytes += size
    return result
