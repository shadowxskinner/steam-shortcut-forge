"""Source availability probing.

Offering "Icon themes" for a Steam game no theme has heard of is an invitation
to click something that cannot work. Sources are asked whether they have
anything before they are offered.
"""

from pathlib import Path

import pytest

from kairo.artwork.iconify import IconifySource
from kairo.artwork.local import LocalFileSource
from kairo.artwork.registry import default_registry
from kairo.artwork.themes import IconThemeSource
from kairo.models import AppEntry, ArtQuery, Artwork
from kairo.themeindex import ThemeIndex


def entry(name="Thing", key="desktop:thing", icon_hint=""):
    return AppEntry(key=key, provider_id="desktop", name=name,
                    icon_hint=icon_hint)


def stub_index(monkeypatch, apps):
    monkeypatch.setattr(ThemeIndex, "index",
                        classmethod(lambda cls: {"Papirus": {"apps": apps,
                                                             "other": {}}}))


# -- installed themes -------------------------------------------------------

def test_theme_probe_finds_an_exact_name(monkeypatch):
    stub_index(monkeypatch, {"org.kde.dolphin": "/t/d.svg"})
    assert IconThemeSource().probe(
        ArtQuery(entry=entry(), icon_name="org.kde.dolphin")) is True


def test_theme_probe_finds_the_short_name(monkeypatch):
    stub_index(monkeypatch, {"dolphin": "/t/d.svg"})
    assert IconThemeSource().probe(
        ArtQuery(entry=entry(), icon_name="org.kde.dolphin")) is True


def test_theme_probe_finds_a_substring_match(monkeypatch):
    """The picker shows a source when browsing it would return something,
    even results too fuzzy to auto-apply."""
    stub_index(monkeypatch, {"dolphin-symbolic": "/t/d.svg"})
    assert IconThemeSource().probe(
        ArtQuery(entry=entry(), icon_name="dolphin")) is True


def test_theme_probe_is_false_for_a_game_no_theme_has(monkeypatch):
    """The case that motivated this: a Steam title in the theme picker."""
    stub_index(monkeypatch, {"firefox": "/t/f.svg", "dolphin": "/t/d.svg"})
    assert IconThemeSource().probe(
        ArtQuery(entry=entry(name="Call of Duty: Black Ops"),
                 icon_name="call of duty: black ops")) is False


def test_theme_probe_is_false_without_a_term(monkeypatch):
    stub_index(monkeypatch, {"firefox": "/t/f.svg"})
    assert IconThemeSource().probe(ArtQuery(entry=entry())) is False


def test_theme_probe_agrees_with_find(monkeypatch):
    stub_index(monkeypatch, {"firefox": "/t/f.svg"})
    source = IconThemeSource()
    hit = ArtQuery(entry=entry(), icon_name="firefox")
    miss = ArtQuery(entry=entry(), icon_name="nothing-like-this")
    assert source.probe(hit) is bool(source.find(hit))
    assert source.probe(miss) is bool(source.find(miss))


# -- iconify ----------------------------------------------------------------

def test_iconify_probe_is_true_when_search_returns_anything(monkeypatch):
    source = IconifySource()
    monkeypatch.setattr(source, "_search", lambda term, limit=32: [
        Artwork(id="i", source_id="iconify", name="x", label="Set")])
    assert source.probe(ArtQuery(entry=entry(), text="firefox")) is True


def test_iconify_probe_is_false_when_nothing_matches(monkeypatch):
    source = IconifySource()
    monkeypatch.setattr(source, "_search", lambda term, limit=32: [])
    assert source.probe(ArtQuery(entry=entry(), text="zzzz")) is False


def test_iconify_probe_tries_the_fallback_term(monkeypatch):
    source = IconifySource()
    monkeypatch.setattr(source, "_search",
                        lambda term, limit=32: [Artwork(id="i", source_id="iconify")]
                        if term == "dolphin" else [])
    assert source.probe(ArtQuery(entry=entry(), text="file manager",
                                 fallback_text="dolphin")) is True


