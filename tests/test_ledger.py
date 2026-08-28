"""The change history, and the rule that it is never the authority."""

import json

import pytest

from kairo import paths
from kairo.desktop import entry as de
from kairo.ledger import (ACTION_CREATED, ACTION_OVERRODE, LEDGER_VERSION,
                          ChangeRecord, Ledger)


def make_record(tmp_path, key="steam:440", name="Team Fortress 2",
                managed=True, **kw):
    target = tmp_path / f"{key.replace(':', '-')}.desktop"
    body = "[Desktop Entry]\nType=Application\nName=X\nIcon=/new.png\n"
    if managed:
        body += f"{de.MANAGED_KEYS[0]}=true\n"
    target.write_text(body)
    fields = dict(key=key, provider_id=key.split(":")[0], name=name,
                  action=ACTION_CREATED, target=str(target),
                  original_icon="old-icon", applied_icon="/new.png")
    fields.update(kw)
    return ChangeRecord(**fields)


@pytest.fixture
def ledger(fake_home):
    return Ledger().load()


# -- persistence ------------------------------------------------------------

def test_missing_ledger_loads_empty(ledger):
    assert len(ledger) == 0
    assert ledger.records() == []


def test_record_round_trips(ledger, tmp_path):
    ledger.record(make_record(tmp_path))
    assert Ledger().load().get("steam:440").name == "Team Fortress 2"


def test_ledger_lives_under_the_data_dir(ledger, tmp_path):
    ledger.record(make_record(tmp_path))
    assert ledger.path == paths.data_dir() / "state.json"
    assert ledger.path.is_file()


def test_written_file_is_versioned_json(ledger, tmp_path):
    ledger.record(make_record(tmp_path))
    blob = json.loads(ledger.path.read_text())
    assert blob["version"] == LEDGER_VERSION
    assert len(blob["changes"]) == 1


def test_write_is_atomic(ledger, tmp_path):
    ledger.record(make_record(tmp_path))
    assert list(paths.data_dir().glob(".kairo-*")) == []


def test_corrupt_ledger_loses_history_not_data(fake_home, tmp_path):
    paths.data_dir().mkdir(parents=True, exist_ok=True)
    (paths.data_dir() / "state.json").write_text("{ not json")
    assert len(Ledger().load()) == 0


def test_unknown_version_is_ignored(fake_home):
    paths.data_dir().mkdir(parents=True, exist_ok=True)
    (paths.data_dir() / "state.json").write_text(
        json.dumps({"version": 999, "changes": [{"key": "steam:1"}]}))
    assert len(Ledger().load()) == 0


def test_unknown_fields_are_dropped_not_fatal(fake_home):
    paths.data_dir().mkdir(parents=True, exist_ok=True)
    (paths.data_dir() / "state.json").write_text(json.dumps({
        "version": LEDGER_VERSION,
        "changes": [{"key": "steam:1", "provider_id": "steam", "name": "A",
                     "action": "created", "target": "/x", "from_the_future": 1}],
    }))
    assert Ledger().load().get("steam:1").name == "A"


# -- content ----------------------------------------------------------------

def test_record_answers_the_questions_it_exists_for(ledger, tmp_path):
    ledger.record(make_record(tmp_path, source_id="steamgriddb",
                              source_label="SteamGridDB", artwork_id="24601"))
    record = ledger.get("steam:440")
    assert record.name == "Team Fortress 2"          # what was modified
    assert record.provider_id == "steam"             # which provider owns it
    assert record.original_icon == "old-icon"        # what was there before
    assert record.applied_icon == "/new.png"         # what Kairo applied
    assert record.source_label == "SteamGridDB"      # where it came from
    assert record.target                             # which launcher entry
    assert record.applied_at                         # when
    assert Ledger.restorable(record)[0] is True      # can it be undone


