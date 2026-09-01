"""Provider discovery and the two launcher-writing strategies."""

from pathlib import Path

import pytest

from kairo import paths
from kairo.desktop import entry as de
from kairo.models import AppEntry
from kairo.providers.desktop_entry import DesktopEntryProvider
from kairo.providers.registry import default_registry
from kairo.providers.steam import SteamProvider
from kairo.providers.writers import GeneratedEntryWriter, OverrideWriter, store_icon


@pytest.fixture
def png(tmp_path):
    path = tmp_path / "art.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    return path


# ---------------------------------------------------------------------------
# Steam provider
# ---------------------------------------------------------------------------

def test_steam_scan_finds_installed_games(steam_library):
    apps = SteamProvider().scan()
    assert [a.name for a in apps] == ["Portal 2", "Team Fortress 2"]


def test_steam_scan_skips_runtimes(steam_library):
    assert all("Runtime" not in a.name for a in SteamProvider().scan())


def test_steam_keys_are_namespaced(steam_library):
    keys = {a.key for a in SteamProvider().scan()}
    assert keys == {"steam:440", "steam:620"}


def test_steam_local_id_round_trips(steam_library):
    app = next(a for a in SteamProvider().scan() if a.name == "Portal 2")
    assert app.local_id == "620"
    assert app.provider_id == "steam"


def test_steam_unavailable_without_a_library(fake_home):
    assert SteamProvider().available() is False


def test_steam_reads_extra_library_folders(steam_library, fake_home):
    other = fake_home / "games" / "steamapps"
    other.mkdir(parents=True)
    (other / "appmanifest_999.acf").write_text(
        '"AppState"\n{\n\t"appid"\t\t"999"\n\t"name"\t\t"Far Away Game"\n}\n')
    (steam_library / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"1"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n'
        % (fake_home / "games"))
    assert "Far Away Game" in {a.name for a in SteamProvider().scan()}


# ---------------------------------------------------------------------------
# Desktop entry provider
# ---------------------------------------------------------------------------

def test_desktop_scan_finds_applications(system_apps):
    names = {a.name for a in DesktopEntryProvider().scan()}
    assert names == {"Dolphin", "Firefox"}


def test_desktop_scan_skips_nodisplay_links_and_malformed(system_apps):
    names = {a.name for a in DesktopEntryProvider().scan()}
    assert "Hidden" not in names
    assert "A Link" not in names


def test_desktop_keys_are_namespaced(system_apps):
    keys = {a.key for a in DesktopEntryProvider().scan()}
    assert keys == {"desktop:org.kde.dolphin", "desktop:firefox"}


def test_desktop_scan_records_icon_hint(system_apps):
    app = next(a for a in DesktopEntryProvider().scan() if a.name == "Dolphin")
    assert app.icon_hint == "org.kde.dolphin"


def test_desktop_scan_ignores_our_generated_entries(system_apps, fake_home):
    local = fake_home / ".local" / "share" / "applications"
    (local / f"{paths.DESKTOP_PREFIX}440.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Team Fortress 2\nIcon=/x.png\n")
    assert "Team Fortress 2" not in {a.name for a in DesktopEntryProvider().scan()}


def test_steam_and_desktop_keys_cannot_collide(steam_library, system_apps):
    keys = [a.key for a in SteamProvider().scan()] + \
           [a.key for a in DesktopEntryProvider().scan()]
    assert len(keys) == len(set(keys))
    assert all(":" in k for k in keys)


# ---------------------------------------------------------------------------
# Icon store
# ---------------------------------------------------------------------------

def test_store_icon_copies_into_the_store(fake_home, png):
    app = AppEntry(key="steam:440", provider_id="steam", name="TF2")
    stored = store_icon(app, png)
    assert stored.parent == paths.icon_store()
    assert stored.read_bytes() == png.read_bytes()


def test_store_icon_leaves_our_own_files_alone(fake_home, png):
    app = AppEntry(key="steam:440", provider_id="steam", name="TF2")
    first = store_icon(app, png)
    assert store_icon(app, first) == first


def test_store_icon_rejects_unsupported_types(fake_home, tmp_path):
    bad = tmp_path / "art.bmp"
    bad.write_bytes(b"BM")
    app = AppEntry(key="steam:440", provider_id="steam", name="TF2")
    with pytest.raises(ValueError):
        store_icon(app, bad)


# ---------------------------------------------------------------------------
# GeneratedEntryWriter
# ---------------------------------------------------------------------------

@pytest.fixture
def steam_entry(steam_library):
    return next(a for a in SteamProvider().scan() if a.local_id == "440")


