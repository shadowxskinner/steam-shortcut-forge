"""Installed icon themes as an artwork source.

The strongest source for ordinary applications and the only one that works
offline: themes already contain artwork named for real Linux applications,
drawn to match the desktop. A user with papirus-icon-theme installed has
thousands of appropriate icons available with no network access and no account.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from kairo.artwork.base import ArtworkSource
from kairo.models import Artwork, ArtQuery
from kairo.themeindex import ThemeIndex

SOURCE_ID = "theme"
DEFAULT_LIMIT = 200
#: Below this length a reverse substring match hits almost everything.
_REVERSE_MATCH_FLOOR = 4


class IconThemeSource(ArtworkSource):
    id = SOURCE_ID
    label = "Icon themes"
    needs_query = True
    query_label = "Icon name"
    query_placeholder = "firefox, org.kde.dolphin..."

    def supports(self, provider_id: str) -> bool:
        return provider_id == "desktop"

    # -- tiles -----------------------------------------------------------

    @staticmethod
    def _tile(theme: str, name: str, path: str) -> Artwork:
        return Artwork(
            id=f"theme_{hashlib.md5(f'{theme}/{name}'.encode()).hexdigest()[:12]}",
            source_id=SOURCE_ID,
            label=theme,
            locator=path,
            mime="image/svg+xml" if path.lower().endswith(".svg") else "image/png",
            kind="icon",
        )

    def lookup(self, icon_name: str) -> list[Artwork]:
        """Every installed theme's version of one exact icon name."""
        return [self._tile(theme, icon_name, path)
                for theme, path in ThemeIndex.lookup(icon_name)]

    # -- search ----------------------------------------------------------

    def find(self, query: ArtQuery, limit: int = DEFAULT_LIMIT) -> list[Artwork]:
        """Broaden from an exact name outward, best matches first.

        Apps declare reverse-DNS icon names (org.kde.dolphin) but most themes
        index generic freedesktop names, so an exact lookup alone returns
        nothing for many KDE applications. Widening in stages keeps precise
        hits at the top while still filling the grid:

        1. exact name across every theme
        2. exact short name - org.kde.dolphin -> dolphin
        3. substring on the short name, so "dolphin" also finds
           "dolphin-symbolic"
        """
        term = (query.text or query.icon_name or "").strip()
        if not term:
            return []
        short = term.rsplit(".", 1)[-1] if "." in term else term

        out: list[Artwork] = []
        seen: set[tuple[str, str]] = set()

        def add(tiles):
            for tile in tiles:
                key = (tile.label, tile.locator)
                if key not in seen:
                    seen.add(key)
                    out.append(tile)

        add(self.lookup(term))
        if short != term:
            add(self.lookup(short))

        # Match both directions: "dolphin" should find "dolphin-symbolic", and
        # "kwalletmanager5" should find "kwalletmanager".
        needle = short.lower()
        per_theme: dict[str, list[Artwork]] = {}
        for theme in ThemeIndex.theme_names():
            icons = ThemeIndex.app_icons(theme)
            hits = [self._tile(theme, name, icons[name])
                    for name in sorted(icons)
                    if needle in name.lower()
                    or (len(name) >= _REVERSE_MATCH_FLOOR and name.lower() in needle)]
            if hits:
                per_theme[theme] = hits

        # Round-robin rather than theme-by-theme. Walking themes in order and
        # stopping at the limit means one large theme consumes every slot and
        # later themes never appear at all, so results would silently disappear
        # as the user installs more themes.
        row = 0
        while len(out) < limit and per_theme:
            for theme in list(per_theme):
                hits = per_theme[theme]
                if row >= len(hits):
                    del per_theme[theme]
                    continue
                add([hits[row]])
                if len(out) >= limit:
                    break
            row += 1
        return out

    # -- transfer --------------------------------------------------------

    def preview(self, art: Artwork) -> bytes:
        """Already on disk - read it rather than fetching anything."""
        return Path(art.locator).read_bytes()

    def fetch(self, art: Artwork, dest_dir: Path, stem: str) -> Path:
        source = Path(art.locator)
        ext = source.suffix.lower()
        if ext not in {".ico", ".png", ".svg", ".xpm"}:
            ext = ".png"
        dest = dest_dir / f"{stem}{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        return dest
