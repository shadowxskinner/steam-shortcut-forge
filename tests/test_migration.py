"""Migration from Steam Shortcut Forge to Kairo.

This code runs once per user and is impossible to debug in the field, so it is
tested against a fixture HOME containing every awkward file shape rather than
against a real desktop.
"""

import json

import pytest

from kairo import migration, paths
from kairo.desktop import entry as de


@pytest.fixture
def migrated(legacy_install):
    return migration.migrate_if_needed()


def read(path):
    return path.read_text(encoding="utf-8", errors="surrogateescape")


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def test_fresh_install_is_a_no_op(fake_home):
    report = migration.migrate_if_needed()
    assert report.performed is False
    assert report.already_done is False
    assert not paths.config_file().exists()      # nothing written


def test_legacy_install_is_detected(legacy_install):
    assert migration.needs_migration() is True
    assert migration.find_legacy_install() == "steam-shortcut-forge"


def test_migration_reports_success(migrated):
    assert migrated.performed is True
    assert migrated.source_name == "steam-shortcut-forge"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def test_config_is_copied(migrated):
    cfg = json.loads(paths.config_file().read_text())
    assert cfg["steamgriddb_api_key"] == "legacy-key-123"
    assert cfg["some_setting"] is True


def test_migration_is_recorded_in_config(migrated):
    cfg = json.loads(paths.config_file().read_text())
    assert cfg[migration.MIGRATED_FROM] == "steam-shortcut-forge"
    assert cfg[migration.MIGRATED_AT]
    assert "shortcuts_moved" in cfg[migration.MIGRATION_REPORT]


def test_old_config_is_left_in_place(migrated, legacy_install):
    """Copy, not move, so a downgrade is not stranded."""
    assert (legacy_install["config"] / "config.json").is_file()


def test_cache_is_not_migrated(migrated):
    """Regenerable, and the index format changed."""
    assert not (paths.cache_dir() / "themes.json").exists()


# ---------------------------------------------------------------------------
# Icon store
# ---------------------------------------------------------------------------

def test_icons_are_copied(migrated):
    names = {p.name for p in paths.icon_store().iterdir()}
    assert names == {"440_aaaa.png", "620_bbbb.png", "dolphin_cccc.png"}
    assert migrated.icons_copied == 3


def test_old_icon_store_is_left_in_place(migrated, legacy_install):
    assert len(list(legacy_install["icons"].iterdir())) == 3


# ---------------------------------------------------------------------------
# Generated shortcuts
# ---------------------------------------------------------------------------

def test_generated_shortcuts_are_renamed(migrated):
    apps = paths.applications_dir()
    assert (apps / "kairo-440.desktop").is_file()
    assert (apps / "kairo-620.desktop").is_file()


def test_old_generated_files_are_removed(migrated):
    """A copy rather than a move would show every game twice in the launcher."""
    apps = paths.applications_dir()
    assert not (apps / "steam-shortcut-forge-440.desktop").exists()
    assert not (apps / "steam-shortcut-forge-620.desktop").exists()


def test_generated_icon_paths_are_repointed(migrated):
    icon = de.read_entry_icon(paths.applications_dir() / "kairo-440.desktop")
    assert icon == str(paths.icon_store() / "440_aaaa.png")
    assert paths.icon_store().joinpath("440_aaaa.png").is_file()


def test_repointed_icons_actually_exist(migrated):
    """The failure this guards against is silent: entry intact, artwork gone."""
    from pathlib import Path

    for name in ("kairo-440.desktop", "kairo-620.desktop"):
        icon = de.read_entry_icon(paths.applications_dir() / name)
        assert icon.startswith(str(paths.icon_store()))
        assert Path(icon).is_file()


def test_generated_entries_keep_their_fields(migrated):
    text = read(paths.applications_dir() / "kairo-440.desktop")
    assert "X-SteamAppId=440" in text
    assert "Exec=steam steam://rungameid/440" in text
    assert "Name=Team Fortress 2" in text


def test_generated_entries_gain_the_kairo_marker(migrated):
    assert de.is_managed(paths.applications_dir() / "kairo-440.desktop")


def test_crlf_generated_entry_keeps_crlf(migrated):
    raw = (paths.applications_dir() / "kairo-620.desktop").read_bytes()
    assert b"\r\n" in raw
    assert b"\n\n" not in raw.replace(b"\r\n", b"")


def test_crlf_entry_icon_is_repointed(migrated):
    icon = de.read_entry_icon(paths.applications_dir() / "kairo-620.desktop")
    assert icon == str(paths.icon_store() / "620_bbbb.png")


# ---------------------------------------------------------------------------
# Managed overrides
# ---------------------------------------------------------------------------