def test_generated_writer_creates_a_launcher_entry(steam_entry, png, fake_home):
    writer = SteamProvider().writer()
    writer.apply(steam_entry, png)
    target = paths.applications_dir() / f"{paths.DESKTOP_PREFIX}440.desktop"
    assert target.is_file()
    text = target.read_text()
    assert "X-SteamAppId=440" in text
    assert "Categories=Game;" in text
    assert "rungameid/440" in text


def test_generated_entry_points_at_the_icon_store(steam_entry, png, fake_home):
    SteamProvider().writer().apply(steam_entry, png)
    target = paths.applications_dir() / f"{paths.DESKTOP_PREFIX}440.desktop"
    icon = Path(de.read_entry_icon(target))
    assert icon.is_relative_to(paths.icon_store())
    assert icon.is_file()


def test_generated_entry_is_self_identifying(steam_entry, png, fake_home):
    SteamProvider().writer().apply(steam_entry, png)
    target = paths.applications_dir() / f"{paths.DESKTOP_PREFIX}440.desktop"
    assert de.is_managed(target)


def test_generated_writer_marks_the_entry_customized(steam_entry, png, fake_home):
    SteamProvider().writer().apply(steam_entry, png)
    assert steam_entry.customized is True
    assert steam_entry.current_icon is not None


def test_restore_resets_artwork_and_keeps_the_shortcut(steam_entry, png, fake_home):
    """The ordinary undo must not delete something the user relies on."""
    writer = SteamProvider().writer()
    writer.apply(steam_entry, png)
    icon = steam_entry.current_icon
    target = paths.applications_dir() / f"{paths.DESKTOP_PREFIX}440.desktop"

    writer.restore(steam_entry)

    assert target.is_file()                       # shortcut survives
    assert de.read_entry_icon(target) == writer.default_icon
    assert not icon.exists()                      # custom artwork discarded
    assert steam_entry.customized is False


def test_reset_preserves_everything_except_the_icon(steam_entry, png, fake_home):
    writer = SteamProvider().writer()
    writer.apply(steam_entry, png)
    writer.restore(steam_entry)
    text = (paths.applications_dir() / f"{paths.DESKTOP_PREFIX}440.desktop").read_text()
    assert "X-SteamAppId=440" in text
    assert "rungameid/440" in text
    assert "Name=Team Fortress 2" in text
    assert de.is_managed(paths.applications_dir() / f"{paths.DESKTOP_PREFIX}440.desktop")


def test_reset_twice_is_harmless(steam_entry, png, fake_home):
    writer = SteamProvider().writer()
    writer.apply(steam_entry, png)
    writer.restore(steam_entry)
    allowed, reason = writer.can_restore(steam_entry)
    assert allowed is False and "default icon" in reason
    writer.restore(steam_entry)                   # must not raise
    assert (paths.applications_dir() / f"{paths.DESKTOP_PREFIX}440.desktop").is_file()


def test_remove_deletes_the_shortcut(steam_entry, png, fake_home):
    """The destructive action, reached only on purpose."""
    writer = SteamProvider().writer()
    writer.apply(steam_entry, png)
    icon = steam_entry.current_icon

    assert writer.can_remove(steam_entry)[0] is True
    writer.remove(steam_entry)

    assert not (paths.applications_dir() / f"{paths.DESKTOP_PREFIX}440.desktop").exists()
    assert not icon.exists()
    assert steam_entry.customized is False


def test_remove_works_after_a_reset(steam_entry, png, fake_home):
    writer = SteamProvider().writer()
    writer.apply(steam_entry, png)
    writer.restore(steam_entry)
    assert writer.can_remove(steam_entry)[0] is True
    writer.remove(steam_entry)
    assert not (paths.applications_dir() / f"{paths.DESKTOP_PREFIX}440.desktop").exists()


def test_overrides_offer_no_separate_removal(system_apps):
    """Removing an override is already non-destructive, so there is nothing
    for a second, scarier button to do."""
    from kairo.providers.writers import OverrideWriter
    assert OverrideWriter().supports_remove is False
    assert OverrideWriter().can_remove(
        next(a for a in DesktopEntryProvider().scan() if a.name == "Dolphin"))[0] is False


def test_a_reset_shortcut_is_no_longer_reported_as_customized(steam_entry, png,
                                                              fake_home):
    writer = SteamProvider().writer()
    writer.apply(steam_entry, png)
    assert next(a for a in SteamProvider().scan() if a.local_id == "440").customized
    writer.restore(steam_entry)
    rescanned = next(a for a in SteamProvider().scan() if a.local_id == "440")
    assert rescanned.customized is False