def test_iconify_probe_propagates_failure_rather_than_reporting_empty():
    """A source that is briefly unreachable must not be mistaken for one that
    has nothing. The caller decides what to do; it is not told 'no results'."""
    source = IconifySource()

    def boom(term, limit=32):
        raise RuntimeError("offline")

    source._search = boom
    with pytest.raises(RuntimeError):
        source.probe(ArtQuery(entry=entry(), text="firefox"))


# -- the default implementation --------------------------------------------

def test_default_probe_delegates_to_find():
    from kairo.artwork.base import ArtworkSource

    class Counting(ArtworkSource):
        id = "counting"
        label = "Counting"

        def __init__(self, results):
            self.results = results
            self.calls = 0

        def supports(self, provider_id):
            return True

        def find(self, query):
            self.calls += 1
            return self.results

        def preview(self, art):
            return b""

        def fetch(self, art, dest_dir, stem):
            raise NotImplementedError

    empty, full = Counting([]), Counting([Artwork(id="a", source_id="counting")])
    query = ArtQuery(entry=entry())
    assert empty.probe(query) is False
    assert full.probe(query) is True
    assert empty.calls == 1


# -- local files are always reachable --------------------------------------

def test_local_file_is_never_in_the_picker_and_always_available():
    """It is a button, not a tab, so hiding dead sources can never take away
    the user's ability to choose their own image."""
    registry = default_registry()
    for provider_id in ("steam", "desktop"):
        assert LocalFileSource.id not in {
            s.id for s in registry.browsable_for(provider_id)}
    assert LocalFileSource().supports("steam") is True
    assert LocalFileSource().available() is True


# ---------------------------------------------------------------------------
# SteamGridDB: enough artwork, and sharp
#
# The browser used to show a handful of assets per game against hundreds on
# the website, and many of those were 32px upscaled into a blur. Both had the
# same two causes: only /icons/ and /logos/ were ever requested, and votes
# outranked resolution.
# ---------------------------------------------------------------------------

def _art(kind, edge, score=0.0, official=False):
    from kairo.models import Artwork
    return Artwork(id=f"{kind}{edge}{score}", source_id="steamgriddb",
                   kind=kind, width=edge, height=edge, score=score,
                   official=official, locator="https://example.invalid/a.png")


def test_a_popular_tiny_icon_never_outranks_a_sharp_asset():
    """This is the blur, exactly: 32px enlarged to fill a 116px tile."""
    from kairo.artwork.steamgriddb import _rank

    tiny = _art("icon", 32, score=900)
    sharp = _art("grid", 512, score=1)
    assert max([tiny, sharp], key=_rank) is sharp


def test_a_real_icon_still_wins_among_equally_sharp_assets():
    """Cover art fills the gap; it does not get to displace a drawn icon."""
    from kairo.artwork.steamgriddb import _rank

    icon = _art("icon", 512, score=1)
    cover = _art("grid", 512, score=900)
    assert max([icon, cover], key=_rank) is icon


def test_resolution_breaks_ties_before_the_crowd_does():
    from kairo.artwork.steamgriddb import _rank

    bigger = _art("icon", 1024, score=0)
    smaller = _art("icon", 256, score=500)
    assert max([bigger, smaller], key=_rank) is bigger


def test_the_lookup_asks_for_square_grids_as_well(monkeypatch):
    """Most of a game's artwork lives under /grids/, not /icons/."""
    from kairo.artwork import steamgriddb as sgdb
    from kairo.models import ArtQuery

    asked = []
    source = sgdb.SteamGridDBSource(api_key="k")
    monkeypatch.setattr(source, "game_id", lambda appid: 7)
    monkeypatch.setattr(sgdb.paths, "cache_dir", lambda: Path("/nonexistent"))

    def fake_get(path):
        asked.append(path)
        return {"data": [], "total": 0}

    monkeypatch.setattr(source, "_api_get", fake_get)
    source.find(ArtQuery(entry=entry(), steam_appid="42700"))

    endpoints = {path.split("/")[1] for path in asked}
    assert {"icons", "grids", "logos"} <= endpoints, asked
    grid_call = next(p for p in asked if p.startswith("/grids"))
    assert "dimensions=512x512,1024x1024" in grid_call


