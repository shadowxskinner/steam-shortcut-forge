"""The extension point for adding a new source of icons."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from kairo.models import Artwork, ArtQuery, Suggestion


class ArtworkSource(ABC):
    """Somewhere icons come from.

    ``supports`` and ``available`` together replace what used to be a chain of
    string comparisons against UI button labels. The source picker is built
    from the sources that pass both, so a source that needs an API key simply
    does not appear until one is set, and no code anywhere compares a label.
    """

    id: str = ""
    label: str = ""

    #: True when the user must type something for this source to return results.
    needs_query: bool = False
    query_label: str = "Search"
    query_placeholder: str = ""

    #: True when results come from a file dialog rather than ``find``.
    interactive: bool = False

    def available(self, config: dict[str, Any] | None = None) -> bool:
        return True

    def unavailable_reason(self, config: dict[str, Any] | None = None) -> str:
        return ""

    @abstractmethod
    def supports(self, provider_id: str) -> bool:
        ...

    @abstractmethod
    def find(self, query: ArtQuery) -> list[Artwork]:
        ...

    def best_match(self, query: ArtQuery) -> Suggestion | None:
        """The one artwork this source would auto-apply, or None.

        Opt-in: the default is None, so a source contributes to automatic
        matching only when it can express real confidence. A source that can
        only offer a fuzzy search result should return None rather than a
        low score, because "no match" is a better outcome than silently
        putting the wrong icon on somebody's application.
        """
        return None

    @abstractmethod
    def preview(self, art: Artwork) -> bytes:
        """Bytes to render in a grid tile."""

    @abstractmethod
    def fetch(self, art: Artwork, dest_dir: Path, stem: str) -> Path:
        """Materialise the artwork on disk and return its path."""