def test_generated_writer_reapply_replaces_the_old_icon(steam_entry, png, fake_home,
                                                        tmp_path):
    writer = SteamProvider().writer()
    writer.apply(steam_entry, png)
    first = steam_entry.current_icon
    other = tmp_path / "other.png"
    other.write_bytes(b"\x89PNG\r\n\x1a\n" + b"1" * 32)
    writer.apply(steam_entry, other)
    assert steam_entry.current_icon != first
    assert not first.exists()          # superseded artwork is cleaned up


def test_scan_reports_existing_shortcuts(steam_entry, png, fake_home):
    SteamProvider().writer().apply(steam_entry, png)
    rescanned = next(a for a in SteamProvider().scan() if a.local_id == "440")
    assert rescanned.customized is True


def test_generated_writer_finds_entries_under_a_legacy_prefix(
        steam_entry, png, fake_home, monkeypatch):
    monkeypatch.setattr(paths, "LEGACY_DESKTOP_PREFIXES", ("old-prefix-",))
    legacy = paths.applications_dir() / "old-prefix-440.desktop"
    # Carries our marker, as everything migration brings forward does. An
    # unmarked file with the same name is covered by
    # test_apply_does_not_delete_a_foreign_legacy_entry.
    legacy.write_text("[Desktop Entry]\nType=Application\nName=TF2\nIcon=/old.png\n"
                      f"{de.MANAGED_KEYS[0]}=true\n")

    writer = GeneratedEntryWriter(paths.DESKTOP_PREFIX, SteamProvider().writer().build_fields)
    assert writer.existing(steam_entry) == legacy

    writer.apply(steam_entry, png)
    # An entry we wrote must go, or the launcher shows the game twice.
    assert not legacy.exists()
    assert (paths.applications_dir() / f"{paths.DESKTOP_PREFIX}440.desktop").is_file()


# ---------------------------------------------------------------------------
# OverrideWriter
# ---------------------------------------------------------------------------

@pytest.fixture
def dolphin(system_apps):
    return next(a for a in DesktopEntryProvider().scan() if a.name == "Dolphin")


def test_override_writes_into_the_user_applications_dir(dolphin, png, fake_home):
    OverrideWriter().apply(dolphin, png)
    assert (paths.applications_dir() / "org.kde.dolphin.desktop").is_file()


def test_override_never_touches_the_source_file(dolphin, png, system_apps):
    before = (system_apps / "org.kde.dolphin.desktop").read_text()
    OverrideWriter().apply(dolphin, png)
    assert (system_apps / "org.kde.dolphin.desktop").read_text() == before


def test_override_preserves_desktop_integration_fields(dolphin, png, fake_home):
    OverrideWriter().apply(dolphin, png)
    text = (paths.applications_dir() / "org.kde.dolphin.desktop").read_text()
    for line in ("MimeType=inode/directory;", "StartupWMClass=dolphin",
                 "Actions=new-window;", "Exec=dolphin %u"):
        assert line in text


def test_override_leaves_action_icons_alone(dolphin, png, fake_home):
    OverrideWriter().apply(dolphin, png)
    text = (paths.applications_dir() / "org.kde.dolphin.desktop").read_text()
    assert "Icon=window-new" in text


def test_override_records_the_original_icon(dolphin, png, fake_home):
    OverrideWriter().apply(dolphin, png)
    target = paths.applications_dir() / "org.kde.dolphin.desktop"
    assert de.read_entry_value(target, de.ORIGINAL_ICON_KEYS) == "org.kde.dolphin"


def test_reapplying_keeps_the_true_original_icon(dolphin, png, fake_home, tmp_path):
    writer = OverrideWriter()
    writer.apply(dolphin, png)
    other = tmp_path / "second.png"
    other.write_bytes(b"\x89PNG\r\n\x1a\n" + b"2" * 32)
    writer.apply(dolphin, other)
    target = paths.applications_dir() / "org.kde.dolphin.desktop"
    # Not our own previous choice.
    assert de.read_entry_value(target, de.ORIGINAL_ICON_KEYS) == "org.kde.dolphin"


def test_override_refuses_to_clobber_a_hand_written_file(dolphin, png, fake_home):
    target = paths.applications_dir() / "org.kde.dolphin.desktop"
    target.write_text("[Desktop Entry]\nType=Application\nName=My Dolphin\nIcon=mine\n")
    with pytest.raises(ValueError):
        OverrideWriter().apply(dolphin, png)
    assert "Name=My Dolphin" in target.read_text()


def test_restore_refuses_on_a_hand_written_file(dolphin, fake_home):
    target = paths.applications_dir() / "org.kde.dolphin.desktop"
    target.write_text("[Desktop Entry]\nType=Application\nName=Mine\nIcon=mine\n")
    allowed, reason = OverrideWriter().can_restore(dolphin)
    assert allowed is False
    assert reason
    with pytest.raises(ValueError):
        OverrideWriter().restore(dolphin)
    assert target.exists()


