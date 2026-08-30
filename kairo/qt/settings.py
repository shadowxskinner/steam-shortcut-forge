"""The Settings destination, read-only for this milestone."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from kairo import APP_ID, APP_NAME, TAGLINE, __version__
from kairo import migration, paths
from kairo.artwork.steamgriddb import CONFIG_KEY as SGDB_KEY
from kairo.qt.emulator_settings import EmulatorsCard
from kairo.qt import theme as Q
from kairo.ui import theme as T


class SettingsPane(QWidget):
    def __init__(self, context, on_providers_changed=None, parent=None):
        super().__init__(parent)
        self.ctx = context
        self._on_providers_changed = on_providers_changed
        self.setObjectName("workspace")
        # A QWidget *subclass* does not paint a stylesheet background unless
        # it is told to; plain QWidget instances do. Both panes name
        # themselves #workspace, so without this they showed the default
        # palette instead of Kairo's backdrop — the reason Settings and
        # Changes read lighter than the library.
        self.setAttribute(Qt.WA_StyledBackground, True)

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

        # -- emulators -----------------------------------------------------
        # The only part of Settings that changes what the sidebar contains,
        # so it tells the shell to rebuild rather than waiting for a restart.
        layout.addWidget(EmulatorsCard(context, self._on_providers_changed))

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

        layout.addStretch(1)
        about = QLabel(f"{APP_NAME} {__version__}  ·  {TAGLINE}\n{APP_ID}")
        about.setObjectName("meta")
        layout.addWidget(about)

    def refresh(self) -> None:
        return None
