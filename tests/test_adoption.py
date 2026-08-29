"""Adopting launcher entries Kairo owns but has no history for.

The case that forced this: everything migrated from Steam Shortcut Forge was
genuinely customised and genuinely restorable, but invisible in Changes and
unreachable from Restore All, because the history is only written at the
moment a change is made.
"""

import pytest

from kairo import adoption, paths
from kairo.desktop import entry as de
from kairo.ledger import Ledger
from kairo.providers.registry import default_registry


@pytest.fixture
def registry():
    return default_registry()


@pytest.fixture
def ledger(fake_home):
    return Ledger().load()


def write(path, body):
    path.write_text(body)
    return path


def migrated_override(apps, name="org.kde.dolphin.desktop", icon="/icons/x.png"):
    return write(apps / name,
                 "[Desktop Entry]\nType=Application\nName=Dolphin\n"
                 f"Icon={icon}\nExec=dolphin %u\n"
                 "X-ShortcutForge-Managed=true\n"
                 "X-ShortcutForge-OriginalIcon=org.kde.dolphin\n")


def generated_entry(apps, appid="440", icon="/icons/tf2.png"):
    return write(apps / f"{paths.DESKTOP_PREFIX}{appid}.desktop",
                 "[Desktop Entry]\nType=Application\nName=Team Fortress 2\n"
                 f"Icon={icon}\nExec=steam steam://rungameid/{appid}\n"
                 f"X-SteamAppId={appid}\n{de.MANAGED_KEYS[0]}=true\n")


# -- what gets adopted ------------------------------------------------------

def test_adopts_a_migrated_override(fake_home, ledger, registry):
    apps = paths.applications_dir()
    migrated_override(apps)
    added = adoption.adopt_untracked(ledger, registry)
    assert [r.key for r in added] == ["desktop:org.kde.dolphin"]
    assert ledger.get("desktop:org.kde.dolphin").action == "overrode"


def test_adopts_a_generated_entry(fake_home, ledger, registry):
    generated_entry(paths.applications_dir())
    adoption.adopt_untracked(ledger, registry)
    record = ledger.get("steam:440")
    assert record is not None
    assert record.action == "created"
    assert record.provider_id == "steam"


def test_adopted_records_are_flagged(fake_home, ledger, registry):
    migrated_override(paths.applications_dir())
    adoption.adopt_untracked(ledger, registry)
    assert ledger.get("desktop:org.kde.dolphin").adopted is True


def test_reconstructs_the_original_icon_from_the_legacy_key(fake_home, ledger,
                                                            registry):
    """Without this the adopted record could not say what to revert to."""
    migrated_override(paths.applications_dir())
    adoption.adopt_untracked(ledger, registry)
    assert ledger.get("desktop:org.kde.dolphin").original_icon == "org.kde.dolphin"


def test_reconstructs_the_display_name(fake_home, ledger, registry):
    migrated_override(paths.applications_dir())
    adoption.adopt_untracked(ledger, registry)
    assert ledger.get("desktop:org.kde.dolphin").name == "Dolphin"


def test_records_the_applied_icon(fake_home, ledger, registry):
    migrated_override(paths.applications_dir(), icon="/icons/custom.png")
    adoption.adopt_untracked(ledger, registry)
    assert ledger.get("desktop:org.kde.dolphin").applied_icon == "/icons/custom.png"


# -- what must never be adopted ---------------------------------------------

def test_never_adopts_an_unmarked_file(fake_home, ledger, registry):
    """The marker is the only thing that authorises a claim."""
    write(paths.applications_dir() / "firefox.desktop",
          "[Desktop Entry]\nType=Application\nName=Firefox\nIcon=mine\n")
    assert adoption.adopt_untracked(ledger, registry) == []
    assert len(ledger) == 0


def test_never_adopts_a_foreign_file_with_our_naming(fake_home, ledger, registry):
    write(paths.applications_dir() / f"{paths.DESKTOP_PREFIX}999.desktop",
          "[Desktop Entry]\nType=Application\nName=Hand written\nIcon=x\n")
    assert adoption.adopt_untracked(ledger, registry) == []


def test_never_adopts_a_malformed_file(fake_home, ledger, registry):
    write(paths.applications_dir() / "broken.desktop", "not a desktop file\n[[[\n")
    assert adoption.adopt_untracked(ledger, registry) == []


def test_ignores_files_outside_the_applications_dir(fake_home, ledger, registry,
                                                    tmp_path):
    migrated_override(tmp_path)
    assert adoption.adopt_untracked(ledger, registry) == []