def test_restore_removes_our_override(dolphin, png, fake_home):
    writer = OverrideWriter()
    writer.apply(dolphin, png)
    icon = dolphin.current_icon
    writer.restore(dolphin)
    assert not (paths.applications_dir() / "org.kde.dolphin.desktop").exists()
    assert not icon.exists()
    assert dolphin.customized is False


def test_restore_is_a_no_op_when_nothing_was_applied(dolphin, fake_home):
    allowed, _ = OverrideWriter().can_restore(dolphin)
    assert allowed is False


def test_scan_reports_managed_overrides(dolphin, png, system_apps):
    OverrideWriter().apply(dolphin, png)
    rescanned = next(a for a in DesktopEntryProvider().scan() if a.name == "Dolphin")
    assert rescanned.customized is True


def test_scan_does_not_claim_hand_written_overrides(system_apps, fake_home):
    (paths.applications_dir() / "firefox.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Firefox\nIcon=my-own\nExec=firefox\n")
    app = next(a for a in DesktopEntryProvider().scan() if a.name == "Firefox")
    assert app.customized is False


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_registry_resolves_a_provider_for_every_entry(steam_library, system_apps):
    registry = default_registry()
    for provider in registry.all():
        for app in provider.scan():
            assert registry.for_entry(app) is provider


def test_registry_hides_providers_with_nothing_to_offer(fake_home):
    ids = {p.id for p in default_registry().available()}
    assert "steam" not in ids          # no Steam install in this fixture
    assert "desktop" in ids


# ---------------------------------------------------------------------------
# Ownership guards on generated entries
#
# The override writer refused to touch a file it did not create from the
# start. The generated writer did not, on the theory that the filename was
# proof enough - the same assumption the migration pass had to abandon.
# ---------------------------------------------------------------------------

def test_apply_refuses_a_foreign_file_with_our_name(steam_entry, png, fake_home):
    target = paths.applications_dir() / f"{paths.DESKTOP_PREFIX}440.desktop"
    target.write_text("[Desktop Entry]\nType=Application\nName=MY OWN\nIcon=mine\n")

    with pytest.raises(ValueError):
        SteamProvider().writer().apply(steam_entry, png)
    assert "Name=MY OWN" in target.read_text()


def test_apply_replaces_our_own_entry_normally(steam_entry, png, fake_home):
    writer = SteamProvider().writer()
    writer.apply(steam_entry, png)
    writer.apply(steam_entry, png)          # no refusal on our own file
    assert de.is_managed(writer.target(steam_entry))


def test_apply_does_not_delete_a_foreign_legacy_entry(steam_entry, png, fake_home,
                                                      monkeypatch):
    """Migration deliberately leaves unproven legacy-named files alone; apply
    must not quietly delete the same file a moment later."""
    monkeypatch.setattr(paths, "LEGACY_DESKTOP_PREFIXES", ("steam-shortcut-forge-",))
    foreign = paths.applications_dir() / "steam-shortcut-forge-440.desktop"
    foreign.write_text("[Desktop Entry]\nType=Application\nName=NOT OURS\nIcon=x\n")

    SteamProvider().writer().apply(steam_entry, png)

    assert foreign.is_file()
    assert "Name=NOT OURS" in foreign.read_text()
    assert (paths.applications_dir() / f"{paths.DESKTOP_PREFIX}440.desktop").is_file()


def test_apply_still_removes_our_own_legacy_entry(steam_entry, png, fake_home,
                                                  monkeypatch):
    monkeypatch.setattr(paths, "LEGACY_DESKTOP_PREFIXES", ("steam-shortcut-forge-",))
    ours = paths.applications_dir() / "steam-shortcut-forge-440.desktop"
    ours.write_text("[Desktop Entry]\nType=Application\nName=TF2\nIcon=/x.png\n"
                    f"{de.MANAGED_KEYS[0]}=true\n")

    SteamProvider().writer().apply(steam_entry, png)
    assert not ours.exists()


def test_neither_action_touches_an_entry_without_our_marker(fake_home):
    from kairo.models import AppEntry

    target = paths.applications_dir() / f"{paths.DESKTOP_PREFIX}777.desktop"
    target.write_text("[Desktop Entry]\nType=Application\nName=HAND WRITTEN\nIcon=x\n")
    entry = AppEntry(key="steam:777", provider_id="steam", name="Hand written")

    writer = SteamProvider().writer()
    assert writer.can_restore(entry)[0] is False
    assert writer.can_remove(entry)[0] is False
    writer.restore(entry)                          # no-op, must not raise
    with pytest.raises(ValueError):
        writer.remove(entry)
    assert target.is_file()
    assert "HAND WRITTEN" in target.read_text()


