"""One cached index of every installed icon theme.

This replaces two separate lookup systems that used to coexist: a cached
``apps/`` walk that powered the icon browser, and a brute-force glob over
``apps``, ``categories``, ``devices`` and ``mimetypes`` that ran per
application during every scan just to resolve the icon a .desktop already
names. The glob repeated work the index had already done and dominated scan
time on a machine with several themes installed.

Now there is one walk, cached to disk, keyed on the mtime of every theme
directory. Application icons are indexed separately from the other categories
so that the icon browser can offer only ``apps/`` artwork while resolution can
still fall back to a category or mimetype icon, which is what a handful of
system entries genuinely use.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from kairo import paths
from kairo.desktop.entry import make_parser

THEME_ICON_EXTS = (".svg", ".png", ".xpm")
THEME_CACHE_NAME = "themes.json"

# Bump when the traversal or the on-disk shape changes, so a cache written by
# an older build is discarded rather than silently reused.
THEME_INDEX_VERSION = 3

_SCALABLE_RANK = 1_000_000      # resolution independent beats any fixed size

_APP_DIR_PREFIX = "apps"
_OTHER_DIR_PREFIXES = ("categories", "devices", "mimetypes", "places", "status")


def _size_rank(path: Path) -> int:
    """Rank a candidate by the size directory in its path.

    Theme layouts put the size in a path component - ``scalable/apps/x.svg`` or
    ``256x256/apps/x.png``. Bigger is better and scalable wins outright.
    """
    for part in path.parts:
        low = part.lower()
        if low == "scalable":
            return _SCALABLE_RANK
        match = re.fullmatch(r"(\d+)(?:x\d+)?", low)
        if match:
            return int(match.group(1))
    return 0


def _category_of(rel: Path) -> str | None:
    """"apps", "other", or None if this directory holds no icons we index."""
    for part in rel.parts:
        low = part.lower()
        # startswith catches the @2x and -symbolic variants; it deliberately
        # does not match "applications".
        if low.startswith(_APP_DIR_PREFIX) and not low.startswith("applications"):
            return "apps"
    for part in rel.parts:
        low = part.lower()
        if any(low.startswith(prefix) for prefix in _OTHER_DIR_PREFIXES):
            return "other"
    return None


def walk_theme(theme_dir: Path) -> dict[str, dict[str, str]]:
    """Map ``{category: {icon name: best path}}`` for one theme.

    Follows symlinks, because themes like WhiteSur are largely symlink farms
    generated at install time and skipping links would find almost nothing. A
    visited ``(st_dev, st_ino)`` set stops circular links hanging the walk, and
    anything resolving outside the theme root is ignored.
    """
    best: dict[str, dict[str, tuple[int, Path]]] = {"apps": {}, "other": {}}
    visited: set[tuple[int, int]] = set()
    try:
        root_real = theme_dir.resolve()
    except OSError:
        return {"apps": {}, "other": {}}

    for dirpath, dirnames, filenames in os.walk(theme_dir, followlinks=True):
        here = Path(dirpath)
        try:
            st = here.stat()
        except OSError:
            dirnames[:] = []
            continue
        marker = (st.st_dev, st.st_ino)
        if marker in visited:
            dirnames[:] = []            # already walked - circular symlink
            continue
        visited.add(marker)
        try:
            if not here.resolve().is_relative_to(root_real):
                dirnames[:] = []        # link escaped the theme
                continue
        except OSError:
            dirnames[:] = []
            continue

        try:
            rel = here.relative_to(theme_dir)
        except ValueError:
            continue
        category = _category_of(rel)
        if category is None:
            continue

        rank = _size_rank(here)
        bucket = best[category]
        for fname in filenames:
            stem, ext = os.path.splitext(fname)
            if ext.lower() not in THEME_ICON_EXTS:
                continue
            current = bucket.get(stem)
            if current is None or rank > current[0]:
                bucket[stem] = (rank, here / fname)

    return {cat: {name: str(path) for name, (_, path) in items.items()}
            for cat, items in best.items()}


def active_theme_names() -> list[str]:
    """Preferred icon themes, most specific first, always ending in hicolor."""
    names: list[str] = []

    kdeglobals = paths.home() / ".config" / "kdeglobals"
    parser = make_parser()
    try:
        parser.read(kdeglobals, encoding="utf-8")
        theme = parser.get("Icons", "Theme", fallback="").strip()
        if theme:
            names.append(theme)
    except Exception:
        pass

    # GTK desktops record the theme here instead. Reading both keeps Kairo
    # from assuming KDE, which matters for the GNOME and Ubuntu targets.
    for candidate in (paths.home() / ".config" / "gtk-3.0" / "settings.ini",
                      paths.home() / ".config" / "gtk-4.0" / "settings.ini"):
        gtk = make_parser()
        try:
            gtk.read(candidate, encoding="utf-8")
            theme = gtk.get("Settings", "gtk-icon-theme-name", fallback="").strip()
            if theme:
                names.append(theme)
        except Exception:
            pass

    names.append("hicolor")

    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            out.append(name)
    return out


class ThemeIndex:
    """Lazily built, disk-cached index of every installed theme."""

    _index: dict[str, dict[str, dict[str, str]]] | None = None
    _signature: list[list] | None = None

    @staticmethod
    def _current_signature() -> list[list]:
        sig: list[list] = []
        for root in paths.theme_roots():
            if not root.is_dir():
                continue
            try:
                children = sorted(root.iterdir())
            except OSError:
                continue
            for theme_dir in children:
                if not theme_dir.is_dir():
                    continue
                try:
                    sig.append([str(theme_dir), int(theme_dir.stat().st_mtime)])
                except OSError:
                    continue
        return sig

    @classmethod
    def reset(cls) -> None:
        cls._index = None
        cls._signature = None

    @classmethod
    def index(cls) -> dict[str, dict[str, dict[str, str]]]:
        signature = cls._current_signature()
        if cls._index is not None and cls._signature == signature:
            return cls._index

        cache = paths.cache_dir() / THEME_CACHE_NAME
        if cache.is_file():
            try:
                blob = json.loads(cache.read_text())
                if (blob.get("version") == THEME_INDEX_VERSION
                        and blob.get("signature") == signature):
                    cls._index = blob["themes"]
                    cls._signature = signature
                    return cls._index
            except (json.JSONDecodeError, OSError, KeyError, TypeError):
                pass

        themes: dict[str, dict[str, dict[str, str]]] = {}
        for root in paths.theme_roots():
            if not root.is_dir():
                continue
            try:
                children = sorted(root.iterdir())
            except OSError:
                continue
            for theme_dir in children:
                if not theme_dir.is_dir():
                    continue
                found = walk_theme(theme_dir)
                if not found["apps"] and not found["other"]:
                    continue
                slot = themes.setdefault(theme_dir.name, {"apps": {}, "other": {}})
                # Later roots win, so a user copy shadows the system one.
                slot["apps"].update(found["apps"])
                slot["other"].update(found["other"])

        cls._index = themes
        cls._signature = signature
        try:
            paths.cache_dir().mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"version": THEME_INDEX_VERSION,
                                         "signature": signature,
                                         "themes": themes}))
        except OSError:
            pass
        return themes

    @classmethod
    def theme_names(cls) -> list[str]:
        return sorted(cls.index())

    @classmethod
    def app_icons(cls, theme: str) -> dict[str, str]:
        return cls.index().get(theme, {}).get("apps", {})

    @classmethod
    def lookup(cls, name: str, *, category: str = "apps") -> list[tuple[str, str]]:
        """``[(theme, path)]`` for one exact icon name, across every theme."""
        name = (name or "").strip()
        if not name:
            return []
        out: list[tuple[str, str]] = []
        for theme, cats in sorted(cls.index().items()):
            path = cats.get(category, {}).get(name)
            if path:
                out.append((theme, path))
        return out

    @classmethod
    def find_in_themes(cls, name: str, theme_order: list[str]) -> str | None:
        """First hit for ``name``, honouring the user's active theme order.

        Checks ``apps`` across the preferred themes, then ``apps`` in any
        remaining theme, then the other categories. Ordering matters: an app
        should get its own theme's artwork rather than whichever theme happens
        to sort first alphabetically.
        """
        index = cls.index()
        ordered = [t for t in theme_order if t in index]
        rest = [t for t in sorted(index) if t not in ordered]

        for category in ("apps", "other"):
            for theme in (*ordered, *rest):
                path = index[theme].get(category, {}).get(name)
                if path and Path(path).is_file():
                    return path
        return None
