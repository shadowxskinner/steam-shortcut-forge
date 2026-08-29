"""Icon-store cleanup.

Deletion is decided by reference and never by the change history. The
migration exposed exactly why: entries can be genuinely owned and customised
while the history knows nothing about them, so "not in the ledger" is not
evidence that artwork is unused.
"""

import pytest

from kairo import housekeeping, paths
from kairo.desktop import entry as de


@pytest.fixture
def store(fake_home):
    store = paths.icon_store()
    store.mkdir(parents=True)
    return store


def icon(store, name):
    path = store / name
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + name.encode())
    return path


def entry_pointing_at(icon_path, name="app.desktop", managed=True):
    body = ("[Desktop Entry]\nType=Application\nName=App\n"
            f"Icon={icon_path}\nExec=app\n")
    if managed:
        body += f"{de.MANAGED_KEYS[0]}=true\n"
    path = paths.applications_dir() / name
    path.write_text(body)
    return path


# -- orphan detection -------------------------------------------------------

def test_unreferenced_icon_is_an_orphan(store):
    lonely = icon(store, "lonely.png")
    assert housekeeping.orphan_icons() == [lonely]


def test_referenced_icon_is_not_an_orphan(store):
    used = icon(store, "used.png")
    entry_pointing_at(used)
    assert housekeeping.orphan_icons() == []


def test_a_reference_from_a_file_we_do_not_own_still_protects_it(store):
    """If someone hand-wrote an entry pointing into our store, that artwork is
    in use. Ownership decides what we may edit, not what is in use."""
    used = icon(store, "used.png")
    entry_pointing_at(used, name="theirs.desktop", managed=False)
    assert housekeeping.orphan_icons() == []


def test_not_being_in_the_ledger_is_not_grounds_for_deletion(store, fake_home):
    """A migrated entry is owned and customised with no history record."""
    from kairo.ledger import Ledger
    used = icon(store, "migrated.png")
    (paths.applications_dir() / "dolphin.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Dolphin\n"
        f"Icon={used}\nX-ShortcutForge-Managed=true\n")
    assert len(Ledger().load()) == 0
    assert housekeeping.orphan_icons() == []


def test_action_group_icons_do_not_create_references(store):
    """Only [Desktop Entry] Icon= counts, matching how the writers behave."""
    orphan = icon(store, "orphan.png")
    (paths.applications_dir() / "x.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=X\nIcon=theme-name\n"
        f"\n[Desktop Action a]\nName=A\nIcon={orphan}\n")
    assert housekeeping.orphan_icons() == [orphan]


def test_nested_directories_are_left_alone(store):
    nested = store / "subdir"
    nested.mkdir()
    (nested / "deep.png").write_bytes(b"x")
    assert housekeeping.orphan_icons() == []


def test_symlinks_are_skipped(store, tmp_path):
    target = tmp_path / "outside.png"
    target.write_bytes(b"x")
    (store / "link.png").symlink_to(target)
    assert housekeeping.orphan_icons() == []
    assert target.is_file()


def test_missing_store_is_not_an_error(fake_home):
    assert housekeeping.orphan_icons() == []


# -- sweeping ---------------------------------------------------------------

def test_sweep_removes_only_orphans(store):
    used = icon(store, "used.png")
    orphan_a = icon(store, "a.png")
    orphan_b = icon(store, "b.png")
    entry_pointing_at(used)

    result = housekeeping.sweep()

    assert result.removed == 2
    assert used.is_file()
    assert not orphan_a.exists() and not orphan_b.exists()


def test_dry_run_deletes_nothing(store):
    orphan = icon(store, "a.png")
    result = housekeeping.sweep(dry_run=True)
    assert result.removed == 1
    assert orphan.is_file()


def test_sweep_reports_freed_space(store):
    icon(store, "a.png")
    assert housekeeping.sweep().freed_bytes > 0


def test_sweep_on_a_clean_store_is_a_no_op(store):
    used = icon(store, "used.png")
    entry_pointing_at(used)
    result = housekeeping.sweep()
    assert result.removed == 0
    assert "No unused artwork" in result.describe()


def test_is_referenced_matches_orphan_detection(store):
    used = icon(store, "used.png")
    orphan = icon(store, "orphan.png")
    entry_pointing_at(used)
    assert housekeeping.is_referenced(used) is True
    assert housekeeping.is_referenced(orphan) is False
