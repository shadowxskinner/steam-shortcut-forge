"""Shared controls, matching the Tk shell's vocabulary.

Same components, same names, same behaviour: an icon well that shows artwork or
a placeholder, a pill group used for both filters and artwork sources, a
clickable entry row, an artwork tile with a chosen state, and navigation icons
drawn rather than shipped.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from kairo.qt import images
from kairo.qt import theme as Q
from kairo.ui import theme as T


# ---------------------------------------------------------------------------
# Navigation icons, drawn
# ---------------------------------------------------------------------------

def nav_pixmap(kind: str, colour: str, size: int = 20) -> QPixmap:
    """A small monochrome pictogram.

    Drawn with QPainter for the same reason the Tk shell drew them on a canvas:
    no asset to package and no glyph font to be missing. A future provider that
    names an unknown icon gets the neutral chip.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(colour))
    pen.setWidthF(1.4)
    painter.setPen(pen)

    if kind == "steam":
        painter.drawEllipse(2, 2, size - 5, size - 5)
        painter.setBrush(QColor(colour))
        painter.drawEllipse(int(size * 0.5), int(size * 0.5), 5, 5)
    elif kind == "grid":
        step = int(size * 0.46)
        for x, y in ((2, 2), (step + 2, 2), (2, step + 2), (step + 2, step + 2)):
            painter.drawRect(x, y, step - 3, step - 3)
    elif kind == "history":
        painter.drawArc(2, 2, size - 5, size - 5, 40 * 16, 280 * 16)
        painter.setBrush(QColor(colour))
        painter.drawEllipse(size - 7, 1, 4, 4)
    elif kind == "sliders":
        painter.setBrush(QColor(colour))
        for index, y in enumerate((4, 9, 14)):
            painter.drawLine(2, y, size - 3, y)
            knob = (11, 5, 13)[index]
            painter.drawEllipse(knob - 2, y - 2, 4, 4)
    else:                                    # "chip" and anything unknown
        painter.drawRect(4, 4, size - 9, size - 9)
        for offset in (6, size - 7):
            painter.drawLine(offset, 1, offset, 4)
            painter.drawLine(offset, size - 5, offset, size - 2)
            painter.drawLine(1, offset, 4, offset)
            painter.drawLine(size - 5, offset, size - 2, offset)
    painter.end()
    return pixmap


class NavButton(QPushButton):
    """One destination. Checkable, so Qt owns the selected state."""

    def __init__(self, key: str, label: str, icon: str, parent=None):
        super().__init__(label, parent)
        self.key = key
        self._icon = icon
        self.setObjectName("nav")
        self.setFixedHeight(Q.H_NAV_ITEM)
        self.setIconSize(QSize(20, 20))
        self.setCheckable(True)
        self.setAutoExclusive(False)
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(18, 18))
        self._paint_icon(False)
        self.toggled.connect(self._paint_icon)

    def _paint_icon(self, on: bool) -> None:
        from PySide6.QtGui import QIcon

        colour = T.C_ACCENT_TEXT if on else T.C_TEXT3
        self.setIcon(QIcon(nav_pixmap(self._icon, colour)))

    def set_count(self, value) -> None:
        self.setToolTip("" if value is None else f"{value} items")


# ---------------------------------------------------------------------------
# Icon well
# ---------------------------------------------------------------------------

