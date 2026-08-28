"""Every filesystem location Kairo reads or writes.

Exposed as functions rather than module constants so that the whole tree can
be redirected by setting ``HOME``. That is what makes the migration testable
against a fixture home instead of the developer's real desktop.
"""

from __future__ import annotations

import os
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


def config_dir() -> Path:
    return home() / ".config" / APP_DIRNAME


def config_file() -> Path:
    return config_dir() / "config.json"


def cache_dir() -> Path:
    return config_dir() / "cache"


def data_dir() -> Path:
    return home() / ".local" / "share" / APP_DIRNAME


def icon_store() -> Path:
    """Where artwork is copied so ``Icon=`` never points into a theme.

    A path into /usr/share/icons/<theme>/ dies the day that theme is upgraded
    or removed; a private copy keeps every override self-contained.
    """
    return data_dir() / "icons"


def applications_dir() -> Path:
    """The only directory Kairo ever writes launcher entries into."""
    return home() / ".local" / "share" / "applications"


def legacy_config_dir(name: str) -> Path:
    return home() / ".config" / name


def legacy_data_dir(name: str) -> Path:
    return home() / ".local" / "share" / name


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
        home() / ".local" / "share" / "flatpak" / "exports" / "share" / "applications",
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
    roots += [home() / ".icons", home() / ".local" / "share" / "icons"]
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
