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
