"""Source availability probing.

Offering "Icon themes" for a Steam game no theme has heard of is an invitation
to click something that cannot work. Sources are asked whether they have
anything before they are offered.
"""

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
