"""The match pass and its confidence model."""

from kairo.artwork.base import ArtworkSource
from kairo.artwork.registry import ArtworkRegistry
from kairo.artwork.themes import IconThemeSource
from kairo.matching import Matcher
from kairo.models import (AUTO_APPLY_THRESHOLD, CONFIDENCE_EXACT_NAME,
                          CONFIDENCE_FUZZY, CONFIDENCE_ID, AppEntry, Artwork,
                          ArtQuery, Suggestion)
from kairo.providers.base import AppProvider
from kairo.providers.registry import ProviderRegistry
from kairo.tasks import CancelToken


# -- doubles ----------------------------------------------------------------

class FakeSource(ArtworkSource):
    def __init__(self, source_id, confidence=None, *, available=True,
                 explode=False):
        self.id = source_id
        self.label = source_id.title()
        self.confidence = confidence
        self._available = available
        self.explode = explode
        self.calls = 0

    def supports(self, provider_id):
        return True

    def available(self, config=None):
        return self._available

    def best_match(self, query):
        self.calls += 1
        if self.explode:
            raise RuntimeError("source is down")
        if self.confidence is None:
            return None
        art = Artwork(id=f"{self.id}-1", source_id=self.id, name="art",
                      label=self.label)
        return Suggestion(art, self.confidence, f"from {self.id}")

    def find(self, query):
        return []

    def preview(self, art):
        return b""

    def fetch(self, art, dest_dir, stem):
        raise NotImplementedError


class FakeProvider(AppProvider):
    id = "fake"
    label = "Fake"
    noun = "apps"

    def __init__(self, order=("a", "b", "c")):
        self.auto_match_sources = tuple(order)

    def scan(self):
        return []

    def artwork_query(self, entry):
        return ArtQuery(entry=entry, text=entry.name.lower(),
                        icon_name=entry.icon_hint)

    def writer(self):
        raise NotImplementedError


def entry(name="Thing", key="fake:1", customized=False, icon_hint=""):
    return AppEntry(key=key, provider_id="fake", name=name,
                    customized=customized, icon_hint=icon_hint)


def matcher(sources, order=("a", "b", "c")):
    provider = FakeProvider(order)
    return Matcher(ProviderRegistry([provider]), ArtworkRegistry(sources))


# -- source order -----------------------------------------------------------

def test_first_confident_source_wins():
    a = FakeSource("a", CONFIDENCE_ID)
    b = FakeSource("b", CONFIDENCE_EXACT_NAME)
    match = matcher([a, b]).match_entry(entry())
    assert match.source_id == "a"
    assert b.calls == 0            # never consulted


def test_falls_through_when_the_preferred_source_has_nothing():
    a = FakeSource("a", None)
    b = FakeSource("b", CONFIDENCE_EXACT_NAME)
    match = matcher([a, b]).match_entry(entry())
    assert match.source_id == "b"
    assert a.calls == 1


def test_falls_through_when_the_preferred_source_is_unavailable():
    """No SteamGridDB key must not mean no matches."""
    a = FakeSource("a", CONFIDENCE_ID, available=False)
    b = FakeSource("b", CONFIDENCE_EXACT_NAME)
    match = matcher([a, b]).match_entry(entry())
    assert match.source_id == "b"
    assert a.calls == 0


def test_a_broken_source_does_not_cost_the_match():
    a = FakeSource("a", CONFIDENCE_ID, explode=True)
    b = FakeSource("b", CONFIDENCE_EXACT_NAME)
    assert matcher([a, b]).match_entry(entry()).source_id == "b"


def test_provider_order_is_respected():
    a = FakeSource("a", CONFIDENCE_EXACT_NAME)
    b = FakeSource("b", CONFIDENCE_ID)
    match = matcher([a, b], order=("b", "a")).match_entry(entry())
    assert match.source_id == "b"


def test_sources_outside_the_chain_are_never_consulted():
    """Browsable-but-not-auto sources must not leak into automatic matching."""
    extra = FakeSource("z", CONFIDENCE_ID)
    match = matcher([FakeSource("a", None), extra], order=("a",)).match_entry(entry())
    assert match is None
    assert extra.calls == 0


# -- the confidence threshold -----------------------------------------------

def test_low_confidence_is_not_a_match():
    """A fuzzy hit is worse than nothing: a wrong icon has to be noticed
    before it can be undone."""
    assert matcher([FakeSource("a", CONFIDENCE_FUZZY)]).match_entry(entry()) is None


def test_exactly_at_the_threshold_counts():
    match = matcher([FakeSource("a", AUTO_APPLY_THRESHOLD)]).match_entry(entry())
    assert match is not None


