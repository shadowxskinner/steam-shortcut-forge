"""Static SteamGridDB landscape heroes as a second artwork type.

Gamebar will read ``X-KairoHero`` later. This suite is the contract: the
endpoint and filters, landscape ranking, dedicated storage, ownership, the
four regressions that must stay red if the implementation slips, and the
distinction between a downed SteamGridDB and an empty hero catalog.
"""

from pathlib import Path

import pytest

from kairo import actions, net, paths
from kairo.desktop import entry as de
from kairo.models import AppEntry, ArtQuery, Artwork
from kairo.providers.desktop_entry import DesktopEntryProvider
from kairo.providers.steam import SteamProvider


def _entry(name="Thing", key="desktop:thing"):
    return AppEntry(key=key, provider_id="desktop", name=name)


def _hero(width, height, score=0.0, official=False, style="custom", ident=""):
    ident = ident or f"{width}x{height}-{score}-{style}"
    return Artwork(id=ident, source_id="steamgriddb", kind="hero",
                   width=width, height=height, score=score,
                   official=official, label=style,
                   locator=f"https://example.invalid/{ident}.png")


def _sgdb_item(ident, width, height, style="custom", up=0, down=0, url=None):
    return {
        "id": ident,
        "url": url or f"https://example.invalid/{ident}.png",
        "width": width,
        "height": height,
        "style": style,
        "upvotes": up,
        "downvotes": down,
        "mime": "image/png",
    }


@pytest.fixture
def steam_entry(steam_library):
    return next(a for a in SteamProvider().scan() if a.local_id == "440")


@pytest.fixture
def dolphin(system_apps):
    return next(a for a in DesktopEntryProvider().scan() if a.name == "Dolphin")


@pytest.fixture
def png(tmp_path):
    path = tmp_path / "art.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    return path


@pytest.fixture
def hero_png(tmp_path):
    path = tmp_path / "hero.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"H" * 64)
    return path


class RecordingSource:
    """Copies a local file into the destination, like a successful download."""

    id = "steamgriddb"
    label = "SteamGridDB"

    def __init__(self, payload: Path, locator="https://example.invalid/h.png"):
        self.payload = payload
        self.locator = locator
        self.fetches = 0

    def fetch(self, art, dest_dir, stem):
        self.fetches += 1
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{stem}.png"
        dest.write_bytes(self.payload.read_bytes())
        return dest


# -- SteamGridDB endpoint, filters, resolution --------------------------------

def test_heroes_are_asked_from_the_heroes_endpoint(monkeypatch):
    from kairo.artwork import steamgriddb as sgdb

    asked = []
    source = sgdb.SteamGridDBSource(api_key="secret-key")
    monkeypatch.setattr(source, "game_id", lambda appid: 7)
    monkeypatch.setattr(sgdb.paths, "cache_dir", lambda: Path("/nonexistent"))

    def fake_get(path):
        asked.append(path)
        return {"data": [], "total": 0}

    monkeypatch.setattr(source, "_api_get", fake_get)
    source.find_heroes(ArtQuery(entry=_entry(), steam_appid="42700"))

    assert asked, "the heroes endpoint was never called"
    assert all(p.startswith("/heroes/game/7") for p in asked), asked
    assert all("types=static" in p and "nsfw=false" in p for p in asked), asked
    assert not any("/icons/" in p or "/grids/" in p for p in asked)


def test_icon_lookup_does_not_fetch_heroes(monkeypatch):
    from kairo.artwork import steamgriddb as sgdb

    asked = []
    source = sgdb.SteamGridDBSource(api_key="k")
    monkeypatch.setattr(source, "game_id", lambda appid: 7)
    monkeypatch.setattr(sgdb.paths, "cache_dir", lambda: Path("/nonexistent"))
    monkeypatch.setattr(source, "_api_get", lambda path: asked.append(path) or {
        "data": [], "total": 0})
    source.find(ArtQuery(entry=_entry(), steam_appid="42700"))
    assert not any(p.startswith("/heroes") for p in asked), asked


