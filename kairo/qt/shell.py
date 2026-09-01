"""The Kairo window in Qt.

Same three columns as the Tk shell and the same rules behind them: navigation
is built from the provider registry rather than hard-coded, so a provider
declaring ``group = "Emulators"`` reaches the sidebar without this file knowing
anything about emulators.

Read-only for this milestone. Scanning, browsing and previewing work against
the real backend; nothing writes to a launcher entry.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMainWindow,
                               QStackedWidget, QVBoxLayout,
                               QWidget)

from kairo import APP_NAME, adoption, navmodel as nav
from kairo import config as config_store
from kairo import migration
from kairo.artwork.registry import default_registry as artwork_registry
from kairo.ledger import Ledger
from kairo.providers.registry import default_registry as provider_registry
from kairo.qt import branding
from kairo.qt import theme as Q
from kairo.qt import work
from kairo.qt.blur import Blur
from kairo.qt.changes import ChangesPane
from kairo.qt.library import LibraryPane
from kairo.qt.settings import SettingsPane
from kairo.qt.widgets import NavButton
from kairo.tasks import ActivityTokens
from kairo.ui import theme as T

#: A close waits this long for artwork work to finish, then goes anyway.
CLOSE_DRAIN_SECONDS = 5.0


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
        self.providers = provider_registry(self.config_data)
        self.sources = artwork_registry(self.config_data)
        self.ledger = Ledger().load()
        self.tokens = ActivityTokens()
        self.ctx = Context(self.providers, self.sources, self.config_data,
                           self.ledger, self.tokens)

        self.blur = Blur()
        self._closing = False
        self._draining = False
        self._screen_bound = False
        #: A deep-link reveal waiting on the Applications scan.
        self._pending_reveal = None
        self._close_timer = QTimer(self)
        self._close_timer.setInterval(50)
        self._close_timer.timeout.connect(self._finish_close)
        self._close_deadline = 0.0
        self._blur_resize_timer = QTimer(self)
        self._blur_resize_timer.setSingleShot(True)
        self._blur_resize_timer.setInterval(80)
        self._blur_resize_timer.timeout.connect(self._update_blur_region)
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
        """One composition from the top edge down.

        The actions used to sit in a strip of their own above everything,
        which left the first eighty pixels of the window as an empty band and
        made the buttons look dropped in rather than placed. They now live in
        each pane's own header, so the top of the window is three columns of
        content beginning on the same line. There is no status strip: the
        window is the three columns and nothing else. Anything that needs
        saying appears where it happened - a scan failure in the entry list,
        a lookup failure in the artwork grid.
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
        # The mark carries the identity and the wordmark carries the name.
        # 回路 used to sit here as well; three elements in a sidebar built
        # around one-per-row was the busiest thing on screen, and the mark
        # says the same thing without needing a font that ships CJK.
        stamp = branding.mark(Q.MARK_SIZE)
        if not stamp.isNull():
            badge = QLabel()
            badge.setObjectName("badge")
            badge.setPixmap(stamp)
            badge.setFixedSize(Q.MARK_SIZE, Q.MARK_SIZE)
            header_layout.addWidget(badge, 0, Qt.AlignVCenter)
            header_layout.addSpacing(T.S2)

        logo = QLabel("KAIRO")
        logo.setObjectName("logo")
        header_layout.addWidget(logo, 0, Qt.AlignVCenter)
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
            logo = (getattr(item.provider, "nav_icon_names", None)
                    or getattr(item.provider, "nav_icon_name", "")
                    ) if item.provider else ""
            button = NavButton(item.key, item.label, nav.icon_for(item), column,
                               logo_name=logo)
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
            # A restore is a write like any other: the library panes are now
            # showing the wrong icon for that entry, and if the entry was
            # Steam's or an emulator's own launcher, so is the sidebar.
            pane.changed.connect(self._rescan_libraries)
            pane.changed.connect(self.refresh_nav_icons)
        elif key == nav.VIEW_SETTINGS:
            pane = SettingsPane(self.ctx, self._providers_changed)
        else:
            item = next(i for i in self.items if i.key == key)
            pane = LibraryPane(item.provider, self.ctx)
            pane.rescan_requested.connect(self.rescan)
            pane.customize_launcher.connect(self.open_launcher_in_applications)
            # A write in one pane changes what Changes has to show.
            pane.changed.connect(self._refresh_changes)
            # An apply or reset in Applications can be a change to Steam's or
            # an emulator's own launcher, so the sidebar re-reads on the same
            # signal that refreshes the history.
            pane.changed.connect(self.refresh_nav_icons)
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

    def _providers_changed(self) -> None:
        """Rebuild the sidebar after an emulator is added, edited or removed.

        Emulators are the only configuration that changes what destinations
        exist, and making the user restart to see a section they just created
        would be a poor way to find out it worked.
        """
        self.providers = provider_registry(self.config_data)
        self.items = nav.build_items(self.providers)
        current = next((k for k, b in self.buttons.items() if b.isChecked()),
                       None)
        for pane in self.panes.values():
            self.stack.removeWidget(pane)
            pane.deleteLater()
        self.panes.clear()
        self.buttons.clear()
        old_nav = self.centralWidget().layout().itemAt(0).itemAt(0).widget()
        body = self.centralWidget().layout().itemAt(0)
        body.removeWidget(old_nav)
        old_nav.setParent(None)
        old_nav.deleteLater()
        body.insertWidget(0, self._build_nav())
        keys = [item.key for item in self.items]
        self._select(current if current in keys else keys[0])

    def open_launcher_in_applications(self, basename: str) -> None:
        """Deep link: show this launcher's row in the Applications provider.

        Applications remains the only place artwork is chosen — nothing here
        applies or resets anything. It navigates, because an emulator's own
        launcher is otherwise one row among several hundred with nothing
        pointing at it.

        The Applications pane scans off the GUI thread, so the row may not
        exist for a moment after switching to it. The request is held and
        retried when rows arrive rather than quietly failing.
        """
        if not basename:
            return
        key = next((item.key for item in self.items
                    if item.provider is not None
                    and item.provider.id == "desktop"), None)
        if key is None:
            return
        self._select(key)
        pane = self.panes.get(key)
        if pane is None:
            return
        if not pane.reveal_launcher(basename):
            self._pending_reveal = (key, basename)
            QTimer.singleShot(120, self._retry_reveal)

    def _retry_reveal(self, attempts: int = 12) -> None:
        pending = getattr(self, "_pending_reveal", None)
        if not pending:
            return
        key, basename = pending
        pane = self.panes.get(key)
        if pane is not None and pane.reveal_launcher(basename):
            self._pending_reveal = None
            return
        if attempts <= 1:
            self._pending_reveal = None     # bounded: never retry forever
            return
        QTimer.singleShot(120, lambda: self._retry_reveal(attempts - 1))

    def refresh_nav_icons(self) -> None:
        """Re-read every provider's launcher icon and repaint just the glyphs.

        Customising Steam or an emulator through the Applications provider
        rewrites that launcher's Icon=, and this is what makes the sidebar
        agree without a restart. Only the pixmap changes: no pane is rebuilt,
        no button is recreated, and the current selection is untouched.

        Providers that share a launcher — two Dolphin libraries, say — read
        the same file and therefore land on the same logo by construction,
        rather than by anything being copied between them.
        """
        for item in self.items:
            button = self.buttons.get(item.key)
            provider = item.provider
            if button is None or provider is None:
                continue
            values = getattr(provider, "nav_icon_values", None)
            if values is None:
                continue
            try:
                button.set_logo_names(values())
            except OSError:
                # A launcher directory that cannot be read is not a reason to
                # leave the sidebar half-painted.
                continue

    def _rescan_libraries(self) -> None:
        """Re-read the providers after a write, without touching Changes.

        Separate from rescan(): that one also refreshes Changes, and calling
        it from Changes' own signal would have the pane rebuild itself in the
        middle of reporting what it just did.
        """
        for pane in self.panes.values():
            if isinstance(pane, LibraryPane):
                pane.rescan()

    def _follow_screen(self) -> None:
        """Tell every pane its device pixel ratio may have changed.

        Plasma runs mixed-DPI outputs happily, so dragging the window from a
        scaled laptop panel to an unscaled external one is an ordinary move.
        Qt re-reports the ratio but redecodes nothing, so without this every
        image on screen stays at the resolution of the display it was built
        for. The panes rebuild from artwork they already hold; no source is
        asked for anything again.
        """
        for pane in self.panes.values():
            if hasattr(pane, "refresh_device_pixel_ratio"):
                pane.refresh_device_pixel_ratio()

    def showEvent(self, event):
        # The window has no screen, and therefore no honest ratio, until it
        # is shown. This is also where a first paint at 1x gets corrected.
        super().showEvent(event)
        handle = self.windowHandle()
        if handle is not None and not self._screen_bound:
            self._screen_bound = True
            handle.screenChanged.connect(lambda _screen: self._follow_screen())
        self._follow_screen()

    def _refresh_changes(self) -> None:
        pane = self.panes.get(nav.VIEW_CHANGES)
        if pane is not None and hasattr(pane, "refresh"):
            pane.refresh()

    def rescan(self) -> None:
        self.ledger.prune()
        self._adopt()
        self.refresh_nav_icons()
        for pane in self.panes.values():
            if isinstance(pane, LibraryPane):
                pane.rescan()
            elif hasattr(pane, "refresh"):
                pane.refresh()

    # -- startup -----------------------------------------------------------

    def _adopt(self) -> None:
        # Silent by design: whatever adoption finds is listed under Changes,
        # which is a better place to read it than a line that scrolls away.
        try:
            adoption.adopt_untracked(self.ledger, self.providers)
        except Exception:
            pass

    def _request_blur(self) -> None:
        if self._closing:
            return
        if not self.translucent:
            self.blur.status = "blur skipped — running opaque"
        elif not self.want_blur:
            self.blur.status = "blur skipped — --no-blur"
        else:
            self.blur.apply(self)
        # Printed once for a terminal launch; the window never mentions it.
        print(f"blur: {self.blur.status}")

    def resizeEvent(self, event):
        """Keep the compositor region in step without flooding Wayland."""
        super().resizeEvent(event)
        if self.blur.active and not self._closing:
            self._blur_resize_timer.start()

    def _update_blur_region(self) -> None:
        if self.blur.active and not self._closing:
            self.blur.update(self)

    # -- appearance --------------------------------------------------------

    def apply_glass(self, glass) -> None:
        """Restyle the application. Kept for the launch flag, not for the UI.

        The sliders and preset shortcuts are gone: the values below are the
        design now, not a thing to tune at runtime.
        """
        self.glass = Q.resolve(glass)
        application = QApplication.instance()
        if application is not None:
            application.setStyleSheet(Q.stylesheet(self.glass))

    def closeEvent(self, event):
        self._closing = True
        self.tokens.cancel_all()
        if not work.is_idle():
            self._draining = True
            # Bounded: a window must always be closable. Waiting is a courtesy
            # to work in flight, not a condition of being allowed to quit.
            self._close_deadline = time.monotonic() + CLOSE_DRAIN_SECONDS
            self.hide()
            self._close_timer.start()
            event.ignore()
            return
        # Release the protocol object while Qt's wl_surface is still valid.
        self.blur.remove(self)
        super().closeEvent(event)

    def _finish_close(self) -> None:
        if not self._draining:
            return
        if work.is_idle() or time.monotonic() >= self._close_deadline:
            self._draining = False
            self._close_timer.stop()
            self.close()


def stylesheet(alpha: float) -> str:
    return Q.stylesheet(alpha)
