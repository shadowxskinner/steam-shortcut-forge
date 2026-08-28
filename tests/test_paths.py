"""Path derivation: XDG bases and anything remote that becomes a filename."""

import pytest

from kairo import paths


# -- XDG base directories ---------------------------------------------------

def test_defaults_when_xdg_is_unset(fake_home):
    assert paths.config_dir() == fake_home / ".config" / "kairo"
    assert paths.data_dir() == fake_home / ".local" / "share" / "kairo"
    assert paths.applications_dir() == fake_home / ".local" / "share" / "applications"


def test_xdg_data_home_is_honoured(fake_home, monkeypatch, tmp_path):
    """Writing entries where the desktop is not looking makes them silently
    never appear."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert paths.applications_dir() == tmp_path / "data" / "applications"
    assert paths.icon_store() == tmp_path / "data" / "kairo" / "icons"


def test_xdg_config_home_is_honoured(fake_home, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert paths.config_file() == tmp_path / "cfg" / "kairo" / "config.json"
    assert paths.cache_dir() == tmp_path / "cfg" / "kairo" / "cache"


def test_relative_xdg_values_are_ignored(fake_home, monkeypatch):
    """The spec requires it, and a relative path would resolve against
    whatever directory Kairo happened to be launched from."""
    monkeypatch.setenv("XDG_DATA_HOME", "relative/path")
    assert paths.applications_dir() == fake_home / ".local" / "share" / "applications"


def test_empty_xdg_value_falls_back(fake_home, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", "")
    assert paths.data_home() == fake_home / ".local" / "share"


def test_legacy_dirs_follow_the_same_bases(fake_home, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert paths.legacy_icon_store("steam-shortcut-forge") == \
        tmp_path / "data" / "steam-shortcut-forge" / "icons"


# -- filename sanitising ----------------------------------------------------

@pytest.mark.parametrize("raw", [
    "../../../etc/passwd", "..", ".", "/absolute/path", "a/b/c",
    "with spaces", "sem;colon", "$(command)", "\x00null",
])
def test_sanitised_names_are_single_safe_components(raw):
    got = paths.safe_component(raw)
    assert "/" not in got
    assert got not in {"", ".", ".."}
    assert not got.startswith(".")


def test_sanitising_keeps_ordinary_ids_readable():
    assert paths.safe_component("24601") == "24601"
    assert paths.safe_component("iconify_a1b2c3") == "iconify_a1b2c3"


def test_sanitising_bounds_the_length():
    assert len(paths.safe_component("x" * 500)) <= 64


def test_artwork_id_cannot_escape_the_icon_store(fake_home):
    """Artwork ids come from remote services and the sources create missing
    parent directories, so an unsanitised id would write outside the store."""
    stem = paths.icon_stem("steam", "440", "../../../evil")
    dest = paths.icon_store() / f"{stem}.png"
    assert str(dest.resolve()).startswith(str(paths.icon_store().resolve()))


def test_icon_stem_is_namespaced_by_provider():
    """Without this a Steam appid and a .desktop basename that happen to match
    would share one file, and restoring one would delete the other's artwork."""
    assert paths.icon_stem("steam", "440", "x") != paths.icon_stem("desktop", "440", "x")


def test_icon_stem_survives_empty_parts():
    assert paths.icon_stem("", "", "") == "app_id"