def test_override_gains_the_kairo_marker(migrated):
    path = paths.applications_dir() / "org.kde.dolphin.desktop"
    assert "X-Kairo-Managed=true" in read(path)


def test_override_keeps_the_legacy_marker(migrated):
    """So a downgrade can still recognise and revert the file."""
    path = paths.applications_dir() / "org.kde.dolphin.desktop"
    assert "X-ShortcutForge-Managed=true" in read(path)


def test_override_original_icon_is_carried_over(migrated):
    path = paths.applications_dir() / "org.kde.dolphin.desktop"
    assert de.read_entry_value(path, de.ORIGINAL_ICON_KEYS) == "org.kde.dolphin"
    assert "X-ShortcutForge-OriginalIcon=org.kde.dolphin" in read(path)


def test_override_icon_is_repointed(migrated):
    path = paths.applications_dir() / "org.kde.dolphin.desktop"
    assert de.read_entry_icon(path) == str(paths.icon_store() / "dolphin_cccc.png")


def test_override_action_icon_is_untouched(migrated):
    text = read(paths.applications_dir() / "org.kde.dolphin.desktop")
    assert "Icon=window-new" in text


def test_override_keeps_desktop_integration_fields(migrated):
    text = read(paths.applications_dir() / "org.kde.dolphin.desktop")
    assert "MimeType=inode/directory;" in text
    assert "Actions=new-window;" in text


def test_migrated_override_is_still_restorable(migrated, fake_home, monkeypatch):
    """The whole reason the legacy marker keys stay in MANAGED_KEYS forever.

    If restore refused here, every override made before the rename would be
    stuck with no in-app way back to the original icon.
    """
    from kairo.models import AppEntry
    from kairo.providers.writers import OverrideWriter

    source = fake_home / "system" / "org.kde.dolphin.desktop"
    source.parent.mkdir(parents=True)
    source.write_text("[Desktop Entry]\nType=Application\nName=Dolphin\n"
                      "Icon=org.kde.dolphin\nExec=dolphin %u\n")

    app = AppEntry(key="desktop:org.kde.dolphin", provider_id="desktop",
                   name="Dolphin", customized=True,
                   payload={"basename": "org.kde.dolphin.desktop",
                            "source": str(source)})

    writer = OverrideWriter()
    allowed, reason = writer.can_restore(app)
    assert allowed is True, reason
    writer.restore(app)
    assert not (paths.applications_dir() / "org.kde.dolphin.desktop").exists()


# ---------------------------------------------------------------------------
# Files that must not be touched
# ---------------------------------------------------------------------------

def test_hand_written_override_is_untouched(migrated, legacy_install):
    path = legacy_install["apps"] / "firefox.desktop"
    assert read(path) == ("[Desktop Entry]\nType=Application\nName=Firefox\n"
                          "Icon=my-own-icon\nExec=firefox %u\n")


def test_malformed_file_is_left_alone(migrated, legacy_install):
    assert read(legacy_install["apps"] / "broken.desktop") == "not a desktop file\n[[[\n"


def test_file_without_desktop_entry_is_left_alone(migrated, legacy_install):
    text = read(legacy_install["apps"] / "noentry.desktop")
    assert text == "[Desktop Action solo]\nName=Orphan\nIcon=x\n"


def test_unrelated_files_gain_no_markers(migrated, legacy_install):
    for name in ("firefox.desktop", "broken.desktop", "noentry.desktop"):
        assert "Kairo" not in read(legacy_install["apps"] / name)


# ---------------------------------------------------------------------------
# Partial failure
# ---------------------------------------------------------------------------

def test_unreadable_entry_is_recorded_not_fatal(migrated):
    assert migrated.performed is True
    assert any("999" in f for f in migrated.failures)


def test_a_failure_does_not_stop_the_other_files(migrated):
    assert migrated.shortcuts_moved == 2
    assert migrated.overrides_updated == 1


def test_failures_are_written_into_the_config(migrated):
    cfg = json.loads(paths.config_file().read_text())
    assert cfg[migration.MIGRATION_REPORT]["failures"]


def test_summary_mentions_the_failures(migrated):
    assert "could not be migrated" in migrated.summary()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_second_run_is_skipped(migrated):
    second = migration.migrate_if_needed()
    assert second.already_done is True
    assert second.performed is False


def test_second_run_changes_nothing_on_disk(migrated):
    apps = paths.applications_dir()
    before = {p.name: p.read_bytes() for p in sorted(apps.iterdir()) if p.is_file()}
    config_before = paths.config_file().read_bytes()

    migration.migrate_if_needed()

    after = {p.name: p.read_bytes() for p in sorted(apps.iterdir()) if p.is_file()}
    assert after == before
    assert paths.config_file().read_bytes() == config_before


