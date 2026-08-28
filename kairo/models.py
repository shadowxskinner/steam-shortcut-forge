"""The shapes that flow between providers, artwork sources and the UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

@dataclass
class AppEntry:
    """One customisable application, from any provider.

    ``key`` is the identity and is namespaced by provider — ``steam:440``,
    ``desktop:org.kde.dolphin``. Everything downstream keys on it: selection
    state, stale-worker checks, and eventually the change ledger. The previous
    design compared a bare ``appid``, which worked only because a Steam appid
    could not collide with a .desktop basename. Namespacing removes the
    coincidence.

    Mutable by design: the UI flips ``customized`` and ``current_icon`` in
    place after an apply, and the sidebar row re-reads them.
    """

    key: str
    provider_id: str
    name: str
    subtitle: str = ""
    icon_hint: str = ""
    current_icon: Path | None = None
    customized: bool = False
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def local_id(self) -> str:
        """The provider-specific part of the key: ``steam:440`` -> ``440``."""
        _, _, rest = self.key.partition(":")
        return rest

    def sort_key(self) -> str:
        return self.name.strip().lower()


def make_key(provider_id: str, local_id: str) -> str:
    return f"{provider_id}:{local_id}"


# ---------------------------------------------------------------------------
# Artwork
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Artwork:
    """One candidate icon from one source.

    ``locator`` is whatever the owning source needs to fetch it: an HTTPS URL
    for SteamGridDB and Iconify, an absolute filesystem path for installed
    themes and local files. Only the source that produced an Artwork ever
    interprets its locator.
    """

    id: str
    source_id: str
    label: str = ""
    #: The source's own name for this icon (theme icon name, Iconify icon
    #: name). Used to tell an exact match from a fuzzy search hit.
    name: str = ""
    width: int = 0
    height: int = 0
    score: float = 0.0
    locator: str = ""
    mime: str = ""
    kind: str = ""          # "icon" | "logo" | "" — drives the tile pill
    official: bool = False

    @property
    def dimensions(self) -> str:
        return f"{self.width}x{self.height}" if self.width and self.height else ""


@dataclass(frozen=True)
class ArtQuery:
    """What a source is being asked to find artwork for.

    Providers build this from an AppEntry, so a source never needs to know
    which provider it is serving - only which of these fields are populated.
    """

    entry: AppEntry
    text: str = ""              # free-text search term
    fallback_text: str = ""     # tried when `text` finds nothing
    icon_name: str = ""         # exact freedesktop icon name, for themes
    steam_appid: str = ""       # SteamGridDB is keyed on this

    def with_text(self, text: str) -> "ArtQuery":
        return ArtQuery(entry=self.entry, text=text,
                        fallback_text=self.fallback_text,
                        icon_name=self.icon_name, steam_appid=self.steam_appid)


# ---------------------------------------------------------------------------
# Match confidence
# ---------------------------------------------------------------------------

#: Matched on an authoritative identifier - a Steam appid resolved through
#: SteamGridDB. There is no ambiguity about which game this is.
CONFIDENCE_ID = 1.0

#: The application's own declared icon name matched a theme icon exactly.
CONFIDENCE_EXACT_NAME = 0.9

#: An icon set contains an icon whose name is exactly the term we searched.
CONFIDENCE_EXACT_SEARCH = 0.75

#: The reverse-DNS short name matched: org.kde.dolphin -> dolphin.
CONFIDENCE_SHORT_NAME = 0.7

#: A substring or search-engine hit. Plausible, never certain.
CONFIDENCE_FUZZY = 0.3

#: Below this, Kairo leaves the application unmatched rather than guessing.
#: Applying questionable artwork automatically is worse than applying none:
#: the user has to notice it happened before they can undo it.
AUTO_APPLY_THRESHOLD = 0.7


@dataclass(frozen=True)
class Suggestion:
    """One source's best answer for one application, with its confidence."""

    artwork: Artwork
    confidence: float
    reason: str

    @property
    def confident(self) -> bool:
        return self.confidence >= AUTO_APPLY_THRESHOLD
