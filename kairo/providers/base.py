"""The two extension points for adding a new kind of application."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from kairo.models import AppEntry, ArtQuery

#: Formats a launcher will actually render.
VALID_ICON_EXTS = {".ico", ".png", ".svg", ".xpm"}


class LauncherWriter(ABC):
    """How an icon is applied to, and removed from, one kind of entry.

    There are exactly two ways to own a launcher entry: you generated it, or
    you shadowed someone else's. Every provider present and future picks one of
    the two implementations in ``writers.py`` rather than inventing a third.
    """

    #: What restoring this kind of entry means, for the change history.
    #: "created" - Kairo made the file, so restoring deletes it.
    #: "overrode" - Kairo shadowed someone else's, so restoring un-shadows it.
    action: str = ""

    #: Button text. One verb cannot cover both writers: for an entry Kairo
    #: generated there is no earlier artwork to go back to, so "restore"
    #: describes a deletion, which is exactly the wrong thing for a button to
    #: do quietly.
    restore_label: str = "Restore original"

    def restore_prompt(self, entry: AppEntry) -> str:
        return f"Put back the original icon for {entry.name}?"

    @abstractmethod
    def target(self, entry: AppEntry) -> Path:
        """The launcher entry this writer owns for ``entry``."""

    @abstractmethod
    def apply(self, entry: AppEntry, icon_src: Path) -> Path:
        """Apply ``icon_src`` to ``entry``. Returns the stored icon path."""

    @abstractmethod
    def restore(self, entry: AppEntry) -> None:
        """Undo whatever ``apply`` did, returning the app to its original icon."""

    @abstractmethod
    def can_restore(self, entry: AppEntry) -> tuple[bool, str]:
        """``(allowed, reason)``. Reason is user-facing when not allowed."""


class AppProvider(ABC):
    """A source of customisable applications."""

    #: Stable identifier; forms the namespace in ``AppEntry.key``.
    id: str = ""
    #: Human label for the UI.
    label: str = ""
    #: What one of these is called, for status lines: "games", "apps".
    noun: str = "apps"

    #: Artwork source ids to consult for automatic matching, best first.
    #: Declared here rather than decided in the UI, so adding a source or
    #: reordering the preference never means comparing button labels again.
    #: A source absent from this tuple can still be browsed manually.
    auto_match_sources: tuple[str, ...] = ()

    def available(self) -> bool:
        """False when this provider has nothing to offer on this machine."""
        return True

    @abstractmethod
    def scan(self) -> list[AppEntry]:
        ...

    @abstractmethod
    def artwork_query(self, entry: AppEntry) -> ArtQuery:
        """Build the default artwork search for one entry."""

    @abstractmethod
    def writer(self) -> LauncherWriter:
        ...

    def refresh(self, entry: AppEntry) -> None:
        """Re-read this entry's current state from disk after a change."""
        return None

    def claim(self, path: Path) -> tuple[str, str, dict] | None:
        """Identify a launcher entry this provider owns.

        Returns ``(key, action, payload)`` or None. Used to adopt entries that
        Kairo owns but has no history for - after a migration, or if the
        change history is lost. The caller has already confirmed the file
        carries an ownership marker; this only answers *which* provider it
        belongs to and how to address it.
        """
        return None