def test_steps_are_individually_idempotent(legacy_install):
    """Even if the seal never got written, re-running must be safe."""
    first = migration.migrate_if_needed()
    paths.config_file().unlink()             # simulate a failed seal
    second = migration.migrate_if_needed()

    assert second.performed is True
    assert second.shortcuts_moved == 0       # nothing left to move
    assert (paths.applications_dir() / "kairo-440.desktop").is_file()
    icon = de.read_entry_icon(paths.applications_dir() / "kairo-440.desktop")
    assert icon == str(paths.icon_store() / "440_aaaa.png")
    assert first.shortcuts_moved == 2


def test_repeated_override_migration_does_not_duplicate_keys(legacy_install):
    migration.migrate_if_needed()
    paths.config_file().unlink()
    migration.migrate_if_needed()
    text = read(paths.applications_dir() / "org.kde.dolphin.desktop")
    assert text.count("X-Kairo-Managed=true") == 1
    assert text.count("X-ShortcutForge-Managed=true") == 1


# ---------------------------------------------------------------------------
# Integration with the providers
# ---------------------------------------------------------------------------

def test_steam_provider_sees_migrated_shortcuts(migrated, fake_home):
    from kairo.providers.steam import SteamProvider

    steamapps = fake_home / ".steam" / "steam" / "steamapps"
    steamapps.mkdir(parents=True)
    (steamapps / "appmanifest_440.acf").write_text(
        '"AppState"\n{\n\t"appid"\t\t"440"\n\t"name"\t\t"Team Fortress 2"\n}\n')

    app = next(a for a in SteamProvider().scan() if a.local_id == "440")
    assert app.customized is True
    assert app.current_icon == paths.icon_store() / "440_aaaa.png"


# ---------------------------------------------------------------------------
# Cleanup is never automatic
# ---------------------------------------------------------------------------

def test_leftovers_are_listed_but_not_removed(migrated):
    leftovers = migration.legacy_leftovers()
    assert len(leftovers) == 2
    assert all(p.is_dir() for p in leftovers)


# ---------------------------------------------------------------------------
# Collision with an existing Kairo entry
# ---------------------------------------------------------------------------

def test_collision_with_foreign_kairo_file_touches_neither(legacy_install):
    """A file named kairo-440.desktop that Kairo did not create is not ours to
    overwrite just because the name matches our scheme."""
    apps = legacy_install["apps"]
    foreign = apps / "kairo-440.desktop"
    foreign.write_text("[Desktop Entry]\nType=Application\nName=My Own TF2\n"
                       "Icon=my-icon\nExec=something-else\n")
    legacy_before = read(apps / "steam-shortcut-forge-440.desktop")

    report = migration.migrate_if_needed()

    assert read(foreign) == ("[Desktop Entry]\nType=Application\nName=My Own TF2\n"
                             "Icon=my-icon\nExec=something-else\n")
    assert (apps / "steam-shortcut-forge-440.desktop").is_file()
    assert read(apps / "steam-shortcut-forge-440.desktop") == legacy_before
    assert any("kairo-440.desktop" in c for c in report.collisions)


def test_collision_does_not_stop_the_other_entries(legacy_install):
    apps = legacy_install["apps"]
    (apps / "kairo-440.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Mine\nIcon=x\n")

    report = migration.migrate_if_needed()

    assert (apps / "kairo-620.desktop").is_file()
    assert report.shortcuts_moved == 1
    assert report.overrides_updated == 1
    assert report.performed is True


def test_collision_is_recorded_in_the_config(legacy_install):
    (legacy_install["apps"] / "kairo-440.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Mine\nIcon=x\n")
    migration.migrate_if_needed()
    cfg = json.loads(paths.config_file().read_text())
    assert cfg[migration.MIGRATION_REPORT]["collisions"]


def test_collision_is_mentioned_in_the_summary(legacy_install):
    (legacy_install["apps"] / "kairo-440.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Mine\nIcon=x\n")
    report = migration.migrate_if_needed()
    assert "already exists" in report.summary()


def test_owned_kairo_target_supersedes_the_legacy_copy(legacy_install):
    """The interrupted-migration case: target written, source not yet removed."""
    apps = legacy_install["apps"]
    icons = legacy_install["icons"]
    (apps / "kairo-440.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Team Fortress 2\n"
        f"Icon={icons / '440_aaaa.png'}\nX-SteamAppId=440\n"
        "X-Kairo-Managed=true\n")

    report = migration.migrate_if_needed()

    assert not (apps / "steam-shortcut-forge-440.desktop").exists()
    assert (apps / "kairo-440.desktop").is_file()
    assert report.collisions == []
    assert report.shortcuts_moved == 2
    # The surviving file is repointed at the new store.
    assert de.read_entry_icon(apps / "kairo-440.desktop") == \
        str(paths.icon_store() / "440_aaaa.png")


