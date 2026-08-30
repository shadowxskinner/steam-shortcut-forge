"""The Settings destination, read-only for this milestone."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QScrollArea,
                               QSlider, QVBoxLayout, QWidget)

from kairo import APP_ID, APP_NAME, TAGLINE, __version__
from kairo import migration, paths
from kairo.artwork.steamgriddb import CONFIG_KEY as SGDB_KEY
from kairo.qt import theme as Q
from kairo.ui import theme as T


class AppearancePanel(QFrame):
    """Live glass tuning, without relying on a keyboard shortcut firing.

    Shortcuts are convenient and were also the only way to reach this, which
    turned out to be no way at all - a control that cannot be found is a
    control that does not exist. Every layer gets a slider, the presets get
    buttons, and the resulting values are printed in a form that can be pasted
    straight back into the source.
    """

    changed = Signal(object)

    def __init__(self, glass, blur_status: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self._glass = Q.resolve(glass)
        self._sliders: dict[str, QSlider] = {}
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Q.PAD_CARD, Q.PAD_CARD, Q.PAD_CARD, Q.PAD_CARD)
        layout.setSpacing(T.S3)

        heading = QLabel("APPEARANCE")
        heading.setObjectName("micro")
        layout.addWidget(heading)

        self.blur = QLabel(blur_status or "blur: not attempted")
        self.blur.setObjectName("rowMeta")
        layout.addWidget(self.blur)

        # The division of labour, stated in the UI so the sliders are not read
        # as controlling something they cannot reach.
        explain = QLabel(
            "Kairo controls opacity. The compositor controls blur.\n\n"
            "The sliders below set how solid each of Kairo's own surfaces is. "
            "Blur is drawn by KWin behind the window, and how hard it smears "
            "is a desktop setting — System Settings → Desktop Effects → Blur. "
            "The ext-background-effect-v1 protocol Kairo uses only asks for a "
            "region to be blurred; it carries no radius or strength, so there "
            "is deliberately no blur control here to imply otherwise.\n\n"
            "If content behind Kairo is still legible, both levers matter: "
            "blur smears what is behind a surface but does not dim it, so a "
            "region with little opacity keeps its contrast however hard the "
            "compositor works. Raise Workspace first — it is the backdrop the "
            "cards sit on.")
        explain.setObjectName("meta")
        explain.setWordWrap(True)
        explain.setMaximumWidth(Q.W_MEASURE)
        layout.addWidget(explain)

        presets = QHBoxLayout()
        presets.setSpacing(T.S2)
        label = QLabel("Preset")
        label.setObjectName("meta")
        label.setFixedWidth(Q.W_LABEL)
        presets.addWidget(label)
        for name in Q.PRESETS:
            button = QPushButton(name.title())
            button.setObjectName("secondary")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked, key=name: self.set_preset(key))
            button.setFixedHeight(Q.H_BUTTON)
            presets.addWidget(button)
        presets.addStretch(1)
        layout.addLayout(presets)

        grid = QGridLayout()
        grid.setHorizontalSpacing(T.S3)
        grid.setVerticalSpacing(T.S1)
        for row, name in enumerate(Q.LAYERS):
            caption = QLabel(name)
            caption.setObjectName("meta")
            caption.setFixedWidth(Q.W_LABEL)
            caption.setMinimumHeight(Q.H_PILLS)
            slider = QSlider(Qt.Horizontal)
            # A QSlider styled only through its sub-controls has no height of
            # its own: the groove is three pixels, so the row collapses and
            # squeezes the labels beside it down to nothing.
            slider.setFixedHeight(Q.H_PILLS)
            slider.setMinimum(30)
            slider.setMaximum(100)
            slider.setValue(int(round(getattr(self._glass, name) * 100)))
            slider.valueChanged.connect(
                lambda value, key=name: self._slider_moved(key, value))
            readout = QLabel(f"{getattr(self._glass, name):.2f}")
            readout.setObjectName("rowMeta")
            readout.setFixedWidth(Q.W_READOUT)
            readout.setMinimumHeight(Q.H_PILLS)
            grid.addWidget(caption, row, 0)
            grid.addWidget(slider, row, 1)
            grid.addWidget(readout, row, 2)
            self._sliders[name] = slider
            slider.setProperty("readout", readout)
        layout.addLayout(grid)

        bottom = QHBoxLayout()
        self.readout = QLabel(self._glass.describe())
        self.readout.setObjectName("rowMeta")
        self.readout.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bottom.addWidget(self.readout, 1)
        copy = QPushButton("Copy values")
        copy.setFixedHeight(Q.H_BUTTON)
        copy.setObjectName("secondary")
        copy.setCursor(Qt.PointingHandCursor)
        copy.clicked.connect(self._copy)
        bottom.addWidget(copy)
        layout.addLayout(bottom)

    # -- state -------------------------------------------------------------

    def glass(self):
        return self._glass

    def set_glass(self, glass, notify: bool = False) -> None:
        """Reflect a value chosen elsewhere - a shortcut, or the command line."""
        self._glass = Q.resolve(glass)
        self._updating = True
        for name, slider in self._sliders.items():
            value = getattr(self._glass, name)
            slider.setValue(int(round(value * 100)))
            readout = slider.property("readout")
            if readout is not None:
                readout.setText(f"{value:.2f}")
        self._updating = False
        self.readout.setText(self._glass.describe())
        if notify:
            self.changed.emit(self._glass)

    def set_preset(self, name: str) -> None:
        self.set_glass(Q.PRESETS.get(name, self._glass), notify=True)

    def set_blur_status(self, status: str) -> None:
        self.blur.setText(status)

    # -- events ------------------------------------------------------------

    def _slider_moved(self, name: str, value: int) -> None:
        if self._updating:
            return
        self._glass = self._glass.replaced(**{name: value / 100.0})
        slider = self._sliders[name]
        readout = slider.property("readout")
        if readout is not None:
            readout.setText(f"{value / 100.0:.2f}")
        self.readout.setText(self._glass.describe())
        self.changed.emit(self._glass)

    def _copy(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._glass.describe())


class SettingsPane(QWidget):
    def __init__(self, context, blur_status: str = "", glass=None,
                 on_glass_change=None, parent=None):
        super().__init__(parent)
        self.ctx = context
        self.setObjectName("workspace")
        # A QWidget *subclass* does not paint a stylesheet background unless
        # it is told to; plain QWidget instances do. Both panes name
        # themselves #workspace, so without this they showed the default
        # palette instead of Kairo's backdrop — the reason Settings and
        # Changes read lighter than the library.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._on_glass_change = on_glass_change

        # The pane used to lay its cards straight into the window with
        # nothing to scroll, so once the content was taller than the window
        # Qt had no choice but to squeeze it — the sliders and their labels
        # collapsed into each other.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(Q.PAD_PANE, 0, Q.PAD_PANE, 0)
        outer.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(Q.H_HEADER)
        head = QHBoxLayout(header)
        head.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Settings")
        title.setObjectName("title")
        head.addWidget(title, 0, Qt.AlignVCenter)
        head.addStretch(1)
        outer.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()          # deliberately unnamed: painting #workspace
        scroll.setWidget(body)    # twice lightens the whole scrolled region
        outer.addWidget(scroll, 1)

        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, T.S3, Q.PAD_PANE)
        layout.setSpacing(Q.GAP_WIDE)

        # -- artwork source key -------------------------------------------
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(Q.PAD_CARD, Q.PAD_CARD,
                                       Q.PAD_CARD, Q.PAD_CARD)
        card_layout.setSpacing(T.S3)
        heading = QLabel("SteamGridDB API key")
        heading.setObjectName("pane")
        note = QLabel("Optional. Only needed for Steam game artwork — icon "
                      "themes, Iconify and your own files work without it.")
        note.setObjectName("meta")
        note.setWordWrap(True)
        note.setMaximumWidth(Q.W_MEASURE)
        self.key = QLineEdit(context.config.get(SGDB_KEY, ""))
        self.key.setPlaceholderText("Paste API key")
        self.key.setEnabled(False)
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.setFixedHeight(Q.H_BUTTON)
        save.setEnabled(False)
        save.setToolTip("Not wired yet — this milestone is read-only")
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(save)
        card_layout.addWidget(heading)
        card_layout.addWidget(note)
        card_layout.addWidget(self.key)
        card_layout.addLayout(row)
        layout.addWidget(card)

        # -- where things live --------------------------------------------
        places = QFrame()
        places.setObjectName("card")
        places_layout = QVBoxLayout(places)
        places_layout.setContentsMargins(Q.PAD_CARD, Q.PAD_CARD,
                                         Q.PAD_CARD, Q.PAD_CARD)
        places_layout.setSpacing(T.S2)
        section = QLabel("WHERE THINGS LIVE")
        section.setObjectName("micro")
        places_layout.addWidget(section)
        for label, value in (("Settings", paths.config_file()),
                             ("Cache (safe to delete)", paths.cache_dir()),
                             ("Artwork", paths.icon_store()),
                             ("Launcher entries", paths.applications_dir())):
            line = QHBoxLayout()
            key = QLabel(label)
            key.setObjectName("meta")
            key.setFixedWidth(Q.W_KEY)
            path = QLabel(str(value))
            path.setObjectName("rowMeta")
            line.addWidget(key)
            line.addWidget(path, 1)
            places_layout.addLayout(line)
        leftovers = migration.legacy_leftovers()
        if leftovers:
            note = QLabel("Steam Shortcut Forge files are still on disk and can "
                          "be removed by hand once you are happy:\n  "
                          + "\n  ".join(str(path) for path in leftovers))
            note.setObjectName("meta")
            places_layout.addWidget(note)
        layout.addWidget(places)

        # -- appearance ----------------------------------------------------
        self.appearance = AppearancePanel(glass, blur_status, self)
        if on_glass_change is not None:
            self.appearance.changed.connect(on_glass_change)
        layout.addWidget(self.appearance)

        layout.addStretch(1)
        about = QLabel(f"{APP_NAME} {__version__}  ·  {TAGLINE}\n{APP_ID}")
        about.setObjectName("meta")
        layout.addWidget(about)

    def set_glass(self, glass) -> None:
        self.appearance.set_glass(glass)

    def set_blur_status(self, status: str) -> None:
        self.appearance.set_blur_status(status)

    def refresh(self) -> None:
        return None
