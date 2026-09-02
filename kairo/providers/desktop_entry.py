"""Everything on the machine that ships a ``.desktop`` launcher entry.

This one provider already covers native packages, Flatpaks and AppImages,
because all three install a freedesktop entry into a directory on
``XDG_DATA_DIRS``. Adding a dedicated FlatpakProvider or AppImageProvider would
not widen coverage by a single application; it would only add richer metadata
(runtime, branch, bundle path). Build those when the metadata is wanted, not to
lengthen a feature list.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from kairo import paths
from kairo.desktop import entry as de
from kairo.desktop.lookup import resolve_icon
from kairo.models import AppEntry, ArtQuery, make_key
from kairo.providers.base import AppProvider, LauncherWriter
from kairo.providers.writers import OverrideWriter
from kairo.themeindex import THEME_ICON_EXTS

PROVIDER_ID = "desktop"


def current_desktops() -> set[str]:
    raw = os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or ""
    return {part.strip().lower() for part in re.split(r"[:;]", raw) if part.strip()}


def only_show_in_matches(value: str) -> bool:
    allowed = {part.strip().lower() for part in value.split(";") if part.strip()}
    current = current_desktops()
    return not allowed or not current or bool(allowed & current)


def not_show_in_matches(value: str) -> bool:
    """False when the entry is explicitly hidden from the current desktop."""
    denied = {part.strip().lower() for part in value.split(";") if part.strip()}
    current = current_desktops()
    if not denied or not current:
        return True
    return not (denied & current)


# ---------------------------------------------------------------------------
# Artwork queries
# ---------------------------------------------------------------------------

def theme_query_for(entry: AppEntry) -> str:
    """The icon name to look up in installed themes.

    ``Icon=`` is normally a bare name (``org.kde.dolphin``), which is exactly
    the key themes index under. Two cases need care:

    * An absolute path into our own icon store, which happens as soon as the
      user assigns anything. Its filename is a generated hash, so searching for
      it finds nothing.
    * Any other absolute path, e.g. /usr/share/pixmaps/foo.png.

    In both cases the .desktop basename is the better key, because that is the
    application id themes index under: org.kde.dolphin.desktop -> org.kde.dolphin.
    """
    raw = (entry.icon_hint or "").strip()
    fallback = Path(entry.payload.get("basename", "")).stem or entry.local_id

    if not raw:
        return fallback
    if raw.startswith(("/", "~")):
        expanded = Path(raw).expanduser()
        try:
            if expanded.is_relative_to(paths.icon_store()):
                return fallback           # our own generated filename
        except (ValueError, OSError):
            pass
        return fallback or expanded.stem
    return Path(raw).stem if Path(raw).suffix.lower() in THEME_ICON_EXTS else raw


def search_query_for(entry: AppEntry) -> str:
    """First free-text query to try, from the display name."""
    return (entry.name or "").strip().lower()


def fallback_query_for(entry: AppEntry) -> str:
    """Second query, used when the display name finds nothing.

    Desktop files are frequently named in reverse-DNS form and the final
    component is usually the canonical application id that icon sets index
    under: org.kde.dolphin -> dolphin, org.mozilla.firefox -> firefox.
    Returns "" when it would duplicate the primary query.
    """
    basename = entry.payload.get("basename", "")
    if not basename:
        return ""
    stem = Path(basename).stem
    candidate = stem.rsplit(".", 1)[-1].strip().lower()
    primary = search_query_for(entry)
    return candidate if candidate and candidate != primary else ""


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class DesktopEntryProvider(AppProvider):
    #: Read-only provenance metadata. Entries carry the path of
    #: the .desktop file that produced them, which is what makes
    #: package ownership answerable without a second scan.
    classifies_sources = True

    id = PROVIDER_ID
    label = "Applications"
    noun = "apps"
    group = "Library"
    order = 1

    # Installed themes first: an application declares its own icon name, so an
    # exact index hit is both offline and unambiguous.
    auto_match_sources = ("theme", "iconify")

    def writer(self) -> LauncherWriter:
        return OverrideWriter()

    def scan(self) -> list[AppEntry]:
        entries: dict[str, AppEntry] = {}
        local_dir = paths.applications_dir()

        for directory in paths.system_application_dirs():
            if not paths.is_readable_dir(directory):
                continue
            for path in paths.entries_matching(directory, "*.desktop"):
                basename = path.name

                # Our own generated entries belong to their own provider.
                if paths.is_generated_name(basename):
                    continue

                parser = de.parse(path)
                if parser is None:
                    continue                # malformed, unreadable, or no group
                section = parser["Desktop Entry"]

                if section.get("Type", "Application").strip() != "Application":
                    continue
                if de.get_bool(section, "NoDisplay") or de.get_bool(section, "Hidden"):
                    continue
                only = section.get("OnlyShowIn", "").strip()
                if only and not only_show_in_matches(only):
                    continue
                not_in = section.get("NotShowIn", "").strip()
                if not_in and not not_show_in_matches(not_in):
                    continue
                name = section.get("Name", "").strip()
                if not name:
                    continue

                local_path = local_dir / basename
                managed = (paths.is_readable_file(local_path)
                           and de.is_managed(local_path))
                icon_value = section.get("Icon", "").strip()

                # Later directories have higher precedence and overwrite
                # earlier ones, matching how the desktop resolves duplicates.
                entries[basename] = AppEntry(
                    key=make_key(self.id, Path(basename).stem),
                    provider_id=self.id,
                    name=name,
                    subtitle=basename,
                    icon_hint=icon_value,
                    current_icon=resolve_icon(icon_value),
                    customized=managed,
                    payload={
                        "basename": basename,
                        "source": str(path),
                        "local": str(local_path),
                    },
                )

        return sorted(entries.values(), key=lambda a: a.sort_key())

    def artwork_query(self, entry: AppEntry) -> ArtQuery:
        return ArtQuery(
            entry=entry,
            text=search_query_for(entry),
            fallback_text=fallback_query_for(entry),
            icon_name=theme_query_for(entry),
        )

    def system_source(self, basename: str) -> Path | None:
        """The system copy an override shadows, if it still exists.

        Absent when the application has since been uninstalled. Restoring then
        just removes the override, which is still the right outcome - it is
        the only way to clear a leftover for something no longer installed.
        """
        local = paths.applications_dir()
        for directory in paths.system_application_dirs():
            if directory == local:
                continue
            candidate = directory / basename
            if paths.is_readable_file(candidate):
                return candidate
        return None

    def claim(self, path: Path) -> tuple[str, str, dict] | None:
        """Any managed override in the user's applications directory."""
        if paths.is_generated_name(path.name):
            return None
        if path.parent.resolve() != paths.applications_dir().resolve():
            return None
        source = self.system_source(path.name)
        return (make_key(self.id, path.stem), "overrode", {
            "basename": path.name,
            "source": str(source) if source else "",
            "local": str(path),
        })

    def refresh(self, entry: AppEntry) -> None:
        local = Path(entry.payload.get("local") or
                     (paths.applications_dir() / entry.payload.get("basename", "")))
        if paths.is_readable_file(local) and de.is_managed(local):
            entry.customized = True
            value = de.read_entry_icon(local)
            entry.current_icon = Path(value) if value else None
            return
        entry.customized = False
        source = entry.payload.get("source")
        if source:
            entry.icon_hint = de.read_entry_icon(Path(source))
            entry.current_icon = resolve_icon(entry.icon_hint)
