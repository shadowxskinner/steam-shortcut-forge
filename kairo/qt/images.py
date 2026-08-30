"""Turning icon files and bytes into pixmaps, once each.

Qt renders SVG through its own plugin, so the Qt frontend has no need of
cairosvg. Results are cached by source and size for the same reason the Tk
build cached them: browsing a library re-selects the same icons constantly and
nothing is gained by decoding them again.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, Qt
from PySide6.QtGui import QImageReader, QPixmap

try:
    from PySide6.QtSvg import QSvgRenderer
except ImportError:                                     # pragma: no cover
    QSvgRenderer = None

CACHE_LIMIT = 256
_CACHE: "OrderedDict[tuple, QPixmap]" = OrderedDict()


def clear_cache() -> None:
    _CACHE.clear()


def _looks_svg(data: bytes) -> bool:
    head = data[:200].lstrip().lower()
    return head.startswith((b"<svg", b"<?xml"))


def _render_svg(data: bytes, size: int):
    if QSvgRenderer is None:
        return None
    from PySide6.QtGui import QPainter

    renderer = QSvgRenderer(data)
    if not renderer.isValid():
        return None
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


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


def _from_data(data: bytes):
    frame = _largest_frame(data)
    if frame is not None and not frame.isNull():
        return QPixmap.fromImage(frame)
    loaded = QPixmap()                  # a format QImageReader would not walk
    return loaded if loaded.loadFromData(data) else None


def _scale(pixmap, size: int):
    if pixmap is None or pixmap.isNull():
        return None
    return pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


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


def load(size: int, *, path=None, data: bytes | None = None):
    """A pixmap fitted to ``size``, or None if it cannot be decoded."""
    key = _key(size, path, data)
    if key is not None and key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]

    pixmap = None
    try:
        if data is None and path is not None:
            path = Path(path)
            if not path.is_file():
                return None
            if path.suffix.lower() == ".svg":
                pixmap = _render_svg(path.read_bytes(), size)
            else:
                pixmap = _scale(_from_data(path.read_bytes()), size)
        elif data is not None:
            if _looks_svg(data):
                pixmap = _render_svg(data, size)
            else:
                pixmap = _scale(_from_data(data), size)
    except Exception:
        return None

    if pixmap is None or pixmap.isNull():
        return None

    if key is not None:
        _CACHE[key] = pixmap
        while len(_CACHE) > CACHE_LIMIT:
            _CACHE.popitem(last=False)
    return pixmap
