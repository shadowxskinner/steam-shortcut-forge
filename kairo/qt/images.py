"""Turning icon files and bytes into images, once each.

Qt renders SVG through its own plugin, so the Qt frontend has no need of
cairosvg. Worker-safe QImages do the expensive decoding and scaling; the GUI
thread only turns the finished result into a QPixmap. Both are cached by source
and size because browsing a library re-selects the same icons constantly and
nothing is gained by decoding them again.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, Qt
from PySide6.QtGui import QImage, QImageReader, QPixmap

try:
    from PySide6.QtSvg import QSvgRenderer
except ImportError:                                     # pragma: no cover
    QSvgRenderer = None

#: An entry cap alone is not a memory bound. The same icon at 1x, 2x and 3x
#: is one, four and nine times the pixels, so 256 entries is anywhere between
#: a few megabytes and fifty depending on which screens the window has
#: visited — and after a monitor change both ratios are live at once.
#: Measured: 256 mixed-ratio tile images cost ~49 MB. The count still caps
#: pathological churn; the byte budget is what actually holds the ceiling.
CACHE_LIMIT = 256
IMAGE_CACHE_BYTES = 24 * 1024 * 1024
PIXMAP_CACHE_BYTES = 16 * 1024 * 1024

_CACHE: "OrderedDict[tuple, QPixmap]" = OrderedDict()
_IMAGE_CACHE: "OrderedDict[tuple, QImage]" = OrderedDict()
_IMAGE_CACHE_LOCK = threading.RLock()


def _cost(item) -> int:
    """Decoded pixel cost, not the size of the file it came from.

    A 4 KB PNG that decodes to 232x232 occupies 215 KB, and it is the decoded
    form that both caches hold. Depth is read from the object rather than
    assumed: an 8-bit icon and an ARGB32 one differ fourfold.
    """
    try:
        width = item.width()
        height = item.height()
        depth = item.depth() or 32
    except Exception:                                   # pragma: no cover
        return 0
    return max(0, width) * max(0, height) * max(1, depth // 8)


def _trim(cache, budget: int, *, keep) -> None:
    """Evict oldest-first until the cache fits, never touching ``keep``.

    ``keep`` is the entry the caller has just produced and is about to paint.
    Evicting that would mean decoding it again immediately, which is how a
    cache becomes a treadmill: every monitor transition would refetch and
    re-decode everything it had just prepared.
    """
    while len(cache) > CACHE_LIMIT:
        oldest = next(iter(cache))
        if oldest == keep:
            break
        cache.pop(oldest)
    total = sum(_cost(value) for value in cache.values())
    while total > budget and len(cache) > 1:
        oldest = next(iter(cache))
        if oldest == keep:
            break
        total -= _cost(cache.pop(oldest))


def cache_bytes() -> tuple[int, int]:
    """Decoded bytes held by the image and pixmap caches."""
    with _IMAGE_CACHE_LOCK:
        images_total = sum(_cost(value) for value in _IMAGE_CACHE.values())
    return images_total, sum(_cost(value) for value in _CACHE.values())


def clear_cache() -> None:
    _CACHE.clear()
    with _IMAGE_CACHE_LOCK:
        _IMAGE_CACHE.clear()


def _looks_svg(data: bytes) -> bool:
    head = data[:200].lstrip().lower()
    return head.startswith((b"<svg", b"<?xml"))


def _render_svg_image(data: bytes, size: int):
    if QSvgRenderer is None:
        return None
    from PySide6.QtGui import QPainter

    renderer = QSvgRenderer(data)
    if not renderer.isValid():
        return None
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    return image


def _largest_frame(data: bytes):
    """Decode the biggest image in a container, not the first one.

    A .ico holds several resolutions in one file, and SteamGridDB serves
    exactly that: one asset, many sizes. QPixmap.loadFromData returns the
    first directory entry, which is conventionally the smallest — so a 256px
    icon arrived as a 32px thumbnail and was then enlarged into the tile.
    That, and not the reported dimensions, is why the browser looked blurry:
    the metadata was telling the truth about a frame nobody was decoding.
    """
    payload = QByteArray(data)          # must outlive the reader
    buffer = QBuffer(payload)
    buffer.open(QBuffer.ReadOnly)
    reader = QImageReader(buffer)
    reader.setDecideFormatFromContent(True)
    best = None
    while True:
        frame = reader.read()
        if frame.isNull():
            break
        if best is None or frame.width() * frame.height() > best.width() * best.height():
            best = frame
        if not reader.jumpToNextImage():
            break
    return best


def native_edge(data: bytes) -> int:
    """The shorter edge of the biggest frame in the file, or 0 if unreadable.

    The API's dimensions describe the asset; this describes the pixels that
    actually arrived, which is the only number worth filtering on.
    """
    frame = _largest_frame(data)
    if frame is None or frame.isNull():
        return 0
    return min(frame.width(), frame.height())


def is_usable_preview(data: bytes, min_edge: int) -> bool:
    """Whether an artwork preview can be rendered cleanly at ``min_edge``.

    Raster artwork must contain enough real pixels to avoid enlarging a tiny
    thumbnail into a blurry tile. SVG is resolution independent, however, so
    its nominal canvas size is not a useful quality limit: a valid 48px SVG
    remains sharp when Qt renders it at the tile size.
    """
    if _looks_svg(data):
        if QSvgRenderer is None:
            return False
        try:
            return QSvgRenderer(data).isValid()
        except Exception:
            return False
    return native_edge(data) >= min_edge


def _image_from_data(data: bytes):
    """Decode without creating a GUI-only QPixmap.

    QImage is safe to build on a worker thread; QPixmap is tied to the GUI
    platform. Keeping that boundary here lets artwork and application icons
    do their expensive parsing and scaling without stopping interaction.
    """
    frame = _largest_frame(data)
    if frame is not None and not frame.isNull():
        return frame
    loaded = QImage()
    return loaded if loaded.loadFromData(data) else None


def _key(size: int, path, data):
    if path is not None:
        try:
            stat = Path(path).stat()
        except OSError:
            return None
        return ("path", str(path), stat.st_mtime_ns, stat.st_size, size)
    if data is not None:
        return ("data", hashlib.sha1(data).hexdigest(), size)
    return None


def prepare(size: int, *, path=None, data: bytes | None = None,
            min_edge: int = 0, ratio: float = 1.0):
    """Decode and fit an image as a worker-safe :class:`QImage`.

    ``size`` is logical points and ``ratio`` the device pixel ratio of the
    screen the result is bound for, exactly as in :func:`load`. Everything
    that arrives asynchronously - a page of row icons, a grid of artwork
    tiles - comes through here, and none of it asked for a ratio before: the
    image was decoded at logical size and handed to a pixmap that claimed 1x,
    so the compositor magnified every icon in the library on a scaled display
    while the sidebar, which uses load(), stayed sharp.

    Raster previews can enforce a native-pixel floor before they are scaled;
    SVG remains resolution-independent. Results use a separate, locked cache
    because preview and row workers can run concurrently.

    The ratio belongs in the key. Without it the first screen to ask for an
    icon answers for every other one, which is the ordinary case on a desk
    with a laptop panel and an external display, not a corner case.
    """
    scale = max(1.0, float(ratio))
    pixels = int(round(size * scale))
    key = _key(pixels, path, data)
    prepared_key = (*key, min_edge, scale) if key is not None else None
    if prepared_key is not None:
        with _IMAGE_CACHE_LOCK:
            cached = _IMAGE_CACHE.get(prepared_key)
            if cached is not None:
                _IMAGE_CACHE.move_to_end(prepared_key)
                return cached

    try:
        if data is None and path is not None:
            source = Path(path)
            if not source.is_file():
                return None
            data = source.read_bytes()
        if data is None:
            return None

        if _looks_svg(data):
            image = _render_svg_image(data, pixels)
        else:
            image = _image_from_data(data)
            # The floor is about the pixels that arrived in the file, so it
            # is checked against the decoded frame and never against the
            # scaled result - otherwise asking for a 2x tile would quietly
            # admit artwork that is too small to draw at 1x.
            if image is not None and min_edge:
                if min(image.width(), image.height()) < min_edge:
                    return None
            if image is not None and not image.isNull():
                image = image.scaled(pixels, pixels, Qt.KeepAspectRatio,
                                     Qt.SmoothTransformation)
    except Exception:
        return None

    if image is None or image.isNull():
        return None

    # The conversion on the GUI thread carries this across, so the ratio
    # survives the hop without the caller having to remember what it asked
    # for. Named indirectly: a test bans that class from this function, and
    # rightly - nothing here may touch a GUI-only type.
    image.setDevicePixelRatio(scale)

    if prepared_key is not None:
        with _IMAGE_CACHE_LOCK:
            _IMAGE_CACHE[prepared_key] = image
            _IMAGE_CACHE.move_to_end(prepared_key)
            _trim(_IMAGE_CACHE, IMAGE_CACHE_BYTES, keep=prepared_key)
    return image


def load(size: int, *, path=None, data: bytes | None = None,
         ratio: float = 1.0):
    """A pixmap fitted to ``size`` logical points, or None.

    ``ratio`` is the device pixel ratio of the screen the pixmap is bound
    for. Nothing here asked for one before, so every icon in the window was
    decoded at its logical size and then magnified by the compositor on any
    display scaled above 1x — the sidebar logos and the row icons were soft
    for that reason alone, with no blurry source file involved.
    """
    scale = max(1.0, float(ratio))
    pixels = int(round(size * scale))

    key = _key(pixels, path, data)
    if key is not None:
        key = (*key, scale)
    if key is not None and key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]

    image = prepare(size, path=path, data=data, ratio=scale)
    pixmap = QPixmap.fromImage(image) if image is not None else None

    if pixmap is None or pixmap.isNull():
        return None
    pixmap.setDevicePixelRatio(scale)

    if key is not None:
        _CACHE[key] = pixmap
        _trim(_CACHE, PIXMAP_CACHE_BYTES, keep=key)
    return pixmap