# ---------------------------------------------------------------------------
# Evidence: a legacy-named file is not automatically ours
# ---------------------------------------------------------------------------

def test_foreign_file_with_our_old_prefix_is_left_alone(legacy_install):
    apps = legacy_install["apps"]
    intruder = apps / "steam-shortcut-forge-notmine.desktop"
    intruder.write_text("[Desktop Entry]\nType=Application\nName=Not Ours\n"
                        "Icon=whatever\nExec=/usr/bin/true\n")

    report = migration.migrate_if_needed()

    assert intruder.is_file()
    assert not (apps / "kairo-notmine.desktop").exists()
    assert any("notmine" in s for s in report.skipped_foreign)


@pytest.mark.parametrize("body,expected", [
    ("[Desktop Entry]\nX-SteamAppId=440\n", True),
    ("[Desktop Entry]\nExec=steam steam://rungameid/440\n", True),
    ("[Desktop Entry]\nX-Kairo-Managed=true\n", True),
    ("[Desktop Entry]\nX-ShortcutForge-Managed=true\n", True),
    ("[Desktop Entry]\nName=Something\nIcon=generic\n", False),
    ("[Desktop Entry]\nX-SteamAppId=999\n", False),
    ("[Desktop Entry]\nExec=steam steam://rungameid/999\n", False),
    ("not a desktop file\n", False),
    ("", False),
])
def test_evidence_rules(body, expected, fake_home):
    store = paths.legacy_icon_store("steam-shortcut-forge")
    got = bool(migration.legacy_generated_evidence(body, "440", store))
    assert got is expected


def test_icon_in_the_old_store_counts_as_evidence(fake_home):
    store = paths.legacy_icon_store("steam-shortcut-forge")
    text = f"[Desktop Entry]\nName=X\nIcon={store / '440_a.png'}\n"
    assert migration.legacy_generated_evidence(text, "440", store)


# ---------------------------------------------------------------------------
# Detection when the legacy directories are already gone
# ---------------------------------------------------------------------------

@pytest.fixture
def orphaned_launchers(fake_home):
    """Launcher entries survive, but the old config and data dirs do not."""
    apps = fake_home / ".local" / "share" / "applications"
    (apps / "steam-shortcut-forge-440.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Team Fortress 2\n"
        "Exec=steam steam://rungameid/440\nIcon=/gone/440.png\n"
        "Categories=Game;\nX-SteamAppId=440\n")
    return apps


def test_detects_install_from_launcher_entries_alone(orphaned_launchers):
    assert not (paths.legacy_config_dir("steam-shortcut-forge")).exists()
    assert not (paths.legacy_data_dir("steam-shortcut-forge")).exists()
    assert migration.find_legacy_install() == "steam-shortcut-forge"
    assert migration.needs_migration() is True


def test_orphaned_launchers_are_migrated(orphaned_launchers):
    report = migration.migrate_if_needed()
    assert report.performed is True
    assert report.shortcuts_moved == 1
    assert (orphaned_launchers / "kairo-440.desktop").is_file()
    assert not (orphaned_launchers / "steam-shortcut-forge-440.desktop").exists()


def test_orphaned_launcher_keeps_an_unresolvable_icon_path(orphaned_launchers):
    """The old icon store is gone, so there is nothing to repoint to. Leave the
    path alone rather than inventing one that does not exist either."""
    migration.migrate_if_needed()
    icon = de.read_entry_icon(orphaned_launchers / "kairo-440.desktop")
    assert icon == "/gone/440.png"


def test_detects_install_from_a_managed_override_alone(fake_home):
    apps = fake_home / ".local" / "share" / "applications"
    (apps / "org.kde.dolphin.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Dolphin\nIcon=/gone/x.png\n"
        "X-ShortcutForge-Managed=true\n"
        "X-ShortcutForge-OriginalIcon=org.kde.dolphin\n")
    assert migration.find_legacy_install() == "steam-shortcut-forge"
    report = migration.migrate_if_needed()
    assert report.overrides_updated == 1
    assert "X-Kairo-Managed=true" in read(apps / "org.kde.dolphin.desktop")


def test_no_evidence_means_no_migration(fake_home):
    apps = fake_home / ".local" / "share" / "applications"
    (apps / "firefox.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Firefox\nIcon=firefox\n")
    (apps / "steam-shortcut-forge-lookalike.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Lookalike\nIcon=x\n")
    assert migration.find_legacy_install() is None
    assert migration.needs_migration() is False
    report = migration.migrate_if_needed()
    assert report.performed is False
    assert not paths.config_file().exists()
