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
