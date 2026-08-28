"""A file the user picks themselves."""

from __future__ import annotations

import shutil
from pathlib import Path

from kairo.artwork.base import ArtworkSource
from kairo.models import Artwork, ArtQuery

SOURCE_ID = "local"


class LocalFileSource(ArtworkSource):
    """Results come from a file dialog, so ``find`` has nothing to return.

    Modelled as a source anyway so that "where did this icon come from" has one
    answer shape for every icon Kairo applies, including hand-picked ones.
    """

    id = SOURCE_ID
    label = "Local file"
    interactive = True

    def supports(self, provider_id: str) -> bool:
        return True

    def find(self, query: ArtQuery) -> list[Artwork]:
        return []

    @staticmethod
    def artwork_for(path: Path) -> Artwork:
        return Artwork(id=f"local_{path.name}", source_id=SOURCE_ID,
                       name=path.stem, label="Local file",
                       locator=str(path), kind="icon")

    def preview(self, art: Artwork) -> bytes:
        return Path(art.locator).read_bytes()

    def fetch(self, art: Artwork, dest_dir: Path, stem: str) -> Path:
        source = Path(art.locator)
        dest = dest_dir / f"{stem}{source.suffix.lower()}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        return dest
