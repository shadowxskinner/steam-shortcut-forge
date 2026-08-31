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

CACHE_LIMIT = 256
_CACHE: "OrderedDict[tuple, QPixmap]" = OrderedDict()
_IMAGE_CACHE: "OrderedDict[tuple, QImage]" = OrderedDict()
_IMAGE_CACHE_LOCK = threading.RLock()


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
            min_edge: int = 0):
    """Decode and fit an image as a worker-safe :class:`QImage`.

    Raster previews can enforce a native-pixel floor before they are scaled;
    SVG remains resolution-independent. Results use a separate, locked cache
    because preview and row workers can run concurrently.
    """
    key = _key(size, path, data)
    prepared_key = (*key, min_edge) if key is not None else None
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
            image = _render_svg_image(data, size)
        else:
            image = _image_from_data(data)
            if image is not None and min_edge:
                if min(image.width(), image.height()) < min_edge:
                    return None
            if image is not None and not image.isNull():
                image = image.scaled(size, size, Qt.KeepAspectRatio,
                                     Qt.SmoothTransformation)
    except Exception:
        return None

    if image is None or image.isNull():
        return None

    if prepared_key is not None:
        with _IMAGE_CACHE_LOCK:
            _IMAGE_CACHE[prepared_key] = image
            _IMAGE_CACHE.move_to_end(prepared_key)
            while len(_IMAGE_CACHE) > CACHE_LIMIT:
                _IMAGE_CACHE.popitem(last=False)
    return image


def load(size: int, *, path=None, data: bytes | None = None):
    """A pixmap fitted to ``size``, or None if it cannot be decoded."""
    key = _key(size, path, data)
    if key is not None and key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]

    image = prepare(size, path=path, data=data)
    pixmap = QPixmap.fromImage(image) if image is not None else None

    if pixmap is None or pixmap.isNull():
        return None

    if key is not None:
        _CACHE[key] = pixmap
        while len(_CACHE) > CACHE_LIMIT:
            _CACHE.popitem(last=False)
    return pixmap
