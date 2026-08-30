"""Emulators, their ROM folders, and the titles inside them.

Every provider so far has *discovered* what it manages: Steam has a library
file, applications have .desktop entries. An emulator has neither. It is the
first thing Kairo has to be told about, so this module owns that
configuration and the scanning that follows from it.

Toolkit-free on purpose, like the rest of the backend: nothing here imports a
GUI library, and its tests run with none installed.

The shape is driven by Dolphin. One emulator covers GameCube *and* Wii, with
different file extensions for each and a different name for the shelf they sit
on, so a folder is not a bare path - it carries its own extensions and its own
system label. An emulator with one folder is simply that case with one entry.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

CONFIG_KEY = "emulators"

#: Substituted with the ROM path when the launch command is built. Anything
#: else in the argument list is passed through untouched, so an emulator that
#: wants ``-e {rom}`` or ``--fullscreen {rom}`` can say so.
ROM_PLACEHOLDER = "{rom}"

#: Bracketed and parenthesised noise that dumps carry: regions, revisions,
#: languages, dump-quality markers. Stripped for the artwork search only - the
#: file on disk is never renamed and never moved.
_TAG = re.compile(r"[\(\[][^\)\]]*[\)\]]")
_SEPARATORS = re.compile(r"[._]+")
_SPACES = re.compile(r"\s{2,}")


def normalise_extension(value: str) -> str:
    """``ISO`` and ``.iso`` and `` .ISO `` all mean the same thing."""
    value = value.strip().lower()
    if not value:
        return ""
    return value if value.startswith(".") else f".{value}"


def slug(value: str) -> str:
    """Lowercase, hyphenated, and safe in a filename or a key."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned or "unnamed"


def clean_title(filename: str) -> str:
    """A searchable title from a ROM filename.

    ``Super Mario Sunshine (USA) (Rev 1) [!].rvz`` becomes ``Super Mario
    Sunshine``. Artwork lookups are only as good as the name handed to them,
    and dump tags are reliably noise. Multi-part extensions are handled by
    taking the stem repeatedly, so ``game.nkit.iso`` does not keep ``.nkit``.

    Falls back to the untouched stem when stripping would leave nothing: a
    file genuinely named ``(BIOS).bin`` is better shown as that than as blank.
    """
    stem = Path(filename).name
    while True:
        trimmed = Path(stem).stem
        if trimmed == stem:
            break
        stem = trimmed

    without_tags = _TAG.sub(" ", stem)
    spaced = _SEPARATORS.sub(" ", without_tags)
    if " " not in spaced:
        spaced = spaced.replace("-", " ")
    cleaned = _SPACES.sub(" ", spaced).strip(" -")
    return cleaned or stem.strip() or filename


@dataclass(frozen=True)
class RomFolder:
    """One directory of ROMs, and what counts as a ROM inside it.

    ``system`` is optional and cosmetic: it labels the entry so a Dolphin
    library reads as GameCube and Wii rather than one undifferentiated pile.
    It never affects where anything is written.
    """

    path: str
    extensions: tuple[str, ...] = ()
    system: str = ""

    def normalised(self) -> "RomFolder":
        seen: list[str] = []
        for raw in self.extensions:
            ext = normalise_extension(raw)
            if ext and ext not in seen:
                seen.append(ext)
        return replace(self, path=str(self.path).strip(),
                       extensions=tuple(seen), system=self.system.strip())

    def matches(self, name: str) -> bool:
        """True when ``name`` ends in one of this folder's extensions.

        Compared against the whole lowercased filename rather than
        ``Path.suffix``, so a configured ``.nkit.iso`` matches only that and
        not every ``.iso`` beside it.
        """
        lowered = name.lower()
        return any(lowered.endswith(ext) for ext in self.extensions)

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "extensions": list(self.extensions),
                "system": self.system}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RomFolder":
        extensions = raw.get("extensions") or []
        if isinstance(extensions, str):             # tolerate ".iso, .rvz"
            extensions = [p for p in re.split(r"[,\s]+", extensions) if p]
        return cls(path=str(raw.get("path", "")),
                   extensions=tuple(str(e) for e in extensions),
                   system=str(raw.get("system", ""))).normalised()


