"""The set of artwork sources this build knows about."""

from __future__ import annotations

from typing import Any

from kairo.artwork.base import ArtworkSource
from kairo.artwork.iconify import IconifySource
from kairo.artwork.local import LocalFileSource
from kairo.artwork.steamgriddb import SteamGridDBSource
from kairo.artwork.themes import IconThemeSource


class ArtworkRegistry:
    def __init__(self, sources: list[ArtworkSource] | None = None):
        self._sources: list[ArtworkSource] = list(sources or [])

    def register(self, source: ArtworkSource) -> None:
        self._sources.append(source)

    def all(self) -> list[ArtworkSource]:
        return list(self._sources)

    def get(self, source_id: str) -> ArtworkSource | None:
        for source in self._sources:
            if source.id == source_id:
                return source
        return None

    def browsable_for(self, provider_id: str,
                      config: dict[str, Any] | None = None) -> list[ArtworkSource]:
        """Sources the picker should offer for this provider.

        This one expression replaces the chain of comparisons against UI button
        labels that used to decide which sources appeared on which tab.
        """
        return [s for s in self._sources
                if not s.interactive
                and s.supports(provider_id)
                and s.available(config)]


def default_registry(config: dict[str, Any] | None = None) -> ArtworkRegistry:
    """Adding a source is one import and one line here."""
    cfg = config or {}
    return ArtworkRegistry([
        SteamGridDBSource(cfg.get("steamgriddb_api_key", "")),
        IconThemeSource(),
        IconifySource(),
        LocalFileSource(),
    ])
