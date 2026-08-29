"""Turning icon bytes on disk or from the network into something Tk can draw."""

from __future__ import annotations

import hashlib
import io
import tkinter as tk
import warnings
from collections import OrderedDict
from pathlib import Path

try:
    from PIL import Image, ImageTk
    _LANCZOS = getattr(Image, "Resampling", Image).LANCZOS
except ImportError:                                     # pragma: no cover
    Image = ImageTk = None
    _LANCZOS = None

try:
    import cairosvg
except ImportError:                                     # pragma: no cover
    cairosvg = None

try:
    import customtkinter as ctk
except ImportError:                                     # pragma: no cover
    ctk = None

# Many .ico files declare a header size that does not match the embedded
# bitmap. Pillow decodes them correctly regardless, so the warning is noise on
# every icon load. Scoped to this one message so nothing else is hidden.
warnings.filterwarnings("ignore", message="Image was not the expected size",
                        module="PIL.IcoImagePlugin")

#: Past this multiple an upscale is more mush than detail.
MAX_UPSCALE = 3.0


def looks_svg(data: bytes) -> bool:
    head = data[:200].lstrip().lower()
    return head.startswith((b"<svg", b"<?xml"))


def svg_available() -> bool:
    return cairosvg is not None


def rasterize_svg(data: bytes, size: int) -> bytes:
    if cairosvg is None:
        raise ValueError("SVG previews require cairosvg")
    return cairosvg.svg2png(bytestring=data, output_width=size, output_height=size)


def fit(img, size: int):
    """Scale to fill a size x size box, enlarging small artwork as well.

    ``Image.thumbnail()`` only ever shrinks, so a 64px icon dropped into a
    152px tile stays 64px and reads as a speck.
    """
    width, height = img.size
    if not width or not height:
        return img
    factor = min(size / width, size / height)
    factor = min(factor, MAX_UPSCALE) if factor > 1 else factor
    if abs(factor - 1.0) < 0.01:
        return img
    return img.resize((max(1, round(width * factor)), max(1, round(height * factor))),
                      _LANCZOS)


def _source_bytes(path: Path | None, data: bytes | None, size: int) -> bytes | None:
    if data is None and path is not None and path.suffix.lower() == ".svg":
        data = path.read_bytes()
    if data is not None and looks_svg(data):
        data = rasterize_svg(data, size)
    return data


def scaled_photo(size: int, *, path: Path | None = None, data: bytes | None = None):
    """A PhotoImage fitted to size x size, smoothly resampled where possible."""
    data = _source_bytes(path, data, size)
    if ImageTk is not None:
        src = io.BytesIO(data) if data is not None else str(path)
        with Image.open(src) as img:
            return ImageTk.PhotoImage(fit(img.convert("RGBA"), size))

    photo = tk.PhotoImage(data=data) if data is not None else tk.PhotoImage(file=str(path))
    shrink = max(photo.width() // size, photo.height() // size, 1)
    if shrink > 1:
        return photo.subsample(shrink, shrink)
    grow = max(1, min(int(size // max(photo.width(), photo.height(), 1)), int(MAX_UPSCALE)))
    return photo.zoom(grow, grow) if grow > 1 else photo


def ctk_icon(size: int, *, path: Path | None = None, data: bytes | None = None):
    """A CTkImage, which respects HiDPI widget scaling.

    A raw PhotoImage handed to a CTk widget bypasses widget scaling and renders
    at a different effective size than everything around it. Returns None when
    Pillow is unavailable so callers fall back to ``scaled_photo``.
    """
    if Image is None or ctk is None:
        return None
    data = _source_bytes(path, data, size)
    src = io.BytesIO(data) if data is not None else str(path)
    with Image.open(src) as img:
        fitted = fit(img.convert("RGBA"), size)
        return ctk.CTkImage(light_image=fitted, dark_image=fitted, size=fitted.size)


#: Decoded icons, keyed on source and size. Browsing a library re-selects the
#: same icons constantly - switching back to an entry should not decode and
#: rescale its artwork again. Entries are only ever evicted once the cache is
#: full, and any widget still showing one keeps its own reference, so eviction
#: can never leave a widget pointing at a freed image.
_CACHE: "OrderedDict[tuple, object]" = OrderedDict()
CACHE_LIMIT = 256


def cache_key(size: int, path: Path | None, data: bytes | None):
    if path is not None:
        try:
            stat = path.stat()
        except OSError:
            return None
        return ("path", str(path), stat.st_mtime_ns, stat.st_size, size)
    if data is not None:
        return ("data", hashlib.sha1(data).hexdigest(), size)
    return None


def clear_cache() -> None:
    _CACHE.clear()


def load_icon(size: int, *, path: Path | None = None, data: bytes | None = None):
    """Best available representation, CTkImage first. Cached."""
    key = cache_key(size, path, data)
    if key is not None:
        cached = _CACHE.get(key)
        if cached is not None:
            _CACHE.move_to_end(key)
            return cached

    photo = ctk_icon(size, path=path, data=data)
    if photo is None:
        photo = scaled_photo(size, path=path, data=data)

    if key is not None and photo is not None:
        _CACHE[key] = photo
        while len(_CACHE) > CACHE_LIMIT:
            _CACHE.popitem(last=False)
    return photo
