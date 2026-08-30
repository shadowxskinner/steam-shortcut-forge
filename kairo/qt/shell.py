"""The Kairo window in Qt.

Same three columns as the Tk shell and the same rules behind them: navigation
is built from the provider registry rather than hard-coded, so a provider
declaring ``group = "Emulators"`` reaches the sidebar without this file knowing
anything about emulators.

Read-only for this milestone. Scanning, browsing and previewing work against
the real backend; nothing writes to a launcher entry.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from kairo import APP_NAME, adoption, navmodel as nav
from kairo import config as config_store
from kairo import migration
from kairo.artwork.registry import default_registry as artwork_registry
from kairo.ledger import Ledger
from kairo.providers.registry import default_registry as provider_registry
from kairo.qt import theme as Q
from kairo.qt.blur import Blur
from kairo.qt.changes import ChangesPane
from kairo.qt.library import LibraryPane
from kairo.qt.settings import SettingsPane
from kairo.qt.widgets import NavButton
from kairo.tasks import ActivityTokens
from kairo.ui import theme as T


class Context:
    """What every pane needs, and nothing more."""

    def __init__(self, providers, sources, config, ledger, tokens):
        self.providers = providers
        self.sources = sources
        self.config = config
        self.ledger = ledger
        self.tokens = tokens


class KairoWindow(QMainWindow):
    def __init__(self, translucent: bool = True, want_blur: bool = True):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1420, 900)
        self.setMinimumSize(1120, 700)

        # Per-pixel alpha. Text and icons stay opaque; only the surfaces let
        # anything through. This is the thing Tk could not express.
        self.translucent = translucent
        if translucent:
            self.setAttribute(Qt.WA_TranslucentBackground, True)

        try:
            self.migration_report = migration.migrate_if_needed()
        except Exception as exc:                        # pragma: no cover
            self.migration_report = migration.MigrationReport(failures=[str(exc)])

        self.config_data = config_store.load()
        self.providers = provider_registry()
        self.sources = artwork_registry(self.config_data)
        self.ledger = Ledger().load()
        self.tokens = ActivityTokens()
        self.ctx = Context(self.providers, self.sources, self.config_data,
                           self.ledger, self.tokens)

        self.blur = Blur()
        self.want_blur = want_blur
        self.items = nav.build_items(self.providers)
        self.buttons: dict[str, NavButton] = {}
        self.panes: dict[str, QWidget] = {}

        self._build()
        self._adopt()

        first = next((item for item in self.items if item.provider is not None),
                     self.items[0])
        self._select(first.key)

        # After show(), so a surface exists to attach the blur region to.
        QTimer.singleShot(300, self._request_blur)

    # -- layout ------------------------------------------------------------

    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_nav())

        right = QWidget()
        right.setObjectName("workspace")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        bar = QHBoxLayout()
        bar.setContentsMargins(T.PAD_WINDOW, T.S4, T.PAD_WINDOW, 0)
        self.banner = QLabel("Shell milestone — read-only. Apply, Reset, "
                             "Remove and Restore are not wired yet.")
        self.banner.setObjectName("meta")
        bar.addWidget(self.banner)
        bar.addStretch(1)
        for label in ("Rescan", "Auto Match"):
            button = QPushButton(label)
            button.setObjectName("secondary" if label == "Rescan" else "primary")
            if label == "Rescan":
                button.clicked.connect(self.rescan)
            else:
                button.setEnabled(False)
                button.setToolTip("Not wired yet — this milestone is read-only")
            bar.addWidget(button)
        right_layout.addLayout(bar)

        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack, 1)

        self.status = QLabel("")
        self.status.setObjectName("meta")
        self.status.setContentsMargins(T.PAD_WINDOW, 0, T.PAD_WINDOW, T.S3)
        right_layout.addWidget(self.status)

        layout.addWidget(right, 1)

    def _build_nav(self) -> QWidget:
        column = QWidget()
        column.setObjectName("nav")
        column.setFixedWidth(T.W_NAV)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(T.S2, T.S6, T.S2, T.S4)
        layout.setSpacing(T.GAP_ROW)

        header = QHBoxLayout()
        header.setContentsMargins(T.S2, 0, T.S2, T.S5)
        logo = QLabel("KAIRO")
        logo.setObjectName("logo")
        sub = QLabel("回路")
        sub.setObjectName("logoSub")
        header.addWidget(logo)
        header.addWidget(sub)
        header.addStretch(1)
        layout.addLayout(header)

        current_group = None
        for item in self.items:
            if item.group != current_group:
                current_group = item.group
                heading = QLabel("  ".join(item.group.upper()))
                heading.setObjectName("micro")
                heading.setContentsMargins(T.S3, T.S4, 0, T.S1)
                layout.addWidget(heading)
            button = NavButton(item.key, item.label, nav.icon_for(item), column)
            button.clicked.connect(lambda _checked, key=item.key: self._select(key))
            layout.addWidget(button)
            self.buttons[item.key] = button

        layout.addStretch(1)
        return column

    # -- navigation --------------------------------------------------------

    def _pane_for(self, key: str) -> QWidget:
        pane = self.panes.get(key)
        if pane is not None:
            return pane
        if key == nav.VIEW_CHANGES:
            pane = ChangesPane(self.ctx)
        elif key == nav.VIEW_SETTINGS:
            pane = SettingsPane(self.ctx, blur_status=f"blur: {self.blur.status}")
        else:
            item = next(i for i in self.items if i.key == key)
            pane = LibraryPane(item.provider, self.ctx)
            pane.changed.connect(self._refresh_status)
            pane.status.connect(self.status.setText)
        self.panes[key] = pane
        self.stack.addWidget(pane)
        return pane

    def _select(self, key: str) -> None:
        pane = self._pane_for(key)
        self.stack.setCurrentWidget(pane)
        for button_key, button in self.buttons.items():
            button.setChecked(button_key == key)
        if hasattr(pane, "refresh"):
            pane.refresh()
        self._refresh_status()

    def _refresh_status(self) -> None:
        pane = self.stack.currentWidget()
        if isinstance(pane, LibraryPane):
            self.status.setText(
                f"{len(pane.entries)} {pane.provider.noun}  ·  "
                f"{pane.customized_count()} customized  ·  "
                f"{len(self.ledger)} change(s) recorded  ·  {self.blur.status}")
        else:
            self.status.setText(self.blur.status)

    def rescan(self) -> None:
        self.ledger.prune()
        self._adopt()
        for pane in self.panes.values():
            if isinstance(pane, LibraryPane):
                pane.rescan()
            elif hasattr(pane, "refresh"):
                pane.refresh()
        self._refresh_status()

    # -- startup -----------------------------------------------------------

    def _adopt(self) -> None:
        try:
            adopted = adoption.adopt_untracked(self.ledger, self.providers)
        except Exception:
            adopted = []
        if adopted:
            self.status.setText(f"Found {len(adopted)} existing "
                                "customization(s) and added them to Changes.")

    def _request_blur(self) -> None:
        if not self.translucent:
            self.blur.status = "blur skipped — running opaque"
        elif not self.want_blur:
            self.blur.status = "blur skipped — --no-blur"
        else:
            self.blur.apply(self)
        print(f"blur: {self.blur.status}")
        self._refresh_status()

    def closeEvent(self, event):
        self.tokens.cancel_all()
        super().closeEvent(event)


def stylesheet(alpha: float) -> str:
    return Q.stylesheet(alpha)