def test_just_below_the_threshold_does_not():
    source = FakeSource("a", AUTO_APPLY_THRESHOLD - 0.01)
    assert matcher([source]).match_entry(entry()) is None


def test_threshold_is_configurable():
    provider = FakeProvider(("a",))
    lenient = Matcher(ProviderRegistry([provider]),
                      ArtworkRegistry([FakeSource("a", CONFIDENCE_FUZZY)]),
                      threshold=0.1)
    assert lenient.match_entry(entry()) is not None


def test_match_carries_its_reason_and_confidence():
    match = matcher([FakeSource("a", CONFIDENCE_ID)]).match_entry(entry())
    assert match.confidence == CONFIDENCE_ID
    assert match.reason == "from a"
    assert match.confident is True
    assert match.source_label == "A"


def test_unknown_provider_yields_no_match():
    m = Matcher(ProviderRegistry([]), ArtworkRegistry([FakeSource("a", CONFIDENCE_ID)]))
    assert m.match_entry(entry()) is None


# -- match_all --------------------------------------------------------------

def test_report_counts_and_headline():
    m = matcher([FakeSource("a", CONFIDENCE_ID)])
    report = m.match_all([entry(key="fake:1"), entry(key="fake:2")])
    assert report.scanned == 2
    assert report.matched == 2
    assert report.headline() == "2 applications discovered  ·  2 artwork matches found"


def test_unmatched_applications_are_listed_not_dropped():
    m = matcher([FakeSource("a", None)])
    report = m.match_all([entry(key="fake:1", name="Alpha")])
    assert report.matched == 0
    assert [e.name for e in report.unmatched] == ["Alpha"]
    assert report.headline().endswith("0 artwork matches found")


def test_already_customized_apps_are_skipped_by_default():
    m = matcher([FakeSource("a", CONFIDENCE_ID)])
    report = m.match_all([entry(key="fake:1", customized=True),
                          entry(key="fake:2")])
    assert report.scanned == 1


def test_customized_apps_can_be_included():
    m = matcher([FakeSource("a", CONFIDENCE_ID)])
    report = m.match_all([entry(key="fake:1", customized=True)],
                         include_customized=True)
    assert report.matched == 1


def test_by_key_indexes_the_matches():
    m = matcher([FakeSource("a", CONFIDENCE_ID)])
    report = m.match_all([entry(key="fake:7")])
    assert set(report.by_key()) == {"fake:7"}


def test_match_all_reports_progress():
    seen = []
    matcher([FakeSource("a", CONFIDENCE_ID)]).match_all(
        [entry(key="fake:1"), entry(key="fake:2")],
        on_progress=lambda i, total, e: seen.append(i))
    assert seen == [0, 1]


def test_match_all_can_be_cancelled():
    token = CancelToken()
    m = matcher([FakeSource("a", CONFIDENCE_ID)])
    report = m.match_all([entry(key=f"fake:{i}") for i in range(10)],
                         token=token,
                         on_progress=lambda i, t, e: token.cancel())
    assert report.cancelled is True
    assert report.matched < 10


def test_matching_writes_nothing(fake_home):
    """The whole point of separating match from apply."""
    apps_dir = fake_home / ".local" / "share" / "applications"
    before = set(apps_dir.iterdir())
    matcher([FakeSource("a", CONFIDENCE_ID)]).match_all(
        [entry(key="fake:1"), entry(key="fake:2")])
    assert set(apps_dir.iterdir()) == before
    assert not (fake_home / ".local" / "share" / "kairo").exists()


# -- the real theme source's confidence rules -------------------------------

def test_theme_source_matches_an_exact_declared_icon_name(monkeypatch):
    from kairo.themeindex import ThemeIndex
    monkeypatch.setattr(ThemeIndex, "index", classmethod(lambda cls: {
        "Papirus": {"apps": {"org.kde.dolphin": "/t/dolphin.svg"}, "other": {}}}))

    source = IconThemeSource()
    got = source.best_match(ArtQuery(entry=entry(icon_hint="org.kde.dolphin"),
                                     icon_name="org.kde.dolphin"))
    assert got.confidence == CONFIDENCE_EXACT_NAME
    assert "Papirus" in got.reason


def test_theme_source_falls_back_to_the_short_name(monkeypatch):
    from kairo.models import CONFIDENCE_SHORT_NAME
    from kairo.themeindex import ThemeIndex
    monkeypatch.setattr(ThemeIndex, "index", classmethod(lambda cls: {
        "Papirus": {"apps": {"dolphin": "/t/dolphin.svg"}, "other": {}}}))

    got = IconThemeSource().best_match(
        ArtQuery(entry=entry(), icon_name="org.kde.dolphin"))
    assert got.confidence == CONFIDENCE_SHORT_NAME


