"""Apply and restore, with the ledger kept in step."""

import shutil
from pathlib import Path

import pytest

from kairo import actions, paths
from kairo.desktop import entry as de
from kairo.ledger import Ledger
from kairo.models import Artwork
from kairo.providers.desktop_entry import DesktopEntryProvider
from kairo.providers.registry import default_registry
from kairo.providers.steam import SteamProvider
from kairo.tasks import CancelToken, Skip


class StubSource:
    """A source that copies a local file, so nothing here touches a network."""

    id = "stub"
    label = "Stub source"

    def __init__(self, png, fail=False):
        self.png = png
        self.fail = fail
        self.fetches = 0

    def fetch(self, art, dest_dir, stem):
        self.fetches += 1
        if self.fail:
            raise RuntimeError("download failed")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{stem}.png"
        shutil.copyfile(self.png, dest)
        return dest


@pytest.fixture
def png(tmp_path):
    path = tmp_path / "art.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    return path


@pytest.fixture
def art():
    return Artwork(id="a1", source_id="stub", name="tf2", label="Stub source")


@pytest.fixture
def ledger(fake_home):
    return Ledger().load()


@pytest.fixture
def steam_entry(steam_library):
    return next(a for a in SteamProvider().scan() if a.local_id == "440")


@pytest.fixture
def dolphin(system_apps):
    return next(a for a in DesktopEntryProvider().scan() if a.name == "Dolphin")


# -- apply ------------------------------------------------------------------

def test_apply_records_a_created_change(steam_entry, png, ledger, art):
    actions.apply_icon(steam_entry, SteamProvider(), png, art=art,
                       source_label="Stub source", ledger=ledger)
    record = ledger.get("steam:440")
    assert record.action == "created"
    assert record.provider_id == "steam"
    assert record.source_label == "Stub source"
    assert Path(record.target).is_file()
    assert Path(record.applied_icon).is_file()


def test_apply_records_an_override_with_its_original(dolphin, png, ledger, art):
    actions.apply_icon(dolphin, DesktopEntryProvider(), png, art=art, ledger=ledger)
    record = ledger.get("desktop:org.kde.dolphin")
    assert record.action == "overrode"
    assert record.original_icon == "org.kde.dolphin"


def test_generated_entries_have_no_original_icon(steam_entry, png, ledger, art):
    """Nothing existed before, so there is nothing to restore back to."""
    actions.apply_icon(steam_entry, SteamProvider(), png, art=art, ledger=ledger)
    assert ledger.get("steam:440").original_icon == ""


def test_reapply_keeps_the_true_original(dolphin, png, ledger, art, tmp_path):
    provider = DesktopEntryProvider()
    actions.apply_icon(dolphin, provider, png, art=art, ledger=ledger)
    other = tmp_path / "b.png"
    other.write_bytes(b"\x89PNG\r\n\x1a\n" + b"1" * 32)
    actions.apply_icon(dolphin, provider, other, art=art, ledger=ledger)
    assert ledger.get("desktop:org.kde.dolphin").original_icon == "org.kde.dolphin"
    assert len(ledger) == 1


def test_fetch_and_apply_uses_the_source(steam_entry, png, ledger, art):
    source = StubSource(png)
    actions.fetch_and_apply(steam_entry, SteamProvider(), source, art, ledger=ledger)
    assert source.fetches == 1
    assert steam_entry.customized is True


def test_fetch_and_apply_honours_cancellation(steam_entry, png, ledger, art):
    from kairo.tasks import Cancelled

    token = CancelToken()
    token.cancel()
    source = StubSource(png)
    with pytest.raises(Cancelled):
        actions.fetch_and_apply(steam_entry, SteamProvider(), source, art,
                                ledger=ledger, token=token)
    assert source.fetches == 0
    assert len(ledger) == 0


# -- restore ----------------------------------------------------------------

