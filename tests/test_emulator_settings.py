"""The one place in Kairo where the user configures rather than discovers."""

from pathlib import Path

QT_DIR = Path(__file__).resolve().parents[1] / "kairo" / "qt"


def test_settings_offers_the_emulators_section():
    source = (QT_DIR / "settings.py").read_text()
    assert "EmulatorsCard" in source


def test_configuration_is_written_through_the_config_module():
    """Not by hand-editing the file the way the launcher writers are banned."""
    source = (QT_DIR / "emulator_settings.py").read_text()
    assert "config_store.save" in source
    for backdoor in ("write_text(", "json.dump", "open("):
        assert backdoor not in source, backdoor


def test_removing_an_emulator_asks_and_says_what_survives():
    """Forgetting the configuration must not read as deleting the shortcuts."""
    source = (QT_DIR / "emulator_settings.py").read_text()
    remove = source.split("def _remove")[1]
    assert "QMessageBox" in remove
    assert "QMessageBox.Cancel" in remove
    assert "stay where they are" in remove


def test_an_unusable_emulator_cannot_be_saved():
    """Storing one would show an empty section with no explanation."""
    source = (QT_DIR / "emulator_settings.py").read_text()
    accept = source.split("def _accept")[1]
    assert ".problems()" in accept
    assert "return" in accept.split("QMessageBox.warning")[1]


def test_extensions_may_be_typed_however_people_type_them():
    source = (QT_DIR / "emulator_settings.py").read_text()
    value = source.split("def value")[1]
    assert 'replace(",", " ")' in value


def test_the_sidebar_rebuilds_without_a_restart():
    """Emulators are the only setting that changes what destinations exist."""
    source = (QT_DIR / "shell.py").read_text()
    assert "_providers_changed" in source
    rebuild = source.split("def _providers_changed")[1].split("\n    def ")[0]
    assert "provider_registry(self.config_data)" in rebuild
    assert "build_items" in rebuild
    assert "_build_nav()" in rebuild


def test_the_registry_is_given_the_configuration():
    """Without it there is nowhere for emulators to come from."""
    shell = (QT_DIR / "shell.py").read_text()
    assert "provider_registry(self.config_data)" in shell
    registry = (Path(__file__).resolve().parents[1] / "kairo" / "providers"
                / "registry.py").read_text()
    assert "providers_from_config(config)" in registry


def test_the_api_key_can_actually_be_saved():
    """It was left disabled from the read-only milestone.

    Settings could write emulator configuration while the field beside it
    stayed inert, which is a confusing pair of behaviours to sit together.
    """
    source = (QT_DIR / "settings.py").read_text()
    assert "Not wired yet" not in source
    assert "def _save_key" in source
    save = source.split("def _save_key")[1].split("\n    def ")[0]
    assert "config_store.save" in save
    assert "OSError" in save, "a failed write must be reported"


def test_save_is_offered_only_when_there_is_a_change():
    source = (QT_DIR / "settings.py").read_text()
    changed = source.split("def _key_changed")[1].split("\n    def ")[0]
    assert "setEnabled(" in changed


def test_no_button_is_narrower_than_its_own_label():
    """#secondary carries 16px of side padding.

    A square button has no room for text, and Qt elides the label rather
    than overflowing — which turned a browse button into a single dot.
    """
    source = (QT_DIR / "emulator_settings.py").read_text()
    assert "setFixedWidth(Q.H_BUTTON)" not in source


def test_the_dialog_wears_kairos_colours_not_the_desktops():
    source = (QT_DIR / "emulator_settings.py").read_text()
    assert 'self.setObjectName("dialog")' in source
    assert "WA_StyledBackground" in source


def test_a_folder_row_reports_what_it_actually_matches():
    """A wrong extension looks completely fine until something counts.

    Typing .rvs instead of .rvz, or putting the folder in the wrong box,
    produces a form that validates and a library that is empty.
    """
    source = (QT_DIR / "emulator_settings.py").read_text()
    assert "def recount" in source
    recount = source.split("def recount")[1].split("\n    def ")[0]
    finished = source.split("def _recounted")[1].split("\n    def ")[0]
    assert "no folder" in recount
    # Pluralised in an f-string, so "files" never appears literally.
    assert "file{" in finished
    assert "rglob" in recount, "the count must come from the filesystem"
    assert "textChanged.connect" in source, "it must update as you type"


def test_a_rom_count_never_walks_the_disk_on_the_gui_thread():
    """A large ROM folder must not freeze after every typed character."""
    source = (QT_DIR / "emulator_settings.py").read_text()
    recount = source.split("def recount")[1].split("\n    def ")[0]
    schedule = source.split("def _schedule_recount")[1].split("\n    def ")[0]
    assert "_recount_timer.start()" in schedule
    assert "work.submit(count_files" in recount
    assert "_recount_serial" in recount, "a stale count must not overwrite a new one"


def test_every_folder_field_says_what_it_is():
    """Unlabelled boxes are how a path ends up in the wrong one.

    The path now has its own line, so it is labelled by its placeholder while
    the narrower fields beside it carry captions.
    """
    source = (QT_DIR / "emulator_settings.py").read_text()
    assert '"Folder your games are in"' in source
    for caption in ("File types", "System"):
        assert f'("{caption}"' in source, caption


def test_arguments_come_after_the_folders_and_say_they_are_optional():
    """Above the folder list it read as the next thing to fill in."""
    source = (QT_DIR / "emulator_settings.py").read_text()
    assert source.index("ROM FOLDERS") < source.index('QLabel("Arguments")')
    assert "Optional." in source
    assert "not where the ROM folder goes" in source


def test_adding_an_emulator_offers_the_catalogue_first():
    """Describing one by hand is the fallback, not the front door."""
    source = (QT_DIR / "emulator_settings.py").read_text()
    assert "class SystemPicker" in source
    add = source.split("def _add(self)")[1].split("\n    def ")[0]
    assert "SystemPicker(self)" in add
    assert "picker.manual" in add, "describing it by hand must stay reachable"


def test_the_picker_explains_that_folder_discovery_is_automatic():
    source = (QT_DIR / "emulator_settings.py").read_text()
    assert "emulator's own game" in source
    assert "common ROM folders" in source
    assert "all you have to point at" not in source


def test_a_picked_system_arrives_already_filled_in():
    """One click plus a folder, not four fields."""
    from kairo import systems
    from kairo.qt.emulator_settings import SystemPicker

    source = (QT_DIR / "emulator_settings.py").read_text()
    build = source.split("def emulator(self)")[1].split("\n    def ")[0]
    assert "system.extensions" in build
    assert "self.chosen.executable" in build
    assert "ROM_PLACEHOLDER" in build
    assert callable(SystemPicker.emulator)
    assert systems.by_id("gamecube").extensions