def test_restore_of_a_missing_entry_is_still_a_no_op(fake_home):
    from kairo.models import AppEntry

    entry = AppEntry(key="steam:999", provider_id="steam", name="Gone",
                     customized=True)
    SteamProvider().writer().restore(entry)      # must not raise
    assert entry.customized is False


def test_stored_icons_are_namespaced_by_provider(fake_home, png):
    """Two providers with the same local id must not share one file, or
    restoring either would delete artwork the other still points at."""
    from kairo.models import AppEntry

    a = AppEntry(key="steam:440", provider_id="steam", name="A")
    b = AppEntry(key="desktop:440", provider_id="desktop", name="B")
    assert store_icon(a, png) != store_icon(b, png)


def test_restoring_one_app_leaves_the_other_artwork_alone(steam_library,
                                                          system_apps, png):
    from kairo.providers.writers import OverrideWriter

    steam = SteamProvider()
    entry = next(a for a in steam.scan() if a.local_id == "440")
    dolphin = next(a for a in DesktopEntryProvider().scan() if a.name == "Dolphin")

    steam_icon = steam.writer().apply(entry, png)
    dolphin_icon = OverrideWriter().apply(dolphin, png)

    steam.writer().restore(entry)

    assert not steam_icon.exists()
    assert dolphin_icon.exists()


# ---------------------------------------------------------------------------
# Compatibility tools are not games
# ---------------------------------------------------------------------------

def manifest(steamapps, appid, name, installdir=None):
    body = ('"AppState"\n{\n'
            f'\t"appid"\t\t"{appid}"\n'
            f'\t"name"\t\t"{name}"\n')
    if installdir:
        body += f'\t"installdir"\t\t"{installdir}"\n'
    body += "}\n"
    (steamapps / f"appmanifest_{appid}.acf").write_text(body)


def test_toolmanifest_marks_a_compatibility_tool(steam_library):
    """The structural signal: Valve ships toolmanifest.vdf in every compat
    tool, and it does not depend on the display language."""
    manifest(steam_library, "9999", "Some Runtime Thing", "SomeRuntime")
    tool_dir = steam_library / "common" / "SomeRuntime"
    tool_dir.mkdir(parents=True)
    (tool_dir / "toolmanifest.vdf").write_text('"manifest" { "version" "2" }')

    assert "Some Runtime Thing" not in {a.name for a in SteamProvider().scan()}


def test_a_game_with_an_install_dir_is_still_a_game(steam_library):
    manifest(steam_library, "8888", "Real Game", "RealGame")
    (steam_library / "common" / "RealGame").mkdir(parents=True)
    assert "Real Game" in {a.name for a in SteamProvider().scan()}


@pytest.mark.parametrize("name", [
    "Proton Experimental",
    "Proton Hotfix",
    "Proton 9.0",
    "Proton 8.0-5",
    "Proton - Experimental",
    "Proton EasyAntiCheat Runtime",
    "Steam Linux Runtime 3.0 (sniper)",
    "Steamworks Common Redistributables",
])
def test_known_compatibility_tools_are_hidden(steam_library, name):
    manifest(steam_library, "7777", name)
    assert name not in {a.name for a in SteamProvider().scan()}


@pytest.mark.parametrize("name", [
    "Proton Pulse",          # a real game whose title starts with the word
    "Protonwar",
    "Steamworld Dig",
    "Portal 2",
])
def test_real_games_are_not_hidden_by_the_name_rules(steam_library, name):
    manifest(steam_library, "6666", name)
    assert name in {a.name for a in SteamProvider().scan()}


# ---------------------------------------------------------------------------
# Restore verbs belong to the writer
# ---------------------------------------------------------------------------

def test_generated_and_override_writers_use_different_verbs():
    """One label cannot cover both: for a generated entry there is no earlier
    artwork, so 'Restore original' would describe a deletion."""
    from kairo.providers.writers import OverrideWriter

    generated = SteamProvider().writer()
    override = OverrideWriter()
    assert generated.restore_label == "Reset artwork"
    assert generated.remove_label == "Remove shortcut"
    assert override.restore_label == "Restore original"
    assert generated.supports_remove is True
    assert override.supports_remove is False