def test_heroes_resolve_a_steam_appid(monkeypatch):
    from kairo.artwork import steamgriddb as sgdb

    asked = []
    source = sgdb.SteamGridDBSource(api_key="k")
    monkeypatch.setattr(sgdb.paths, "cache_dir", lambda: Path("/nonexistent"))

    def fake_get(path):
        asked.append(path)
        if path.startswith("/games/steam/440"):
            return {"data": {"id": 99}}
        if path.startswith("/heroes/game/99"):
            return {"total": 1, "data": [
                _sgdb_item(1, 1920, 620, style="official")]}
        return {"data": [], "total": 0}

    monkeypatch.setattr(source, "_api_get", fake_get)
    found = source.find_heroes(ArtQuery(entry=_entry(), steam_appid="440"))
    assert any(p.startswith("/games/steam/440") for p in asked)
    assert [a.width for a in found] == [1920]


def test_heroes_resolve_an_emulator_title(monkeypatch):
    from kairo.artwork import steamgriddb as sgdb

    asked = []
    source = sgdb.SteamGridDBSource(api_key="k")
    monkeypatch.setattr(sgdb.paths, "cache_dir", lambda: Path("/nonexistent"))

    def fake_get(path):
        asked.append(path)
        if path.startswith("/search/autocomplete"):
            return {"data": [{"id": 4242, "name": "Metroid Prime"}]}
        if path.startswith("/heroes/game/4242"):
            return {"total": 1, "data": [
                _sgdb_item(1, 1920, 620, style="official")]}
        return {"data": [], "total": 0}

    monkeypatch.setattr(source, "_api_get", fake_get)
    found = source.find_heroes(ArtQuery(entry=_entry(), text="metroid prime",
                                        fallback_text="metroid prime gamecube"))
    assert any(p.startswith("/search/autocomplete") for p in asked)
    assert any("/heroes/game/4242" in p for p in asked)
    assert [a.kind for a in found] == ["hero"]


def test_desktop_applications_are_not_offered_heroes():
    from kairo.artwork.steamgriddb import SteamGridDBSource

    source = SteamGridDBSource(api_key="k")
    assert source.supports("steam") is True
    assert source.supports("emu-dolphin") is True
    assert source.supports("desktop") is False


# -- landscape filter and ranking --------------------------------------------

def test_square_and_portrait_heroes_are_dropped(monkeypatch):
    from kairo.artwork import steamgriddb as sgdb

    source = sgdb.SteamGridDBSource(api_key="k")
    monkeypatch.setattr(source, "game_id", lambda appid: 7)
    monkeypatch.setattr(sgdb.paths, "cache_dir", lambda: Path("/nonexistent"))

    def fake_get(path):
        return {"total": 3, "data": [
            _sgdb_item("sq", 1024, 1024, style="official", up=50),
            _sgdb_item("port", 620, 1920, style="official", up=50),
            _sgdb_item("land", 1920, 620, style="custom", up=1),
        ]}

    monkeypatch.setattr(source, "_api_get", fake_get)
    found = source.find_heroes(ArtQuery(entry=_entry(), steam_appid="440"))
    assert [a.id for a in found] == ["land"]


def test_hero_ranking_is_sharp_then_official_then_votes():
    from kairo.artwork.steamgriddb import _rank_hero

    tiny = _hero(400, 80, score=900, official=True, ident="tiny")
    sharp_custom = _hero(1920, 620, score=900, official=False, style="blur",
                         ident="custom")
    sharp_official = _hero(1920, 620, score=1, official=True, style="official",
                           ident="official")
    sharper = _hero(3840, 1240, score=0, official=False, ident="huge")
    ordered = sorted([tiny, sharp_custom, sharp_official, sharper],
                     key=_rank_hero)
    assert [a.id for a in ordered] == ["huge", "official", "custom", "tiny"]


def test_hero_ranking_is_deterministic_for_ties():
    from kairo.artwork.steamgriddb import _rank_hero

    a = _hero(1920, 620, score=5, official=False, style="alternate", ident="a")
    b = _hero(1920, 620, score=5, official=False, style="alternate", ident="b")
    first = sorted([a, b], key=_rank_hero)
    second = sorted([b, a], key=_rank_hero)
    assert [x.id for x in first] == [x.id for x in second]