def test_generated_name_with_a_non_numeric_id_is_not_claimed_by_steam(
        fake_home, ledger, registry):
    """Keeps Steam from claiming a future provider's generated entries."""
    write(paths.applications_dir() / f"{paths.DESKTOP_PREFIX}some-appimage.desktop",
          "[Desktop Entry]\nType=Application\nName=Thing\nIcon=/x.png\n"
          f"{de.MANAGED_KEYS[0]}=true\n")
    added = adoption.adopt_untracked(ledger, registry)
    assert [r.provider_id for r in added] != ["steam"]


# -- idempotency ------------------------------------------------------------

def test_running_twice_adopts_nothing_new(fake_home, ledger, registry):
    apps = paths.applications_dir()
    migrated_override(apps)
    generated_entry(apps)
    first = adoption.adopt_untracked(ledger, registry)
    second = adoption.adopt_untracked(ledger, registry)
    assert len(first) == 2
    assert second == []
    assert len(ledger) == 2


def test_does_not_overwrite_a_real_record(fake_home, ledger, registry):
    """A record written at the time of the change knows its artwork source;
    adoption must not replace it with a guess."""
    from kairo.ledger import ChangeRecord
    apps = paths.applications_dir()
    migrated_override(apps)
    ledger.record(ChangeRecord(
        key="desktop:org.kde.dolphin", provider_id="desktop", name="Dolphin",
        action="overrode", target=str(apps / "org.kde.dolphin.desktop"),
        source_label="SteamGridDB", original_icon="real-original"))

    adoption.adopt_untracked(ledger, registry)

    record = ledger.get("desktop:org.kde.dolphin")
    assert record.source_label == "SteamGridDB"
    assert record.adopted is False
    assert record.original_icon == "real-original"


def test_adoption_persists(fake_home, ledger, registry):
    migrated_override(paths.applications_dir())
    adoption.adopt_untracked(ledger, registry)
    assert len(Ledger().load()) == 1


# -- the point of the exercise: adopted records are restorable --------------

def test_an_adopted_override_can_be_restored(fake_home, ledger, registry,
                                             system_apps):
    from kairo import actions
    apps = paths.applications_dir()
    migrated_override(apps)
    adoption.adopt_untracked(ledger, registry)

    record = ledger.get("desktop:org.kde.dolphin")
    allowed, reason = Ledger.restorable(record)
    assert allowed is True, reason

    actions.restore_record(record, registry, ledger=ledger)
    assert not (apps / "org.kde.dolphin.desktop").exists()
    assert ledger.get("desktop:org.kde.dolphin") is None


def test_an_adopted_generated_entry_can_be_removed(fake_home, ledger, registry):
    """The destructive action still reaches an adopted record."""
    from kairo import actions
    from kairo.actions import entry_from_record
    apps = paths.applications_dir()
    generated_entry(apps)
    adoption.adopt_untracked(ledger, registry)

    record = ledger.get("steam:440")
    actions.remove_entry(entry_from_record(record), registry.get("steam"),
                         ledger=ledger)
    assert not (apps / f"{paths.DESKTOP_PREFIX}440.desktop").exists()
    assert ledger.get("steam:440") is None


def test_restore_all_reaches_adopted_records(fake_home, ledger, registry):
    """Adopted entries whose artwork lives outside Kairo's store have nothing
    to reset, so they are skipped rather than failed."""
    from kairo import actions
    apps = paths.applications_dir()
    migrated_override(apps)
    generated_entry(apps)
    adoption.adopt_untracked(ledger, registry)

    summary = actions.restore_all(ledger, registry)
    assert summary.failed == 0
    assert summary.succeeded + summary.skipped == 2
    assert not (apps / "org.kde.dolphin.desktop").exists()   # override undone
    assert len(ledger) == 0


# -- end to end with a real migration ---------------------------------------

def test_migration_then_adoption_tracks_everything(legacy_install, registry):
    """The exact situation found on the real machine: migrate, then every
    migrated customisation should appear in the history."""
    from kairo import migration

    report = migration.migrate_if_needed()
    assert report.performed

    ledger = Ledger().load()
    assert len(ledger) == 0            # migration itself records nothing

    added = adoption.adopt_untracked(ledger, registry)
    managed = [p for p in paths.applications_dir().glob("*.desktop")
               if de.is_managed(p)]
    assert len(added) == len(managed)
    assert all(r.adopted for r in ledger.records())
    assert all(Ledger.restorable(r)[0] for r in ledger.records())
