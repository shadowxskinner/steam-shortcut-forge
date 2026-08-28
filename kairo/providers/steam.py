"""Steam games as a provider.

Steam is a first-class provider, not the application's identity. Everything
genuinely Steam-specific lives here: library discovery, ``appmanifest_*.acf``
parsing, and the ``steam://rungameid/`` launch command with its native and
Flatpak variants.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from kairo import paths
from kairo.desktop import entry as de
from kairo.models import AppEntry, ArtQuery, make_key
from kairo.providers.base import AppProvider, LauncherWriter
from kairo.providers.writers import GeneratedEntryWriter

PROVIDER_ID = "steam"

_RE_APPID = re.compile(r'"appid"\s+"(\d+)"')
_RE_NAME = re.compile(r'"name"\s+"([^"]+)"')

# Runtimes and redistributables are installed like games but are not games.
_SKIP_NAMES = {"steamworks common redistributables", "steam linux runtime"}

FLATPAK_STEAM_ID = "com.valvesoftware.Steam"


# ---------------------------------------------------------------------------
# Library discovery
# ---------------------------------------------------------------------------

def candidate_roots() -> list[Path]:
    """Standard Steam install locations, native and Flatpak."""
    h = paths.home()
    candidates = [
        h / ".steam" / "steam",
        h / ".local" / "share" / "Steam",
        h / ".var" / "app" / FLATPAK_STEAM_ID / ".local" / "share" / "Steam",
        h / ".var" / "app" / FLATPAK_STEAM_ID / "data" / "Steam",
        Path("/usr/share/steam"),
    ]
    return [p for p in candidates if (p / "steamapps").is_dir()]


def extra_libraries(steamapps: Path) -> list[Path]:
    """Additional library folders on other drives, from libraryfolders.vdf."""
    vdf = steamapps / "libraryfolders.vdf"
    if not vdf.is_file():
        return []
    try:
        text = vdf.read_text(errors="ignore")
    except OSError:
        return []
    out: list[Path] = []
    for raw in re.findall(r'"path"\s+"([^"]+)"', text):
        candidate = Path(raw.replace("\\\\", "/")) / "steamapps"
        if candidate.is_dir():
            out.append(candidate)
    return out


def find_steamapps() -> list[Path]:
    dirs: list[Path] = []
    seen: set[str] = set()
    for root in candidate_roots():
        steamapps = root / "steamapps"
        for directory in [steamapps, *extra_libraries(steamapps)]:
            try:
                key = str(directory.resolve())
            except OSError:
                continue
            if key not in seen:
                seen.add(key)
                dirs.append(directory)
    return dirs


# ---------------------------------------------------------------------------
# Launch command
# ---------------------------------------------------------------------------

def _flatpak_steam() -> bool:
    if not shutil.which("flatpak"):
        return False
    try:
        return subprocess.run(["flatpak", "info", FLATPAK_STEAM_ID],
                              capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def steam_cmd(appid: str) -> str:
    uri = f"steam://rungameid/{appid}"
    if shutil.which("steam"):
        return f"steam {uri}"
    if _flatpak_steam():
        return f"flatpak run {FLATPAK_STEAM_ID} {uri}"
    return f"xdg-open {uri}"


# ---------------------------------------------------------------------------
# Generated entries
# ---------------------------------------------------------------------------

def existing_generated() -> dict[str, Path]:
    """``{appid: path}`` for entries we generated, under any known prefix.

    Legacy prefixes are included, so shortcuts written before the rename stay
    visible to the app rather than every game reporting itself uncustomised.
    """
    out: dict[str, Path] = {}
    directory = paths.applications_dir()
    if not directory.is_dir():
        return out
    for prefix in paths.all_desktop_prefixes():
        for path in directory.glob(f"{prefix}*.desktop"):
            appid = paths.strip_generated_prefix(path.name)
            if appid and appid not in out:
                out[appid] = path
    return out


def build_fields(entry: AppEntry, icon: Path) -> dict[str, str]:
    """The complete contents of a generated Steam launcher entry."""
    appid = entry.local_id
    return {
        "Type": "Application",
        "Name": de.escape_value(entry.name.strip()),
        "Exec": steam_cmd(appid),
        "Icon": str(icon),
        "Categories": "Game;",
        "Terminal": "false",
        "StartupNotify": "true",
        "X-SteamAppId": appid,
        # Self-identifying, so ownership no longer rests on the filename alone.
        de.MANAGED_KEYS[0]: "true",
    }


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class SteamProvider(AppProvider):
    id = PROVIDER_ID
    label = "Steam"
    noun = "games"

    def available(self) -> bool:
        return bool(candidate_roots())

    def writer(self) -> LauncherWriter:
        return GeneratedEntryWriter(paths.DESKTOP_PREFIX, build_fields)

    def scan(self) -> list[AppEntry]:
        found: dict[str, AppEntry] = {}
        for steamapps in find_steamapps():
            for manifest in steamapps.glob("appmanifest_*.acf"):
                try:
                    text = manifest.read_text(errors="ignore")
                except OSError:
                    continue
                appid_match = _RE_APPID.search(text)
                name_match = _RE_NAME.search(text)
                if not appid_match or not name_match:
                    continue
                appid, name = appid_match.group(1), name_match.group(1)
                low = name.strip().lower()
                if low in _SKIP_NAMES or low.startswith("steam linux runtime"):
                    continue
                if appid in found:
                    continue
                found[appid] = AppEntry(
                    key=make_key(self.id, appid),
                    provider_id=self.id,
                    name=name,
                    subtitle=appid,
                    payload={"appid": appid, "library_root": str(steamapps)},
                )

        existing = existing_generated()
        for appid, app in found.items():
            path = existing.get(appid)
            if path is None:
                continue
            app.customized = True
            value = de.read_entry_icon(path)
            app.current_icon = Path(value) if value else None

        return sorted(found.values(), key=lambda a: a.sort_key())

    def artwork_query(self, entry: AppEntry) -> ArtQuery:
        return ArtQuery(
            entry=entry,
            text=(entry.name or "").strip().lower(),
            icon_name=(entry.name or "").strip().lower(),
            steam_appid=entry.local_id,
        )

    def refresh(self, entry: AppEntry) -> None:
        path = existing_generated().get(entry.local_id)
        entry.customized = path is not None
        if path is not None:
            value = de.read_entry_icon(path)
            entry.current_icon = Path(value) if value else None
        else:
            entry.current_icon = None