def test_restore_prompts_describe_the_actual_outcome(steam_library, system_apps):
    from kairo.providers.writers import OverrideWriter

    game = next(a for a in SteamProvider().scan() if a.local_id == "440")
    app = next(a for a in DesktopEntryProvider().scan() if a.name == "Dolphin")

    writer = SteamProvider().writer()
    reset_prompt = writer.restore_prompt(game)
    remove_prompt = writer.remove_prompt(game)
    override_prompt = OverrideWriter().restore_prompt(app)

    assert "shortcut stays" in reset_prompt.lower()
    assert "delete" in remove_prompt.lower()
    assert "not affected" in remove_prompt.lower()
    assert "keeps its launcher entry" in override_prompt.lower()


def test_deletes_launcher_distinguishes_the_two_actions():
    from kairo.ledger import ACTION_CREATED, ACTION_OVERRODE, deletes_launcher
    assert deletes_launcher(ACTION_CREATED) is True
    assert deletes_launcher(ACTION_OVERRODE) is False


# ---------------------------------------------------------------------------
# Applications, against launcher directories that fight back
# ---------------------------------------------------------------------------

def test_one_unreadable_launcher_directory_does_not_end_the_scan(
        fake_home, system_apps, monkeypatch):
    """Path.is_dir() raises on a directory that cannot be stat'ed.

    This is the same failure that once crashed the emulator picker on the way
    open. One unreadable entry on the search path — a stale automount, a
    permission-denied parent, a Flatpak export dir mid-uninstall — took the
    entire Applications list with it.
    """
    import os
    from kairo import paths
    from kairo.providers.desktop_entry import DesktopEntryProvider

    blocked = fake_home / "blocked"
    (blocked / "applications").mkdir(parents=True)
    unreadable = blocked / "applications"
    local = fake_home / ".local" / "share" / "applications"
    monkeypatch.setattr(paths, "system_application_dirs",
                        lambda: [unreadable, system_apps, local])

    os.chmod(blocked, 0o000)
    try:
        entries = DesktopEntryProvider().scan()
    finally:
        os.chmod(blocked, 0o755)

    names = {entry.name for entry in entries}
    assert "Firefox" in names, "a readable directory was skipped too"
    assert "Dolphin" in names


def test_visibility_keys_are_all_honoured(fake_home, system_apps, monkeypatch):
    from kairo.providers.desktop_entry import DesktopEntryProvider

    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    (system_apps / "onlygnome.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=OnlyGnome\n"
        "OnlyShowIn=GNOME;\nIcon=x\nExec=x\n")
    (system_apps / "notkde.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=NotKde\n"
        "NotShowIn=KDE;\nIcon=x\nExec=x\n")
    (system_apps / "onlykde.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=OnlyKde\n"
        "OnlyShowIn=KDE;\nIcon=x\nExec=x\n")
    (system_apps / "reallyhidden.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=ReallyHidden\n"
        "Hidden=true\nIcon=x\nExec=x\n")

    names = {entry.name for entry in DesktopEntryProvider().scan()}
    assert "OnlyKde" in names
    assert "OnlyGnome" not in names
    assert "NotKde" not in names
    assert "ReallyHidden" not in names
    assert "Hidden" not in names          # NoDisplay, from the fixture
    assert "A Link" not in names          # Type=Link
    assert all(n for n in names), "an entry with no Name got through"


def test_the_users_own_copy_outranks_the_packaged_one(
        fake_home, system_apps, monkeypatch):
    """Duplicate basenames resolve by precedence, user last and highest."""
    from kairo.providers.desktop_entry import DesktopEntryProvider

    local = fake_home / ".local" / "share" / "applications"
    (local / "firefox.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Firefox Nightly\n"
        "Icon=firefox-nightly\nExec=firefox %u\n")

    entries = {e.payload["basename"]: e for e in DesktopEntryProvider().scan()}
    assert entries["firefox.desktop"].name == "Firefox Nightly"
    assert len([e for e in DesktopEntryProvider().scan()
                if e.payload["basename"] == "firefox.desktop"]) == 1


def test_unusual_icon_values_do_not_break_a_row(
        fake_home, system_apps, monkeypatch):
    """Absolute, extensionless, missing, and outright corrupt."""
    from kairo.providers.desktop_entry import DesktopEntryProvider

    art = fake_home / "art"
    art.mkdir()
    real = art / "custom.png"
    from PIL import Image
    Image.new("RGBA", (64, 64), (1, 2, 3, 255)).save(real)
    corrupt = art / "corrupt.png"
    corrupt.write_bytes(b"\x89PNG\r\n\x1a\n" + b"garbage" * 8)

    (system_apps / "abs.desktop").write_text(
        f"[Desktop Entry]\nType=Application\nName=Absolute\n"
        f"Icon={real}\nExec=x\n")
    (system_apps / "corrupt-icon.desktop").write_text(
        f"[Desktop Entry]\nType=Application\nName=CorruptIcon\n"
        f"Icon={corrupt}\nExec=x\n")
    (system_apps / "gone.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=MissingIcon\n"
        "Icon=/nowhere/at/all.png\nExec=x\n")
    (system_apps / "noicon.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=NoIconAtAll\nExec=x\n")
    (system_apps / "unicode.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Тест — 日本語 ✓\n"
        "Icon=x\nExec=x\n", encoding="utf-8")

    by_name = {e.name: e for e in DesktopEntryProvider().scan()}
    assert by_name["Absolute"].current_icon == real
    assert by_name["MissingIcon"].current_icon is None
    assert by_name["NoIconAtAll"].current_icon is None
    assert "Тест — 日本語 ✓" in by_name, "a Unicode name was dropped"
    # A corrupt file still resolves as a path; decoding is the UI's problem
    # and must produce a placeholder, not an exception.
    assert by_name["CorruptIcon"].current_icon == corrupt


