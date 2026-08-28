import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """An isolated HOME.

    Every path in kairo.paths is derived from HOME at call time precisely so
    that this fixture can exist. Nothing in the test suite is permitted to read
    or write the real user's config, icon store or applications directory.
    """
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)
    (home / ".local" / "share" / "applications").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "nonexistent-share"))
    monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)
    monkeypatch.delenv("DESKTOP_SESSION", raising=False)

    from kairo.themeindex import ThemeIndex
    ThemeIndex.reset()
    yield home
    ThemeIndex.reset()


@pytest.fixture
def steam_library(fake_home):
    """A Steam install with three installed apps, one of them a runtime."""
    steamapps = fake_home / ".steam" / "steam" / "steamapps"
    steamapps.mkdir(parents=True)

    def manifest(appid, name):
        (steamapps / f"appmanifest_{appid}.acf").write_text(
            '"AppState"\n{\n'
            f'\t"appid"\t\t"{appid}"\n'
            f'\t"name"\t\t"{name}"\n'
            "}\n")

    manifest("440", "Team Fortress 2")
    manifest("620", "Portal 2")
    manifest("1070560", "Steam Linux Runtime 3.0")
    return steamapps


@pytest.fixture
def system_apps(fake_home, monkeypatch):
    """A read-only system applications directory."""
    system = fake_home / "usr-share-applications"
    system.mkdir()

    (system / "org.kde.dolphin.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Dolphin\n"
        "Icon=org.kde.dolphin\nExec=dolphin %u\nMimeType=inode/directory;\n"
        "StartupWMClass=dolphin\nActions=new-window;\n"
        "\n[Desktop Action new-window]\nName=New Window\nIcon=window-new\n"
        "Exec=dolphin --new-window\n")
    (system / "firefox.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Firefox\nIcon=firefox\n"
        "Exec=firefox %u\n")
    (system / "hidden.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Hidden\nNoDisplay=true\n"
        "Icon=x\nExec=x\n")
    (system / "link.desktop").write_text(
        "[Desktop Entry]\nType=Link\nName=A Link\nURL=https://example.com\n")
    (system / "broken.desktop").write_text(
        "not a desktop file at all\n[[[\n")
    (system / "noname.desktop").write_text(
        "[Desktop Entry]\nType=Application\nIcon=x\nExec=x\n")

    from kairo import paths
    local = fake_home / ".local" / "share" / "applications"
    monkeypatch.setattr(paths, "system_application_dirs", lambda: [system, local])
    return system


@pytest.fixture
def legacy_install(fake_home):
    """A realistic Steam Shortcut Forge installation to migrate from.

    Deliberately includes the awkward shapes: CRLF, a hand-written override we
    must not touch, a malformed file, a file with no [Desktop Entry], an
    override whose [Desktop Action] carries its own Icon=, and a path that
    cannot be read at all.
    """
    config = fake_home / ".config" / "steam-shortcut-forge"
    cache = config / "cache"
    cache.mkdir(parents=True)
    (config / "config.json").write_text(
        '{"steamgriddb_api_key": "legacy-key-123", "some_setting": true}\n')
    (cache / "themes.json").write_text('{"version": 2, "themes": {}}')

    icons = fake_home / ".local" / "share" / "steam-shortcut-forge" / "icons"
    icons.mkdir(parents=True)
    for name in ("440_aaaa.png", "620_bbbb.png", "dolphin_cccc.png"):
        (icons / name).write_bytes(b"\x89PNG\r\n\x1a\n" + name.encode())

    apps = fake_home / ".local" / "share" / "applications"

    # A generated Steam shortcut.
    (apps / "steam-shortcut-forge-440.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Team Fortress 2\n"
        f"Exec=steam steam://rungameid/440\nIcon={icons / '440_aaaa.png'}\n"
        "Categories=Game;\nTerminal=false\nX-SteamAppId=440\n")

    # A generated shortcut with Windows line endings.
    (apps / "steam-shortcut-forge-620.desktop").write_bytes(
        ("[Desktop Entry]\r\nType=Application\r\nName=Portal 2\r\n"
         f"Exec=steam steam://rungameid/620\r\nIcon={icons / '620_bbbb.png'}\r\n"
         "Categories=Game;\r\nX-SteamAppId=620\r\n").encode())

    # A managed system override, with an action carrying its own icon.
    (apps / "org.kde.dolphin.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Dolphin\n"
        f"Icon={icons / 'dolphin_cccc.png'}\n"
        "Exec=dolphin %u\nMimeType=inode/directory;\nActions=new-window;\n"
        "X-ShortcutForge-Managed=true\n"
        "X-ShortcutForge-OriginalIcon=org.kde.dolphin\n"
        "\n[Desktop Action new-window]\nName=New Window\nIcon=window-new\n"
        "Exec=dolphin --new-window\n")

    # A hand-written override. Kairo must never touch this.
    (apps / "firefox.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Firefox\nIcon=my-own-icon\n"
        "Exec=firefox %u\n")

    # Malformed, and a file with no [Desktop Entry] group.
    (apps / "broken.desktop").write_text("not a desktop file\n[[[\n")
    (apps / "noentry.desktop").write_text(
        "[Desktop Action solo]\nName=Orphan\nIcon=x\n")

    # Unreadable: a directory where a file is expected, so the read raises.
    (apps / "steam-shortcut-forge-999.desktop").mkdir()

    return {"config": config, "cache": cache, "icons": icons, "apps": apps}
