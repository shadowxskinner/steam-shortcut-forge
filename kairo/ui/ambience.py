"""A single cached ambient backdrop.

CustomTkinter has no real transparency: ``fg_color="transparent"`` resolves to
the master's flat colour, so anything placed behind a panel is painted over by
the panel's own children. An ambient image can therefore only be seen in the
gaps - the margins around cards and the space between them. That is a genuine
limitation, and it is also where the reference keeps its colour, so the effect
lands roughly where it should.

Everything here happens once. The backdrop is rendered at first launch, written
to the cache directory, and reloaded from there afterwards. Nothing regenerates
on selection, on resize, or on any interaction: the image fades to the window
colour at its edges, so a window larger than the asset simply shows flat
background beyond it with no visible seam.
"""

from __future__ import annotations

from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageOps
except ImportError:                                     # pragma: no cover
    Image = ImageDraw = ImageOps = None

try:
    import customtkinter as ctk
except ImportError:                                     # pragma: no cover
    ctk = None

from kairo import paths
from kairo.ui import theme as T

#: Bump when the recipe changes so stale assets are not reused. The cache key
#: carries the palette but not the glow parameters, so retuning these without
#: bumping this would quietly keep serving the old image.
VERSION = 2

#: Generous enough to cover a maximised window on a common display. Beyond it
#: the backdrop has already faded to the window colour.
SIZE = (1600, 1000)

#: (centre x, centre y, radius, colour, strength). Strength is the peak alpha
#: of the glow, and it is deliberately low - removing the whole backdrop should
#: not change how readable anything is.
#: Centres sit clear of the edge fade, so the glow peaks where it is meant to
#: read rather than in the band that is on its way back to the window colour.
GLOWS = (
    (1210, 210, 780, "#7A4AF2", 0.20),     # purple-magenta, upper right
    (210, 860, 700, "#2C74E6", 0.09),      # blue, opposite corner
    (180, 620, 420, "#22A2D6", 0.04),      # a whisper of cyan further left
)

#: How far in from each edge the composite fades back to the window colour.
#: This is what guarantees the seamless edge rather than hoping the glow
#: geometry happens to miss the borders - and it is why resizing costs
#: nothing: beyond the asset there is flat background and no visible step.
EDGE_FADE = 150

_CACHED = {}


def cache_path(size: tuple[int, int] = SIZE, base: str = None) -> Path:
    # The base colour is part of the key: retune the palette and the old
    # asset stops matching the window it sits behind.
    tone = (base or T.C_BG).lstrip("#")
    return (paths.cache_dir() / "ambience"
            / f"workspace-{size[0]}x{size[1]}-{tone}-v{VERSION}.png")


def edge_mask(size: tuple[int, int], inset: int = EDGE_FADE):
    """Opaque in the middle, ramping to nothing at the borders."""
    mask = Image.new("L", size, 255)
    draw = ImageDraw.Draw(mask)
    inset = max(1, min(inset, min(size) // 2))
    for step in range(inset):
        value = int(255 * step / inset)
        draw.rectangle([step, step, size[0] - 1 - step, size[1] - 1 - step],
                       outline=value)
    return mask


def render(size: tuple[int, int] = SIZE, base: str = T.C_BG, glows=GLOWS):
    """Compose the backdrop.

    Built from PIL's own radial gradient rather than a per-pixel loop: each
    glow is one 256x256 gradient resized and pasted through as a mask, so the
    whole image costs a handful of resizes instead of a million iterations.

    The composite is then faded back to the window colour at its borders, so
    the edges match whatever lies beyond them no matter where the glows sit.
    """
    if Image is None:
        return None
    plain = Image.new("RGB", size, base)
    image = plain.copy()
    for centre_x, centre_y, radius, colour, strength in glows:
        diameter = radius * 2
        mask = ImageOps.invert(Image.radial_gradient("L"))
        mask = mask.resize((diameter, diameter), Image.LANCZOS)
        if strength < 1.0:
            mask = mask.point(lambda value: int(value * strength))
        layer = Image.new("RGB", (diameter, diameter), colour)
        image.paste(layer, (centre_x - radius, centre_y - radius), mask)
    return Image.composite(image, plain, edge_mask(size))


def backdrop(size: tuple[int, int] = SIZE):
    """The cached PIL image, generating and storing it on first use."""
    if Image is None:
        return None
    if size in _CACHED:
        return _CACHED[size]

    path = cache_path(size)
    image = None
    if path.is_file():
        try:
            with Image.open(path) as stored:
                image = stored.convert("RGB")
        except Exception:
            image = None

    if image is None:
        image = render(size)
        if image is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                image.save(path, optimize=True)
            except OSError:
                pass                       # cosmetic; never fail a launch

    _CACHED[size] = image
    return image


def photo(size: tuple[int, int] = SIZE):
    """A CTkImage of the backdrop, or None when it cannot be made."""
    if ctk is None:
        return None
    key = ("photo", size)
    if key in _CACHED:
        return _CACHED[key]
    image = backdrop(size)
    if image is None:
        return None
    try:
        result = ctk.CTkImage(light_image=image, dark_image=image, size=size)
    except Exception:
        result = None
    _CACHED[key] = result
    return result


def attach(frame, size: tuple[int, int] = SIZE):
    """Place the backdrop behind ``frame``'s content.

    Must be called before the frame's children are created: Tk stacks later
    siblings above earlier ones, and this has to sit underneath.
    """
    image = photo(size)
    if image is None or ctk is None:
        return None
    try:
        label = ctk.CTkLabel(frame, text="", image=image)
        label.place(x=0, y=0)
        return label
    except Exception:
        return None                        # ambience is never worth a crash


def clear_cache() -> None:
    _CACHED.clear()