def test_an_unreachable_steam_library_does_not_end_the_steam_scan(
        fake_home, steam_library):
    """The everyday case: a library folder on a drive that is not plugged in.

    libraryfolders.vdf still lists it, so every scan probes a path whose
    parent cannot be stat'ed.
    """
    import os
    from kairo.providers.steam import SteamProvider

    detached = fake_home / "detached"
    (detached / "games" / "steamapps").mkdir(parents=True)
    (steam_library / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"0"\n\t{\n'
        f'\t\t"path"\t\t"{detached / "games"}"\n\t}}\n}}\n')

    os.chmod(detached, 0o000)
    try:
        entries = SteamProvider().scan()
    finally:
        os.chmod(detached, 0o755)

    names = {entry.name for entry in entries}
    assert "Team Fortress 2" in names, "the reachable library was dropped too"
    assert "Portal 2" in names
    assert "Steam Linux Runtime 3.0" not in names, "runtimes are still filtered"


# ---------------------------------------------------------------------------
# Sidebar logos follow the effective launcher icon
# ---------------------------------------------------------------------------

@pytest.fixture
def launchers(fake_home, monkeypatch):
    """A packaged launcher for PCSX2, Dolphin and Steam, plus the user's dir."""
    from kairo import paths

    system = fake_home / "usr-share-applications"
    system.mkdir()
    for basename, name, icon, command in (
            ("PCSX2.desktop", "PCSX2", "PCSX2", "pcsx2-qt %f"),
            ("dolphin-emu.desktop", "Dolphin Emulator", "dolphin-emu",
             "dolphin-emu -b %f"),
            ("steam.desktop", "Steam", "steam", "steam %U")):
        (system / basename).write_text(
            f"[Desktop Entry]\nType=Application\nName={name}\n"
            f"Icon={icon}\nExec={command}\n")

    local = fake_home / ".local" / "share" / "applications"
    monkeypatch.setattr(paths, "system_application_dirs",
                        lambda: [system, local])
    return system, local


def _emulator_provider(name, system_id, **kwargs):
    from kairo.emulators import Emulator, RomFolder
    from kairo.providers.emulator import EmulatorProvider

    emulator = Emulator(id=kwargs.pop("id", name.lower()), name=name,
                        executable=kwargs.pop("executable", f"/usr/bin/{name}"),
                        folders=(RomFolder(path="/roms", system=system_id),),
                        **kwargs)
    return EmulatorProvider(emulator, order=0)


def _customize(entry_name, art, launchers):
    """Apply an icon through the Applications provider, as a user would."""
    from kairo import actions
    from kairo.ledger import Ledger
    from kairo.providers.desktop_entry import DesktopEntryProvider

    apps = DesktopEntryProvider()
    entry = {e.name: e for e in apps.scan()}[entry_name]
    ledger = Ledger()
    actions.apply_icon(entry, apps, art, source_label="Local file",
                       ledger=ledger)
    return apps, ledger


@pytest.fixture
def artwork(fake_home):
    from PIL import Image

    path = fake_home / "chosen.png"
    Image.new("RGBA", (256, 256), (255, 90, 20, 255)).save(path)
    return path


def test_a_sidebar_logo_starts_at_the_packaged_icon(launchers):
    """Acceptance 1."""
    assert _emulator_provider("PCSX2", "ps2").nav_icon_values()[0] == "PCSX2"
    assert _emulator_provider("Dolphin", "gamecube").nav_icon_values()[0] \
        == "dolphin-emu"

    from kairo.providers.steam import SteamProvider
    assert SteamProvider().nav_icon_values()[0] == "steam"


def test_customising_moves_every_matching_sidebar_row(launchers, artwork):
    """Acceptance 2, 3 and 7 — and the two-Dolphin-libraries case."""
    from kairo.providers.steam import SteamProvider

    _, local = launchers
    _customize("PCSX2", artwork, launchers)

    applied = _emulator_provider("PCSX2", "ps2").nav_icon_values()[0]
    assert Path(applied).is_absolute(), "the override writes a path, not a name"
    assert Path(applied).is_file()

    # A second provider for the same emulator reads the same launcher.
    second = _emulator_provider("PCSX2", "ps2", id="pcsx2-b")
    assert second.nav_icon_values()[0] == applied

    # And an unrelated emulator is unaffected.
    assert _emulator_provider("Dolphin", "gamecube").nav_icon_values()[0] \
        == "dolphin-emu"
    assert SteamProvider().nav_icon_values()[0] == "steam"

    # The desktop sees it too: the override is what precedence selects.
    assert (local / "PCSX2.desktop").is_file()
    assert "X-Kairo-Managed" in (local / "PCSX2.desktop").read_text()


def test_the_customised_logo_survives_a_restart(launchers, artwork):
    """Acceptance 4. Nothing is cached in the provider that made the change."""
    _customize("PCSX2", artwork, launchers)
    applied = _emulator_provider("PCSX2", "ps2").nav_icon_values()[0]

    fresh = _emulator_provider("PCSX2", "ps2", icon="PCSX2")
    assert fresh.nav_icon_values()[0] == applied, (
        "a value stored when the emulator was configured went stale")


def test_reset_returns_the_packaged_icon_everywhere(launchers, artwork):
    """Acceptance 5 and 6."""
    from types import SimpleNamespace
    from kairo import actions

    system, local = launchers
    apps, ledger = _customize("PCSX2", artwork, launchers)
    assert _emulator_provider("PCSX2", "ps2").nav_icon_values()[0] != "PCSX2"

    registry = SimpleNamespace(get=lambda provider_id: apps)
    actions.restore_record(ledger.records()[0], registry, ledger=ledger)

    assert _emulator_provider("PCSX2", "ps2").nav_icon_values()[0] == "PCSX2"
    assert not (local / "PCSX2.desktop").exists(), "the override outlived reset"
    assert "Icon=PCSX2" in (system / "PCSX2.desktop").read_text(), (
        "the packaged file must never have been touched")
    assert ledger.records() == []


def test_steam_follows_and_resets_too(launchers, artwork):
    """Acceptance 7, for the provider that is not an emulator."""
    from types import SimpleNamespace
    from kairo import actions
    from kairo.providers.steam import SteamProvider

    apps, ledger = _customize("Steam", artwork, launchers)
    assert Path(SteamProvider().nav_icon_values()[0]).is_absolute()

    registry = SimpleNamespace(get=lambda provider_id: apps)
    actions.restore_record(ledger.records()[0], registry, ledger=ledger)
    assert SteamProvider().nav_icon_values()[0] == "steam"


def test_an_emulator_with_no_launcher_falls_back_without_error(launchers):
    """Acceptance 8. A bare AppImage registers nothing."""
    provider = _emulator_provider("Cemu", "wiiu",
                                  executable="/home/x/Cemu.AppImage")
    assert provider.launcher_path() is None
    assert provider.nav_icon_values(), "the row must still have candidates"
    assert provider.nav_icon == "disc", "and a drawn glyph behind them"
    assert all(not Path(v).is_absolute() for v in provider.nav_icon_values())


def test_the_lookup_survives_an_unreadable_launcher_directory(
        launchers, monkeypatch):
    """Acceptance 8, the hostile variant."""
    import os
    from kairo import paths

    system, local = launchers
    blocked = system.parent / "blocked"
    (blocked / "applications").mkdir(parents=True)
    monkeypatch.setattr(paths, "system_application_dirs",
                        lambda: [blocked / "applications", system, local])
    os.chmod(blocked, 0o000)
    try:
        assert _emulator_provider("PCSX2", "ps2").nav_icon_values()[0] == "PCSX2"
    finally:
        os.chmod(blocked, 0o755)


def test_no_second_icon_writing_path_was_introduced(launchers):
    """Acceptance 10. Exactly two writers, and the lookup only reads."""
    import inspect
    from kairo.providers import writers
    from kairo.providers.base import LauncherWriter
    from kairo.desktop import lookup

    concrete = {name for name, obj in vars(writers).items()
                if inspect.isclass(obj) and issubclass(obj, LauncherWriter)
                and obj is not LauncherWriter}
    assert concrete == {"GeneratedEntryWriter", "OverrideWriter"}, concrete

    source = Path(lookup.__file__).read_text()
    for forbidden in ("open(", "write_text", "atomic_write", "unlink",
                      "mkdir", "replace("):
        assert forbidden not in source, (
            f"the icon lookup must only read; found {forbidden!r}")