def test_the_first_hero_is_the_automatic_proposal(monkeypatch):
    from kairo.artwork import steamgriddb as sgdb

    source = sgdb.SteamGridDBSource(api_key="k")
    monkeypatch.setattr(source, "game_id", lambda appid: 7)
    monkeypatch.setattr(sgdb.paths, "cache_dir", lambda: Path("/nonexistent"))
    monkeypatch.setattr(source, "_api_get", lambda path: {
        "total": 2, "data": [
            _sgdb_item("low", 1280, 400, style="custom", up=1),
            _sgdb_item("best", 1920, 620, style="official", up=0),
        ]})
    found = source.find_heroes(ArtQuery(entry=_entry(), steam_appid="440"))
    assert found[0].id == "best"


# -- storage, ownership, apply/remove ----------------------------------------

def test_applied_hero_is_an_absolute_local_path(steam_entry, png, hero_png):
    """Catch: writing the download URL instead of a local file."""
    provider = SteamProvider()
    actions.apply_icon(steam_entry, provider, png)
    source = RecordingSource(hero_png)
    art = _hero(1920, 620, official=True, ident="h1")
    art = Artwork(**{**art.__dict__, "locator": source.locator})
    stored = actions.fetch_and_apply_hero(steam_entry, provider, source, art)

    target = provider.writer().target(steam_entry)
    text = target.read_text()
    value = de.read_entry_value(target, de.HERO_KEY)
    assert value.startswith("/"), value
    assert "://" not in value
    assert Path(value).is_file()
    assert Path(value).resolve() == stored.resolve()
    assert stored.resolve().is_relative_to(paths.hero_store().resolve())
    assert "http" not in text.lower()
    assert "example.invalid" not in text
    assert "secret-key" not in text
    assert "steamgriddb_api_key" not in text


def test_applying_a_hero_preserves_icon(steam_entry, png, hero_png):
    """Catch: hero apply rewriting Icon=."""
    provider = SteamProvider()
    actions.apply_icon(steam_entry, provider, png)
    target = provider.writer().target(steam_entry)
    icon_before = de.read_entry_icon(target)
    extra = target.read_text() + "X-Custom=keep-me\nComment=unrelated\n"
    target.write_text(extra)

    actions.apply_hero(steam_entry, provider, hero_png)

    text = target.read_text()
    assert de.read_entry_icon(target) == icon_before
    assert "X-Custom=keep-me" in text
    assert "Comment=unrelated" in text
    assert de.read_entry_value(target, de.HERO_KEY).startswith("/")


def test_applying_an_icon_preserves_the_hero(steam_entry, png, hero_png, tmp_path):
    """Catch: generated launcher rewrite dropping X-KairoHero."""
    provider = SteamProvider()
    actions.apply_icon(steam_entry, provider, png)
    actions.apply_hero(steam_entry, provider, hero_png)
    target = provider.writer().target(steam_entry)
    hero_before = de.read_entry_value(target, de.HERO_KEY)
    assert hero_before

    other = tmp_path / "other.png"
    other.write_bytes(b"\x89PNG\r\n\x1a\n" + b"1" * 32)
    actions.apply_icon(steam_entry, provider, other)

    assert de.read_entry_value(target, de.HERO_KEY) == hero_before
    assert de.read_entry_icon(target) != str(png)


def test_resetting_artwork_preserves_the_hero(steam_entry, png, hero_png):
    provider = SteamProvider()
    actions.apply_icon(steam_entry, provider, png)
    actions.apply_hero(steam_entry, provider, hero_png)
    target = provider.writer().target(steam_entry)
    hero_before = de.read_entry_value(target, de.HERO_KEY)
    actions.restore_entry(steam_entry, provider)
    assert target.is_file()
    assert de.read_entry_value(target, de.HERO_KEY) == hero_before
    assert de.read_entry_icon(target) == provider.writer().default_icon


