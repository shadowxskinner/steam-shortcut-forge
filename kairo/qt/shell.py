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
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMainWindow,
                               QPushButton, QStackedWidget, QVBoxLayout,
                               QWidget)

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
    def __init__(self, translucent: bool = True, want_blur: bool = True,
                 glass=None):
        super().__init__()
        self.glass = Q.resolve(glass)
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
        self._shortcuts: list = []

        self._build()
        self._install_shortcuts()
        self._adopt()

        first = next((item for item in self.items if item.provider is not None),
                     self.items[0])
        self._select(first.key)

        # After show(), so a surface exists to attach the blur region to.
        QTimer.singleShot(300, self._request_blur)

    # -- layout ------------------------------------------------------------

    def _build(self) -> None:
        """One composition from the top edge down.

        The actions used to sit in a strip of their own above everything,
        which left the first eighty pixels of the window as an empty band and
        made the buttons look dropped in rather than placed. They now live in
        each pane's own header, so the top of the window is three columns of
        content beginning on the same line, and the status text has moved to a
        footer spanning the whole width instead of stopping at the sidebar.
        """
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_nav())
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        outer.addLayout(body, 1)

        footer = QWidget()
        footer.setObjectName("footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(Q.PAD_COLUMN, T.S2, Q.PAD_PANE, T.S2)
        self.status = QLabel("")
        self.status.setObjectName("status")
        footer_layout.addWidget(self.status)
        footer_layout.addStretch(1)
        outer.addWidget(footer)

    def _build_nav(self) -> QWidget:
        column = QWidget()
        column.setObjectName("nav")
        column.setFixedWidth(Q.W_NAV)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(T.S2, 0, T.S2, Q.PAD_COLUMN)
        layout.setSpacing(1)

        # The header band every column uses, so the wordmark, the provider
        # name and the selected item's title all begin on one line.
        header = QWidget()
        header.setFixedHeight(Q.H_HEADER)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(T.S3, 0, T.S3, 0)
        header_layout.setSpacing(T.S2)
        logo = QLabel("KAIRO")
        logo.setObjectName("logo")
        sub = QLabel("回路")
        sub.setObjectName("logoSub")
        header_layout.addWidget(logo, 0, Qt.AlignVCenter)
        header_layout.addWidget(sub, 0, Qt.AlignVCenter)
        header_layout.addStretch(1)
        layout.addWidget(header)

        current_group = None
        for item in self.items:
            if item.group != current_group:
                current_group = item.group
                heading = QLabel(item.group.upper())
                heading.setObjectName("micro")
                heading.setContentsMargins(T.S3, Q.GAP_WIDE, 0, T.S2)
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
            pane = SettingsPane(self.ctx, blur_status=f"blur: {self.blur.status}",
                                glass=self.glass,
                                on_glass_change=self.apply_glass)
        else:
            item = next(i for i in self.items if i.key == key)
            pane = LibraryPane(item.provider, self.ctx)
            pane.changed.connect(self._refresh_status)
            pane.status.connect(self.status.setText)
            pane.rescan_requested.connect(self.rescan)
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
                f"{len(self.ledger)} change(s) recorded  ·  {self.blur.status}"
                f"  ·  read-only shell")
        else:
            self.status.setText(f"{self.blur.status}  ·  read-only shell")

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
        settings = self.panes.get(nav.VIEW_SETTINGS)
        if settings is not None and hasattr(settings, "set_blur_status"):
            settings.set_blur_status(f"blur: {self.blur.status}")
        self._refresh_status()

    # -- live tuning -------------------------------------------------------

    def _install_shortcuts(self) -> None:
        """Bind the tuning keys as real shortcuts.

        The previous attempt overrode keyPressEvent on the window, which fails
        twice over: a focused child - the search box, the entry list - consumes
        the event before the window sees it, and with Control held
        QKeyEvent.text() returns a control character rather than the digit, so
        even the branch that did run matched nothing.

        QShortcut with ApplicationShortcut context has neither problem: Qt
        matches the sequence regardless of which widget holds focus.
        """
        names = list(Q.PRESETS)
        for index, name in enumerate(names[:9], start=1):
            self._bind(f"Ctrl+{index}",
                       lambda key=name: self.apply_glass(Q.PRESETS[key]))

        for sequence in ("Ctrl+]", "Ctrl+=", "Ctrl++"):
            self._bind(sequence, lambda: self.nudge_glass(+0.02))
        for sequence in ("Ctrl+[", "Ctrl+-"):
            self._bind(sequence, lambda: self.nudge_glass(-0.02))

    def _bind(self, sequence: str, handler) -> None:
        shortcut = QShortcut(QKeySequence(sequence), self)
        shortcut.setContext(Qt.ApplicationShortcut)
        shortcut.activated.connect(handler)
        self._shortcuts.append(shortcut)

    def nudge_glass(self, delta: float) -> None:
        self.apply_glass(self.glass.shifted(delta))

    def apply_glass(self, glass) -> None:
        """Restyle, and say so everywhere the value is shown.

        A stylesheet swap, not a repaint loop - nothing here is periodic.
        """
        self.glass = Q.resolve(glass)
        application = QApplication.instance()
        if application is not None:
            application.setStyleSheet(Q.stylesheet(self.glass))

        settings = self.panes.get(nav.VIEW_SETTINGS)
        if settings is not None and hasattr(settings, "set_glass"):
            settings.set_glass(self.glass)

        self.status.setText(f"{self.glass.describe()}   ·   {self.blur.status}")

    def closeEvent(self, event):
        self.tokens.cancel_all()
        super().closeEvent(event)


def stylesheet(alpha: float) -> str:
    return Q.stylesheet(alpha)