@dataclass(frozen=True)
class Emulator:
    """One configured emulator and the folders it plays from."""

    id: str = ""
    name: str = ""
    executable: str = ""
    arguments: tuple[str, ...] = (ROM_PLACEHOLDER,)
    folders: tuple[RomFolder, ...] = field(default_factory=tuple)

    def normalised(self) -> "Emulator":
        arguments = tuple(str(a) for a in self.arguments if str(a).strip())
        if ROM_PLACEHOLDER not in arguments:
            # Without it the emulator launches with no ROM at all, which is
            # never what a per-game shortcut is for.
            arguments = (*arguments, ROM_PLACEHOLDER)
        return replace(self,
                       id=(self.id or slug(self.name)),
                       name=self.name.strip(),
                       executable=str(self.executable).strip(),
                       arguments=arguments,
                       folders=tuple(f.normalised() for f in self.folders))

    def problems(self) -> list[str]:
        """Everything wrong with this configuration, in user-facing words."""
        issues: list[str] = []
        if not self.name.strip():
            issues.append("This emulator needs a name.")
        if not self.executable.strip():
            issues.append(f"{self.name or 'This emulator'} has no executable.")
        elif not Path(self.executable).expanduser().exists():
            issues.append(f"{self.executable} does not exist.")
        if not self.folders:
            issues.append(f"{self.name or 'This emulator'} has no ROM folders.")
        for folder in self.folders:
            if not folder.path:
                issues.append("A ROM folder has no path.")
            elif not Path(folder.path).expanduser().is_dir():
                issues.append(f"{folder.path} is not a folder.")
            elif not folder.extensions:
                issues.append(f"{folder.path} has no file extensions set.")
        return issues

    def usable(self) -> bool:
        return not self.problems()

    def command(self, rom: Path) -> list[str]:
        """The argv for launching ``rom``, with the placeholder substituted."""
        executable = str(Path(self.executable).expanduser())
        return [executable] + [str(rom) if arg == ROM_PLACEHOLDER else arg
                               for arg in self.arguments]

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name,
                "executable": self.executable,
                "arguments": list(self.arguments),
                "folders": [f.as_dict() for f in self.folders]}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Emulator":
        arguments = raw.get("arguments") or [ROM_PLACEHOLDER]
        if isinstance(arguments, str):
            arguments = arguments.split()
        return cls(id=str(raw.get("id", "")),
                   name=str(raw.get("name", "")),
                   executable=str(raw.get("executable", "")),
                   arguments=tuple(str(a) for a in arguments),
                   folders=tuple(RomFolder.from_dict(f)
                                 for f in raw.get("folders") or [])).normalised()


@dataclass(frozen=True)
class Rom:
    """One ROM found on disk."""

    emulator_id: str
    path: Path
    title: str
    system: str = ""

    @property
    def local_id(self) -> str:
        """Stable, readable, and legal in a filename.

        The provider id already namespaces this, so the emulator is not
        repeated here. Built from the file's own stem and a digest of its
        full path: no slashes or colons to break a .desktop filename, and
        nothing derived from the display title, so correcting a title later
        cannot orphan that shortcut's history.
        """
        digest = hashlib.sha1(str(self.path).encode()).hexdigest()[:8]
        return f"{slug(self.path.stem)[:48]}-{digest}"


def load(config: dict[str, Any] | None) -> list[Emulator]:
    """Read the configured emulators. Never raises on malformed data."""
    raw = (config or {}).get(CONFIG_KEY) or []
    out: list[Emulator] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            emulator = Emulator.from_dict(item)
        except (TypeError, ValueError):
            continue
        if emulator.name:
            out.append(emulator)
    return out


def store(emulators: Iterable[Emulator]) -> list[dict[str, Any]]:
    """The JSON-safe form, for writing back into the config."""
    return [e.normalised().as_dict() for e in emulators]


def scan(emulator: Emulator) -> list[Rom]:
    """Every ROM under one emulator's folders.

    Walked recursively, because collections are usually filed by system or by
    letter. An unreadable folder is skipped rather than raised: one bad path
    should not cost you the rest of the library.
    """
    found: list[Rom] = []
    seen: set[Path] = set()
    for folder in emulator.folders:
        if not folder.extensions:
            continue
        root = Path(folder.path).expanduser()
        try:
            if not root.is_dir():
                continue
            candidates = sorted(root.rglob("*"))
        except OSError:
            continue
        for path in candidates:
            try:
                if not path.is_file() or not folder.matches(path.name):
                    continue
                resolved = path.resolve()
            except OSError:
                continue
            if resolved in seen:        # overlapping folders, or a symlink
                continue
            seen.add(resolved)
            found.append(Rom(emulator_id=emulator.id, path=path,
                             title=clean_title(path.name),
                             system=folder.system))
    found.sort(key=lambda rom: (rom.system.lower(), rom.title.lower()))
    return found