def test_hero_apply_refuses_an_unowned_override(steam_entry, hero_png, fake_home):
    """Catch: treating a hand-written launcher as Kairo's to edit."""
    provider = SteamProvider()
    target = provider.writer().target(steam_entry)
    original = (
        "[Desktop Entry]\nType=Application\nName=MY OWN\n"
        "Icon=mine\nExec=true\n"
    )
    target.write_text(original)

    with pytest.raises(ValueError):
        actions.apply_hero(steam_entry, provider, hero_png)
    assert target.read_text() == original
    assert de.HERO_KEY not in target.read_text()
    assert list(paths.hero_store().glob("*")) == [] if paths.hero_store().is_dir() else True


def test_hero_apply_refuses_an_unowned_desktop_override(dolphin, hero_png, fake_home):
    target = paths.applications_dir() / "org.kde.dolphin.desktop"
    original = "[Desktop Entry]\nType=Application\nName=Mine\nIcon=mine\n"
    target.write_text(original)
    with pytest.raises(ValueError):
        DesktopEntryProvider().writer().apply_hero(dolphin, hero_png)
    assert target.read_text() == original


def test_reapplying_replaces_only_the_hero(steam_entry, png, hero_png, tmp_path):
    provider = SteamProvider()
    actions.apply_icon(steam_entry, provider, png)
    first = actions.apply_hero(steam_entry, provider, hero_png)
    target = provider.writer().target(steam_entry)
    icon = de.read_entry_icon(target)

    other = tmp_path / "hero2.png"
    other.write_bytes(b"\x89PNG\r\n\x1a\n" + b"2" * 64)
    second = actions.apply_hero(steam_entry, provider, other)

    assert de.read_entry_icon(target) == icon
    assert de.read_entry_value(target, de.HERO_KEY) == str(second)
    assert second != first
    assert not first.exists()
    assert second.is_file()
    assert target.is_file()


def test_remove_hero_leaves_the_launcher_and_icon(steam_entry, png, hero_png):
    provider = SteamProvider()
    actions.apply_icon(steam_entry, provider, png)
    stored = actions.apply_hero(steam_entry, provider, hero_png)
    target = provider.writer().target(steam_entry)
    icon = de.read_entry_icon(target)

    actions.remove_hero(steam_entry, provider)

    assert target.is_file()
    assert de.read_entry_icon(target) == icon
    assert de.HERO_KEY not in target.read_text()
    assert not stored.exists()


def test_remove_hero_does_not_delete_a_hero_another_entry_uses(
        steam_entry, png, hero_png, steam_library):
    provider = SteamProvider()
    tf2 = steam_entry
    portal = next(a for a in provider.scan() if a.local_id == "620")
    actions.apply_icon(tf2, provider, png)
    actions.apply_icon(portal, provider, png)
    shared = actions.apply_hero(tf2, provider, hero_png)
    # Point the other launcher at the same stored file.
    other = provider.writer().target(portal)
    text = de.read_text_exact(other)
    de.atomic_write_text(other, de.set_entry_values(text, {de.HERO_KEY: str(shared)}))

    actions.remove_hero(tf2, provider)
    assert shared.is_file()
    assert de.read_entry_value(other, de.HERO_KEY) == str(shared)


def test_a_manual_alternative_is_what_gets_written(steam_entry, png, tmp_path):
    provider = SteamProvider()
    actions.apply_icon(steam_entry, provider, png)
    first = tmp_path / "first.png"
    first.write_bytes(b"\x89PNG\r\n\x1a\n" + b"A" * 32)
    second = tmp_path / "second.png"
    second.write_bytes(b"\x89PNG\r\n\x1a\n" + b"B" * 32)
    stored = actions.apply_hero(steam_entry, provider, second)
    assert stored.read_bytes() == second.read_bytes()
    target = provider.writer().target(steam_entry)
    assert Path(de.read_entry_value(target, de.HERO_KEY)).read_bytes() == b"\x89PNG\r\n\x1a\n" + b"B" * 32


SECRET_KEY = "secret-key-do-not-leak"


def _title_query():
    return ArtQuery(entry=_entry(), text="metroid prime",
                    fallback_text="metroid prime gamecube")


def _http_error(code: int):
    import io
    import urllib.error

    return urllib.error.HTTPError(
        "https://www.steamgriddb.com/api/v2/x", code, "error",
        None, io.BytesIO(b""))


