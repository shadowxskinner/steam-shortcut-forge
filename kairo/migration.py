"""One-time migration from Steam Shortcut Forge to Kairo.

Renaming the application moves three things a user already has on disk: their
config, their icon store, and the launcher entries that point into it. Getting
this wrong is not a cosmetic failure.

* Every ``.desktop`` Kairo has ever written contains an absolute path into the
  icon store. Moving the store without rewriting those lines leaves the entry
  in place with its artwork silently gone - a delayed, invisible breakage that
  looks like Kairo broke the user's desktop.
* Generated entries were discovered by filename prefix. Changing the prefix
  without moving the files makes every previously created shortcut invisible to
  the app, so the whole library reports itself uncustomised while the old files
  stay in the launcher as duplicates nothing can remove.
* Overrides are protected by a marker key inside the file. Changing the key
  without accepting the old one makes every existing override permanently
  unrevertable, because restore refuses on any file carrying no marker.

The third is handled permanently rather than by migration: ``MANAGED_KEYS`` and
``ORIGINAL_ICON_KEYS`` in ``desktop.entry`` list the Kairo key first and the
Shortcut Forge key second, and every read accepts either. Those tuples are not
cleanup material - dropping the legacy entry at any point in the future would
strand exactly the users this migration was written to protect.

Design rules:

* **Copy config and icons; move only the generated entries.** Copying leaves
  the old installation intact, so a user who downgrades or hits a bug is not
  stranded. Generated entries must move, because two copies of the same game in
  the launcher is a visible regression.
* **Atomic per-file writes.** A crash mid-migration leaves whole files.
* **Never block launch.** Every step is individually guarded; failures are
  recorded in the report and Kairo starts normally. A migration that bricks
  startup is worse than one that skips three files.
* **Never delete user data automatically.** The old directories stay where they
  are. Removing them is a separate, explicit action.
* **Idempotent.** Completion is recorded in the new config, and every step is
  safe to re-run regardless.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from kairo import paths
from kairo.desktop import entry as de

#: Config key recording that migration has run.
MIGRATED_FROM = "migrated_from"
MIGRATED_AT = "migrated_at"
MIGRATION_REPORT = "migration_report"


@dataclass
class MigrationReport:
    performed: bool = False
    already_done: bool = False
    source_name: str = ""
    config_copied: bool = False
    icons_copied: int = 0
    shortcuts_moved: int = 0
    overrides_updated: int = 0
    failures: list[str] = field(default_factory=list)
    #: Legacy entries whose Kairo-named target already existed and could not
    #: be proven to belong to Kairo. Both files are left untouched.
    collisions: list[str] = field(default_factory=list)
    #: Legacy-prefixed files with no evidence of being ours. Never touched.
    skipped_foreign: list[str] = field(default_factory=list)

    @property
    def changed_anything(self) -> bool:
        return bool(self.shortcuts_moved or self.overrides_updated
                    or self.icons_copied or self.config_copied)

    def summary(self) -> str:
        if not self.performed:
            return ""
        bits = []
        if self.shortcuts_moved:
            bits.append(f"{self.shortcuts_moved} shortcut(s)")
        if self.overrides_updated:
            bits.append(f"{self.overrides_updated} icon override(s)")
        if self.icons_copied:
            bits.append(f"{self.icons_copied} icon file(s)")
        moved = ", ".join(bits) if bits else "your settings"
        text = f"Migrated {moved} from Steam Shortcut Forge."
        if self.collisions:
            text += (f" {len(self.collisions)} entr(y/ies) were left alone "
                     "because a file with the new name already exists.")
        if self.failures:
            text += f" {len(self.failures)} item(s) could not be migrated."
        return text

    def as_dict(self) -> dict:
        return {
            "shortcuts_moved": self.shortcuts_moved,
            "overrides_updated": self.overrides_updated,
            "icons_copied": self.icons_copied,
            "config_copied": self.config_copied,
            "failures": self.failures,
            "collisions": self.collisions,
            "skipped_foreign": self.skipped_foreign,
        }


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _read_new_config() -> dict:
    path = paths.config_file()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def legacy_generated_evidence(text: str, local_id: str, legacy_store: Path) -> str:
    """Why we believe a legacy-named .desktop was written by us, or "".

    The filename prefix alone is not proof. Someone can create
    ``steam-shortcut-forge-anything.desktop`` by hand, and a rename must not
    give Kairo licence to move or rewrite a file it did not create. Generated
    entries from before 2.0.0 carried no ownership marker - they were found by
    prefix - so evidence has to come from what the old generator actually
    wrote into them.

    Any single one of these is conclusive; a file with none is left alone.
    """
    if not text.strip():
        return ""
    try:
        if not any(_ln.strip() == de.DESKTOP_ENTRY_GROUP
                   for _ln in text.splitlines()):
            return ""
    except Exception:
        return ""

    if de.managed_from_text(text):
        return "carries a Kairo ownership marker"
    if de.entry_value_from_text(text, "X-SteamAppId") == local_id:
        return "X-SteamAppId matches the filename"

    icon = de.entry_icon_from_text(text)
    if icon.startswith("/"):
        try:
            if Path(icon).is_relative_to(legacy_store):
                return "icon points into the old icon store"
        except ValueError:
            pass

    if local_id and f"rungameid/{local_id}" in de.entry_value_from_text(text, "Exec"):
        return "Exec launches the matching Steam app"
    return ""


def _has_legacy_launcher_entries(name: str) -> bool:
    """True when launcher entries prove an old install, even with its dirs gone.

    Users clear ~/.config and ~/.local/share far more readily than they clear
    ~/.local/share/applications, because the launcher entries are the part they
    can see. Detecting only on the directories would strand exactly those
    shortcuts: invisible to Kairo, undeletable from the launcher.
    """
    applications = paths.applications_dir()
    if not applications.is_dir():
        return False
    legacy_store = paths.legacy_icon_store(name)

    for prefix in paths.LEGACY_DESKTOP_PREFIXES:
        for path in applications.glob(f"{prefix}*.desktop"):
            local_id = paths.strip_generated_prefix(path.name)
            try:
                text = de.read_text_exact(path)
            except OSError:
                continue
            if legacy_generated_evidence(text, local_id, legacy_store):
                return True

    # An override stamped with the old marker is unambiguous proof.
    for path in applications.glob("*.desktop"):
        if paths.is_generated_name(path.name):
            continue
        if de.is_managed(path, de.MANAGED_KEYS[1:]):
            return True
    return False


def find_legacy_install() -> str | None:
    """The name of an older installation with data worth migrating."""
    for name in paths.LEGACY_APP_DIRNAMES:
        if (paths.legacy_config_dir(name).is_dir()
                or paths.legacy_data_dir(name).is_dir()
                or _has_legacy_launcher_entries(name)):
            return name
    return None


def needs_migration() -> bool:
    if _read_new_config().get(MIGRATED_FROM):
        return False
    return find_legacy_install() is not None


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def _repoint_icon(value: str, legacy_store: Path, new_store: Path) -> str | None:
    """Rewrite an ``Icon=`` path that points into the old icon store."""
    if not value or not value.startswith("/"):
        return None
    candidate = Path(value)
    try:
        if not candidate.is_relative_to(legacy_store):
            return None
    except ValueError:
        return None
    return str(new_store / candidate.relative_to(legacy_store))


def _migrate_config(legacy_name: str, report: MigrationReport) -> dict:
    """Old settings, with anything already in the new config taking priority."""
    merged: dict = {}
    legacy_file = paths.legacy_config_dir(legacy_name) / "config.json"
    if legacy_file.is_file():
        try:
            data = json.loads(legacy_file.read_text())
            if isinstance(data, dict):
                merged.update(data)
                report.config_copied = True
        except (json.JSONDecodeError, OSError) as exc:
            report.failures.append(f"config.json: {exc}")

    # The cache is deliberately not migrated: the theme index, thumbnails and
    # game-id lookups all rebuild themselves, and the index format changed.
    merged.update(_read_new_config())
    return merged


def _migrate_icons(legacy_name: str, report: MigrationReport) -> None:
    source = paths.legacy_icon_store(legacy_name)
    if not source.is_dir():
        return
    dest = paths.icon_store()
    dest.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.iterdir()):
        if not path.is_file():
            continue
        target = dest / path.name
        if target.exists():
            continue                    # already migrated
        try:
            shutil.copyfile(path, target)
            report.icons_copied += 1
        except OSError as exc:
            report.failures.append(f"{path.name}: {exc}")


def _kairo_values(text: str, legacy_store: Path, new_store: Path) -> dict[str, str]:
    """The keys to set on a file being brought forward into Kairo."""
    values: dict[str, str] = {de.MANAGED_KEYS[0]: "true"}
    repointed = _repoint_icon(de.entry_icon_from_text(text), legacy_store, new_store)
    if repointed:
        values["Icon"] = repointed
    return values


def _migrate_generated(legacy_name: str, report: MigrationReport) -> None:
    """Rename generated entries and repoint them at the new icon store.

    Three things can go wrong here and each has to be handled without ever
    damaging a file we cannot prove we wrote:

    * The legacy file may not be ours at all - anyone can create a file whose
      name happens to start with our old prefix.
    * A file with the new Kairo name may already exist. If it is ours it
      supersedes the legacy copy; if it is not, both files are left exactly as
      they are and the collision is reported.
    * The file may simply be unreadable.
    """
    applications = paths.applications_dir()
    if not applications.is_dir():
        return
    legacy_store = paths.legacy_icon_store(legacy_name)
    new_store = paths.icon_store()

    for prefix in paths.LEGACY_DESKTOP_PREFIXES:
        for path in sorted(applications.glob(f"{prefix}*.desktop")):
            local_id = paths.strip_generated_prefix(path.name)
            if not local_id:
                continue
            target = applications / f"{paths.DESKTOP_PREFIX}{local_id}.desktop"

            try:
                text = de.read_text_exact(path)
            except OSError as exc:
                report.failures.append(f"{path.name}: {exc}")
                continue

            evidence = legacy_generated_evidence(text, local_id, legacy_store)
            if not evidence:
                # Named like ours, but nothing says we wrote it. Hands off.
                report.skipped_foreign.append(
                    f"{path.name}: no evidence Kairo created it")
                continue

            try:
                if target.exists() and target != path:
                    if not de.is_managed(target):
                        # Cannot prove the target is ours. Leaving the legacy
                        # file in place too, so nothing is lost either way.
                        report.collisions.append(
                            f"{target.name} already exists and was not created "
                            f"by Kairo — left it and {path.name} untouched")
                        continue
                    # The Kairo-named file is ours and is the current one; the
                    # legacy copy is a leftover, most likely from a migration
                    # interrupted between writing and deleting.
                    target_text = de.read_text_exact(target)
                    de.atomic_write_text(target, de.set_entry_values(
                        target_text, _kairo_values(target_text, legacy_store, new_store)))
                    path.unlink()
                    report.shortcuts_moved += 1
                    continue

                de.atomic_write_text(target, de.set_entry_values(
                    text, _kairo_values(text, legacy_store, new_store)))
                # Must be a move: leaving both would duplicate the entry.
                if path != target:
                    path.unlink()
                report.shortcuts_moved += 1
            except (OSError, de.DesktopEntryError, ValueError) as exc:
                report.failures.append(f"{path.name}: {exc}")


def _migrate_overrides(legacy_name: str, report: MigrationReport) -> None:
    """Stamp Kairo markers onto existing overrides and repoint their icons.

    The legacy marker keys are left in place alongside the new ones, so a file
    written here stays recognisable to the release that created it.
    """
    applications = paths.applications_dir()
    if not applications.is_dir():
        return
    legacy_store = paths.legacy_icon_store(legacy_name)
    new_store = paths.icon_store()
    legacy_managed = de.MANAGED_KEYS[1:]

    for path in sorted(applications.glob("*.desktop")):
        if paths.is_generated_name(path.name):
            continue                    # handled by _migrate_generated
        try:
            if not de.is_managed(path, legacy_managed):
                continue                # not ours - never touch it
            text = de.read_text_exact(path)

            values: dict[str, str] = {de.MANAGED_KEYS[0]: "true"}
            original = de.entry_value_from_text(text, de.ORIGINAL_ICON_KEYS)
            if original:
                values[de.ORIGINAL_ICON_KEYS[0]] = original
            repointed = _repoint_icon(de.entry_icon_from_text(text),
                                      legacy_store, new_store)
            if repointed:
                values["Icon"] = repointed

            de.atomic_write_text(path, de.set_entry_values(text, values))
            report.overrides_updated += 1
        except (OSError, de.DesktopEntryError, ValueError) as exc:
            report.failures.append(f"{path.name}: {exc}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def migrate_if_needed() -> MigrationReport:
    """Run the migration once. Safe to call on every launch."""
    report = MigrationReport()

    if _read_new_config().get(MIGRATED_FROM):
        report.already_done = True
        return report

    legacy_name = find_legacy_install()
    if legacy_name is None:
        return report                   # fresh install, nothing to do

    report.source_name = legacy_name

    for step in (_migrate_icons, _migrate_generated, _migrate_overrides):
        try:
            step(legacy_name, report)
        except Exception as exc:        # never let a step block startup
            report.failures.append(f"{step.__name__}: {exc}")

    try:
        merged = _migrate_config(legacy_name, report)
    except Exception as exc:
        report.failures.append(f"config: {exc}")
        merged = _read_new_config()

    merged[MIGRATED_FROM] = legacy_name
    merged[MIGRATED_AT] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    merged[MIGRATION_REPORT] = report.as_dict()

    try:
        de.atomic_write_text(paths.config_file(), json.dumps(merged, indent=2) + "\n")
        report.performed = True
    except OSError as exc:
        # Without the seal the migration would repeat next launch. Every step
        # is idempotent, so that is survivable, but record it.
        report.failures.append(f"could not record migration: {exc}")

    return report


def legacy_leftovers() -> list[Path]:
    """Old directories still on disk, for an explicit user-initiated cleanup.

    Never removed automatically. The user confirms Kairo works first.
    """
    out: list[Path] = []
    for name in paths.LEGACY_APP_DIRNAMES:
        for path in (paths.legacy_config_dir(name), paths.legacy_data_dir(name)):
            if path.is_dir():
                out.append(path)
    return out
