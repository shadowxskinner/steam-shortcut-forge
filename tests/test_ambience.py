"""The ambient backdrop.

Everything here is about it costing nothing after startup and being quiet
enough that removing it would change nothing about readability.
"""

import pytest

from kairo import paths
from kairo.ui import ambience
from kairo.ui import theme as T

pytest.importorskip("PIL")

SMALL = (160, 100)


@pytest.fixture(autouse=True)
def fresh(fake_home):
    ambience.clear_cache()
    yield
    ambience.clear_cache()


def channels(colour: str):
    colour = colour.lstrip("#")
    return tuple(int(colour[i:i + 2], 16) for i in (0, 2, 4))


# -- the image itself -------------------------------------------------------

def test_the_backdrop_fades_to_the_window_colour(fresh):
    """A window larger than the asset shows flat background beyond it, so the
    asset's own border has to already be that colour or there is a visible step.

    Checked at the real size: the glow centres sit outside a small test canvas
    entirely, so a scaled-down render would pass this without meaning anything.
    """
    image = ambience.render(ambience.SIZE)
    width, height = ambience.SIZE
    base = channels(T.C_BG)
    probes = [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1),
              (width // 2, 0), (width // 2, height - 1),
              (0, height // 2), (width - 1, height // 2)]
    for probe in probes:
        assert image.getpixel(probe) == base, f"{probe} is not the window colour"


def test_the_edge_fade_is_what_guarantees_it(fresh):
    """Structural rather than a happy accident of where the glows sit."""
    mask = ambience.edge_mask((200, 140), inset=20)
    assert mask.getpixel((0, 0)) == 0
    assert mask.getpixel((100, 70)) == 255


def test_the_glow_is_barely_there(fresh):
    """Subtle enough that removing it would not affect readability."""
    image = ambience.render(ambience.SIZE)
    base = channels(T.C_BG)
    pixels = image.load()
    width, height = image.size
    peak = max(
        sum(abs(a - b) for a, b in zip(pixels[x, y], base))
        for y in range(0, height, 8) for x in range(0, width, 8)
    )
    # Summed across three channels, so roughly a third of this per channel.
    # Raised deliberately from 90 when the wash was measured as too faint on a
    # real display; still low enough that removing it changes no readability.
    assert peak <= 110, f"total channel lift of {peak} is too strong"
    assert peak >= 30, "too faint to be worth the asset"


def test_nothing_is_tinted_at_the_centre_of_the_content(fresh):
    """The glow belongs around the panels, not across the reading area."""
    image = ambience.render(ambience.SIZE)
    base = channels(T.C_BG)
    middle = image.getpixel((760, 520))
    assert sum(abs(a - b) for a, b in zip(middle, base)) <= 60


# -- generated once ---------------------------------------------------------

def test_the_asset_is_written_to_the_cache(fresh):
    ambience.backdrop(SMALL)
    assert ambience.cache_path(SMALL).is_file()


def test_a_second_call_does_not_re_render(fresh, monkeypatch):
    ambience.backdrop(SMALL)
    ambience.clear_cache()

    calls = []
    real = ambience.render
    monkeypatch.setattr(ambience, "render",
                        lambda *a, **k: calls.append(1) or real(*a, **k))

    ambience.backdrop(SMALL)
    assert calls == [], "the cached asset should have been reused"


def test_repeated_calls_in_one_session_hit_memory(fresh):
    first = ambience.backdrop(SMALL)
    assert ambience.backdrop(SMALL) is first


def test_the_cache_key_follows_the_palette(fresh):
    """Retune the background and the old asset no longer matches the window
    it sits behind, so it must not be reused."""
    one = ambience.cache_path(SMALL, base="#000000")
    two = ambience.cache_path(SMALL, base="#101020")
    assert one != two


def test_the_cache_key_follows_the_version(fresh, monkeypatch):
    before = ambience.cache_path(SMALL)
    monkeypatch.setattr(ambience, "VERSION", ambience.VERSION + 1)
    assert ambience.cache_path(SMALL) != before


def test_the_asset_lives_under_the_cache_directory(fresh):
    """Regenerable, so it belongs somewhere the user can delete freely."""
    assert ambience.cache_path(SMALL).is_relative_to(paths.cache_dir())


# -- never worth a crash ----------------------------------------------------

def test_no_pillow_means_no_ambience_rather_than_no_app(fresh, monkeypatch):
    monkeypatch.setattr(ambience, "Image", None)
    assert ambience.render(SMALL) is None
    assert ambience.backdrop(SMALL) is None
    assert ambience.photo(SMALL) is None


def test_an_unwritable_cache_still_yields_an_image(fresh, monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("read-only")

    monkeypatch.setattr(type(ambience.cache_path(SMALL)), "mkdir", refuse)
    assert ambience.backdrop(SMALL) is not None


def test_a_corrupt_cached_asset_is_regenerated(fresh):
    path = ambience.cache_path(SMALL)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a png")
    ambience.clear_cache()
    assert ambience.backdrop(SMALL) is not None
