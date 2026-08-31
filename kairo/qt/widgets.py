"""Shared controls, matching the Tk shell's vocabulary.

Same components, same names, same behaviour: an icon well that shows artwork or
a placeholder, a pill group used for both filters and artwork sources, a
clickable entry row, an artwork tile with a chosen state, and navigation icons
drawn rather than shipped.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QFontMetrics, QImage, QPainter, QPen,
                           QPixmap, QPolygonF)
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from kairo.qt import images
from kairo.qt import theme as Q
from kairo.ui import theme as T


def _theme_logo(name: str, size: int, ratio: float = 1.0):
    """A provider's own icon from the installed theme, or None.

    Nothing is bundled: this uses whatever the user's Steam, Dolphin or
    emulator package already installed, so no trademark ships with Kairo and
    a machine without that package simply keeps the drawn glyph.
    """
    if not name:
        return None
    from kairo.desktop.lookup import resolve_icon
    from kairo.qt import images

    path = resolve_icon(name)
    if path is None:
        return None
    return images.load(size, path=path, ratio=ratio)


def restyle(*widgets) -> None:
    """Re-run the stylesheet after an objectName change.

    Qt resolves QSS by object name at polish time, so changing the name is
    inert until the widget is repolished. Three classes were each carrying
    their own copy of this loop.
    """
    for widget in widgets:
        widget.style().unpolish(widget)
        widget.style().polish(widget)


# ---------------------------------------------------------------------------
# Navigation icons, drawn
# ---------------------------------------------------------------------------

def _arrowhead(painter, ink, cx, cy, radius, degrees, length, width) -> None:
    """A triangle standing on a circle, pointing the way the arc travels."""
    theta = math.radians(degrees)
    px, py = cx + radius * math.cos(theta), cy - radius * math.sin(theta)
    tx, ty = -math.sin(theta), -math.cos(theta)      # tangent, rising angle
    nx, ny = ty, -tx                                 # and its normal
    head = QPolygonF([
        QPointF(px + tx * length * 0.55, py + ty * length * 0.55),
        QPointF(px - tx * length * 0.45 + nx * width / 2,
                py - ty * length * 0.45 + ny * width / 2),
        QPointF(px - tx * length * 0.45 - nx * width / 2,
                py - ty * length * 0.45 - ny * width / 2)])
    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(ink)
    painter.drawPolygon(head)
    painter.restore()


def nav_pixmap(kind: str, colour: str, size: int = 20,
               ratio: float = 1.0) -> QPixmap:
    """A small monochrome pictogram, drawn onto the display's own pixel grid.

    Drawn with QPainter for the same reason the Tk shell drew them on a
    canvas: no asset to package and no glyph font to be missing. A future
    provider that names an unknown icon gets the neutral chip.

    Two things separate this from the first version. Every coordinate is now
    a fraction of ``size`` rather than a pixel count: the old geometry was
    written against size 20 and never revisited when the scale moved to 22,
    so each glyph sat about a pixel off its own centre and no two shared a
    stroke weight. And ``ratio`` renders at the screen's device pixel ratio,
    without which a 22-pixel bitmap is simply what a 2x display magnifies.

    Terminals are round. Square ends on a 2-pixel stroke are the difference
    between a drawn icon and a shipped one.
    """
    scale = max(1.0, float(ratio))
    pixmap = QPixmap(int(round(size * scale)), int(round(size * scale)))
    pixmap.fill(Qt.transparent)
    pixmap.setDevicePixelRatio(scale)

    # No explicit scale here. QPainter reads the pixmap's device pixel ratio
    # and applies it to every coordinate already; scaling on top of that drew
    # the glyph at ratio-squared and clipped all but its top-left corner.
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)

    ink = QColor(colour)
    stroke = size * 0.085
    pen = QPen(ink)
    pen.setWidthF(stroke)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    centre = size / 2.0
    inset = stroke / 2.0 + size * 0.07

    if kind == "grid":
        gap = size * 0.13
        cell = (size - 2 * inset - gap) / 2.0
        corner = cell * 0.34
        for row in (0, 1):
            for column in (0, 1):
                painter.drawRoundedRect(
                    QRectF(inset + column * (cell + gap),
                           inset + row * (cell + gap), cell, cell),
                    corner, corner)
    elif kind == "history":
        radius = centre - inset
        painter.drawArc(QRectF(centre - radius, centre - radius,
                               radius * 2, radius * 2), 90 * 16, 300 * 16)
        # The head sits at the open end and points back into the gap, so the
        # circle reads as returning to where it started rather than as a
        # letter C with a bead on it, which is how the dot read.
        _arrowhead(painter, ink, centre, centre, radius, 30.0,
                   size * 0.30, size * 0.26)
    elif kind == "sliders":
        span = size - 2 * inset
        for y_place, knob_place in ((0.28, 0.66), (0.5, 0.30), (0.72, 0.74)):
            y = size * y_place
            painter.drawLine(QPointF(inset, y), QPointF(size - inset, y))
            painter.save()
            painter.setPen(Qt.NoPen)
            painter.setBrush(ink)
            painter.drawEllipse(QPointF(inset + span * knob_place, y),
                                stroke * 1.25, stroke * 1.25)
            painter.restore()
    elif kind == "steam":
        radius = centre - inset
        painter.drawEllipse(QPointF(centre, centre), radius, radius)
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(ink)
        painter.drawEllipse(QPointF(centre + radius * 0.34,
                                    centre - radius * 0.34),
                            stroke * 1.3, stroke * 1.3)
        painter.restore()
    else:                                # "chip" and anything unknown
        body = size * 0.46
        painter.drawRoundedRect(
            QRectF(centre - body / 2, centre - body / 2, body, body),
            size * 0.10, size * 0.10)
        leg, half = size * 0.13, body / 2
        for offset in (-body * 0.26, body * 0.26):
            painter.drawLine(QPointF(centre + offset, centre - half),
                             QPointF(centre + offset, centre - half - leg))
            painter.drawLine(QPointF(centre + offset, centre + half),
                             QPointF(centre + offset, centre + half + leg))
            painter.drawLine(QPointF(centre - half, centre + offset),
                             QPointF(centre - half - leg, centre + offset))
            painter.drawLine(QPointF(centre + half, centre + offset),
                             QPointF(centre + half + leg, centre + offset))
    painter.end()
    return pixmap


class NavButton(QPushButton):
    """One destination.

    A plain QPushButton puts its icon and text in a single centred run, which
    leaves the count with nowhere to sit and the glyph off the text's left
    edge by a variable amount. Laying the three out explicitly puts every
    icon on one vertical line, every name on another, and the counts flush
    right — which is most of what makes a sidebar look deliberate.
    """

    def __init__(self, key: str, label: str, icon: str, parent=None,
                 logo_name: str = ""):
        super().__init__(parent)
        self.key = key
        self._icon = icon
        self._logo_name = logo_name
        self._logo = None
        self._logo_ratio = 0.0
        self.setObjectName("nav")
        self.setFixedHeight(Q.H_NAV_ITEM)
        self.setCheckable(True)
        self.setAutoExclusive(False)
        self.setCursor(Qt.PointingHandCursor)

        row = QHBoxLayout(self)
        row.setContentsMargins(T.S3, 0, T.S3, 0)
        row.setSpacing(T.S3)
        self.glyph = QLabel(self)
        self.glyph.setFixedSize(QSize(Q.NAV_ICON, Q.NAV_ICON))
        self.glyph.setAlignment(Qt.AlignCenter)
        self.name = QLabel(label, self)
        self.name.setObjectName("navName")
        self.count = QLabel("", self)
        self.count.setObjectName("navCount")
        # Children of a button must not swallow the press that reaches it.
        for child in (self.glyph, self.name, self.count):
            child.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        row.addWidget(self.glyph)
        row.addWidget(self.name)
        row.addStretch(1)
        row.addWidget(self.count)

        self._paint_icon(False)
        self.toggled.connect(self._paint_icon)

    def _paint_icon(self, on: bool) -> None:
        # The label first: returning early for a row that has a logo meant
        # Steam and Dolphin never took the selected text style at all, while
        # every glyph row did.
        self.name.setObjectName("navNameOn" if on else "navName")
        restyle(self.name)

        # A real logo if the theme has one — Steam's and Dolphin's are what a
        # person recognises — and the drawn glyph when it does not. The glyph
        # stays neutral so the only colour in the sidebar belongs to a real
        # product; an accent-tinted pictogram read as a third brand competing
        # with the two actual ones.
        # Resolved here rather than in __init__ because a widget has no
        # screen until it is shown, and the screen is what says how many real
        # pixels a 22-point icon is allowed to use.
        ratio = self.devicePixelRatioF()
        if self._logo_ratio != ratio:
            self._logo = _theme_logo(self._logo_name, Q.NAV_ICON, ratio)
            self._logo_ratio = ratio
        if self._logo is not None and not self._logo.isNull():
            self.glyph.setPixmap(self._logo)
            return
        colour = Q.GLYPH_ON if on else Q.GLYPH
        self.glyph.setPixmap(
            nav_pixmap(self._icon, colour, Q.NAV_ICON, ratio))

    def showEvent(self, event) -> None:
        # __init__ paints at ratio 1 because the button has no screen yet.
        super().showEvent(event)
        self._paint_icon(self.isChecked())

    def set_count(self, value) -> None:
        self.count.setText("" if value is None else str(value))
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
        self.label.setObjectName("wellMark")
        layout.addWidget(self.label)

    def show_placeholder(self, text: str = "○") -> None:
        self.label.setPixmap(QPixmap())
        self.label.setText(text)

    def show_path(self, path, placeholder: str = "○") -> None:
        pixmap = (images.load(self._size - 12, path=path,
                              ratio=self.devicePixelRatioF())
                  if path else None)
        if pixmap is None:
            self.show_placeholder(placeholder)
            return
        self.label.setText("")
        self.label.setPixmap(pixmap)

    def show_data(self, data: bytes) -> None:
        pixmap = images.load(self._size - 12, data=data,
                             ratio=self.devicePixelRatioF())
        if pixmap is None:
            self.show_placeholder("?")
            return
        self.label.setText("")
        self.label.setPixmap(pixmap)

    def show_image(self, image: QImage | None, placeholder: str = "?") -> None:
        """Paint an image that was already decoded away from the GUI thread."""
        if image is None or image.isNull():
            self.show_placeholder(placeholder)
            return
        self.label.setText("")
        self.label.setPixmap(QPixmap.fromImage(image))


# ---------------------------------------------------------------------------
# Pills
# ---------------------------------------------------------------------------

class Pills(QWidget):
    """A rounded segmented control, used for filters and artwork sources."""

    changed = Signal(str)

    def __init__(self, values=None, parent=None):
        super().__init__(parent)
        self.setObjectName("pillGroup")
        # QWidget subclasses opt in to stylesheet backgrounds; without this
        # the group's rounded track never painted and the pills floated.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(3, 3, 3, 3)
        self._layout.setSpacing(2)
        self.setFixedHeight(Q.H_PILLS)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        self.set_values(list(values or []))

    def set_values(self, values) -> None:
        # Source/filter refreshes commonly repeat the same choices. Preserve
        # the existing controls in that case so they neither flash nor briefly
        # lose their checked state while deleteLater waits for the event loop.
        values = list(dict.fromkeys(values))
        current = self.value()
        if values == list(self._buttons):
            self.setVisible(bool(values))
            return

        for button in self._buttons.values():
            self._group.removeButton(button)
            self._layout.removeWidget(button)
            button.setParent(None)
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
        self._icon_ready = False
        self.setObjectName("row")
        self.setFixedHeight(Q.H_ROW)
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(T.S3, 0, T.S4, 0)
        layout.setSpacing(T.S3)

        self.well = IconWell(Q.WELL_ROW, self)
        layout.addWidget(self.well, 0, Qt.AlignVCenter)

        # The name, and nothing under it. The second line carried a Steam
        # appid, a .desktop basename or a system label depending on the
        # provider — an identifier the reader did not ask for in two cases
        # out of three, and a row is easier to scan without it.
        self.name = QLabel("", self)
        self.name.setObjectName("rowName")
        layout.addWidget(self.name, 1)

        self.dot = QLabel("", self)
        self.dot.setObjectName("dot")
        layout.addWidget(self.dot, 0, Qt.AlignVCenter)

    def bind(self, entry, *, defer_icon: bool = False,
             icon_generation: int = 0) -> bool:
        """Bind text immediately and optionally leave icon work to a worker.

        The return value tells the pane that this row needs an icon prepared.
        Stable rows keep their current pixmap across searches and filtering,
        avoiding both a flash and unnecessary decoding.
        """
        identity = (entry.key, str(entry.current_icon or ""), icon_generation)
        icon_changed = identity != getattr(self, "_icon_identity", None)
        if icon_changed:
            # A new identity has nothing painted for it yet.
            self._icon_ready = False
        self._icon_identity = identity
        self.entry = entry
        self.name.setText(T.ellipsize(entry.name, Q.LIST_NAME_CHARS))
        self.dot.setText("●" if entry.customized else "")
        # A ring inside a rounded square reads as a broken image. The
        # initial reads as a placeholder, the way a contacts list does.
        placeholder = (entry.name or "?").strip()[:1].upper()
        if not defer_icon:
            if icon_changed:
                self.well.show_path(entry.current_icon, placeholder)
                self._icon_ready = True
            return False
        if icon_changed:
            self.well.show_placeholder(placeholder)
        # Ask again for anything still unpainted, not merely for what just
        # changed. Growing the page starts a new rows token and cancels the
        # pump feeding the previous page, so rows whose icon never arrived
        # would otherwise keep their placeholder letter forever.
        return bool(entry.current_icon) and not self._icon_ready

    def show_prepared_icon(self, image: QImage | None, key: str,
                           generation: int) -> None:
        if self.entry is None or self.entry.key != key:
            return
        if self._icon_identity[2] != generation:
            return
        placeholder = (self.entry.name or "?").strip()[:1].upper()
        self.well.show_image(image, placeholder)
        # Delivered: this row no longer needs to be queued by a later page.
        self._icon_ready = True

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.setObjectName("rowOn" if selected else "row")
        self.name.setObjectName("rowNameOn" if selected else "rowName")
        restyle(self, self.name)

    def mousePressEvent(self, event):
        if self.entry is not None:
            self.clicked.emit(self)


class ArtworkTile(QFrame):
    """One candidate icon. Image first, almost no chrome."""

    WIDTH = Q.TILE + 20
    HEIGHT = Q.TILE + 38

    picked = Signal(object)

    def __init__(self, art, parent=None, *, origin: str = ""):
        super().__init__(parent)
        self.art = art
        self.origin = origin
        self._chosen = False
        self.setObjectName("tile")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(self.WIDTH, self.HEIGHT)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.S2, T.S2, T.S2, T.S1)
        layout.setSpacing(T.S2)

        self.well = IconWell(Q.TILE, self)
        self.well.show_placeholder("")
        layout.addWidget(self.well, 0, Qt.AlignHCenter)

        # With one grid, where a tile came from is what the tabs used to
        # say, so that is what the caption carries. Style and size go to the
        # tooltip: "HighContrast · Icon themes" does not fit a 136px tile and
        # was being clipped to "ighContrast · Icon the."
        style = art.label or ("official" if art.official else "")
        noun = {"logo": "logo", "grid": "cover"}.get(art.kind, "")
        detail = " · ".join(p for p in (style, noun, art.dimensions) if p)
        self.caption = QLabel(self)
        self.caption.setObjectName("meta")
        self.caption.setToolTip(" · ".join(p for p in (detail, origin) if p))
        shown = origin or style or art.dimensions or " "
        metrics = QFontMetrics(self.caption.font())
        self.caption.setText(metrics.elidedText(shown, Qt.ElideRight,
                                                self.WIDTH - T.S4))
        self.caption.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.caption)

    def set_image(self, image: QImage) -> None:
        self.well.show_image(image)

    def set_chosen(self, chosen: bool) -> None:
        self._chosen = chosen
        self.setObjectName("tileOn" if chosen else "tile")
        restyle(self)

    def mousePressEvent(self, event):
        self.picked.emit(self.art)
