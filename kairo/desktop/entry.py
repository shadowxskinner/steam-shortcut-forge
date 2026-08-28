"""Parsing and surgical editing of freedesktop ``.desktop`` files.

This module is deliberately free of any GUI import so that it can be unit
tested. It is the only place in Kairo that writes to a ``.desktop`` file, and
it is the most dangerous code in the project: it edits files that live in the
user's launcher directory.

Two rules govern everything here.

1. **Only ``Icon=`` inside the ``[Desktop Entry]`` group is ever touched.**
   A ``[Desktop Action ...]`` group may carry its own ``Icon=`` for a jump-list
   item; rewriting that would change an action's appearance for no reason.
2. **Everything else survives byte for byte.** ``MimeType``, ``StartupWMClass``,
   ``Actions``, translated ``Name[xx]`` keys, vendor ``X-*`` keys, comments,
   blank lines and the file's original line endings are all preserved. A
   regenerated file loses default-handler associations and window matching.
"""

from __future__ import annotations

import configparser
import os
import tempfile
from pathlib import Path

DESKTOP_ENTRY_GROUP = "[Desktop Entry]"

# Marker keys, most-preferred first. Kairo writes the first entry and accepts
# any of them on read. The legacy Shortcut Forge keys must stay in these tuples
# permanently: ``revert`` refuses to delete a file that carries no marker, so
# dropping the old key would strand every override made before the rename with
# no in-app way to restore the original icon.
MANAGED_KEYS: tuple[str, ...] = ("X-Kairo-Managed", "X-ShortcutForge-Managed")
ORIGINAL_ICON_KEYS: tuple[str, ...] = ("X-Kairo-OriginalIcon",
                                       "X-ShortcutForge-OriginalIcon")


class DesktopEntryError(ValueError):
    """Raised when a .desktop file cannot be safely edited."""


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def make_parser() -> configparser.RawConfigParser:
    """A parser configured for the .desktop dialect.

    ``optionxform = str`` keeps key case, which matters because ``Icon`` and
    ``X-Kairo-Managed`` are case sensitive in the spec. ``strict=False``
    tolerates duplicate keys rather than raising on a file we did not write.
    """
    parser = configparser.RawConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    return parser


def parse(path: Path) -> configparser.RawConfigParser | None:
    """Parse a .desktop file, or return None if it is unusable.

    Returns None rather than raising for malformed, unreadable or
    non-UTF-8 files, and for anything lacking a ``[Desktop Entry]`` group.
    Callers treat None as "skip this file".
    """
    parser = make_parser()
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, UnicodeDecodeError, OSError):
        return None
    if not parser.has_section("Desktop Entry"):
        return None
    return parser


def get_bool(entry, key: str) -> bool:
    try:
        return entry.getboolean(key, fallback=False)
    except ValueError:
        return False


def entry_icon_from_text(text: str) -> str:
    """The ``Icon=`` value from ``[Desktop Entry]``, or "" if absent.

    Scoped to the group deliberately. A plain scan for a line starting with
    ``Icon=`` also matches ``[Desktop Action ...]`` groups, which frequently
    declare their own, and would then report an action's icon as the
    application's.
    """
    for group, key, value, _raw in _iter_lines(text):
        if group == DESKTOP_ENTRY_GROUP and key == "Icon":
            return value.strip()
    return ""


def entry_value_from_text(text: str, keys: tuple[str, ...] | str) -> str:
    """First present value among ``keys`` in ``[Desktop Entry]``, else ""."""
    if isinstance(keys, str):
        keys = (keys,)
    found: dict[str, str] = {}
    for group, key, value, _raw in _iter_lines(text):
        if group == DESKTOP_ENTRY_GROUP and key in keys and key not in found:
            found[key] = value.strip()
    for key in keys:
        if key in found:
            return found[key]
    return ""


def read_entry_icon(path: Path) -> str:
    text = _read_text(path)
    return entry_icon_from_text(text) if text is not None else ""


def read_entry_value(path: Path, keys: tuple[str, ...] | str) -> str:
    text = _read_text(path)
    return entry_value_from_text(text, keys) if text is not None else ""


def managed_from_text(text: str, keys: tuple[str, ...] = MANAGED_KEYS) -> bool:
    return entry_value_from_text(text, keys).strip().lower() in {"true", "1", "yes"}


def is_managed(path: Path, keys: tuple[str, ...] = MANAGED_KEYS) -> bool:
    """True when the file carries one of our ownership markers set to true.

    This is the authoritative permission check before deleting or overwriting
    anything in the user's applications directory. A hand-written override
    carries no marker and must never be touched.
    """
    value = read_entry_value(path, keys).strip().lower()
    return value in {"true", "1", "yes"}


def read_text_exact(path: Path) -> str:
    """Read a .desktop file without translating its line endings.

    ``Path.read_text`` opens in universal-newline mode, which silently turns
    every CRLF into LF. The rewriter then sees an LF-only file, writes LF, and
    a CRLF file comes back with different bytes on every line - a change we
    never intended to make to somebody else's file. ``newline=""`` disables the
    translation so the original endings survive round-tripping.
    """
    with open(path, encoding="utf-8", errors="surrogateescape", newline="") as fh:
        return fh.read()


