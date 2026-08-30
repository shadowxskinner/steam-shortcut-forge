"""The catalogue: what Kairo knows so the user does not have to type it.

Every comparable tool ships one — ES-DE's es_systems.xml, Steam ROM Manager's
community presets. These pin the shape of ours and the detection around it.
"""

from pathlib import Path

from kairo import systems


def test_every_system_knows_its_own_file_types():
    """The whole point: nobody should have to know GameCube means .rvz."""
    for system in systems.CATALOGUE:
        assert system.extensions, system.id
        for ext in system.extensions:
            assert ext.startswith("."), (system.id, ext)
            assert ext == ext.lower(), (system.id, ext)


def test_every_system_names_something_that_runs_it():
    for system in systems.CATALOGUE:
        assert system.commands or system.flatpaks, system.id
        assert system.emulator, system.id


def test_ids_are_unique():
    ids = [s.id for s in systems.CATALOGUE]
    assert len(ids) == len(set(ids))


def test_dolphin_covers_both_of_its_systems():
    """The case that drove the whole design."""
    gc = systems.by_id("gamecube")
    wii = systems.by_id("wii")
    assert gc and wii
    assert gc.emulator == wii.emulator == "Dolphin"
    assert gc.extensions != wii.extensions
    assert ".wbfs" in wii.extensions and ".wbfs" not in gc.extensions
    assert ".gcm" in gc.extensions


def test_a_native_binary_is_preferred_over_a_flatpak(monkeypatch):
    """Fewer moving parts, and no flatpak run to prepend."""
    system = systems.by_id("gamecube")
    monkeypatch.setattr(systems.shutil, "which",
                        lambda name: "/usr/bin/dolphin-emu"
                        if name == "dolphin-emu" else None)
    executable, arguments = systems.find_executable(system)
    assert executable == "/usr/bin/dolphin-emu"
    assert "run" not in arguments


def test_a_flatpak_is_invoked_through_flatpak_run(monkeypatch):
    system = systems.by_id("gamecube")
    monkeypatch.setattr(systems.shutil, "which",
                        lambda name: "/usr/bin/flatpak" if name == "flatpak" else None)
    monkeypatch.setattr(systems, "_flatpak_installed", lambda app_id: True)
    executable, arguments = systems.find_executable(system)
    assert executable.endswith("flatpak")
    assert arguments[:2] == ("run", "org.DolphinEmu.dolphin-emu")


def test_nothing_installed_is_reported_not_guessed(monkeypatch):
    monkeypatch.setattr(systems.shutil, "which", lambda name: None)
    monkeypatch.setattr(systems, "_flatpak_installed", lambda app_id: False)
    assert systems.find_executable(systems.by_id("ps2")) == ("", ())


def test_a_conventional_rom_folder_is_found(monkeypatch, tmp_path):
    """EmuDeck's layout is standard enough to look for."""
    roms = tmp_path / "Emulation" / "roms" / "gc"
    roms.mkdir(parents=True)
    (roms / "Some Game.rvz").write_bytes(b"")
    monkeypatch.setattr(systems, "ROM_ROOTS", (str(tmp_path / "Emulation/roms"),))
    assert systems.find_roms(systems.by_id("gamecube")) == str(roms)


def test_an_empty_folder_is_not_offered(monkeypatch, tmp_path):
    """A directory that exists but holds no games is not a find."""
    (tmp_path / "Emulation" / "roms" / "gc").mkdir(parents=True)
    monkeypatch.setattr(systems, "ROM_ROOTS", (str(tmp_path / "Emulation/roms"),))
    assert systems.find_roms(systems.by_id("gamecube")) == ""


def test_detection_puts_what_is_installed_first(monkeypatch):
    monkeypatch.setattr(systems.shutil, "which",
                        lambda name: "/usr/bin/pcsx2-qt" if name == "pcsx2-qt" else None)
    monkeypatch.setattr(systems, "_flatpak_installed", lambda app_id: False)
    monkeypatch.setattr(systems, "find_roms", lambda system: "")
    found = systems.detect()
    assert found[0].system.id == "ps2"
    assert found[0].installed is True
    assert all(not d.installed for d in found[1:])
    assert len(found) == len(systems.CATALOGUE), "nothing may disappear"