@pytest.mark.parametrize("query", [
    ArtQuery(entry=_entry(), steam_appid="440"),
    ArtQuery(entry=_entry(), text="metroid prime",
             fallback_text="metroid prime gamecube"),
], ids=["steam-appid", "title-search"])
@pytest.mark.parametrize("error, needle", [
    ("url", "Network error"),
    (401, "Invalid API key"),
    (429, "Rate-limited"),
    (500, "HTTP 500"),
], ids=["offline", "http-401", "http-429", "http-500"])
def test_hero_network_errors_are_failures_not_an_empty_catalog(
        query, error, needle, monkeypatch, fake_home):
    import urllib.error

    from kairo.artwork import steamgriddb as sgdb

    source = sgdb.SteamGridDBSource(api_key=SECRET_KEY)
    monkeypatch.setattr(sgdb.paths, "cache_dir", lambda: Path("/nonexistent"))

    if error == "url":
        exc = urllib.error.URLError("timed out")
    else:
        exc = _http_error(error)

    def fake_get(url, headers=None, timeout=15):
        raise exc

    monkeypatch.setattr(sgdb.net, "get", fake_get)
    with pytest.raises(net.NetworkError) as caught:
        source.find_heroes(query)
    message = str(caught.value)
    assert needle in message
    assert SECRET_KEY not in message
    assert "Bearer" not in message
    store = paths.hero_store()
    assert not store.exists() or list(store.iterdir()) == []


def test_hero_network_failure_does_not_mutate_the_launcher(
        steam_entry, png, monkeypatch):
    from kairo.artwork import steamgriddb as sgdb

    provider = SteamProvider()
    actions.apply_icon(steam_entry, provider, png)
    target = provider.writer().target(steam_entry)
    before = target.read_bytes()
    icon = de.read_entry_icon(target)

    source = sgdb.SteamGridDBSource(api_key=SECRET_KEY)
    monkeypatch.setattr(sgdb.paths, "cache_dir", lambda: Path("/nonexistent"))
    monkeypatch.setattr(source, "_api_get", lambda path: (_ for _ in ()).throw(
        net.NetworkError("down")))

    with pytest.raises(net.NetworkError, match="down"):
        source.find_heroes(ArtQuery(entry=steam_entry, steam_appid="440"))
    assert target.read_bytes() == before
    assert de.read_entry_icon(target) == icon
    assert de.HERO_KEY not in target.read_text()
    store = paths.hero_store()
    assert not store.exists() or list(store.iterdir()) == []


def test_title_search_network_failure_is_not_a_missing_game(monkeypatch):
    """Icon lookup still swallows this; hero lookup must not."""
    from kairo.artwork import steamgriddb as sgdb

    source = sgdb.SteamGridDBSource(api_key=SECRET_KEY)
    monkeypatch.setattr(sgdb.paths, "cache_dir", lambda: Path("/nonexistent"))
    monkeypatch.setattr(source, "_api_get", lambda path: (_ for _ in ()).throw(
        net.NetworkError("down")))
    query = _title_query()
    assert source.find(query) == []
    with pytest.raises(net.NetworkError, match="down"):
        source.find_heroes(query)


def test_hero_retrieval_failure_is_not_an_empty_catalog(monkeypatch, fake_home):
    from kairo.artwork import steamgriddb as sgdb

    source = sgdb.SteamGridDBSource(api_key=SECRET_KEY)
    monkeypatch.setattr(sgdb.paths, "cache_dir", lambda: Path("/nonexistent"))
    monkeypatch.setattr(source, "_api_get", lambda path: (_ for _ in ()).throw(
        net.NetworkError("down")))

    monkeypatch.setattr(source, "game_id", lambda appid: 7)
    with pytest.raises(net.NetworkError, match="down"):
        source.find_heroes(ArtQuery(entry=_entry(), steam_appid="440"))

    monkeypatch.setattr(source, "search_id", lambda term: 4242)
    with pytest.raises(net.NetworkError, match="down"):
        source.find_heroes(_title_query())
    store = paths.hero_store()
    assert not store.exists() or list(store.iterdir()) == []