def test_one_failing_asset_class_does_not_lose_the_others(monkeypatch):
    """Grids are a bonus. Losing them must not empty the browser."""
    from kairo import net
    from kairo.artwork import steamgriddb as sgdb
    from kairo.models import ArtQuery

    source = sgdb.SteamGridDBSource(api_key="k")
    monkeypatch.setattr(source, "game_id", lambda appid: 7)
    monkeypatch.setattr(sgdb.paths, "cache_dir", lambda: Path("/nonexistent"))

    def fake_get(path):
        if path.startswith("/grids"):
            raise net.NetworkError("down")
        if path.startswith("/icons"):
            return {"data": [{"id": 1, "url": "https://e.invalid/i.png",
                              "width": 512, "height": 512, "style": "official"}],
                    "total": 1}
        return {"data": [], "total": 0}

    monkeypatch.setattr(source, "_api_get", fake_get)
    found = source.find(ArtQuery(entry=entry(), steam_appid="42700"))
    assert [a.kind for a in found] == ["icon"]


def test_an_upscaled_asset_is_dropped_when_something_sharp_exists(monkeypatch):
    """A 32px icon enlarged into a 116px tile arrives as a smear."""
    from kairo.artwork import steamgriddb as sgdb
    from kairo.models import ArtQuery

    source = sgdb.SteamGridDBSource(api_key="k")
    monkeypatch.setattr(source, "game_id", lambda appid: 7)
    monkeypatch.setattr(sgdb.paths, "cache_dir", lambda: Path("/nonexistent"))

    def fake_get(path):
        if path.startswith("/icons"):
            return {"total": 2, "data": [
                {"id": 1, "url": "https://e.invalid/small.png",
                 "width": 32, "height": 32, "style": "custom"},
                {"id": 2, "url": "https://e.invalid/big.png",
                 "width": 512, "height": 512, "style": "official"}]}
        return {"data": [], "total": 0}

    monkeypatch.setattr(source, "_api_get", fake_get)
    found = source.find(ArtQuery(entry=entry(), steam_appid="42700"))
    assert [a.width for a in found] == [512]


def test_a_blurry_icon_still_beats_an_empty_browser(monkeypatch):
    """Dropped only when the game has something better to offer."""
    from kairo.artwork import steamgriddb as sgdb
    from kairo.models import ArtQuery

    source = sgdb.SteamGridDBSource(api_key="k")
    monkeypatch.setattr(source, "game_id", lambda appid: 7)
    monkeypatch.setattr(sgdb.paths, "cache_dir", lambda: Path("/nonexistent"))

    def fake_get(path):
        if path.startswith("/icons"):
            return {"total": 1, "data": [
                {"id": 1, "url": "https://e.invalid/small.png",
                 "width": 32, "height": 32, "style": "custom"}]}
        return {"data": [], "total": 0}

    monkeypatch.setattr(source, "_api_get", fake_get)
    found = source.find(ArtQuery(entry=entry(), steam_appid="42700"))
    assert [a.width for a in found] == [32]


def test_unknown_dimensions_are_never_treated_as_blurry():
    """Not every source reports a size; absence is not evidence of smallness."""
    from kairo.artwork.steamgriddb import _sharp
    from kairo.models import Artwork

    unknown = Artwork(id="u", source_id="steamgriddb", width=0, height=0)
    assert _sharp(unknown) is True


# ---------------------------------------------------------------------------
# SteamGridDB for games that were never on Steam
#
# The Steam-only restriction was Kairo's, not the API's, and it is what left
# emulator libraries with generic symbols instead of cover art.
# ---------------------------------------------------------------------------

