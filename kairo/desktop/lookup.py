"""Resolving a ``Icon=`` value to an actual file on disk.

``Icon=`` is normally a bare name (``org.kde.dolphin``) that the desktop
resolves against the freedesktop icon theme specification. Kairo needs the same
answer in order to show the user what an application currently looks like.

Everything here goes through the shared ThemeIndex rather than globbing the
theme directories per application, which is what the previous implementation
did once per app on every scan.
"""

from __future__ import annotations

from pathlib import Path

from kairo import paths
from kairo.themeindex import THEME_ICON_EXTS, ThemeIndex, active_theme_names


def resolve_icon(value: str) -> Path | None:
    """The file an ``Icon=`` value points at, or None."""
    value = (value or "").strip()
    if not value:
        return None

    # An absolute or ~-relative path is used verbatim, per the spec.
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate if candidate.is_file() else None

    # A bare name is the normal case. Themes index by stem, so a value that
    # carries an extension is tried both ways.
    names = [value]
    if Path(value).suffix.lower() in THEME_ICON_EXTS:
        names.append(Path(value).stem)
    names = list(dict.fromkeys(names))

    theme_order = active_theme_names()
    for name in names:
        hit = ThemeIndex.find_in_themes(name, theme_order)
        if hit:
            return Path(hit)

    # Legacy location, still used by a few packages.
    pixmaps = paths.pixmaps_dir()
    for name in names:
        for ext in THEME_ICON_EXTS:
            path = pixmaps / f"{name}{ext}"
            if path.is_file():
                return path
        direct = pixmaps / name
        if direct.is_file():
            return direct

    return None


def launcher_entry(desktop_ids) -> "Path | None":
    """The launcher file the desktop would actually use, by precedence.

    ``desktop_ids`` are basenames to accept, compared case-insensitively
    because packages disagree about capitalisation — PCSX2 installs
    ``PCSX2.desktop`` while its binary is ``pcsx2-qt``.

    Later directories in the search path outrank earlier ones and the user's
    own directory is last, so a Kairo override shadows the packaged file here
    exactly as it does for the desktop itself. That is the whole point: the
    answer has to come from the same precedence the menu obeys, not from a
    value copied out of a package at some earlier moment.
    """
    from kairo import paths

    wanted = {str(name).lower() for name in desktop_ids if name}
    if not wanted:
        return None
    found = None
    for directory in paths.system_application_dirs():
        if not paths.is_readable_dir(directory):
            continue
        for path in paths.entries_matching(directory, "*.desktop"):
            if path.name.lower() in wanted:
                found = path            # keep going: last wins
    return found


def effective_icon(desktop_ids) -> str:
    """The ``Icon=`` value in force for a launcher, or "".

    Returned raw, because both forms are legitimate and mean different
    things: a bare name is looked up in the icon theme, while an absolute
    path is used verbatim. Kairo's own overrides write an absolute path, so
    collapsing the two here would lose exactly the case this exists for.
    """
    from kairo.desktop import entry as de

    path = launcher_entry(desktop_ids)
    if path is None:
        return ""
    return de.read_entry_icon(path)