def test_theme_source_refuses_a_substring_match(monkeypatch):
    """'dolphin' must not be matched by 'dolphin-emulator'. This is the
    confident-looking mistake the threshold exists to prevent."""
    from kairo.themeindex import ThemeIndex
    monkeypatch.setattr(ThemeIndex, "index", classmethod(lambda cls: {
        "Papirus": {"apps": {"dolphin-emulator": "/t/e.svg"}, "other": {}}}))

    assert IconThemeSource().best_match(
        ArtQuery(entry=entry(), icon_name="dolphin")) is None


def test_theme_source_needs_a_name(monkeypatch):
    from kairo.themeindex import ThemeIndex
    monkeypatch.setattr(ThemeIndex, "index", classmethod(lambda cls: {}))
    assert IconThemeSource().best_match(ArtQuery(entry=entry())) is None


# -- the real Iconify and SteamGridDB confidence rules -----------------------

def test_iconify_matches_only_an_exact_icon_name(monkeypatch):
    """Iconify ranks by relevance over 275,000 icons, so its top hit is often
    merely thematically related - searching 'steam' returns locomotives."""
    from kairo.artwork.iconify import IconifySource
    from kairo.models import CONFIDENCE_EXACT_SEARCH

    source = IconifySource()
    monkeypatch.setattr(source, "_search", lambda term, limit=64: [
        Artwork(id="i1", source_id="iconify", name="steam-locomotive",
                label="Material"),
        Artwork(id="i2", source_id="iconify", name="firefox", label="Logos"),
    ])

    got = source.best_match(ArtQuery(entry=entry(), text="firefox"))
    assert got.confidence == CONFIDENCE_EXACT_SEARCH
    assert got.artwork.name == "firefox"


def test_iconify_returns_nothing_when_only_related_icons_exist(monkeypatch):
    from kairo.artwork.iconify import IconifySource

    source = IconifySource()
    monkeypatch.setattr(source, "_search", lambda term, limit=64: [
        Artwork(id="i1", source_id="iconify", name="steam-locomotive",
                label="Material"),
    ])
    assert source.best_match(ArtQuery(entry=entry(), text="steam")) is None


def test_iconify_tries_the_fallback_term(monkeypatch):
    from kairo.artwork.iconify import IconifySource

    source = IconifySource()

    def search(term, limit=64):
        if term == "dolphin":
            return [Artwork(id="i", source_id="iconify", name="dolphin",
                            label="Logos")]
        return []

    monkeypatch.setattr(source, "_search", search)
    got = source.best_match(ArtQuery(entry=entry(), text="file manager",
                                     fallback_text="dolphin"))
    assert got is not None and got.artwork.name == "dolphin"


def test_iconify_survives_a_network_failure(monkeypatch):
    from kairo.artwork.iconify import IconifySource

    source = IconifySource()

    def boom(term, limit=64):
        raise RuntimeError("offline")

    monkeypatch.setattr(source, "_search", boom)
    assert source.best_match(ArtQuery(entry=entry(), text="firefox")) is None


def test_steamgriddb_match_is_authoritative(monkeypatch):
    """Keyed on the Steam app ID, so it cannot have found the wrong game."""
    from kairo.artwork.steamgriddb import SteamGridDBSource

    source = SteamGridDBSource("key")
    monkeypatch.setattr(source, "find", lambda q: [
        Artwork(id="1", source_id="steamgriddb", name="", label="Official",
                kind="icon"),
    ])
    got = source.best_match(ArtQuery(entry=entry(), steam_appid="440"))
    assert got.confidence == CONFIDENCE_ID
    assert "440" in got.reason


def test_steamgriddb_returns_nothing_for_an_unindexed_game(monkeypatch):
    from kairo.artwork.steamgriddb import SteamGridDBSource

    source = SteamGridDBSource("key")
    monkeypatch.setattr(source, "find", lambda q: [])
    assert source.best_match(ArtQuery(entry=entry(), steam_appid="440")) is None


def test_steam_provider_prefers_steamgriddb_then_themes_then_iconify():
    """The order the user asked for, declared by the provider."""
    from kairo.providers.steam import SteamProvider
    assert SteamProvider.auto_match_sources == ("steamgriddb", "theme", "iconify")


def test_desktop_provider_prefers_themes_then_iconify():
    from kairo.providers.desktop_entry import DesktopEntryProvider
    assert DesktopEntryProvider.auto_match_sources == ("theme", "iconify")
