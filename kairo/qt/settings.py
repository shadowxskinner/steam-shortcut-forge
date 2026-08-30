"""The Settings destination, read-only for this milestone."""

from __future__ import annotations

from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout, QWidget)

from kairo import APP_ID, APP_NAME, TAGLINE, __version__
from kairo import migration, paths
from kairo.artwork.steamgriddb import CONFIG_KEY as SGDB_KEY
from kairo.ui import theme as T


class SettingsPane(QWidget):
    def __init__(self, context, blur_status: str = "", parent=None):
        super().__init__(parent)
        self.ctx = context
        self.setObjectName("workspace")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(T.PAD_WINDOW, T.S5, T.PAD_WINDOW, T.S5)
        layout.setSpacing(T.S4)

        title = QLabel("Settings")
        title.setObjectName("title")
        layout.addWidget(title)

        # -- artwork source key -------------------------------------------
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(T.PAD_CARD, T.PAD_CARD,
                                       T.PAD_CARD, T.PAD_CARD)
        card_layout.setSpacing(T.S2)
        heading = QLabel("SteamGridDB API key")
        heading.setObjectName("rowNameOn")
        note = QLabel("Optional. Only needed for Steam game artwork — icon "
                      "themes, Iconify and your own files work without it.")
        note.setObjectName("meta")
        note.setWordWrap(True)
        self.key = QLineEdit(context.config.get(SGDB_KEY, ""))
        self.key.setPlaceholderText("Paste API key")
        self.key.setEnabled(False)
        save = QPushButton("Save")
        save.setObjectName("primary")
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
        places_layout.setContentsMargins(T.PAD_CARD, T.PAD_CARD,
                                         T.PAD_CARD, T.PAD_CARD)
        places_layout.setSpacing(T.S1)
        section = QLabel("W H E R E   T H I N G S   L I V E")
        section.setObjectName("micro")
        places_layout.addWidget(section)
        for label, value in (("Settings", paths.config_file()),
                             ("Cache (safe to delete)", paths.cache_dir()),
                             ("Artwork", paths.icon_store()),
                             ("Launcher entries", paths.applications_dir())):
            line = QHBoxLayout()
            key = QLabel(label)
            key.setObjectName("meta")
            key.setFixedWidth(190)
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
        appearance = QFrame()
        appearance.setObjectName("card")
        appearance_layout = QVBoxLayout(appearance)
        appearance_layout.setContentsMargins(T.PAD_CARD, T.PAD_CARD,
                                             T.PAD_CARD, T.PAD_CARD)
        appearance_layout.setSpacing(T.S1)
        section = QLabel("A P P E A R A N C E")
        section.setObjectName("micro")
        appearance_layout.addWidget(section)
        status = QLabel(blur_status or "blur: not attempted")
        status.setObjectName("rowMeta")
        appearance_layout.addWidget(status)
        explain = QLabel(
            "Blur is drawn by the compositor, never by Kairo. Without it the "
            "window is simply translucent, which is the normal appearance "
            "everywhere except a KDE Wayland session offering "
            "ext-background-effect-v1.")
        explain.setObjectName("meta")
        explain.setWordWrap(True)
        appearance_layout.addWidget(explain)
        layout.addWidget(appearance)

        layout.addStretch(1)
        about = QLabel(f"{APP_NAME} {__version__}  ·  {TAGLINE}\n{APP_ID}")
        about.setObjectName("meta")
        layout.addWidget(about)

    def refresh(self) -> None:
        return None