def test_restore_removes_a_generated_entry_and_its_record(steam_entry, png,
                                                          ledger, art):
    provider = SteamProvider()
    actions.apply_icon(steam_entry, provider, png, art=art, ledger=ledger)
    target = provider.writer().target(steam_entry)

    actions.restore_entry(steam_entry, provider, ledger=ledger)

    assert not target.exists()
    assert ledger.get("steam:440") is None
    assert steam_entry.customized is False


def test_restore_removes_an_override_and_its_record(dolphin, png, ledger, art):
    provider = DesktopEntryProvider()
    actions.apply_icon(dolphin, provider, png, art=art, ledger=ledger)

    actions.restore_entry(dolphin, provider, ledger=ledger)

    assert not (paths.applications_dir() / "org.kde.dolphin.desktop").exists()
    assert ledger.get("desktop:org.kde.dolphin") is None


def test_restore_refuses_a_hand_edited_entry(dolphin, png, ledger, art):
    provider = DesktopEntryProvider()
    actions.apply_icon(dolphin, provider, png, art=art, ledger=ledger)
    target = paths.applications_dir() / "org.kde.dolphin.desktop"
    target.write_text("[Desktop Entry]\nType=Application\nName=Mine\nIcon=mine\n")

    with pytest.raises(ValueError):
        actions.restore_entry(dolphin, provider, ledger=ledger)
    assert target.is_file()


def test_restore_record_works_without_a_rescan(dolphin, png, ledger, art):
    """Restore All must work from history alone, even for an app since removed."""
    actions.apply_icon(dolphin, DesktopEntryProvider(), png, art=art, ledger=ledger)
    record = ledger.get("desktop:org.kde.dolphin")

    actions.restore_record(record, default_registry(), ledger=ledger)

    assert not (paths.applications_dir() / "org.kde.dolphin.desktop").exists()


def test_restore_record_skips_when_the_marker_is_gone(dolphin, png, ledger, art):
    actions.apply_icon(dolphin, DesktopEntryProvider(), png, art=art, ledger=ledger)
    record = ledger.get("desktop:org.kde.dolphin")
    record.target_path.write_text("[Desktop Entry]\nName=Theirs\nIcon=x\n")

    with pytest.raises(Skip):
        actions.restore_record(record, default_registry(), ledger=ledger)


def test_restore_record_skips_an_unknown_provider(ledger, tmp_path):
    from kairo.ledger import ChangeRecord

    target = tmp_path / "x.desktop"
    target.write_text(f"[Desktop Entry]\nName=X\nIcon=/x\n{de.MANAGED_KEYS[0]}=true\n")
    record = ChangeRecord(key="mystery:1", provider_id="mystery", name="X",
                          action="created", target=str(target))
    with pytest.raises(ValueError):
        actions.restore_record(record, default_registry(), ledger=ledger)


# -- restore all ------------------------------------------------------------

@pytest.fixture
def three_changes(steam_library, system_apps, png, ledger, art):
    steam = SteamProvider()
    desktop = DesktopEntryProvider()
    for app in steam.scan():
        actions.apply_icon(app, steam, png, art=art, ledger=ledger)
    dolphin = next(a for a in desktop.scan() if a.name == "Dolphin")
    actions.apply_icon(dolphin, desktop, png, art=art, ledger=ledger)
    return ledger


def test_restore_all_undoes_everything(three_changes):
    summary = actions.restore_all(three_changes, default_registry())
    assert summary.succeeded == 3
    assert summary.failed == 0
    assert len(three_changes) == 0
    assert list(paths.applications_dir().glob("kairo-*.desktop")) == []


def test_restore_all_summarises_rather_than_stopping(three_changes):
    """One entry taken over by something else must not cost the other two."""
    stolen = paths.applications_dir() / "org.kde.dolphin.desktop"
    stolen.write_text("[Desktop Entry]\nType=Application\nName=Theirs\nIcon=x\n")

    summary = actions.restore_all(three_changes, default_registry())

    assert summary.succeeded == 2
    assert summary.skipped == 1
    assert summary.failed == 0
    assert stolen.is_file()                      # untouched
    assert len(three_changes) == 1               # its record survives


