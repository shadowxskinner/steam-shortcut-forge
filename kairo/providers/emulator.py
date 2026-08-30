"""One provider per configured emulator.

Every other provider discovers what it manages. This one is *told*: the user
names an emulator, points at its executable and at folders of ROMs, and each
configured emulator becomes its own destination in the sidebar. Cemu and PCSX2
are one folder each; Dolphin is two, because it covers GameCube and Wii with
different extensions and deserves to read as both.

Providers are built from configuration rather than hard-coded, so the registry
asks this module for a list rather than importing a class per emulator. Adding
support for another emulator is a row in Settings, not a code change.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from kairo import emulators as emu
from kairo import paths
from kairo.desktop import entry as de
from kairo.models import AppEntry, ArtQuery, make_key
from kairo.providers.base import AppProvider, LauncherWriter
from kairo.desktop.lookup import resolve_icon
from kairo.providers.steam import existing_generated
from kairo.providers.writers import GeneratedEntryWriter, has_custom_artwork

#: Provider ids are namespaced so a ROM can never collide with a Steam appid,
#: and so removing one emulator does not disturb another's history. A hyphen,
#: not a colon: AppEntry splits its key on the first colon, so a colon here
#: would leave the separator inside local_id and then inside a filename.
ID_PREFIX = "emu-"

GROUP = "Emulators"


def provider_id(emulator_id: str) -> str:
    return f"{ID_PREFIX}{emulator_id}"


def build_fields(emulator: emu.Emulator):
    """A field builder bound to one emulator's launch command.

    GeneratedEntryWriter takes a callable, so the emulator's executable and
    arguments are closed over here rather than looked up again at write time.
    """

    def fields(entry: AppEntry, icon: Path) -> dict[str, str]:
        rom = Path(entry.payload.get("rom", ""))
        command = emulator.command(rom)
        return {
            "Type": "Application",
            "Name": de.escape_value(entry.name.strip()),
            "Exec": " ".join(shlex.quote(part) for part in command),
            "Icon": str(icon),
            "Categories": "Game;Emulator;",
            "Terminal": "false",
            "StartupNotify": "true",
            "X-KairoEmulator": emulator.id,
            # Self-identifying, so ownership never rests on the filename.
            de.MANAGED_KEYS[0]: "true",
        }

    return fields


class EmulatorProvider(AppProvider):
    """The ROMs of one configured emulator."""

    noun = "games"
    group = GROUP

    # SteamGridDB first, by title rather than by appid. It is the only source
    # that carries actual game art; themes and Iconify carry symbols, and a
    # symbol is a poor substitute for a cover on a games shelf. Declared here
    # rather than decided in the UI, like every other provider.
    auto_match_sources = ("steamgriddb", "iconify", "theme")

    def __init__(self, emulator: emu.Emulator, order: int = 0):
        self.emulator = emulator
        self.id = provider_id(emulator.id)
        self.label = emulator.name
        self.order = order

    def available(self) -> bool:
        """Configured badly is still configured: the section stays visible.

        Hiding an emulator the user has just set up, because they typed the
        path wrong, would leave them nowhere to go and fix it. scan() returns
        nothing and the pane says why.
        """
        return bool(self.emulator.name)

    def problems(self) -> list[str]:
        return self.emulator.problems()

    def writer(self) -> LauncherWriter:
        return GeneratedEntryWriter(paths.DESKTOP_PREFIX,
                                    build_fields(self.emulator),
                                    default_icon="applications-games")

    def scan(self) -> list[AppEntry]:
        if not self.emulator.usable():
            return []
        entries: list[AppEntry] = []
        for rom in emu.scan(self.emulator):
            entry = AppEntry(
                key=make_key(self.id, rom.local_id),
                provider_id=self.id,
                name=rom.title,
                subtitle=rom.system or rom.path.name,
                payload={"rom": str(rom.path), "system": rom.system,
                         "emulator": self.emulator.id},
            )
            entries.append(entry)

        # One listing of the applications directory, then a dict lookup per
        # ROM. Asking the writer for each entry cost two stat calls apiece,
        # which is 4000 syscalls for a 2000-game library and is felt on any
        # disk slower than a tmpfs.
        existing = existing_generated()
        for entry in entries:
            path = existing.get(entry.local_id)
            if path is None:
                continue
            entry.customized = has_custom_artwork(path)
            value = de.read_entry_icon(path)
            entry.icon_hint = value
            entry.current_icon = (Path(value) if value.startswith("/")
                                  else resolve_icon(value))
        return entries

    def artwork_query(self, entry: AppEntry) -> ArtQuery:
        """Search on the cleaned title, with the system as a fallback term.

        ``Metroid Prime`` finds artwork; ``Metroid Prime GameCube`` finds it
        when the bare title is ambiguous, which is why the system rides along
        as the second attempt rather than being folded into the first.
        """
        title = (entry.name or "").strip()
        system = str(entry.payload.get("system", "")).strip()
        return ArtQuery(
            entry=entry,
            text=title.lower(),
            fallback_text=f"{title} {system}".strip().lower() if system else "",
            icon_name=title.lower(),
        )

    def refresh(self, entry: AppEntry) -> None:
        existing = existing_generated().get(entry.local_id)
        if existing is None:
            entry.customized = False
            entry.current_icon = None
            entry.icon_hint = ""
            return
        entry.customized = has_custom_artwork(existing)
        value = de.read_entry_icon(existing)
        entry.icon_hint = value
        entry.current_icon = (Path(value) if value.startswith("/")
                              else resolve_icon(value))

    def claim(self, path: Path):
        """Recognise a shortcut this emulator wrote, for adoption.

        Keyed on the marker Kairo writes into the file, so a shortcut whose
        ledger entry was lost can still be traced back to the emulator that
        produced it rather than being orphaned.
        """
        if not paths.is_generated_name(path.name):
            return None
        try:
            owner = de.read_entry_value(path, "X-KairoEmulator")
        except OSError:
            return None
        if owner != self.emulator.id:
            return None
        local_id = paths.strip_generated_prefix(path.name)
        if not local_id:
            return None
        return make_key(self.id, local_id), "created", {}


def providers_from_config(config: dict | None) -> list[EmulatorProvider]:
    """One provider per configured emulator, in configured order."""
    return [EmulatorProvider(emulator, order=index)
            for index, emulator in enumerate(emu.load(config))]
