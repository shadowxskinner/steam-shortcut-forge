"""One provider per configured emulator.

The interesting cases are the ones that only appear once configuration
reaches a filename: keys with separators in them, paths with spaces, and an
emulator the user has half-finished setting up.
"""

from pathlib import Path


from kairo import emulators as emu
from kairo.providers.emulator import EmulatorProvider, providers_from_config


def dolphin(tmp_path):
    gc = tmp_path / "gc"
    wii = tmp_path / "wii"
    gc.mkdir()
    wii.mkdir()
    (gc / "Super Mario Sunshine (USA).rvz").write_bytes(b"x")
    (wii / "Twilight Princess.wbfs").write_bytes(b"x")
    exe = tmp_path / "dolphin-emu"
    exe.write_bytes(b"")
    return emu.Emulator(
        name="Dolphin", executable=str(exe),
        folders=(emu.RomFolder(str(gc), ("rvz",), "GameCube"),
                 emu.RomFolder(str(wii), ("wbfs",), "Wii"))).normalised()


def test_each_emulator_becomes_its_own_destination():
    config = {"emulators": [
        {"name": "Cemu", "executable": "/usr/bin/cemu", "folders": []},
        {"name": "PCSX2", "executable": "/usr/bin/pcsx2", "folders": []}]}
    providers = providers_from_config(config)
    assert [p.label for p in providers] == ["Cemu", "PCSX2"]
    assert [p.id for p in providers] == ["emu-cemu", "emu-pcsx2"]
    assert {p.group for p in providers} == {"Emulators"}


def test_a_provider_id_never_contains_the_key_separator():
    """AppEntry splits its key on the first colon.

    A colon in the provider id would leave the separator inside local_id, and
    local_id becomes a .desktop filename.
    """
    provider = EmulatorProvider(emu.Emulator(name="PCSX2").normalised())
    assert ":" not in provider.id


def test_entry_keys_are_legal_in_a_filename(tmp_path):
    provider = EmulatorProvider(dolphin(tmp_path))
    for entry in provider.scan():
        assert "/" not in entry.local_id
        assert ":" not in entry.local_id
        assert entry.local_id.strip() == entry.local_id


def test_the_system_label_reaches_the_entry(tmp_path):
    provider = EmulatorProvider(dolphin(tmp_path))
    assert {e.name: e.subtitle for e in provider.scan()} == {
        "Super Mario Sunshine": "GameCube",
        "Twilight Princess": "Wii"}


def test_a_half_configured_emulator_stays_visible_but_empty():
    """Hiding it would leave nowhere to go and fix the mistake."""
    provider = EmulatorProvider(
        emu.Emulator(name="Cemu", executable="/nope/cemu").normalised())
    assert provider.available() is True
    assert provider.scan() == []
    assert provider.problems()


def test_the_launch_command_survives_spaces(tmp_path):
    """ROM paths have spaces far more often than not."""
    provider = EmulatorProvider(dolphin(tmp_path))
    entry = next(e for e in provider.scan() if "Sunshine" in e.name)
    fields = provider.writer().build_fields(entry, Path("/icons/a.png"))
    assert "Super Mario Sunshine (USA).rvz" in fields["Exec"]
    assert fields["Exec"].count("'") >= 2, "the ROM path must be quoted"
    assert fields["X-KairoEmulator"] == "dolphin"


def test_the_entry_identifies_itself_as_kairos(tmp_path):
    from kairo.desktop import entry as de

    provider = EmulatorProvider(dolphin(tmp_path))
    entry = provider.scan()[0]
    fields = provider.writer().build_fields(entry, Path("/icons/a.png"))
    assert fields[de.MANAGED_KEYS[0]] == "true"


def test_the_artwork_search_falls_back_to_the_system(tmp_path):
    """A bare title can be ambiguous; the console name disambiguates it."""
    provider = EmulatorProvider(dolphin(tmp_path))
    entry = next(e for e in provider.scan() if "Twilight" in e.name)
    query = provider.artwork_query(entry)
    assert query.text == "twilight princess"
    assert query.fallback_text == "twilight princess wii"


def test_steamgriddb_leads_for_roms():
    """It carries game art; themes and Iconify carry symbols.

    It was excluded on the belief that it needed a Steam appid. That was
    Kairo's restriction, not the API's - it searches by title too.
    """
    provider = EmulatorProvider(emu.Emulator(name="Cemu").normalised())
    assert provider.auto_match_sources[0] == "steamgriddb"


def test_a_retitled_rom_keeps_its_key(tmp_path):
    """Editing the display name must not orphan that shortcut's history."""
    provider = EmulatorProvider(dolphin(tmp_path))
    before = {e.key for e in provider.scan()}
    entries = provider.scan()
    entries[0].name = "Something Entirely Different"
    assert {e.key for e in provider.scan()} == before
