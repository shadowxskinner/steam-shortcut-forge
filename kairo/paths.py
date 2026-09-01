"""Every filesystem location Kairo reads or writes.

Exposed as functions rather than module constants so that the whole tree can
be redirected by setting ``HOME``. That is what makes the migration testable
against a fixture home instead of the developer's real desktop.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

#: Directory name under ~/.config and ~/.local/share.
APP_DIRNAME = "kairo"

#: Older directory names, newest first. Read for migration; never written.
LEGACY_APP_DIRNAMES: tuple[str, ...] = ("steam-shortcut-forge",)

#: Filename prefix for launcher entries this application generates.
DESKTOP_PREFIX = "kairo-"

#: Prefixes used by earlier releases. Generated-entry discovery must keep
#: matching these or previously created shortcuts become invisible to the app,
#: which would report every game as uncustomised while leaving the old files
#: behind in the user's launcher as undeletable duplicates.
LEGACY_DESKTOP_PREFIXES: tuple[str, ...] = ("steam-shortcut-forge-",)


def home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def _xdg_base(variable: str, fallback: str) -> Path:
    """An XDG base directory, honouring the environment.

    Hardcoding ~/.config and ~/.local/share is wrong on any machine where
    these are set: Kairo would write launcher entries into a directory the
    desktop is not reading, and the entries would simply never appear. The
    spec requires relative values to be ignored, hence the absolute check.
    """
    raw = os.environ.get(variable, "").strip()
    if raw.startswith("/"):
        return Path(raw)
    return home() / fallback


def config_home() -> Path:
    return _xdg_base("XDG_CONFIG_HOME", ".config")


def data_home() -> Path:
    return _xdg_base("XDG_DATA_HOME", ".local/share")


def config_dir() -> Path:
    return config_home() / APP_DIRNAME


def config_file() -> Path:
    return config_dir() / "config.json"


def cache_dir() -> Path:
    return config_dir() / "cache"


def data_dir() -> Path:
    return data_home() / APP_DIRNAME


def icon_store() -> Path:
    """Where artwork is copied so ``Icon=`` never points into a theme.

    A path into /usr/share/icons/<theme>/ dies the day that theme is upgraded
    or removed; a private copy keeps every override self-contained.
    """
    return data_dir() / "icons"


def applications_dir() -> Path:
    """The only directory Kairo ever writes launcher entries into."""
    return data_home() / "applications"


def legacy_config_dir(name: str) -> Path:
    return config_home() / name


def legacy_data_dir(name: str) -> Path:
    return data_home() / name


def legacy_icon_store(name: str) -> Path:
    return legacy_data_dir(name) / "icons"


def system_application_dirs() -> list[Path]:
    """Launcher directories in ascending precedence.

    Read only. Kairo never writes outside ``applications_dir()``, so a package
    or Flatpak update always wins over a stale system file and nothing needs
    root.
    """
    return [
        Path("/usr/share/applications"),
        Path("/usr/local/share/applications"),
        Path("/var/lib/flatpak/exports/share/applications"),
        data_home() / "flatpak" / "exports" / "share" / "applications",
        applications_dir(),
    ]


def all_desktop_prefixes() -> tuple[str, ...]:
    """Current prefix first, then every legacy prefix."""
    return (DESKTOP_PREFIX, *LEGACY_DESKTOP_PREFIXES)


def is_generated_name(name: str) -> bool:
    return any(name.startswith(p) for p in all_desktop_prefixes())


def strip_generated_prefix(name: str) -> str:
    """``kairo-440.desktop`` -> ``440``. Returns "" if no prefix matches."""
    stem = name[:-len(".desktop")] if name.endswith(".desktop") else name
    for prefix in all_desktop_prefixes():
        if stem.startswith(prefix):
            return stem[len(prefix):]
    return ""


_UNSAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")


def safe_component(text: str, fallback: str = "icon") -> str:
    """Reduce arbitrary text to one harmless filename component.

    Artwork identifiers come from remote services, and they end up in the name
    of a file Kairo writes. An id of "../../evil" would otherwise escape the
    icon store entirely, because the writers create missing parent
    directories. Everything outside a conservative allowlist is collapsed, and
    leading dots are stripped so no result can be "." or "..".
    """
    cleaned = _UNSAFE_COMPONENT.sub("_", str(text)).strip("._")
    return cleaned[:64] or fallback


def icon_stem(provider_id: str, local_id: str, artwork_id: str = "") -> str:
    """The filename stem for stored artwork.

    Namespaced by provider for the same reason AppEntry.key is: without it a
    Steam appid and a .desktop basename that happen to match would share a
    file in the icon store, and restoring one would delete artwork the other
    still points at.
    """
    parts = [safe_component(provider_id, "app"), safe_component(local_id, "id")]
    if artwork_id:
        parts.append(safe_component(artwork_id, "art"))
    return "_".join(parts)


def icon_roots() -> list[Path]:
    roots: list[Path] = []
    raw_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    for raw in raw_dirs.split(":"):
        if raw:
            roots.append(Path(raw) / "icons")
    return roots


def theme_roots() -> list[Path]:
    """Every directory that can contain installed icon themes."""
    roots = list(icon_roots())
    roots += [home() / ".icons", data_home() / "icons"]
    seen: set[str] = set()
    out: list[Path] = []
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            out.append(root)
    return out


def pixmaps_dir() -> Path:
    return Path("/usr/share/pixmaps")


# ---------------------------------------------------------------------------
# Probing paths we do not control
# ---------------------------------------------------------------------------
#
# Every scan walks directories supplied by the system, the user, or another
# package's installer. ``Path.is_dir`` and ``Path.is_file`` do not return
# False for something that cannot be stat'ed at all — they raise. An
# unreadable parent, a stale automount, or a Flatpak export directory being
# replaced mid-uninstall is therefore an uncaught exception rather than a
# directory to skip, and it takes the whole scan with it.

def is_readable_dir(path: Path) -> bool:
    """True when ``path`` is a directory that can actually be looked at."""
    try:
        return path.is_dir()
    except OSError:
        return False


def is_readable_file(path: Path) -> bool:
    """True when ``path`` is a file that can actually be looked at."""
    try:
        return path.is_file()
    except OSError:
        return False


def entries_matching(directory: Path, pattern: str) -> list[Path]:
    """Sorted matches inside ``directory``, or nothing if it cannot be read.

    Listing can fail even after is_dir() succeeded — the directory may lose
    its read bit, or vanish, between the two calls.
    """
    try:
        return sorted(directory.glob(pattern))
    except OSError:
        return []