def _read_text(path: Path) -> str | None:
    try:
        return read_text_exact(path)
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Line-level scanning
# ---------------------------------------------------------------------------

def _split_key(line: str) -> tuple[str, str] | None:
    """Split a ``Key=Value`` line, or None for comments, blanks and headers."""
    stripped = line.lstrip()
    if not stripped or stripped.startswith(("#", ";", "[")) or "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    return key.strip(), value.rstrip("\r\n")


def _group_header(line: str) -> str | None:
    stripped = line.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        return stripped
    return None


def _iter_lines(text: str):
    """Yield ``(group, key, value, raw_line)`` for every line in the file.

    ``group`` is the current section header (or "" before the first one) and
    ``key``/``value`` are None for headers, comments and blank lines.
    """
    group = ""
    for raw in text.splitlines(keepends=True):
        header = _group_header(raw)
        if header is not None:
            group = header
            yield group, None, None, raw
            continue
        pair = _split_key(raw)
        if pair is None:
            yield group, None, None, raw
        else:
            yield group, pair[0], pair[1], raw


def detect_newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def escape_value(value: str) -> str:
    """Escape a value for a .desktop field."""
    return (value
            .replace("\\", "\\\\")
            .replace("\n", "\\n")
            .replace("\t", "\\t")
            .replace("\r", "\\r"))


def atomic_write_text(path: Path, text: str) -> None:
    """Write via a temp file in the same directory, then ``os.replace``.

    A crash or a full disk mid-write then leaves either the old file or the new
    one, never a truncated .desktop that the launcher will show as a broken
    entry. Same-directory placement keeps the replace on one filesystem, which
    is what makes it atomic.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".kairo-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def set_entry_values(text: str, values: dict[str, str]) -> str:
    """Set keys inside the first ``[Desktop Entry]`` group, preserving all else.

    Existing keys are replaced in place, so field order is kept; missing ones
    are appended to the end of the group. Every other line in the file -
    including keys we know nothing about, ``[Desktop Action ...]`` groups,
    comments, blank lines and the original line endings - is passed through
    untouched.

    Only the *first* ``[Desktop Entry]`` group is edited. The spec permits
    exactly one; a malformed file with two is left alone after the first rather
    than having lines silently dropped from it.

    Raises DesktopEntryError when there is no ``[Desktop Entry]`` group at all.
    Fabricating one would write a file into the launcher that claims to
    describe an application it knows nothing about.
    """
    newline = detect_newline(text)
    lines = text.splitlines(keepends=True)

    if not any(_group_header(ln) == DESKTOP_ENTRY_GROUP for ln in lines):
        raise DesktopEntryError("no [Desktop Entry] group")

    out: list[str] = []
    pending = dict(values)
    in_entry = False
    entry_seen = False

    def flush(buf: list[str]) -> None:
        """Append the keys that had no existing line to replace.

        A file whose last line has no trailing newline would otherwise get the
        first generated key glued onto it: ``Terminal=falseIcon=/path``.
        """
        if not pending:
            return
        if buf and not buf[-1].endswith(("\n", "\r")):
            buf[-1] = buf[-1] + newline
        for key, value in pending.items():
            buf.append(f"{key}={value}{newline}")
        pending.clear()

    for raw in lines:
        header = _group_header(raw)
        if header is not None:
            if in_entry:
                flush(out)
                in_entry = False
            if header == DESKTOP_ENTRY_GROUP and not entry_seen:
                in_entry = True
                entry_seen = True
            out.append(raw)
            continue

        if in_entry:
            pair = _split_key(raw)
            if pair is not None and pair[0] in pending:
                key = pair[0]
                out.append(f"{key}={pending.pop(key)}{newline}")
                continue
        out.append(raw)

    if in_entry:
        flush(out)

    return "".join(out)


def rewrite_entry_icon(
    text: str,
    icon_value: str,
    original_icon: str,
    *,
    managed_key: str = MANAGED_KEYS[0],
    original_key: str = ORIGINAL_ICON_KEYS[0],
) -> str:
    """Replace ``Icon=`` and stamp the ownership markers.

    Recording the pre-change icon makes a restore possible even if the source
    file later changes. Marker keys written by older releases are left in
    place, so a file stays revertable by both this build and the one that
    created it.
    """
    return set_entry_values(text, {
        "Icon": icon_value,
        managed_key: "true",
        original_key: original_icon,
    })


def build_entry(fields: dict[str, str], *, newline: str = "\n") -> str:
    """Render a fresh ``[Desktop Entry]`` file from ordered fields."""
    parts = [f"{DESKTOP_ENTRY_GROUP}{newline}"]
    for key, value in fields.items():
        parts.append(f"{key}={value}{newline}")
    return "".join(parts)