def test_reapply_replaces_rather_than_appends(ledger, tmp_path):
    ledger.record(make_record(tmp_path))
    ledger.record(make_record(tmp_path, applied_icon="/second.png"))
    assert len(ledger) == 1
    assert ledger.get("steam:440").applied_icon == "/second.png"


def test_reapply_keeps_the_first_original_icon(ledger, tmp_path):
    """Only the first recorded value returns the app to how the user found it."""
    ledger.record(make_record(tmp_path))
    second = make_record(tmp_path, applied_icon="/second.png")
    second.original_icon = ""
    ledger.record(second)
    assert ledger.get("steam:440").original_icon == "old-icon"


def test_records_are_newest_first(ledger, tmp_path):
    ledger.record(make_record(tmp_path, key="steam:1", name="A",
                              applied_at="2026-01-01T00:00:00Z"))
    ledger.record(make_record(tmp_path, key="steam:2", name="B",
                              applied_at="2026-06-01T00:00:00Z"))
    assert [r.name for r in ledger.records()] == ["B", "A"]


def test_for_provider_filters(ledger, tmp_path):
    ledger.record(make_record(tmp_path, key="steam:440"))
    ledger.record(make_record(tmp_path, key="desktop:firefox"))
    assert len(ledger.for_provider("steam")) == 1
    assert len(ledger.for_provider("desktop")) == 1


def test_forget_removes_and_persists(ledger, tmp_path):
    ledger.record(make_record(tmp_path))
    assert ledger.forget("steam:440") is True
    assert Ledger().load().get("steam:440") is None


def test_forget_unknown_key_is_false(ledger):
    assert ledger.forget("steam:nope") is False


# -- the ledger is an index, not a permission -------------------------------

def test_marker_not_ledger_decides_ownership(ledger, tmp_path):
    """The whole point: history claiming a file is ours proves nothing."""
    record = make_record(tmp_path, managed=False)
    ledger.record(record)
    assert Ledger.owns(record) is False
    allowed, reason = Ledger.restorable(record)
    assert allowed is False
    assert "changed by something other than Kairo" in reason


def test_hand_edited_entry_is_refused(ledger, tmp_path):
    record = make_record(tmp_path)
    record.target_path.write_text(
        "[Desktop Entry]\nType=Application\nName=Mine now\nIcon=mine\n")
    assert Ledger.restorable(record)[0] is False


def test_missing_entry_reports_already_restored(ledger, tmp_path):
    record = make_record(tmp_path)
    record.target_path.unlink()
    allowed, reason = Ledger.restorable(record)
    assert allowed is False
    assert "Already restored" in reason


def test_legacy_marker_still_counts_as_ours(ledger, tmp_path):
    """A migrated Shortcut Forge override must stay restorable."""
    record = make_record(tmp_path, managed=False)
    record.target_path.write_text(
        "[Desktop Entry]\nType=Application\nName=X\nIcon=/new.png\n"
        "X-ShortcutForge-Managed=true\n")
    assert Ledger.restorable(record)[0] is True


# -- pruning ----------------------------------------------------------------

def test_prune_drops_entries_that_are_gone(ledger, tmp_path):
    ledger.record(make_record(tmp_path, key="steam:1"))
    gone = make_record(tmp_path, key="steam:2")
    ledger.record(gone)
    gone.target_path.unlink()

    assert ledger.prune() == 1
    assert len(ledger) == 1


def test_prune_drops_entries_no_longer_ours(ledger, tmp_path):
    ledger.record(make_record(tmp_path, key="steam:1"))
    taken = make_record(tmp_path, key="steam:2")
    ledger.record(taken)
    taken.target_path.write_text("[Desktop Entry]\nName=Theirs\nIcon=x\n")

    assert ledger.prune() == 1
    assert ledger.get("steam:2") is None


def test_prune_keeps_valid_entries(ledger, tmp_path):
    ledger.record(make_record(tmp_path))
    assert ledger.prune() == 0
    assert len(ledger) == 1