def test_no_results_does_not_mutate_the_launcher(steam_entry, png, monkeypatch):
    from kairo.artwork import steamgriddb as sgdb

    provider = SteamProvider()
    actions.apply_icon(steam_entry, provider, png)
    target = provider.writer().target(steam_entry)
    before = target.read_bytes()

    source = sgdb.SteamGridDBSource(api_key="k")
    monkeypatch.setattr(source, "game_id", lambda appid: 7)
    monkeypatch.setattr(sgdb.paths, "cache_dir", lambda: Path("/nonexistent"))
    monkeypatch.setattr(source, "_api_get", lambda path: {"data": [], "total": 0})
    assert source.find_heroes(ArtQuery(entry=steam_entry, steam_appid="440")) == []
    assert target.read_bytes() == before


def test_fetch_keeps_the_downloaded_bytes(steam_entry, png, hero_png):
    """Heroes are not resized for a particular monitor."""
    provider = SteamProvider()
    actions.apply_icon(steam_entry, provider, png)
    original = hero_png.read_bytes()
    stored = actions.fetch_and_apply_hero(
        steam_entry, provider, RecordingSource(hero_png),
        _hero(1920, 620, ident="raw"))
    assert stored.read_bytes() == original


def test_hero_key_is_not_an_ownership_marker(steam_entry, png, hero_png, fake_home):
    provider = SteamProvider()
    actions.apply_icon(steam_entry, provider, png)
    actions.apply_hero(steam_entry, provider, hero_png)
    target = provider.writer().target(steam_entry)
    text = target.read_text().replace(f"{de.MANAGED_KEYS[0]}=true\n", "")
    target.write_text(text)
    assert de.HERO_KEY in target.read_text()
    assert de.is_managed(target) is False
    with pytest.raises(ValueError):
        actions.apply_hero(steam_entry, provider, hero_png)
    with pytest.raises(ValueError):
        actions.remove_hero(steam_entry, provider)
    assert target.is_file()
    assert de.read_entry_icon(target)


# -- Qt: Icon/Hero choice, landscape tiles, automatic proposal ---------------

def test_hero_mode_auto_selects_the_proposal_and_fits_landscape(qt_app, fake_home,
                                                                steam_library):
    from kairo.artwork.registry import ArtworkRegistry
    from kairo.ledger import Ledger
    from kairo.qt import images
    from kairo.qt.library import LibraryPane
    from kairo.qt.shell import Context
    from kairo.qt.theme import HERO_TILE, HERO_TILE_H
    from kairo.qt.widgets import ArtworkTile
    from kairo.tasks import ActivityTokens
    from tests.conftest import settle

    payload = _landscape_png()
    best = _hero(1920, 620, official=True, ident="best")
    other = _hero(1280, 400, official=False, ident="other")

    class FakeSGDB:
        id = "steamgriddb"
        label = "SteamGridDB"
        needs_query = False
        interactive = False

        def supports(self, provider_id):
            return provider_id == "steam" or provider_id.startswith("emu-")

        def available(self, config=None):
            return True

        def find(self, query):
            return []

        def find_heroes(self, query):
            return [best, other]

        def preview(self, art):
            return payload

    images.clear_cache()
    ctx = Context(providers=None, sources=ArtworkRegistry([FakeSGDB()]),
                  config={"steamgriddb_api_key": "not-a-real-key"},
                  ledger=Ledger().load(), tokens=ActivityTokens())
    pane = LibraryPane(SteamProvider(), ctx)
    try:
        pane.show()
        qt_app.processEvents()
        settle(qt_app)
        assert pane.kind_pills.isVisible()
        assert pane.kind_pills.values() == ["Icon", "Hero"]
        assert pane.apply_btn.isVisible()
        assert not pane.apply_hero_btn.isVisible()

        pane.kind_pills.set_value("Hero")
        qt_app.processEvents()
        settle(qt_app)

        assert pane._artwork_kind == "hero"
        assert pane.apply_hero_btn.isVisible()
        assert pane.remove_hero_btn.isVisible()
        assert not pane.apply_btn.isVisible()
        assert pane.proposed is best
        assert pane.apply_hero_btn.isEnabled()
        assert pane.tiles
        chosen = [t for t in pane.tiles if t._chosen]
        assert len(chosen) == 1
        assert chosen[0].art is best
        assert chosen[0].landscape is True
        well = chosen[0].well
        assert well.width() > well.height()
        assert well.width() == HERO_TILE
        assert well.height() == HERO_TILE_H
        assert ArtworkTile.HERO_WIDTH > ArtworkTile.WIDTH

        shot = pane.grab()
        assert not shot.isNull()
        assert shot.width() > 0
    finally:
        pane.close()
        from kairo.qt import work
        work.drain()


