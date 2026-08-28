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


def test_generated_writer_restore_deletes_entry_and_icon(steam_entry, png, fake_home):
    writer = SteamProvider().writer()
    writer.apply(steam_entry, png)
    icon = steam_entry.current_icon
    writer.restore(steam_entry)
    assert not (paths.applications_dir() / f"{paths.DESKTOP_PREFIX}440.desktop").exists()
    assert not icon.exists()
    assert steam_entry.customized is False


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
    legacy.write_text("[Desktop Entry]\nType=Application\nName=TF2\nIcon=/old.png\n")

    writer = GeneratedEntryWriter(paths.DESKTOP_PREFIX, SteamProvider().writer().build_fields)
    assert writer.existing(steam_entry) == legacy

    writer.apply(steam_entry, png)
    # The legacy file must go, or the launcher shows the game twice.
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
