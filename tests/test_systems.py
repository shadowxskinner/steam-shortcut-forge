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
    executable, arguments, icon = systems.find_executable(system)
    assert executable == "/usr/bin/dolphin-emu"
    assert "run" not in arguments
    assert icon == "dolphin-emu", "a native binary names its own icon"


def test_a_flatpak_is_invoked_through_flatpak_run(monkeypatch):
    system = systems.by_id("gamecube")
    monkeypatch.setattr(systems.shutil, "which",
                        lambda name: "/usr/bin/flatpak" if name == "flatpak" else None)
    monkeypatch.setattr(systems, "from_desktop_entry",
                        lambda _system: ("", (), ""))
    monkeypatch.setattr(systems, "_flatpak_installed", lambda app_id: True)
    executable, arguments, icon = systems.find_executable(system)
    assert executable.endswith("flatpak")
    assert arguments[:2] == ("run", "org.DolphinEmu.dolphin-emu")
    assert icon == "org.DolphinEmu.dolphin-emu"


def test_nothing_installed_is_reported_not_guessed(monkeypatch):
    monkeypatch.setattr(systems.shutil, "which", lambda name: None)
    monkeypatch.setattr(systems, "_flatpak_installed", lambda app_id: False)
    assert systems.find_executable(systems.by_id("ps2")) == ("", (), "")


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
    monkeypatch.setattr(systems, "from_desktop_entry",
                        lambda _system: ("", (), ""))
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
        "Exec=/var/lib/flatpak/exports/bin/org.DolphinEmu.dolphin-emu %U\n"
        "Icon=org.DolphinEmu.dolphin-emu\n")
    monkeypatch.setattr(systems.shutil, "which", lambda name: None)
    monkeypatch.setattr(systems.paths, "system_application_dirs", lambda: [apps])

    executable, arguments, icon = systems.find_executable(systems.by_id("gamecube"))
    assert executable.endswith("org.DolphinEmu.dolphin-emu")
    assert "%U" not in " ".join(arguments), "field codes must not survive"
    assert arguments[-2:] == ("-b", "-e")
    assert icon == "org.DolphinEmu.dolphin-emu", "Icon= is the declared name"


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


def test_the_icon_name_comes_from_the_launcher_entry(monkeypatch, tmp_path):
    """Deriving it from the executable works for Dolphin by luck alone.

    pcsx2-qt installs PCSX2, duckstation-qt installs duckstation, PPSSPPQt
    installs ppsspp: the binary is not named after the icon.
    """
    apps = tmp_path / "applications"
    apps.mkdir()
    (apps / "PCSX2.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=PCSX2\n"
        "Exec=/usr/bin/pcsx2-qt %f\nIcon=PCSX2\n")
    monkeypatch.setattr(systems.paths, "system_application_dirs", lambda: [apps])
    monkeypatch.setattr(systems.shutil, "which",
                        lambda n: "/usr/bin/pcsx2-qt" if n == "pcsx2-qt" else None)

    executable, _arguments, icon = systems.find_executable(systems.by_id("ps2"))
    assert executable == "/usr/bin/pcsx2-qt", "the native binary still wins"
    assert icon == "PCSX2", "but the icon is the one the package declared"


def test_an_emulator_keeps_the_icon_it_was_detected_with():
    from kairo import emulators as emu

    original = emu.Emulator(name="PCSX2", executable="/usr/bin/pcsx2-qt",
                            icon="PCSX2").normalised()
    assert emu.Emulator.from_dict(original.as_dict()).icon == "PCSX2"


def test_an_unreadable_directory_does_not_crash_detection(monkeypatch, tmp_path):
    """is_dir() raises rather than returning False on an unstattable path.

    One unreadable entry in XDG_DATA_DIRS crashed the emulator picker on the
    way open, with a PermissionError rather than a message.
    """
    class Hostile:
        def is_dir(self):
            raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(systems.paths, "system_application_dirs",
                        lambda: [Hostile()])
    assert systems.from_desktop_entry(systems.by_id("ps2")) == ("", (), "")

    monkeypatch.setattr(systems, "ROM_ROOTS", ("/nope",))
    assert systems.find_roms(systems.by_id("ps2")) == ""


def test_an_unreadable_flatpak_export_is_not_installed(monkeypatch):
    def explode(self):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "exists", explode)
    assert systems._flatpak_installed("net.pcsx2.PCSX2") is False


# ---------------------------------------------------------------------------
# Emulator identity: the icon to look for, and the glyph when there is none
# ---------------------------------------------------------------------------

def test_every_catalogued_emulator_has_icon_candidates_and_a_medium():
    from kairo.systems import CATALOGUE

    for system in CATALOGUE:
        assert system.icons, f"{system.emulator} has nothing to look up"
        assert system.medium in {"disc", "cartridge", "handheld"}, (
            f"{system.id} has no drawable medium")


def test_icon_candidates_are_ordered_and_deduplicated():
    from kairo.systems import icon_candidates

    found = icon_candidates("PCSX2", ("ps2",))
    assert found[0] == "PCSX2", "the packaged name should be tried first"
    assert "net.pcsx2.PCSX2" in found, "a Flatpak install names its icon by id"
    assert len(found) == len(set(found))


def test_candidates_survive_a_renamed_emulator():
    """The name is user-editable; the configured systems are not."""
    from kairo.systems import icon_candidates

    assert icon_candidates("My PS2 Thing", ("ps2",))[0] == "PCSX2"
    assert icon_candidates("Unknown", ()) == ()


def test_a_multi_system_front_end_does_not_claim_a_medium():
    from kairo.systems import medium_for

    assert medium_for(("gamecube", "wii")) == "disc"
    assert medium_for(("nes", "genesis")) == "cartridge"
    assert medium_for(("gba", "nds")) == "handheld"
    # RetroArch across a disc system and a cartridge one is neither.
    assert medium_for(("ps2", "snes")) == "chip"
    assert medium_for(()) == "chip"


def test_an_emulator_with_no_launcher_entry_still_has_a_logo_to_find():
    """The PCSX2 case: an AppImage registers no .desktop, so Icon= is empty.

    Before this, nav_icon_name fell back to the executable file name, which
    for an AppImage is something like 'pcsx2-Qt.AppImage' and resolves to
    nothing — so PCSX2 drew a generic chip while Dolphin, installed as a
    package, showed its real logo.
    """
    from kairo.emulators import Emulator, RomFolder
    from kairo.providers.emulator import EmulatorProvider

    emulator = Emulator(id="pcsx2", name="PCSX2",
                        executable="/home/someone/Apps/pcsx2-Qt.AppImage",
                        icon="",
                        folders=(RomFolder(path="/roms/ps2", system="ps2"),))
    provider = EmulatorProvider(emulator, order=0)

    assert "PCSX2" in provider.nav_icon_names
    assert "net.pcsx2.PCSX2" in provider.nav_icon_names
    assert provider.nav_icon_names[-1] == "pcsx2-Qt.AppImage", (
        "the executable stays as a last resort, not the only one")
    assert provider.nav_icon == "disc", "PS2 games came on discs"


def test_a_declared_icon_still_wins():
    from kairo.emulators import Emulator, RomFolder
    from kairo.providers.emulator import EmulatorProvider

    emulator = Emulator(id="dolphin", name="Dolphin",
                        executable="/usr/bin/dolphin-emu", icon="dolphin-emu",
                        folders=(RomFolder(path="/roms/gc",
                                           system="gamecube"),))
    provider = EmulatorProvider(emulator, order=0)
    assert provider.nav_icon_names[0] == "dolphin-emu"