def _empty_grid_note(pane) -> str:
    from PySide6.QtWidgets import QLabel

    notes = []
    for i in range(pane.grid.count()):
        item = pane.grid.itemAt(i)
        widget = item.widget() if item is not None else None
        if isinstance(widget, QLabel) and widget.objectName() == "empty":
            notes.append(widget.text())
    assert notes, "the artwork grid has no status note"
    return notes[-1]


def _hero_pane(qt_app, source):
    from kairo.artwork.registry import ArtworkRegistry
    from kairo.ledger import Ledger
    from kairo.qt.library import LibraryPane
    from kairo.qt.shell import Context
    from kairo.tasks import ActivityTokens
    from tests.conftest import settle

    ctx = Context(providers=None, sources=ArtworkRegistry([source]),
                  config={"steamgriddb_api_key": SECRET_KEY},
                  ledger=Ledger().load(), tokens=ActivityTokens())
    pane = LibraryPane(SteamProvider(), ctx)
    pane.show()
    qt_app.processEvents()
    settle(qt_app)
    pane.kind_pills.set_value("Hero")
    qt_app.processEvents()
    settle(qt_app)
    return pane


def test_hero_failure_message_is_not_the_empty_catalog_message(
        qt_app, fake_home, steam_library, monkeypatch):
    from kairo.artwork import steamgriddb as sgdb
    from kairo.qt import work

    source = sgdb.SteamGridDBSource(api_key=SECRET_KEY)
    monkeypatch.setattr(sgdb.paths, "cache_dir", lambda: Path("/nonexistent"))
    monkeypatch.setattr(source, "_api_get", lambda path: (_ for _ in ()).throw(
        net.NetworkError("Invalid API key - check Settings.")))

    pane = _hero_pane(qt_app, source)
    try:
        note = _empty_grid_note(pane)
        name = pane.selected.entry.name
        assert "Could not reach SteamGridDB." in note
        assert f"No landscape heroes for {name}." not in note
        assert SECRET_KEY not in note
    finally:
        pane.close()
        work.drain()

    monkeypatch.setattr(source, "game_id", lambda appid: 7)
    monkeypatch.setattr(source, "_api_get", lambda path: {"data": [], "total": 0})
    pane = _hero_pane(qt_app, source)
    try:
        note = _empty_grid_note(pane)
        name = pane.selected.entry.name
        assert f"No landscape heroes for {name}." in note
        assert "Could not reach SteamGridDB." not in note
        assert SECRET_KEY not in note
    finally:
        pane.close()
        work.drain()


def test_applications_pane_has_no_hero_choice(qt_app, fake_home, system_apps):
    from kairo.artwork.registry import default_registry
    from kairo.ledger import Ledger
    from kairo.qt.library import LibraryPane
    from kairo.qt.shell import Context
    from kairo.tasks import ActivityTokens
    from tests.conftest import settle

    ctx = Context(providers=None, sources=default_registry(
                      {"steamgriddb_api_key": "not-a-real-key"}),
                  config={"steamgriddb_api_key": "not-a-real-key"},
                  ledger=Ledger().load(), tokens=ActivityTokens())
    pane = LibraryPane(DesktopEntryProvider(), ctx)
    try:
        pane.show()
        qt_app.processEvents()
        settle(qt_app)
        assert not pane.kind_pills.isVisible()
        assert pane._artwork_kind == "icon"
        assert not pane.apply_hero_btn.isVisible()
    finally:
        pane.close()
        from kairo.qt import work
        work.drain()


def _landscape_png():
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGBA", (1920, 620), (40, 80, 160, 255)).save(buffer, format="PNG")
    return buffer.getvalue()
