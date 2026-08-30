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
import shutil
from dataclasses import dataclass, field
from pathlib import Path

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

    def display(self) -> str:
        return f"{self.name} — {self.emulator}" if self.emulator else self.name


CATALOGUE: tuple[System, ...] = (
    System("gamecube", "GameCube", (".iso", ".gcm", ".rvz", ".ciso", ".gcz", ".tgc"),
           ("dolphin-emu",), ("org.DolphinEmu.dolphin-emu",), ("-b", "-e"),
           ("gc", "gamecube", "ngc"), "Dolphin"),
    System("wii", "Wii", (".iso", ".wbfs", ".rvz", ".ciso", ".wad", ".nkit.iso"),
           ("dolphin-emu",), ("org.DolphinEmu.dolphin-emu",), ("-b", "-e"),
           ("wii",), "Dolphin"),
    System("wiiu", "Wii U", (".wud", ".wux", ".wua", ".rpx", ".elf"),
           ("cemu", "Cemu"), ("info.cemu.Cemu",), ("-g",),
           ("wiiu", "wii_u"), "Cemu"),
    System("ps2", "PlayStation 2", (".iso", ".chd", ".cso", ".bin", ".gz"),
           ("pcsx2-qt", "pcsx2"), ("net.pcsx2.PCSX2",), ("-batch",),
           ("ps2",), "PCSX2"),
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
        if (Path(root) / app_id).exists():
            return True
    return False


def find_executable(system: System) -> tuple[str, tuple[str, ...]]:
    """``(executable, leading arguments)`` for this system, or ``("", ())``.

    A native binary wins over a Flatpak: fewer moving parts, and the Flatpak
    form needs `flatpak run <id>` in front of everything else.
    """
    for command in system.commands:
        found = shutil.which(command)
        if found:
            return found, system.arguments
    for app_id in system.flatpaks:
        if _flatpak_installed(app_id):
            flatpak = shutil.which("flatpak") or "/usr/bin/flatpak"
            return flatpak, ("run", app_id, *system.arguments)
    return "", ()


def find_roms(system: System) -> str:
    """A conventional ROM folder for this system, if one exists and has files."""
    for root in ROM_ROOTS:
        base = Path(root).expanduser()
        if not base.is_dir():
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
    found = [Detection(system, *find_executable(system), find_roms(system))
             for system in CATALOGUE]
    found.sort(key=lambda d: (not d.installed, d.system.name.lower()))
    return found