class IconWell(QFrame):
    """A fixed square showing artwork, or a placeholder when there is none."""

    def __init__(self, size: int = 48, parent=None):
        super().__init__(parent)
        self.setObjectName("well")
        self._size = size
        self.setFixedSize(size, size)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel("", self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setObjectName("meta")
        layout.addWidget(self.label)

    def show_placeholder(self, text: str = "○") -> None:
        self.label.setPixmap(QPixmap())
        self.label.setText(text)

    def show_path(self, path, placeholder: str = "○") -> None:
        pixmap = images.load(self._size - 12, path=path) if path else None
        if pixmap is None:
            self.show_placeholder(placeholder)
            return
        self.label.setText("")
        self.label.setPixmap(pixmap)

    def show_data(self, data: bytes) -> None:
        pixmap = images.load(self._size - 12, data=data)
        if pixmap is None:
            self.show_placeholder("?")
            return
        self.label.setText("")
        self.label.setPixmap(pixmap)


# ---------------------------------------------------------------------------
# Pills
# ---------------------------------------------------------------------------

class Pills(QWidget):
    """A rounded segmented control, used for filters and artwork sources."""

    changed = Signal(str)

    def __init__(self, values=None, parent=None):
        super().__init__(parent)
        self.setObjectName("pillGroup")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(3, 3, 3, 3)
        self._layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        self.set_values(list(values or []))

    def set_values(self, values) -> None:
        current = self.value()
        for button in self._buttons.values():
            self._group.removeButton(button)
            button.deleteLater()
        self._buttons.clear()

        for value in values:
            button = QPushButton(value, self)
            button.setObjectName("pill")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked, v=value: self.changed.emit(v))
            self._group.addButton(button)
            self._layout.addWidget(button)
            self._buttons[value] = button

        if values:
            self.set_value(current if current in values else values[0],
                           notify=False)
        self.setVisible(bool(values))

    def value(self) -> str:
        for value, button in self._buttons.items():
            if button.isChecked():
                return value
        return ""

    def set_value(self, value: str, notify: bool = True) -> None:
        button = self._buttons.get(value)
        if button is None:
            return
        button.setChecked(True)
        if notify:
            self.changed.emit(value)

    def values(self):
        return list(self._buttons)


# ---------------------------------------------------------------------------
# Rows and tiles
# ---------------------------------------------------------------------------

class EntryRow(QFrame):
    """One application in the middle column. Rebindable, like the Tk row."""

    clicked = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entry = None
        self._selected = False
        self.setObjectName("row")
        self.setFixedHeight(Q.H_ROW)
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(T.S3, T.S2, T.S4, T.S2)
        layout.setSpacing(T.S3)

        self.well = IconWell(Q.WELL_ROW, self)
        layout.addWidget(self.well)

        text = QVBoxLayout()
        text.setSpacing(3)
        self.name = QLabel("", self)
        self.name.setObjectName("rowName")
        self.meta = QLabel("", self)
        self.meta.setObjectName("rowMeta")
        text.addWidget(self.name)
        text.addWidget(self.meta)
        layout.addLayout(text, 1)

        self.dot = QLabel("", self)
        self.dot.setObjectName("dot")
        layout.addWidget(self.dot)

    def bind(self, entry) -> None:
        self.entry = entry
        self.name.setText(T.ellipsize(entry.name, T.LIST_NAME_CHARS))
        self.meta.setText(T.ellipsize(entry.subtitle or entry.local_id, 38))
        self.dot.setText("●" if entry.customized else "")
        self.well.show_path(entry.current_icon, "○")

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.setObjectName("rowOn" if selected else "row")
        self.name.setObjectName("rowNameOn" if selected else "rowName")
        self.meta.setObjectName("rowMetaOn" if selected else "rowMeta")
        for widget in (self, self.name, self.meta):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def mousePressEvent(self, event):
        if self.entry is not None:
            self.clicked.emit(self)


class ArtworkTile(QFrame):

    WIDTH = Q.TILE + 20
    HEIGHT = Q.TILE + 38
    """One candidate icon. Image first, almost no chrome."""

    picked = Signal(object)

    def __init__(self, art, parent=None):
        super().__init__(parent)
        self.art = art
        self._chosen = False
        self.setObjectName("tile")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(self.WIDTH, self.HEIGHT)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.S2, T.S2, T.S2, T.S2)
        layout.setSpacing(T.S1)

        self.well = IconWell(Q.TILE, self)
        self.well.show_placeholder("")
        layout.addWidget(self.well, 0, Qt.AlignHCenter)

        caption = art.label or ("official" if art.official else "")
        if art.kind == "logo":
            caption = f"{caption} logo".strip()
        self.caption = QLabel(T.ellipsize(caption or art.dimensions or " ", 16), self)
        self.caption.setObjectName("meta")
        self.caption.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.caption)

    def set_image(self, data: bytes) -> None:
        self.well.show_data(data)

    def set_chosen(self, chosen: bool) -> None:
        self._chosen = chosen
        self.setObjectName("tileOn" if chosen else "tile")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        self.picked.emit(self.art)
