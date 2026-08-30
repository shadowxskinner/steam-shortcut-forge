"""Emulator configuration and ROM scanning.

Driven by Dolphin: one emulator, two systems, different extensions each.
Nothing here touches a real ROM library or a real emulator - a fake tree in
tmp_path is enough to pin every rule that matters.
"""

from pathlib import Path

from kairo import emulators as emu


# -- titles -----------------------------------------------------------------

def test_dump_tags_are_stripped_for_the_search():
    assert emu.clean_title("Super Mario Sunshine (USA) (Rev 1) [!].rvz") == \
        "Super Mario Sunshine"


def test_a_multi_part_extension_is_fully_removed():
    """game.nkit.iso must not keep .nkit in its title."""
    assert emu.clean_title("Metroid Prime.nkit.iso") == "Metroid Prime"


def test_separators_become_spaces():
    assert emu.clean_title("The_Legend_of_Zelda.iso") == "The Legend of Zelda"
    assert emu.clean_title("Paper-Mario.iso") == "Paper Mario"


def test_a_hyphen_inside_a_spaced_name_survives():
    """Only the all-hyphen style is a separator; real punctuation stays."""
    assert emu.clean_title("Spider-Man 2 (USA).iso") == "Spider-Man 2"


def test_stripping_never_returns_nothing():
    """A file that is entirely tag is still better shown than blank."""
    assert emu.clean_title("(BIOS).bin") == "(BIOS)"


# -- configuration ----------------------------------------------------------

def test_extensions_are_normalised_however_they_are_typed():
    folder = emu.RomFolder("/roms", ("ISO", ".rvz", " .GCM ", "iso")).normalised()
    assert folder.extensions == (".iso", ".rvz", ".gcm")


def test_the_rom_placeholder_is_always_present():
    """An emulator launched with no ROM is not a per-game shortcut."""
    assert emu.ROM_PLACEHOLDER in emu.Emulator(
        name="Dolphin", arguments=("--fullscreen",)).normalised().arguments


def test_the_launch_command_substitutes_the_rom():
    dolphin = emu.Emulator(name="Dolphin", executable="/usr/bin/dolphin-emu",
                           arguments=("-b", emu.ROM_PLACEHOLDER)).normalised()
    assert dolphin.command(Path("/roms/game.rvz")) == \
        ["/usr/bin/dolphin-emu", "-b", "/roms/game.rvz"]


def test_configuration_survives_a_round_trip():
    original = emu.Emulator(
        name="Dolphin", executable="/usr/bin/dolphin-emu",
        folders=(emu.RomFolder("/roms/gc", ("iso", "rvz"), "GameCube"),
                 emu.RomFolder("/roms/wii", ("wbfs",), "Wii"))).normalised()
    assert emu.Emulator.from_dict(original.as_dict()) == original


def test_malformed_configuration_is_ignored_not_fatal():
    assert emu.load({"emulators": "nonsense"}) == []
    assert emu.load({"emulators": [None, 3, {"name": ""}]}) == []
    assert emu.load(None) == []


def test_problems_are_reported_in_words_a_person_can_act_on(tmp_path):
    broken = emu.Emulator(name="Dolphin", executable=str(tmp_path / "nope"))
    problems = broken.problems()
    assert any("does not exist" in p for p in problems)
    assert any("no ROM folders" in p for p in problems)
    assert broken.usable() is False


# -- scanning ---------------------------------------------------------------

def dolphin_tree(tmp_path):
    """One emulator, two systems, as Dolphin actually is."""
    gc = tmp_path / "gc"
    wii = tmp_path / "wii"
    (gc / "subfolder").mkdir(parents=True)
    wii.mkdir()
    (gc / "Super Mario Sunshine (USA).rvz").write_bytes(b"x")
    (gc / "subfolder" / "Metroid Prime.iso").write_bytes(b"x")
    (gc / "notes.txt").write_bytes(b"x")
    (wii / "Twilight Princess (USA).wbfs").write_bytes(b"x")
    executable = tmp_path / "dolphin-emu"
    executable.write_bytes(b"#!/bin/sh\n")
    return emu.Emulator(
        name="Dolphin", executable=str(executable),
        folders=(emu.RomFolder(str(gc), ("rvz", "iso"), "GameCube"),
                 emu.RomFolder(str(wii), ("wbfs",), "Wii"))).normalised()


def test_each_folder_uses_its_own_extensions(tmp_path):
    roms = emu.scan(dolphin_tree(tmp_path))
    assert [rom.title for rom in roms] == \
        ["Metroid Prime", "Super Mario Sunshine", "Twilight Princess"]


def test_the_system_label_rides_along(tmp_path):
    roms = emu.scan(dolphin_tree(tmp_path))
    assert {rom.title: rom.system for rom in roms} == {
        "Metroid Prime": "GameCube",
        "Super Mario Sunshine": "GameCube",
        "Twilight Princess": "Wii"}


def test_files_that_are_not_roms_are_left_alone(tmp_path):
    roms = emu.scan(dolphin_tree(tmp_path))
    assert not any(rom.path.name.endswith(".txt") for rom in roms)


def test_scanning_recurses(tmp_path):
    """Collections are filed by system or by letter, not flat."""
    roms = emu.scan(dolphin_tree(tmp_path))
    assert any(rom.path.parent.name == "subfolder" for rom in roms)


def test_a_missing_folder_does_not_lose_the_others(tmp_path):
    good = dolphin_tree(tmp_path)
    with_ghost = emu.Emulator(
        name=good.name, executable=good.executable,
        folders=(*good.folders,
                 emu.RomFolder(str(tmp_path / "gone"), ("iso",)))).normalised()
    assert len(emu.scan(with_ghost)) == 3


def test_the_same_rom_seen_twice_appears_once(tmp_path):
    """Overlapping folders are a configuration mistake, not a duplicate game."""
    tree = dolphin_tree(tmp_path)
    overlapping = emu.Emulator(
        name=tree.name, executable=tree.executable,
        folders=(*tree.folders,
                 emu.RomFolder(str(tmp_path / "gc"), ("rvz", "iso"))))
    assert len(emu.scan(overlapping.normalised())) == 3


def test_an_id_is_stable_against_a_retitle(tmp_path):
    """Correcting a title must not orphan that shortcut's history."""
    roms = emu.scan(dolphin_tree(tmp_path))
    first = roms[0]
    renamed = emu.Rom(first.emulator_id, first.path, "Something Else",
                      first.system)
    assert renamed.local_id == first.local_id


def test_a_narrow_extension_does_not_catch_its_neighbours(tmp_path):
    """.nkit.iso configured must not match a plain .iso."""
    roms_dir = tmp_path / "roms"
    roms_dir.mkdir()
    (roms_dir / "One.nkit.iso").write_bytes(b"x")
    (roms_dir / "Two.iso").write_bytes(b"x")
    executable = tmp_path / "emu"
    executable.write_bytes(b"")
    narrow = emu.Emulator(name="Narrow", executable=str(executable),
                          folders=(emu.RomFolder(str(roms_dir),
                                                 (".nkit.iso",)),)).normalised()
    assert [rom.title for rom in emu.scan(narrow)] == ["One"]
