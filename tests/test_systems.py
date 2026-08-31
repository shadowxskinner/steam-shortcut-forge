"""The catalogue: what Kairo knows so the user does not have to type it.

Every comparable tool ships one — ES-DE's es_systems.xml, Steam ROM Manager's
community presets. These pin the shape of ours and the detection around it.
"""

from dataclasses import replace
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


def test_pcsx2_catalogue_matches_its_current_scanner_and_cli():
    """Keep Kairo's preset aligned with the formats PCSX2 itself scans."""
    ps2 = systems.by_id("ps2")
    assert ps2.emulator == "PCSX2"
    assert ps2.arguments == ("-batch",)
    assert "net.pcsx2.PCSX2" in ps2.flatpaks
    assert {".iso", ".bin", ".img", ".mdf", ".gz", ".cso", ".zso",
            ".chd", ".elf"} <= set(ps2.extensions)


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
    monkeypatch.setattr(systems, "from_desktop_entry", lambda _system: ("", ()))
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
    monkeypatch.setattr(systems, "from_desktop_entry", lambda _system: ("", ()))
    monkeypatch.setattr(systems, "_flatpak_installed", lambda app_id: False)
    monkeypatch.setattr(systems, "find_roms", lambda system: "")
    found = systems.detect()
    assert found[0].system.id == "ps2"
    assert found[0].installed is True
    assert all(not d.installed for d in found[1:])
    assert len(found) == len(systems.CATALOGUE), "nothing may disappear"


def test_an_installed_launcher_entry_is_enough_to_find_it(monkeypatch, tmp_path):
    """The general answer to "how was it installed".

    A native package, an AUR build, a Flatpak, a Snap and an AppImage all drop
    a .desktop file. Its Exec line is the command that works on this machine,
    with no guessing at binary names or export paths.
    """
    apps = tmp_path / "applications"
    apps.mkdir()
    (apps / "org.DolphinEmu.dolphin-emu.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Dolphin\n"
        "Exec=/var/lib/flatpak/exports/bin/org.DolphinEmu.dolphin-emu %U\n")
    monkeypatch.setattr(systems.shutil, "which", lambda name: None)
    monkeypatch.setattr(systems.paths, "system_application_dirs", lambda: [apps])

    executable, arguments = systems.find_executable(systems.by_id("gamecube"))
    assert executable.endswith("org.DolphinEmu.dolphin-emu")
    assert "%U" not in " ".join(arguments), "field codes must not survive"
    assert arguments[-2:] == ("-b", "-e")


def test_the_emulators_own_config_is_read_for_rom_paths(monkeypatch, tmp_path):
    """Every setup guide ends with "make this match the emulator".

    If the emulator already knows where the games are, Kairo can read it
    rather than asking again.
    """
    roms = tmp_path / "games"
    roms.mkdir()
    (roms / "Some Game.rvz").write_bytes(b"")
    ini = tmp_path / "Dolphin.ini"
    ini.write_text("[General]\nISOPath0 = " + str(roms) + "\nISOPaths = 1\n")

    # System is frozen on purpose, so a variant is made rather than mutated.
    system = replace(systems.by_id("gamecube"), config=str(ini))
    assert systems.from_emulator_config(system) == [str(roms)]
    monkeypatch.setattr(systems, "ROM_ROOTS", ())
    assert systems.find_roms(system) == str(roms)


def test_pcsx2_game_list_paths_are_discovered(monkeypatch, tmp_path):
    """PCSX2 writes repeated Paths values rather than Dolphin's numbered keys."""
    direct = tmp_path / "direct"
    recursive = tmp_path / "recursive"
    unrelated = tmp_path / "not-a-game-list"
    direct.mkdir()
    recursive.mkdir()
    unrelated.mkdir()
    (recursive / "A Game.zso").write_bytes(b"")
    ini = tmp_path / "PCSX2.ini"
    ini.write_text(
        f"[Folders]\nPaths = {unrelated}\n"
        f"[GameList]\nPaths = {direct}\nRecursivePaths = {recursive}\n")

    system = replace(systems.by_id("ps2"), config=str(ini),
                     config_fallbacks=())
    assert systems.from_emulator_config(system) == [str(direct), str(recursive)]
    monkeypatch.setattr(systems, "ROM_ROOTS", ())
    assert systems.find_roms(system) == str(recursive)


def test_pcsx2_flatpak_config_is_a_real_fallback(tmp_path):
    roms = tmp_path / "roms"
    roms.mkdir()
    fallback = tmp_path / "flatpak" / "PCSX2.ini"
    fallback.parent.mkdir()
    fallback.write_text(f"[GameList]\nRecursivePaths = {roms}\n")
    system = replace(systems.by_id("ps2"), config=str(tmp_path / "missing.ini"),
                     config_fallbacks=(str(fallback),))
    assert systems.from_emulator_config(system) == [str(roms)]


def test_pcsx2_native_config_respects_xdg_config_home(monkeypatch, tmp_path):
    roms = tmp_path / "roms"
    roms.mkdir()
    xdg = tmp_path / "xdg"
    ini = xdg / "PCSX2" / "inis" / "PCSX2.ini"
    ini.parent.mkdir(parents=True)
    ini.write_text(f"[GameList]\nPaths = {roms}\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    system = replace(systems.by_id("ps2"), config_fallbacks=())
    assert systems.from_emulator_config(system) == [str(roms)]


def test_a_configured_path_that_no_longer_exists_is_ignored(tmp_path):
    ini = tmp_path / "Dolphin.ini"
    ini.write_text("[General]\nISOPath0 = /gone/for/good\n")
    system = replace(systems.by_id("gamecube"), config=str(ini))
    assert systems.from_emulator_config(system) == []