def test_emulators_are_served_but_desktop_applications_are_not():
    """Searching a game artwork database for a text editor finds nonsense."""
    from kairo.artwork.steamgriddb import SteamGridDBSource

    source = SteamGridDBSource(api_key="k")
    assert source.supports("steam") is True
    assert source.supports("emu-dolphin") is True
    assert source.supports("desktop") is False


def test_a_title_is_searched_when_there_is_no_appid(monkeypatch):
    from kairo.artwork import steamgriddb as sgdb
    from kairo.models import ArtQuery

    asked = []
    source = sgdb.SteamGridDBSource(api_key="k")
    monkeypatch.setattr(sgdb.paths, "cache_dir", lambda: Path("/nonexistent"))

    def fake_get(path):
        asked.append(path)
        if path.startswith("/search/autocomplete"):
            return {"data": [{"id": 4242, "name": "Metroid Prime"}]}
        if path.startswith("/icons"):
            return {"total": 1, "data": [
                {"id": 1, "url": "https://e.invalid/i.png",
                 "width": 512, "height": 512, "style": "official"}]}
        return {"data": [], "total": 0}

    monkeypatch.setattr(source, "_api_get", fake_get)
    found = source.find(ArtQuery(entry=entry(), text="metroid prime"))
    assert any(p.startswith("/search/autocomplete") for p in asked)
    assert any("/game/4242" in p for p in asked), "the searched id must be used"
    assert [a.width for a in found] == [512]


def test_the_fallback_term_is_tried_when_the_title_finds_nothing(monkeypatch):
    """Emulator queries carry 'title system' as a second attempt."""
    from kairo.artwork import steamgriddb as sgdb
    from kairo.models import ArtQuery

    terms = []
    source = sgdb.SteamGridDBSource(api_key="k")
    monkeypatch.setattr(sgdb.paths, "cache_dir", lambda: Path("/nonexistent"))

    def fake_get(path):
        if path.startswith("/search/autocomplete"):
            terms.append(path)
            if "wii" in path.lower():
                return {"data": [{"id": 7}]}
            return {"data": []}
        return {"data": [], "total": 0}

    monkeypatch.setattr(source, "_api_get", fake_get)
    source.find(ArtQuery(entry=entry(), text="twilight princess",
                         fallback_text="twilight princess wii"))
    assert len(terms) == 2, terms


def test_an_appid_still_outranks_a_title(monkeypatch):
    from kairo.artwork import steamgriddb as sgdb
    from kairo.models import (AUTO_APPLY_THRESHOLD, CONFIDENCE_ID, ArtQuery)

    source = sgdb.SteamGridDBSource(api_key="k")
    monkeypatch.setattr(sgdb.paths, "cache_dir", lambda: Path("/nonexistent"))
    monkeypatch.setattr(source, "game_id", lambda appid: 1)
    monkeypatch.setattr(source, "search_id", lambda term: 2)
    monkeypatch.setattr(source, "_api_get", lambda path: {
        "total": 1, "data": [{"id": 9, "url": "https://e.invalid/i.png",
                              "width": 512, "height": 512, "style": "official"}]})

    by_id = source.best_match(ArtQuery(entry=entry(), steam_appid="440"))
    by_name = source.best_match(ArtQuery(entry=entry(), text="team fortress"))
    assert by_id.confidence == CONFIDENCE_ID
    assert by_name.confidence < by_id.confidence
    assert by_name.confidence >= AUTO_APPLY_THRESHOLD


def test_a_search_failure_is_not_an_empty_library(monkeypatch):
    """Unreachable is not the same as 'this game has no artwork'."""
    from kairo import net
    from kairo.artwork import steamgriddb as sgdb
    from kairo.models import ArtQuery

    source = sgdb.SteamGridDBSource(api_key="k")
    monkeypatch.setattr(sgdb.paths, "cache_dir", lambda: Path("/nonexistent"))

    def fake_get(path):
        raise net.NetworkError("down")

    monkeypatch.setattr(source, "_api_get", fake_get)
    assert source.find(ArtQuery(entry=entry(), text="anything")) == []
