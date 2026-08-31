"""The application mark, wherever it happens to live.

Installed, the icon is in the hicolor theme and the desktop supplies it by
name. Run from a checkout there is no theme entry, so the same files are
found in the repository instead — otherwise the app has no icon during the
only time anyone is actually looking at it closely.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon, QPixmap

from kairo import APP_ID

#: Largest first: QIcon picks the best size, and a downscale beats an upscale.
_SIZES = (512, 256, 128, 64, 48, 32)


def _repository_icons() -> list[Path]:
    root = Path(__file__).resolve().parents[2] / "icons" / "hicolor"
    found = []
    for size in _SIZES:
        candidate = root / f"{size}x{size}" / "apps" / f"{APP_ID}.png"
        if candidate.is_file():
            found.append(candidate)
    return found


def icon() -> QIcon:
    """The application icon, from the icon theme or from the checkout."""
    themed = QIcon.fromTheme(APP_ID)
    if not themed.isNull():
        return themed
    built = QIcon()
    for path in _repository_icons():
        built.addFile(str(path))
    return built


def mark(size: int) -> QPixmap:
    """The mark at ``size``, or a null pixmap if it cannot be found."""
    return icon().pixmap(size, size)
