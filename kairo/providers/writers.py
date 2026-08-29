"""The two launcher-writing strategies.

Both write only into ``~/.local/share/applications``. Neither ever touches
``/usr``, ``/usr/local`` or ``/var/lib/flatpak``, and neither needs root. That
is not incidental: writing a user-level entry that shadows the system copy is
what makes every change here reversible by deleting one file, and what lets a
package or Flatpak update continue to work normally underneath.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from kairo import paths
from kairo.desktop import entry as de
from kairo.models import AppEntry
from kairo.providers.base import VALID_ICON_EXTS, LauncherWriter


def store_icon(entry: AppEntry, icon_src: Path) -> Path:
    """Copy artwork into Kairo's private icon store and return the copy.

    Everything that ends up in an ``Icon=`` line goes through here first. A
    path into an installed theme dies when that theme is upgraded or removed,
    and a path into the user's Pictures folder dies when they tidy up; a
    private copy keeps every entry we write self-contained.
    """
    suffix = icon_src.suffix.lower()
    if suffix not in VALID_ICON_EXTS:
        raise ValueError(f"Unsupported icon type: {icon_src.suffix}")

    store = paths.icon_store()
    store.mkdir(parents=True, exist_ok=True)

    try:
        if icon_src.parent.resolve() == store.resolve():
            return icon_src           # already ours
    except OSError:
        pass

    digest = hashlib.md5(str(icon_src).encode()).hexdigest()[:8]
    dest = store / f"{paths.icon_stem(entry.provider_id, entry.local_id)}_{digest}{suffix}"
    shutil.copyfile(icon_src, dest)
    return dest


def _discard_stored_icon(path: Path | None, keep: Path | None = None) -> None:
    """Delete a superseded icon, but only if it is one of ours."""
    if path is None:
        return
    try:
        store = paths.icon_store().resolve()
        resolved = path.resolve()
        if keep is not None and resolved == keep.resolve():
            return
        if resolved.is_relative_to(store):
            path.unlink(missing_ok=True)
    except OSError:
        pass


class GeneratedEntryWriter(LauncherWriter):
    """For applications with no launcher entry of their own.

    Kairo creates the file from scratch, so every field in it is ours and
    restoring means deleting it. Steam games work this way; AppImages will.
    """

    action = "created"
    restore_label = "Remove shortcut"

    def restore_prompt(self, entry: AppEntry) -> str:
        return (f"Remove the launcher shortcut Kairo created for {entry.name}?\n\n"
                "The application itself is not affected — only the shortcut "
                "goes away. You can create it again at any time by giving the "
                "application artwork.")

    def __init__(self, prefix: str, build_fields):
        self.prefix = prefix
        self.build_fields = build_fields

    def target(self, entry: AppEntry) -> Path:
        return paths.applications_dir() / f"{self.prefix}{entry.local_id}.desktop"

    def existing(self, entry: AppEntry) -> Path | None:
        """Our entry for this app, including one written under an old prefix."""
        directory = paths.applications_dir()
        for prefix in paths.all_desktop_prefixes():
            candidate = directory / f"{prefix}{entry.local_id}.desktop"
            if candidate.is_file():
                return candidate
        return None

    def apply(self, entry: AppEntry, icon_src: Path) -> Path:
        target = self.target(entry)

        # A filename matching our naming scheme is not proof we wrote it.
        # Someone can create kairo-440.desktop by hand, and overwriting it
        # would destroy their work. Same rule the override writer follows and
        # the same rule migration follows.
        if target.exists() and not de.is_managed(target):
            raise ValueError(
                "There is already a launcher entry with this name that Kairo "
                "did not create. Remove or rename it first.")

        stored = store_icon(entry, icon_src)
        paths.applications_dir().mkdir(parents=True, exist_ok=True)

        previous_file = self.existing(entry)
        previous_icon = None
        previous_is_ours = False
        if previous_file is not None:
            previous_is_ours = de.is_managed(previous_file)
            if previous_is_ours:
                value = de.read_entry_icon(previous_file)
                previous_icon = Path(value) if value else None

        fields = self.build_fields(entry, stored)
        de.atomic_write_text(target, de.build_entry(fields))

        # An entry we wrote under a legacy prefix would otherwise linger and
        # show up in the launcher a second time. One we did not write is left
        # exactly where it is.
        if (previous_file is not None and previous_file != target
                and previous_is_ours):
            previous_file.unlink(missing_ok=True)

        _discard_stored_icon(previous_icon, keep=stored)

        entry.customized = True
        entry.current_icon = stored
        return stored

    def can_restore(self, entry: AppEntry) -> tuple[bool, str]:
        target = self.existing(entry)
        if target is None:
            return False, "No shortcut to remove."
        if not de.is_managed(target):
            return False, ("There is a launcher entry with this name that "
                           "Kairo did not create, so Kairo will not remove it.")
        return True, ""

    def restore(self, entry: AppEntry) -> None:
        allowed, reason = self.can_restore(entry)
        if not allowed:
            target = self.existing(entry)
            if target is None:
                entry.customized = False
                entry.current_icon = None
                return
            raise ValueError(reason)

        target = self.existing(entry)
        if target is not None:
            target.unlink(missing_ok=True)
        _discard_stored_icon(entry.current_icon)
        entry.customized = False
        entry.current_icon = None


class OverrideWriter(LauncherWriter):
    """For applications that already ship a launcher entry.

    The original file is copied verbatim into the user's applications
    directory and only the ``Icon=`` line inside ``[Desktop Entry]`` is
    rewritten. Regenerating it instead would destroy the application's desktop
    integration: default-handler associations, window matching and jump-list
    actions all live in fields we neither own nor understand.

    Restoring means deleting the override so the system copy shows through
    again. Native apps, Flatpaks and AppImages that install a .desktop all work
    this way, which is why they need no scanner of their own.
    """

    action = "overrode"
    restore_label = "Restore original"

    def restore_prompt(self, entry: AppEntry) -> str:
        return (f"Put back the original icon for {entry.name}?\n\n"
                "The application keeps its launcher entry.")

    def target(self, entry: AppEntry) -> Path:
        basename = entry.payload.get("basename") or f"{entry.local_id}.desktop"
        return paths.applications_dir() / basename

    def source(self, entry: AppEntry) -> Path | None:
        raw = entry.payload.get("source")
        return Path(raw) if raw else None

    def apply(self, entry: AppEntry, icon_src: Path) -> Path:
        source = self.source(entry)
        if source is None or not source.is_file():
            raise ValueError("Missing source .desktop file")

        target = self.target(entry)
        if target.parent.resolve() != paths.applications_dir().resolve():
            raise ValueError(
                "Overrides must be written under ~/.local/share/applications")
        if target.exists() and not de.is_managed(target):
            raise ValueError(
                "Refusing to overwrite a .desktop file this application "
                "did not create.")

        stored = store_icon(entry, icon_src)

        # Read the override if we already made one, so repeated applies do not
        # record our own previous icon as the "original".
        read_from = target if (target.exists() and de.is_managed(target)) else source
        text = de.read_text_exact(read_from)

        # If we already own this file, its recorded original icon is the real
        # one. Re-reading Icon= would capture our own previous choice and make
        # the true default unrecoverable after a second apply.
        original = de.entry_value_from_text(text, de.ORIGINAL_ICON_KEYS)
        if not original:
            original = de.read_entry_icon(source)

        previous_icon = None
        if target.exists():
            value = de.read_entry_icon(target)
            previous_icon = Path(value) if value else None

        rewritten = de.rewrite_entry_icon(text, str(stored), original)
        de.atomic_write_text(target, rewritten)
        _discard_stored_icon(previous_icon, keep=stored)

        entry.customized = True
        entry.current_icon = stored
        entry.payload["local"] = str(target)
        return stored

    def can_restore(self, entry: AppEntry) -> tuple[bool, str]:
        target = self.target(entry)
        if not target.exists():
            return False, "This application is already using its default icon."
        if not de.is_managed(target):
            return False, ("There is a .desktop file for this application in "
                           "your applications folder that Kairo did not "
                           "create. Remove it yourself if you want the "
                           "default icon back.")
        return True, ""

    def restore(self, entry: AppEntry) -> None:
        target = self.target(entry)
        allowed, reason = self.can_restore(entry)
        if not allowed:
            if not target.exists():
                entry.customized = False
                return
            raise ValueError(reason)

        previous_icon = None
        value = de.read_entry_icon(target)
        if value:
            previous_icon = Path(value)

        target.unlink()
        _discard_stored_icon(previous_icon)

        entry.customized = False
        source = self.source(entry)
        entry.current_icon = None
        if source is not None:
            from kairo.desktop.lookup import resolve_icon
            entry.icon_hint = de.read_entry_icon(source)
            entry.current_icon = resolve_icon(entry.icon_hint)
