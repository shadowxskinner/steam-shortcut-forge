"""What Kairo already knows about game systems and the emulators that run them.

Every comparable tool ships this rather than asking for it. ES-DE has
es_systems.xml with the extensions and launch command for each system; Steam
ROM Manager has community presets you pick by name; EmuDeck standardises the
ROM folder layout so there is nothing to point at. Asking a person to type
".rvz" is asking them to be the database.

So Kairo carries a small catalogue: a system knows its own file extensions and
the emulators that usually run it, and an emulator knows how it is invoked.
Anything not in here is still reachable by describing it by hand - the
catalogue is a shortcut, never a limit.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from kairo import paths
from kairo.desktop import entry as de

#: Where ROM collections conventionally live. EmuDeck's layout first, since it
#: is the most standardised, then the obvious hand-rolled ones.
ROM_ROOTS = (
    "~/Emulation/roms",
    "~/Games/roms",
    "~/ROMs",
    "~/roms",
)


@dataclass(frozen=True)
class System:
    """One console, and how to recognise and run its games."""

    id: str
    name: str
    extensions: tuple[str, ...]
    #: Executables that run this system, most preferred first. Plain names are
    #: looked up on PATH; a Flatpak id is tried through `flatpak run`.
    commands: tuple[str, ...] = ()
    flatpaks: tuple[str, ...] = ()
    #: Extra arguments the emulator wants, before the ROM.
    arguments: tuple[str, ...] = ()
    #: Directory names a collection of these games is usually filed under.
    folders: tuple[str, ...] = ()
    emulator: str = ""
    #: Where this emulator records its own ROM directories, and the keys it
    #: uses. Reading it means the folder never has to be pointed at by hand.
    config: str = ""
    config_keys: tuple[str, ...] = ()
    #: Sandboxed packages keep the same file below a different data root.
    config_fallbacks: tuple[str, ...] = ()
    #: Restrict generic key parsing when an INI uses the same name elsewhere.
    config_section: str = ""

    def display(self) -> str:
        return f"{self.name} — {self.emulator}" if self.emulator else self.name


CATALOGUE: tuple[System, ...] = (
    System("gamecube", "GameCube", (".iso", ".gcm", ".rvz", ".ciso", ".gcz", ".tgc"),
           ("dolphin-emu",), ("org.DolphinEmu.dolphin-emu",), ("-b", "-e"),
           ("gc", "gamecube", "ngc"), "Dolphin",
           "~/.config/dolphin-emu/Dolphin.ini", ("ISOPath",)),
    System("wii", "Wii", (".iso", ".wbfs", ".rvz", ".ciso", ".wad", ".nkit.iso"),
           ("dolphin-emu",), ("org.DolphinEmu.dolphin-emu",), ("-b", "-e"),
           ("wii",), "Dolphin",
           "~/.config/dolphin-emu/Dolphin.ini", ("ISOPath",)),
    System("wiiu", "Wii U", (".wud", ".wux", ".wua", ".rpx", ".elf"),
           ("cemu", "Cemu"), ("info.cemu.Cemu",), ("-g",),
           ("wiiu", "wii_u"), "Cemu"),
    System("ps2", "PlayStation 2",
           (".iso", ".bin", ".img", ".mdf", ".gz", ".cso", ".zso", ".chd", ".elf"),
           ("pcsx2-qt", "pcsx2"), ("net.pcsx2.PCSX2",), ("-batch",),
           ("ps2",), "PCSX2",
           "~/.config/PCSX2/inis/PCSX2.ini", ("Paths", "RecursivePaths"),
           ("~/.var/app/net.pcsx2.PCSX2/config/PCSX2/inis/PCSX2.ini",),
           "GameList"),
    System("ps1", "PlayStation", (".cue", ".chd", ".pbp", ".bin", ".img"),
           ("duckstation-qt", "duckstation"), ("org.duckstation.DuckStation",),
           ("-batch",), ("ps1", "psx"), "DuckStation"),
    System("ps3", "PlayStation 3", (".iso", ".pkg"),
           ("rpcs3",), ("net.rpcs3.RPCS3",), (), ("ps3",), "RPCS3"),
    System("psp", "PSP", (".iso", ".cso", ".chd", ".pbp"),
           ("PPSSPPQt", "PPSSPPSDL", "ppsspp"), ("org.ppsspp.PPSSPP",), (),
           ("psp",), "PPSSPP"),
    System("switch", "Switch", (".nsp", ".xci"),
           ("ryujinx", "Ryujinx"), ("org.ryujinx.Ryujinx",), (),
           ("switch",), "Ryujinx"),
    System("3ds", "Nintendo 3DS", (".3ds", ".cci", ".cxi", ".app", ".3dsx"),
           ("azahar", "citra-qt", "citra"), ("org.azahar_emu.Azahar",), (),
           ("3ds", "n3ds"), "Azahar"),
    System("nds", "Nintendo DS", (".nds", ".dsi"),
           ("melonDS", "melonds", "desmume"), ("net.kuribo64.melonDS",), (),
           ("nds", "ds"), "melonDS"),
    System("n64", "Nintendo 64", (".z64", ".n64", ".v64", ".ndd"),
           ("simple64-gui", "mupen64plus-gui", "mupen64plus"),
           ("io.github.simple64.simple64",), (), ("n64",), "simple64"),
    System("snes", "Super Nintendo", (".sfc", ".smc", ".fig", ".swc"),
           ("snes9x-gtk", "snes9x"), ("com.snes9x.Snes9x",), (),
           ("snes", "sfc"), "Snes9x"),
    System("nes", "NES", (".nes", ".unf", ".unif", ".fds"),
           ("mesen",), ("io.github.mesen.Mesen",), (), ("nes", "fds"), "Mesen"),
    System("gba", "Game Boy Advance", (".gba",),
           ("mgba-qt", "mgba"), ("io.mgba.mGBA",), (), ("gba",), "mGBA"),
    System("gb", "Game Boy", (".gb", ".gbc"),
           ("mgba-qt", "mgba"), ("io.mgba.mGBA",), (), ("gb", "gbc"), "mGBA"),
    System("genesis", "Mega Drive", (".md", ".gen", ".smd", ".bin"),
           ("retroarch",), ("org.libretro.RetroArch",), (),
           ("genesis", "megadrive"), "RetroArch"),
    System("dreamcast", "Dreamcast", (".gdi", ".cdi", ".chd", ".cue"),
           ("flycast",), ("org.flycast.Flycast",), (),
           ("dreamcast", "dc"), "Flycast"),
)


def by_id(system_id: str) -> System | None:
    for system in CATALOGUE:
        if system.id == system_id:
            return system
    return None


def _flatpak_installed(app_id: str) -> bool:
    for root in ("/var/lib/flatpak/exports/bin",
                 os.path.expanduser("~/.local/share/flatpak/exports/bin")):
        try:
            if (Path(root) / app_id).exists():
                return True
        except OSError:
            continue        # unreadable is not installed
    return False


#: Field codes a launcher substitutes. Meaningless to us and must not survive
#: into a command line.
_FIELD_CODE = re.compile(r"%[fFuUdDnNickvm]")


def from_desktop_entry(system: System) -> tuple[str, tuple[str, ...], str]:
    """Find the emulator through its installed launcher entry.

    This is the general answer to "how was it installed". A native package, an
    AUR build, a Flatpak, a Snap and an AppImage all drop a .desktop file, and
    its Exec line is the command that actually works on this machine — no
    guessing at binary names or export paths.
    """
    wanted = {f"{app_id}.desktop".lower() for app_id in system.flatpaks}
    wanted |= {f"{command}.desktop".lower() for command in system.commands}
    for directory in paths.system_application_dirs():
        # is_dir() raises rather than returning False on a directory the user
        # cannot stat, and one unreadable entry in XDG_DATA_DIRS would
        # otherwise crash the emulator picker on the way open.
        try:
            if not directory.is_dir():
                continue
            candidates = sorted(directory.glob("*.desktop"))
        except OSError:
            continue
        for path in candidates:
            if path.name.lower() not in wanted:
                continue
            parser = de.parse(path)
            if parser is None:
                continue
            exec_line = parser["Desktop Entry"].get("Exec", "").strip()
            if not exec_line:
                continue
            parts = _FIELD_CODE.sub("", exec_line).split()
            if not parts:
                continue
            # Icon= is the authoritative name. Deriving it from the executable
            # works for Dolphin by luck and misses PCSX2, DuckStation, PPSSPP,
            # simple64 and snes9x, whose binaries are not named after their
            # icons.
            icon = parser["Desktop Entry"].get("Icon", "").strip()
            return parts[0], (*parts[1:], *system.arguments), icon
    return "", (), ""


def find_executable(system: System) -> tuple[str, tuple[str, ...], str]:
    """``(executable, leading arguments)`` for this system, or ``("", ())``.

    A native binary on PATH first, then the installed launcher entry — which
    covers Flatpak, Snap, AppImage and anything else that registers itself —
    then the Flatpak export directories as a last resort.
    """
    # The command is found exactly as before — a native binary first, then
    # the launcher entry, then the Flatpak exports. Only the icon name is new,
    # and it always comes from the launcher entry when there is one, because
    # that is the only place it is declared rather than guessed.
    _entry_exec, _entry_args, declared = from_desktop_entry(system)
    for command in system.commands:
        found = shutil.which(command)
        if found:
            return found, system.arguments, declared or command
    if _entry_exec:
        return _entry_exec, _entry_args, declared
    for app_id in system.flatpaks:
        if _flatpak_installed(app_id):
            flatpak = shutil.which("flatpak") or "/usr/bin/flatpak"
            return flatpak, ("run", app_id, *system.arguments), declared or app_id
    return "", (), ""


def _config_path(value: str) -> Path:
    """Expand an emulator config path with XDG's native override.

    Catalogue entries use ``~/.config`` because it is readable and portable,
    but PCSX2 follows ``XDG_CONFIG_HOME`` when it is set. Treat that prefix as
    the conventional default, not as a hard-coded location.
    """
    prefix = "~/.config/"
    if value.startswith(prefix):
        return paths.config_home() / value[len(prefix):]
    return Path(value).expanduser()


def from_emulator_config(system: System) -> list[str]:
    """ROM directories the emulator has already been told about.

    Dolphin records its ISO paths in Dolphin.ini, and every setup guide for
    every one of these tools ends with "make this match what you set in the
    emulator". If the emulator already knows, Kairo can just read it.
    """
    locations = tuple(value for value in (system.config, *system.config_fallbacks)
                      if value)
    if not locations:
        return []
    found: list[str] = []
    for location in locations:
        try:
            text = _config_path(location).read_text(errors="ignore")
        except OSError:
            continue
        section = ""
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped[1:-1].strip()
                continue
            if (system.config_section
                    and section.casefold() != system.config_section.casefold()):
                continue
            key, separator, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if not separator or not value:
                continue
            # Dolphin numbers them: ISOPath0, ISOPath1, ... PCSX2 stores
            # repeated Paths/RecursivePaths values in its GameList section.
            if not any(key.startswith(prefix) for prefix in system.config_keys):
                continue
            candidate = Path(value).expanduser()
            if candidate.is_dir() and str(candidate) not in found:
                found.append(str(candidate))
    return found


def find_roms(system: System) -> str:
    """Where this system's games are, without being told.

    The emulator's own configuration first — it is authoritative and it is
    what the user already set up — then the conventional layouts.
    """
    for directory in from_emulator_config(system):
        base = Path(directory)
        try:
            for path in base.rglob("*"):
                if path.suffix.lower() in system.extensions and path.is_file():
                    return str(base)
        except OSError:
            continue

    for root in ROM_ROOTS:
        base = Path(root).expanduser()
        try:
            if not base.is_dir():
                continue
        except OSError:
            continue
        for name in system.folders:
            candidate = base / name
            try:
                if not candidate.is_dir():
                    continue
                for path in candidate.rglob("*"):
                    if path.suffix.lower() in system.extensions and path.is_file():
                        return str(candidate)
            except OSError:
                continue
    return ""


@dataclass(frozen=True)
class Detection:
    """What Kairo found for one system on this machine."""

    system: System
    executable: str = ""
    arguments: tuple[str, ...] = field(default_factory=tuple)
    icon: str = ""
    roms: str = ""

    @property
    def installed(self) -> bool:
        return bool(self.executable)


def detect() -> list[Detection]:
    """Every catalogue system, with whatever was found for it.

    Systems whose emulator is installed come first: those are the ones worth
    offering. The rest stay in the list so a system can still be set up before
    its emulator is, rather than silently disappearing.
    """
    found = []
    for system in CATALOGUE:
        executable, arguments, icon = find_executable(system)
        found.append(Detection(system, executable, arguments, icon,
                               find_roms(system)))
    found.sort(key=lambda d: (not d.installed, d.system.name.lower()))
    return found