def test_restore_all_reports_progress(three_changes):
    seen = []
    actions.restore_all(three_changes, default_registry(),
                        on_progress=lambda i, total, r: seen.append(total))
    assert seen == [3, 3, 3]


def test_restore_all_can_be_cancelled(three_changes):
    token = CancelToken()
    calls = []

    def progress(index, total, record):
        calls.append(record)
        if len(calls) == 1:
            token.cancel()

    summary = actions.restore_all(three_changes, default_registry(),
                                  token=token, on_progress=progress)
    assert summary.cancelled is True
    assert summary.succeeded == 1
    assert len(three_changes) == 2               # the rest are still recorded


def test_restore_all_persists_the_pruned_ledger(three_changes):
    actions.restore_all(three_changes, default_registry())
    assert len(Ledger().load()) == 0


def test_restore_all_on_an_empty_ledger_is_clean(ledger):
    summary = actions.restore_all(ledger, default_registry())
    assert summary.total == 0
    assert summary.succeeded == 0


# -- bulk apply -------------------------------------------------------------

def test_apply_many_applies_and_records(steam_library, png, ledger, art):
    steam = SteamProvider()
    source = StubSource(png)
    plans = [(app, source, art) for app in steam.scan()]

    summary = actions.apply_many(plans, default_registry(), ledger=ledger)

    assert summary.succeeded == 2
    assert len(ledger) == 2
    assert len(Ledger().load()) == 2             # saved once at the end


def test_apply_many_survives_a_failing_download(steam_library, png, ledger, art):
    steam = SteamProvider()
    good, bad = StubSource(png), StubSource(png, fail=True)
    apps = steam.scan()
    plans = [(apps[0], bad, art), (apps[1], good, art)]

    summary = actions.apply_many(plans, default_registry(), ledger=ledger)

    assert summary.succeeded == 1
    assert summary.failed == 1
    assert len(ledger) == 1
    assert any(apps[0].name in f for f in summary.failures)


def test_apply_many_can_be_cancelled(steam_library, png, ledger, art):
    steam = SteamProvider()
    source = StubSource(png)
    token = CancelToken()
    plans = [(app, source, art) for app in steam.scan()]

    summary = actions.apply_many(plans, default_registry(), ledger=ledger,
                                 token=token,
                                 on_progress=lambda i, t, p: token.cancel())

    assert summary.cancelled is True
    assert summary.succeeded <= 1


# ---------------------------------------------------------------------------
# The ledger must survive a UI that goes away mid-run
# ---------------------------------------------------------------------------

def test_apply_many_saves_the_ledger_even_if_progress_explodes(steam_library, png,
                                                               ledger, art):
    """Closing the review window mid-apply used to abort apply_many before
    ledger.save(), leaving applications customised with no record - invisible
    in Changes and impossible to Restore All."""
    steam = SteamProvider()
    source = StubSource(png)
    plans = [(app, source, art) for app in steam.scan()]

    def boom(index, total, plan):
        raise RuntimeError("window destroyed")

    summary = actions.apply_many(plans, default_registry(), ledger=ledger,
                                 on_progress=boom)

    assert summary.succeeded == 2
    assert len(Ledger().load()) == 2


def test_restore_all_saves_the_ledger_even_if_progress_explodes(three_changes):
    def boom(index, total, record):
        raise RuntimeError("window destroyed")

    actions.restore_all(three_changes, default_registry(), on_progress=boom)
    assert len(Ledger().load()) == 0


def test_apply_many_records_every_success_before_returning(steam_library, png,
                                                           ledger, art):
    steam = SteamProvider()
    good, bad = StubSource(png), StubSource(png, fail=True)
    apps = steam.scan()
    actions.apply_many([(apps[0], good, art), (apps[1], bad, art)],
                       default_registry(), ledger=ledger)
    on_disk = Ledger().load()
    assert len(on_disk) == 1
    assert on_disk.get(apps[0].key) is not None
