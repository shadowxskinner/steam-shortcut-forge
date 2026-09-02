"""The library list, artwork browser and guarded apply/reset actions."""

from __future__ import annotations

import math
import time

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QSizePolicy,
                               QLabel, QLineEdit, QMessageBox, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from kairo import actions, appsource
from kairo.artwork.local import SOURCE_ID as LOCAL_SOURCE_ID

from kairo.qt import images
from kairo.qt import theme as Q
from kairo.qt import work
from kairo.qt.widgets import ArtworkTile, EntryRow, IconWell, Pills
from kairo.tasks import ActivityTokens
from kairo.ui import theme as T

FILTERS = {"All": "all", "Customized": "with", "Untouched": "without"}
SEARCH_DEBOUNCE_MS = 250
ACTIVITY_ARTWORK = "artwork"
ACTIVITY_APPLY = "apply"
ACTIVITY_SCAN = "scan"
ACTIVITY_ROWS = "rows"
ACTIVITY_DPR = "dpr"
ACTIVITY_SOURCES = "sources"

#: The resting tooltip on the artwork query. Replaced by the query
#: itself when the text is wider than the field.
QUERY_HINT = ("Type a different title and press Enter to search "
              "every source")

#: Prepared images are handed over in groups rather than one at a time. One
#: signal per icon made a page of rows fill in a visible trickle — 120
#: separate paints over 86ms, which reads as the window assembling itself in
#: front of you. A group is flushed when it reaches this many or when this
#: long has passed, whichever comes first, so a fast disk delivers a page in
#: one go and a slow one still shows progress.
BATCH_SIZE = 24
BATCH_MS = 45

#: How many rows exist at once. A row is five widgets, so a 2000-game library
#: built the lot and spent 1.8 seconds and 225MB doing it — every time the
#: search box was cleared. Rows are built in pages instead and the next page
#: arrives as you reach the bottom, which keeps the cost proportional to what
#: is on screen rather than to the size of the library.
ROW_PAGE = 120

#: Raster artwork below this never fills a tile without being enlarged, so it
#: is not offered. Scalable SVG artwork is judged by whether Qt can render it,
#: not by its nominal canvas size.
MIN_USABLE_EDGE = 128


def query_for(source, base, typed: str, seeded: str):
    """What to ask one source, given what is in the search box. None to skip.

    A module-level function because this decision was the entire bug and it
    used to be three lines inside a closure inside a method, where no test
    could see it. What it got wrong: ``typed`` was consumed only by sources
    declaring ``needs_query``. SteamGridDB does not declare it — it is keyed
    on an appid — so it never saw a character the user typed, and since it
    supplies nearly every result for a game, the search box did nothing.

    Editing the term overrides the identifier; leaving it alone does not.
    That distinction matters: the box arrives pre-filled with the entry's own
    name, so treating the seeded text as a search would silently downgrade
    every Steam game from an exact appid match to a title guess.
    """
    if source.needs_query:
        term = typed or (base.icon_name if source.id == "theme" else base.text)
        return base.with_text(term) if term else None
    if typed and typed.casefold() != seeded.strip().casefold():
        return base.with_text(typed, keep_id=False)
    return base


class LibraryPane(QWidget):
    """One provider's entries, and the artwork workspace for the selected one."""

    changed = Signal()
    status = Signal(str)
    rescan_requested = Signal()

    def __init__(self, provider, context, parent=None):
        super().__init__(parent)
        self.provider = provider
        self.ctx = context
        self.tokens: ActivityTokens = context.tokens

        self.entries = []
        self.rows: list[EntryRow] = []
        self._filtered: list = []
        self._shown = 0
        self.visible = 0
        self.selected: EntryRow | None = None
        self.proposed = None
        self.tiles: list[ArtworkTile] = []
        self._tile_at: dict[int, ArtworkTile] = {}
        self.chosen_tile = None
        self._streamer = None
        self._row_streamer = None
        self._icon_generation = 0
        self._preview_generation = 0
        self._paint_ratio = 0.0
        self._paint_token = None
        self._layout_mode = "wide"
        # The selection is a catalogue fact; ``selected`` is only the
        # row currently drawing it. A page that happens not to include
        # the entry must not be able to forget which entry it is.
        self._selected_key = None
        # Read-only provenance metadata: which installation source each entry
        # came from. Never part of a key, a filename or a ledger identity.
        self._source_of: dict[str, str] = {}
        self._source_filter = appsource.ALL
        self._source_counts = {}
        self._restore_full_label = ""
        self._remove_full_label = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_list())
        layout.addWidget(self._build_workspace(), 1)

        # A scrollbar appearing after the tiles are seated narrows the
        # viewport they were measured against.
        bar = self.grid_scroll.verticalScrollBar()
        bar.rangeChanged.connect(lambda _lo, _hi: self._follow_grid_scrollbar())

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(lambda: self.refilter())

        self.rescan()

    # -- middle column -----------------------------------------------------

    def _build_list(self) -> QWidget:
        column = QWidget()
        self._list_column = column
        column.setObjectName("list")
        column.setFixedWidth(Q.W_LIST)
        layout = QVBoxLayout(column)
        self._list_layout = layout
        layout.setContentsMargins(Q.PAD_COLUMN, 0, Q.PAD_COLUMN, Q.PAD_COLUMN)
        layout.setSpacing(Q.GAP)

        head = QWidget()
        head.setFixedHeight(Q.H_HEADER)
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(T.S1, 0, T.S1, 0)
        title = QLabel(self.provider.label)
        title.setObjectName("pane")
        self.count = QLabel("0")
        self.count.setObjectName("count")
        head_layout.addWidget(title, 0, Qt.AlignVCenter)
        head_layout.addStretch(1)
        head_layout.addWidget(self.count, 0, Qt.AlignVCenter)
        layout.addWidget(head)

        self.search = QLineEdit()
        self.search.setPlaceholderText(f"Search {self.provider.noun}…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(
            lambda _text: self._search_timer.start(SEARCH_DEBOUNCE_MS))
        layout.addWidget(self.search)

        self.filters = Pills(list(FILTERS))
        self.filters.changed.connect(lambda _label: self.refilter())
        layout.addWidget(self.filters, 0, Qt.AlignLeft)

        # One destination, not five. Applications is a single list with a
        # quiet selector over it; splitting the sidebar per packaging format
        # would make the shape of the machine the shape of the navigation.
        # Named apart from sources(): that is the artwork-source ordering
        # this pane already has, and shadowing it with a widget silently
        # broke the merged artwork grid.
        self.origin_pills = Pills([])
        self.origin_pills.changed.connect(self._choose_source)
        self.origin_pills.setVisible(False)
        layout.addWidget(self.origin_pills, 0, Qt.AlignLeft)
        if self._classifies_sources():
            # Built once, with every bucket present from the start. Pills that
            # appear as a scan finishes move the list under the pointer.
            self._refresh_origin_pills()

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        self.rows_layout = QVBoxLayout(holder)
        self.rows_layout.setContentsMargins(0, 0, T.S2, 0)
        self.rows_layout.setSpacing(Q.GAP_ROW)
        self.rows_layout.addStretch(1)
        self.scroll.setWidget(holder)
        self.scroll.verticalScrollBar().valueChanged.connect(
            self._grow_if_near_bottom)
        layout.addSpacing(T.S1)
        layout.addWidget(self.scroll, 1)
        return column

    # -- right column ------------------------------------------------------

    def _build_workspace(self) -> QWidget:
        space = QWidget()
        self._workspace = space
        space.setObjectName("workspace")
        layout = QVBoxLayout(space)
        self._workspace_layout = layout
        layout.setContentsMargins(Q.PAD_PANE, 0, Q.PAD_PANE, Q.PAD_PANE)
        layout.setSpacing(Q.GAP_WIDE)

        header = QWidget()
        header.setFixedHeight(Q.H_HEADER)
        head = QHBoxLayout(header)
        self._header_layout = head
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(T.S2)
        # The icon belongs to the title, not to a labelled column beside a
        # second one. An App Store page does not caption its own artwork
        # "CURRENT" — it puts the icon next to the name and says what would
        # replace it only once something has been chosen.
        self.current_well = IconWell(Q.WELL_TITLE)
        head.addWidget(self.current_well, 0, Qt.AlignVCenter)
        head.addSpacing(Q.GAP)

        names = QVBoxLayout()
        names.setContentsMargins(0, 0, 0, 0)
        names.setSpacing(2)
        self.title = QLabel("")
        self.title.setObjectName("title")
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("subtitle")
        # Without the stretches the two labels split the band between them,
        # which pushes the title flush against the top edge of the window and
        # leaves the subtitle floating far below it. Stretched top and bottom,
        # both take their own height, centred in the band — on the same line
        # as the wordmark and the provider name beside them.
        names.addStretch(1)
        names.addWidget(self.title)
        names.addWidget(self.subtitle)
        names.addStretch(1)
        # A long game name must yield to the actions rather than run under
        # them. QLabel asks for its full text width and a QHBoxLayout grants
        # it, so without this a third button in the header simply overlapped
        # the title. Ignored lets the column shrink below that request; the
        # text itself is elided to whatever room is left.
        for label in (self.title, self.subtitle):
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        head.addLayout(names, 1)
        self.rescan_btn = QPushButton("Rescan")
        self.rescan_btn.setObjectName("secondary")
        # clicked carries a checked flag; a zero-argument Signal cannot take it.
        self.rescan_btn.clicked.connect(
            lambda _checked: self.rescan_requested.emit())
        # The header carries the selected icon, its title and Rescan. The
        # deep link to a provider's own launcher entry used to sit here as a
        # third button, in three different abbreviations depending on the
        # window width, competing with the title for the room the title
        # needed. Editing a launcher icon was never a second editor - it only
        # jumped to that entry under Applications, which is where the entry
        # already is. reveal_launcher() is still the mechanism; nothing in
        # the header duplicates it.
        self.rescan_btn.setFixedHeight(Q.H_BUTTON)
        head.addWidget(self.rescan_btn, 0, Qt.AlignVCenter)
        layout.addWidget(header)

        # -- the inspector -------------------------------------------------
        # One surface, three registers: what is about to change, the browser
        # you spend your time in, and the actions. Hairlines separate them;
        # the browser takes all the room left over, and the action bar is
        # anchored to the bottom of the surface rather than floating under it.
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)
        card_layout.addLayout(self._build_compare())
        card_layout.addWidget(self._divider())
        card_layout.addLayout(self._build_artwork_controls())
        card_layout.addWidget(self._build_grid(), 1)
        card_layout.addWidget(self._divider())
        card_layout.addLayout(self._build_actions())
        layout.addWidget(card, 1)
        self._update_actions()
        return space

    def _build_compare(self):
        """What would change, once something has been chosen.

        The current icon moved up beside the title, so this row is no longer
        a before-and-after pair — it is the proposal and nothing else, and it
        says nothing at all until there is one.
        """
        row = QHBoxLayout()
        self._compare_layout = row
        row.setContentsMargins(Q.PAD_CARD, Q.PAD_CARD, Q.PAD_CARD, Q.GAP)
        row.setSpacing(Q.GAP)
        caption = QLabel("PROPOSED")
        caption.setObjectName("micro")
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(T.S2)
        self.proposed_well = IconWell(Q.WELL_COMPARE)
        box.addWidget(caption)
        box.addWidget(self.proposed_well)
        row.addLayout(box)
        self.proposal = QLabel("Choose artwork below")
        self.proposal.setObjectName("meta")
        self.proposal.setWordWrap(True)
        row.addSpacing(Q.GAP)
        row.addWidget(self.proposal, 1, Qt.AlignVCenter)
        return row

    def _build_artwork_controls(self):
        row = QHBoxLayout()
        self._artwork_controls_layout = row
        row.setContentsMargins(Q.PAD_CARD, Q.GAP, Q.PAD_CARD, Q.GAP)
        row.setSpacing(Q.GAP)
        heading = QLabel("ARTWORK")
        heading.setObjectName("micro")
        row.addWidget(heading, 0, Qt.AlignVCenter)
        row.addSpacing(T.S1)
        row.addStretch(1)
        self._seeded = ""
        self._heading = ("", "")
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search artwork…")
        self.query.setToolTip(
            QUERY_HINT)
        self.query.setFixedWidth(Q.W_QUERY)
        self.query.setClearButtonEnabled(True)
        self.query.returnPressed.connect(self._load_artwork)
        # The clear button emits no returnPressed, so emptying the
        # field left the results of a search it no longer showed.
        self.query.textChanged.connect(self._query_cleared)
        row.addWidget(self.query, 0, Qt.AlignVCenter)
        return row

    def _build_grid(self) -> QWidget:
        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid_holder = QWidget()
        self.grid = QGridLayout(self.grid_holder)
        self.grid.setContentsMargins(Q.PAD_CARD - T.S2, 0, Q.PAD_CARD - T.S2, 0)
        self.grid.setSpacing(T.S1)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.grid_scroll.setWidget(self.grid_holder)
        return self.grid_scroll

    def _build_actions(self):
        row = QHBoxLayout()
        self._actions_layout = row
        row.setContentsMargins(Q.PAD_CARD, Q.GAP, Q.PAD_CARD, Q.GAP)
        row.setSpacing(T.S2)
        self.browse_btn = QPushButton("Browse local file…")
        self.browse_btn.setObjectName("secondary")
        # Left blank on purpose: _update_actions fills them from the writer,
        # so there is exactly one place these verbs can come from.
        self.restore_btn = QPushButton("")
        self.restore_btn.setObjectName("secondary")
        self.remove_btn = QPushButton("")
        self.remove_btn.setObjectName("danger")
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setObjectName("primary")
        for button in (self.browse_btn, self.restore_btn, self.remove_btn,
                       self.apply_btn):
            button.setFixedHeight(Q.H_BUTTON)
        self.browse_btn.clicked.connect(lambda _c: self._browse())
        self.restore_btn.clicked.connect(lambda _c: self._restore())
        self.remove_btn.clicked.connect(lambda _c: self._remove())
        self.apply_btn.clicked.connect(lambda _c: self._apply())
        # Apply needs something to apply; the rest need a selected entry.
        self.apply_btn.setEnabled(False)
        row.addWidget(self.browse_btn)
        row.addWidget(self.restore_btn)
        row.addWidget(self.remove_btn)
        row.addStretch(1)
        row.addWidget(self.apply_btn)
        return row

    def set_layout_mode(self, mode: str) -> None:
        """Compress secondary chrome while protecting the artwork workspace."""
        if mode not in ("wide", "compact", "narrow"):
            mode = "wide"
        self._layout_mode = mode
        widths = {
            "wide": Q.W_LIST,
            "compact": Q.W_LIST_COMPACT,
            "narrow": Q.W_LIST_NARROW,
        }
        self._list_column.setFixedWidth(widths[mode])

        narrow = mode == "narrow"
        pane_pad = 20 if narrow else Q.PAD_PANE
        card_pad = 16 if narrow else Q.PAD_CARD
        self._workspace_layout.setContentsMargins(
            pane_pad, 0, pane_pad, pane_pad)
        self._compare_layout.setContentsMargins(
            card_pad, card_pad, card_pad, Q.GAP)
        self._artwork_controls_layout.setContentsMargins(
            card_pad, Q.GAP, card_pad, Q.GAP)
        self._actions_layout.setContentsMargins(
            card_pad, Q.GAP, card_pad, Q.GAP)
        self.grid.setContentsMargins(max(0, card_pad - T.S2), 0,
                                    max(0, card_pad - T.S2), 0)

        query_width = {
            "wide": Q.W_QUERY,
            "compact": Q.W_QUERY_COMPACT,
            "narrow": Q.W_QUERY_NARROW,
        }
        self.query.setFixedWidth(query_width[mode])
        self._refresh_action_labels()
        self._elide_heading()
        if self.tiles:
            self._reflow_tiles()
        else:
            # Nothing to re-seat, but the next resize still compares against
            # this number and must not be measuring the previous mode.
            self._last_columns = self._columns()

    @staticmethod
    def _short_action_label(label: str) -> str:
        for verb in ("Reset", "Restore", "Remove"):
            if label.startswith(verb):
                return verb
        return label

    def _refresh_action_labels(self) -> None:
        compact = self._layout_mode != "wide"
        self.browse_btn.setText("Local file…" if compact
                                else "Browse local file…")
        self.browse_btn.setToolTip("Browse local file…" if compact else "")
        restore = self._restore_full_label
        remove = self._remove_full_label
        self.restore_btn.setText(
            self._short_action_label(restore) if compact else restore)
        self.remove_btn.setText(
            self._short_action_label(remove) if compact else remove)
        self.restore_btn.setToolTip(restore if compact else "")
        self.remove_btn.setToolTip(remove if compact else "")

    @staticmethod
    def _divider() -> QFrame:
        """A hairline, not a gap — it groups where a gap would separate."""
        line = QFrame()
        line.setObjectName("divider")
        line.setFixedHeight(1)
        return line

    def _update_actions(self) -> None:
        """Take the verbs from the writer, never from this file.

        A generated Steam entry has no earlier artwork to go back to, so its
        ordinary undo is Reset artwork and deleting the shortcut is a separate,
        destructive action. An override has the opposite shape: removing it is
        already non-destructive, so there is nothing for a second button to do.
        Hard-coding either label here is how the Tk build ended up describing a
        deletion as a restore.
        """
        try:
            writer = self.provider.writer()
        except Exception:
            return
        self._restore_full_label = writer.restore_label
        supports_remove = bool(getattr(writer, "supports_remove", False))
        self.remove_btn.setVisible(supports_remove)
        if supports_remove:
            self._remove_full_label = writer.remove_label
        self._refresh_action_labels()

    # -- writing -----------------------------------------------------------
    #
    # Every one of these goes through kairo.actions, which owns the marker
    # checks, the ledger and the atomic write. Nothing here touches a launcher
    # file directly, and nothing here decides whether an operation is allowed:
    # the writer does, and it raises with a reason when it is not.

    def _busy(self, busy: bool, verb: str = "") -> None:
        for button in (self.browse_btn, self.restore_btn, self.remove_btn,
                       self.apply_btn):
            button.setEnabled(not busy)
        if busy and verb:
            self.proposal.setText(f"{verb}…")

    def _finished(self, message: str) -> None:
        self._busy(False)
        self.proposal.setText(message)
        self.apply_btn.setEnabled(self.proposed is not None)
        self.rescan()
        self.changed.emit()

    def _failed(self, message: str) -> None:
        self._busy(False)
        self.apply_btn.setEnabled(self.proposed is not None)
        self.proposal.setText(message)

    def _apply(self) -> None:
        if self.selected is None or self.proposed is None:
            return
        entry, art = self.selected.entry, self.proposed
        source = self.ctx.sources.get(art.source_id)
        if source is None:
            self._failed("that artwork's source is no longer available")
            return
        token = self.tokens.start(ACTIVITY_APPLY)
        self._busy(True, "Applying")

        def run():
            return actions.fetch_and_apply(entry, self.provider, source, art,
                                           ledger=self.ctx.ledger, token=token)

        work.submit(run,
                    on_done=lambda _path: self._finished(f"applied to {entry.name}"),
                    on_failed=self._failed)

    def _restore(self) -> None:
        if self.selected is None:
            return
        entry = self.selected.entry
        self._busy(True, self.restore_btn.text())

        def run():
            actions.restore_entry(entry, self.provider, ledger=self.ctx.ledger)

        work.submit(run,
                    on_done=lambda _r: self._finished(f"restored {entry.name}"),
                    on_failed=self._failed)

    def _remove(self) -> None:
        """The destructive one, and the only action that asks first."""
        if self.selected is None:
            return
        entry = self.selected.entry
        confirm = QMessageBox(self)
        confirm.setIcon(QMessageBox.Warning)
        confirm.setWindowTitle(self.remove_btn.text())
        confirm.setText(f"{self.remove_btn.text()} for {entry.name}?")
        confirm.setInformativeText(
            "This deletes the launcher entry Kairo created. Artwork you "
            "applied to other applications is unaffected.")
        confirm.setStandardButtons(QMessageBox.Cancel | QMessageBox.Yes)
        confirm.setDefaultButton(QMessageBox.Cancel)
        if confirm.exec() != QMessageBox.Yes:
            return
        self._busy(True, self.remove_btn.text())

        def run():
            actions.remove_entry(entry, self.provider, ledger=self.ctx.ledger)

        work.submit(run,
                    on_done=lambda _r: self._finished(f"removed {entry.name}"),
                    on_failed=self._failed)

    def _browse(self) -> None:
        """A file on disk is just another artwork source."""
        if self.selected is None:
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, "Choose an icon", str(Path.home()),
            "Images (*.png *.svg *.ico *.xpm *.jpg *.jpeg);;All files (*)")
        if not path:
            return
        source = self.ctx.sources.get(LOCAL_SOURCE_ID)
        if source is None:
            self._failed("the local-file source is not registered")
            return
        art = source.artwork_for(Path(path))
        self._propose(art)

    # -- entries -----------------------------------------------------------

    def _set_heading(self, title: str, subtitle: str = "") -> None:
        """Remember the full text; show as much of it as there is room for."""
        self._heading = (title, subtitle)
        self._elide_heading()

    def _elide_heading(self) -> None:
        title, subtitle = getattr(self, "_heading", ("", ""))
        for label, text in ((self.title, title), (self.subtitle, subtitle)):
            room = max(0, label.width())
            if not room:
                label.setText(text)
                continue
            metrics = QFontMetrics(label.font())
            label.setText(metrics.elidedText(text, Qt.ElideRight, room))
            label.setToolTip(text if metrics.horizontalAdvance(text) > room
                             else "")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide_heading()
        if hasattr(self, "grid"):
            columns = self._columns()
            if columns != getattr(self, "_last_columns", None):
                # Recorded whether or not there is anything to reflow. Only
                # tracking it when tiles exist leaves the count describing
                # whatever geometry the grid last happened to be populated
                # at, so the first resize after a search skips its reflow.
                self._last_columns = columns
                if self.tiles:
                    self._reflow_tiles()

    def _customizable(self) -> bool:
        """Steam and emulators have an application of their own; games do not."""
        return hasattr(self.provider, "launcher_ids")

    def _launcher_id(self) -> str:
        """The basename of this provider's own launcher, or ""."""
        finder = getattr(self.provider, "launcher_path", None)
        if finder is None:
            return ""
        try:
            path = finder()
        except OSError:
            return ""
        return path.name if path is not None else ""

    def reveal_launcher(self, basename: str) -> bool:
        """Select the row for ``basename`` and scroll it into view.

        Matched on the launcher file, which is identity: two applications can
        share a display name, and the name shown is the one in the entry
        rather than anything Kairo controls.

        Returns False when the scan has not produced that entry yet; the
        caller retries once rows arrive rather than silently doing nothing.
        """
        if not basename:
            return False
        wanted = next((entry for entry in self.entries
                       if entry.payload.get("basename") == basename), None)
        if wanted is None:
            return False

        # Clear any filter hiding it, then page far enough to build its row.
        if self.search.text():
            self.search.clear()
        self.refilter()
        index = next((i for i, entry in enumerate(self._filtered)
                      if entry.key == wanted.key), None)
        if index is None:
            return False
        if index >= self._shown:
            self._shown = min(len(self._filtered),
                              ((index // ROW_PAGE) + 1) * ROW_PAGE)
            self._bind_rows(self._filtered[:self._shown])

        for row in self.rows[:self._shown]:
            if row.entry is not None and row.entry.key == wanted.key:
                self.select(row)
                self.scroll.ensureWidgetVisible(row, 0, Q.H_ROW)
                return True
        return False

    def rescan(self) -> None:
        """Scan off the UI thread.

        A Steam library is a handful of manifest files, but a ROM folder can
        be thousands of entries on a spinning disk, and doing that here froze
        the window for as long as it took. The token means a rescan triggered
        while one is already running discards the older result rather than
        letting two land in either order.
        """
        provider = self.provider
        # Every provider pane shares the application's ActivityTokens. A
        # provider-specific name lets the shell rescan all panes together;
        # the old global "scan" token cancelled every scan except the last.
        token = self.tokens.start(f"{ACTIVITY_SCAN}:{provider.id}")

        def run():
            return provider.scan() if provider.available() else []

        # Named apart from the artwork lookup's callbacks: two nested
        # functions called arrived/failed in one file is how a test ends up
        # asserting against the wrong one.
        def scanned(entries):
            if token.cancelled:
                return
            self.entries = entries
            if self._classifies_sources():
                self._classify_sources(
                    entries,
                    self.tokens.start(f"{ACTIVITY_SOURCES}:{provider.id}"))
            # A rescan may replace bytes at the same icon path. Search and
            # filter changes keep the generation, so stable rows retain their
            # already painted image; a real scan deliberately refreshes it.
            self._icon_generation += 1
            self.refilter(auto_select=True)

        def scan_failed(message):
            if token.cancelled:
                return
            self.entries = []
            self._icon_generation += 1
            self.refilter(auto_select=True)
            self.status.emit(f"{provider.label}: {message}")

        work.submit(run, on_done=scanned, on_failed=scan_failed)

    def _classifies_sources(self) -> bool:
        """Only the desktop-entry provider has an installation source."""
        return bool(getattr(self.provider, "classifies_sources", False))

    def source_of(self, entry) -> str:
        """The bucket an entry belongs to; Local until proven otherwise."""
        return self._source_of.get(entry.key, appsource.LOCAL)

    def _refresh_origin_pills(self) -> None:
        tally = self._source_counts
        labels = [appsource.label_for(bucket, tally)
                  for bucket, _name in appsource.LABELS]
        self._source_labels = dict(zip(labels,
                                       [b for b, _n in appsource.LABELS]))
        chosen = next((label for label, bucket in self._source_labels.items()
                       if bucket == self._source_filter), labels[0])
        self.origin_pills.set_values(labels)
        self.origin_pills.set_value(chosen, notify=False)
        self.origin_pills.setVisible(True)

    def _choose_source(self, label: str) -> None:
        bucket = getattr(self, "_source_labels", {}).get(label, appsource.ALL)
        if bucket == self._source_filter:
            return
        self._source_filter = bucket
        # The query and the selection are the person's, not the filter's.
        # refilter() restores the selected entry by key when it survives, and
        # empties the inspector deliberately when it does not.
        self.refilter()

    def _classify_sources(self, entries, token) -> None:
        """Work out provenance once per scan, off the GUI thread.

        Batched inside appsource: one package query for the whole list rather
        than one per row, so this costs the same whether the pane is repainted
        once or a hundred times.
        """
        wanted = [(entry.key, entry.payload.get("source", ""))
                  for entry in entries if entry.payload.get("source")]
        if not wanted:
            self._source_of = {}
            self._source_counts = appsource.counts([])
            self._refresh_origin_pills()
            return

        def run():
            mapping = appsource.classify([path for _key, path in wanted])
            return {key: mapping.get(path, appsource.LOCAL)
                    for key, path in wanted}

        def arrived(mapping):
            # A rescan or a provider switch during classification makes this
            # answer describe a list that is no longer on screen.
            if token.cancelled or not self.tokens.is_current(
                    f"{ACTIVITY_SOURCES}:{self.provider.id}", token):
                return
            self._source_of = mapping
            self._source_counts = appsource.counts(mapping.values())
            self._refresh_origin_pills()
            if self._source_filter != appsource.ALL:
                self.refilter()

        work.submit(run, on_done=arrived, on_failed=lambda _message: None)

    def visible_entries(self):
        term = self.search.text().strip().lower()
        mode = FILTERS.get(self.filters.value(), "all")
        entries = self.entries
        if self._source_filter != appsource.ALL and self._classifies_sources():
            entries = [e for e in entries
                       if self.source_of(e) == self._source_filter]
        if term:
            entries = [e for e in entries if term in e.name.lower()]
        if mode == "with":
            entries = [e for e in entries if e.customized]
        elif mode == "without":
            entries = [e for e in entries if not e.customized]
        return entries

    def refilter(self, auto_select: bool = False) -> None:
        entries = self.visible_entries()
        previous = (self.selected.entry.key if self.selected
                    else self._selected_key)
        self._filtered = entries
        self._shown = min(len(entries), max(ROW_PAGE, self._shown_floor()))
        self._bind_rows(entries[:self._shown])
        self.visible = len(entries)
        self.selected = None
        self.count.setText(str(len(entries)))

        if previous is not None:
            for row in self.rows[:self._shown]:
                if row.entry.key == previous:
                    self.select(row, load=False)
                    break
        if self.selected is None:
            if auto_select and entries:
                self.select(self.rows[0])
            else:
                self._empty_workspace()
        self.changed.emit()

    def _catalogue_has(self, key: str) -> bool:
        """Whether any entry with this key still exists to be selected."""
        for pool in (self._filtered, self.entries):
            for entry in pool:
                if entry.key == key:
                    return True
        return False

    def _shown_floor(self) -> int:
        """Keep at least a viewport's worth, however short the viewport is."""
        try:
            height = self.scroll.viewport().height()
        except Exception:
            return ROW_PAGE
        return max(1, height // max(1, Q.H_ROW + Q.GAP_ROW) + 4)

    def _bind_rows(self, entries) -> None:
        """Materialise rows now; decode their icons on one pool worker."""
        token = self.tokens.start(f"{ACTIVITY_ROWS}:{self.provider.id}")
        selected_key = self._selected_key
        if selected_key is None and self.selected is not None \
                and self.selected.entry is not None:
            selected_key = self.selected.entry.key
        restored = None
        while len(self.rows) < len(entries):
            row = EntryRow(self.grid_holder)
            row.clicked.connect(self.select)
            self.rows.append(row)
            self.rows_layout.insertWidget(len(self.rows) - 1, row)
        pending = []
        for index, entry in enumerate(entries):
            row = self.rows[index]
            needs_icon = row.bind(entry, defer_icon=True,
                                  icon_generation=self._icon_generation)
            if needs_icon:
                pending.append((index, entry.current_icon, entry.key,
                                self._icon_generation))
            is_selected = entry.key == selected_key
            row.set_selected(is_selected)
            if is_selected:
                restored = row
            row.setVisible(True)
        for row in self.rows[len(entries):]:
            row.setVisible(False)
        if selected_key is not None:
            self.selected = restored
            if restored is None and not self._catalogue_has(selected_key):
                # Genuinely gone — filtered away entirely, or removed by a
                # rescan. Only then is the selection itself over. Being off
                # the current page is not the same thing, and treating it as
                # such silently dropped the selection on every DPR refresh
                # that happened while the entry sat below the fold.
                self._selected_key = None
        if pending:
            self._stream_row_icons(pending, token)

    def _stream_row_icons(self, pending, token) -> None:
        """Prepare a page of row icons without blocking its first paint."""
        streamer = work.Streamer()
        streamer.item.connect(self._fill_row_icon)
        self._row_streamer = streamer
        # Read here, not inside pump: devicePixelRatioF() is a GUI-thread
        # question about which screen this widget is on, and a pool thread
        # has no business asking it.
        ratio = self.devicePixelRatioF()

        def pump():
            # Every row in a group has its own entry key, so the key travels
            # per item. Tagging the whole group with one — the last one seen —
            # made show_prepared_icon reject every other row in it, and a page
            # of 120 painted five icons.
            batch = []
            last = time.monotonic()

            def flush():
                if batch and not token.cancelled:
                    streamer.item.emit(0, list(batch), "")
                batch.clear()

            for index, path, key, generation in pending:
                if token.cancelled:
                    return
                image = images.prepare(Q.WELL_ROW - 12, path=path,
                                       ratio=ratio)
                if token.cancelled:
                    return
                batch.append((index, image, key, generation))
                now = time.monotonic()
                if len(batch) >= BATCH_SIZE or (now - last) * 1000 >= BATCH_MS:
                    flush()
                    last = now
            flush()

        work.submit(pump)

    def _fill_row_icon(self, _index: int, payload: object, _key: str) -> None:
        """Paint a whole group, so a page fills in waves rather than drips."""
        for index, image, key, generation in payload:
            if 0 <= index < len(self.rows):
                row = self.rows[index]
                accepted = row.show_prepared_icon(image, key, generation)
                if accepted and self.selected is row:
                    # Not `image`: that was prepared for a WELL_ROW row and is
                    # 32 logical points, while this well is WELL_TITLE and
                    # renders at 52. Reusing it shrank the title icon to 38%
                    # of its area every time a page filled.
                    self._refresh_current_well(key)

    def _refresh_current_well(self, key: str) -> None:
        """Re-render the title icon at this well's size, off the GUI thread.

        The row's image is the wrong size and the well's own ``show_path``
        would decode on the GUI thread, so neither is usable here. One job per
        accepted batch, and only for the row that is actually selected.
        """
        row = self.selected
        if row is None or row.entry is None or row.entry.key != key:
            return
        path = row.entry.current_icon
        if not path:
            self.current_well.show_placeholder("—")
            return
        size = Q.WELL_TITLE - 12
        ratio = self.devicePixelRatioF()

        def render():
            return images.prepare(size, path=path, ratio=ratio)

        def arrived(image):
            current = self.selected
            if (current is not None and current.entry is not None
                    and current.entry.key == key):
                self.current_well.show_image(image, "—")

        work.submit(render, on_done=arrived, on_failed=lambda _message: None)

    def _show_proposal(self, raw, art) -> None:
        """Draw the proposed artwork at the compare well's size.

        The bytes are already in hand — this never re-enters a source — but
        they still have to be prepared for *this* well rather than borrowed
        from the tile, and prepared off the GUI thread like everything else.
        """
        if raw is None:
            return
        size = Q.WELL_COMPARE - 12
        ratio = self.devicePixelRatioF()

        def render():
            return images.prepare(size, data=raw, ratio=ratio)

        def arrived(image):
            if self.proposed is art:
                self.proposed_well.show_image(image)

        work.submit(render, on_done=arrived, on_failed=lambda _message: None)

    def _grow_if_near_bottom(self, value: int) -> None:
        """Add the next page as the end of the built rows comes into view."""
        bar = self.scroll.verticalScrollBar()
        if bar.maximum() - value > Q.H_ROW * 3:
            return
        if self._shown >= len(self._filtered):
            return
        keep = self.selected.entry.key if self.selected else None
        self._shown = min(len(self._filtered), self._shown + ROW_PAGE)
        self._bind_rows(self._filtered[:self._shown])
        if keep is not None:
            for row in self.rows[:self._shown]:
                if row.entry is not None and row.entry.key == keep:
                    row.set_selected(True)
                    self.selected = row
                    break

    def customized_count(self) -> int:
        return sum(1 for entry in self.entries if entry.customized)

    def select(self, row: EntryRow, load: bool = True) -> None:
        if self.selected is not None:
            self.selected.set_selected(False)
        row.set_selected(True)
        self.selected = row
        self._selected_key = row.entry.key if row.entry is not None else None

        entry = row.entry
        # Elided to the room actually available, not to a fixed
        # character count that cannot know how wide the header is.
        self._set_heading(entry.name)
        # entry.subtitle is a Steam appid or a .desktop basename for two
        # providers out of three. The artwork count replaces it once a
        # search lands; until then the title stands alone.
        self.current_well.show_path(entry.current_icon, "—")
        self._clear_proposal()
        self._update_actions()
        if load:
            self._seed_query()
            self._load_artwork()

    def _empty_workspace(self) -> None:
        term = self.search.text().strip()
        if self.entries:
            heading = "No matches"
            note = (f"Nothing here matches “{term}”." if term
                    else "Nothing matches the current filter.")
        else:
            heading = f"No {self.provider.noun} found"
            # A provider that knows why it is empty should say so. An
            # emulator pointed at the wrong folder, or at an executable that
            # is not there, otherwise shows a blank list and no explanation —
            # the same failure the setup form used to have.
            reasons = []
            try:
                reasons = list(self.provider.problems())
            except AttributeError:
                pass
            except Exception:
                reasons = []
            if reasons:
                note = "\n".join(reasons) + "\n\nFix this under Settings."
            else:
                note = (f"Kairo found no {self.provider.noun} for "
                        f"{self.provider.label} on this machine.")
        self._set_heading(heading)
        self.current_well.show_placeholder("—")
        self._clear_grid()
        self._grid_note(note)

    # -- sources -----------------------------------------------------------

    def sources(self):
        """Every browsable source, best first.

        Ordered by the provider's own declared preference rather than by
        registration, so SteamGridDB leads for games and icon themes lead for
        applications — the same order automatic matching already trusts.
        """
        available = self.ctx.sources.browsable_for(self.provider.id,
                                                   self.ctx.config)
        preference = list(getattr(self.provider, "auto_match_sources", ()))

        def rank(source):
            return (preference.index(source.id) if source.id in preference
                    else len(preference))

        return sorted(available, key=rank)


    def _update_query_tooltip(self) -> None:
        """Show the whole query when the field is too narrow to hold it."""
        text = self.query.text()
        metrics = QFontMetrics(self.query.font())
        room = max(0, self.query.width() - 12)
        self.query.setToolTip(
            text if text and metrics.horizontalAdvance(text) > room
            else QUERY_HINT)

    def _seed_query(self) -> None:
        """One search box, over every source rather than some of them.

        It used to be hidden unless a source declared ``needs_query``, and its
        text used only by those sources. For a Steam game that meant a box
        that appeared, arrived pre-filled with the game's own name, and then
        changed nothing when you edited it: SteamGridDB supplies nearly all
        the results and was never shown a word of it.
        """
        if self.selected is None or not self.sources():
            self.query.setVisible(False)
            self._seeded = ""
            return
        self._seeded = self.provider.artwork_query(self.selected.entry).text
        self.query.setVisible(True)
        blocked = self.query.blockSignals(True)
        self.query.setText(self._seeded)
        # setText leaves the cursor at the end, and a QLineEdit scrolls to
        # keep the cursor visible - so a query longer than the field opened
        # showing its tail: "ed network configuration". Only reposition when
        # the box is not being typed in; taking the cursor away from someone
        # mid-edit is worse than the tail.
        if not self.query.hasFocus():
            self.query.setCursorPosition(0)
            self.query.deselect()
        self.query.blockSignals(blocked)
        self._update_query_tooltip()

    def _query_cleared(self, text: str) -> None:
        if not text.strip() and self._seeded:
            self._load_artwork()

    def _clear_grid(self) -> None:
        # Any retained-image preparation belongs to the grid being removed.
        # It must not be allowed to land in a later grid whose indexes happen
        # to match.
        self.tokens.cancel(f"{ACTIVITY_DPR}:{self.provider.id}")
        self._preview_generation += 1
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # deleteLater only runs when control returns to the event
                # loop, so an old tile keeps painting over the new grid until
                # then. Unparenting first takes it off screen immediately.
                widget.setParent(None)
                widget.deleteLater()
        self.tiles.clear()
        self._tile_at.clear()
        self.chosen_tile = None

    def _grid_note(self, text: str) -> None:
        """Centred, because the browser is the largest region on screen.

        Left in the top corner of an otherwise empty rectangle, a status line
        reads as something that failed to load rather than as a state. The
        grid's own alignment wins over a per-item one, so it is set here and
        put back when tiles arrive.
        """
        label = QLabel(text)
        label.setObjectName("empty")
        label.setAlignment(Qt.AlignCenter)
        self.grid.setAlignment(Qt.AlignCenter)
        self.grid.addWidget(label, 0, 0)

    def _load_artwork(self) -> None:
        self._clear_grid()
        # Starting the token before the early exits also cancels an older
        # in-flight search when the selection becomes unavailable.
        token = self.tokens.start(ACTIVITY_ARTWORK)
        if self.selected is None:
            return
        entry = self.selected.entry
        sources = self.sources()
        if not sources:
            self._grid_note("No online source has artwork for this one.")
            return

        base = self.provider.artwork_query(entry)
        typed = self.query.text().strip()
        self._grid_note("Looking for artwork…")
        key = entry.key

        def search():
            """Ask every source, in preference order, on one worker.

            A source that fails or is unreachable contributes nothing and
            costs the others nothing; the alternative was a tab that had to
            be found and clicked before its results existed at all.
            """
            found = []
            failures = 0
            asked = 0
            for source in sources:
                if token.cancelled:
                    return found, failures, asked
                query = query_for(source, base, typed, self._seeded)
                if query is None:
                    continue
                asked += 1
                try:
                    found.extend((art, source) for art in source.find(query))
                except Exception:
                    failures += 1   # one source down is not an empty library
            return found, failures, asked

        def arrived(outcome):
            results, failures, asked = outcome
            if token.cancelled or self.selected is None:
                return
            if self.selected.entry.key != key:
                return
            self._clear_grid()
            if not results:
                # Every source failing is not the same as this game having no
                # artwork, and telling someone to try a different search when
                # their network is down sends them the wrong way entirely.
                if asked and failures == asked:
                    self._grid_note("Could not reach any artwork source.\n"
                                    "Check your connection and try again.")
                else:
                    self._grid_note(f"Nothing found for {entry.name}.\n"
                                    "Try a different search.")
                return
            self._set_heading(self._heading[0],
                              f"{len(results)} artwork options")
            arts = [art for art, _source in results]
            self._build_tiles(arts, [source.label for _art, source in results])
            self._stream_previews(results, token, key)

        def failed(message):
            if token.cancelled:
                return
            self._grid_note(str(message))

        work.submit(search, on_done=arrived, on_failed=failed)

    def _columns(self) -> int:
        """How many whole tiles fit across the artwork viewport.

        Two things were missing and both clip the right-hand column. The
        grid carries its own left and right contents margins, which are not
        available to tiles; and n columns need n-1 gaps, not n, so dividing
        by (tile + spacing) asks for one gap too many and then spends it on
        an extra column. Measured across 900-1499px, 34 window widths put
        the last column 1-10px past the viewport edge - every one of them a
        width where the viewport was just over a multiple of the pitch.

        Logical pixels throughout: device pixel ratio decides how an image is
        decoded, never how many of them fit on a row.
        """
        margins = self.grid.contentsMargins()
        spacing = max(0, self.grid.horizontalSpacing())
        usable = (self.grid_scroll.viewport().width()
                  - margins.left() - margins.right())
        pitch = ArtworkTile.WIDTH + spacing
        return max(1, (usable + spacing) // pitch)

    def _build_tiles(self, results, origins=None) -> None:
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        columns = self._columns()
        # Previews arrive by their index in `results`, and tiles get dropped
        # as they arrive, so position in self.tiles stops matching almost
        # immediately. Keyed lookup instead: drop one tile and the rest still
        # receive their own image.
        self._tile_at = {}
        for index, art in enumerate(results):
            origin = origins[index] if origins and index < len(origins) else ""
            tile = ArtworkTile(art, self.grid_holder, origin=origin)
            tile.picked.connect(self._propose)
            self.grid.addWidget(tile, index // columns, index % columns)
            self.tiles.append(tile)
            self._tile_at[index] = tile

    def _stream_previews(self, results, token, key) -> None:
        """Fetch each preview on a pool thread, painting them as they land.

        The streamer is held on the instance so it outlives this call; a signal
        whose sender has been collected delivers nothing.
        """
        streamer = work.Streamer()
        streamer.item.connect(self._fill_tile)
        self._streamer = streamer
        ratio = self.devicePixelRatioF()
        generation = self._preview_generation

        def pump():
            batch = []
            last = time.monotonic()

            def flush():
                # The entry key alone is not enough: changing the query keeps
                # the same selected entry. The token says which request asked.
                if batch and not token.cancelled:
                    streamer.item.emit(
                        0, ((list(batch), generation), token), key)
                batch.clear()

            for index, (art, source) in enumerate(results):
                if token.cancelled:
                    return
                raw = None
                try:
                    raw = source.preview(art)
                    data = images.prepare(Q.TILE - 12, data=raw,
                                          min_edge=MIN_USABLE_EDGE,
                                          ratio=ratio)
                except Exception:
                    data = None         # say so, rather than leaving a blank
                    raw = None
                if token.cancelled:
                    return
                # The undecoded bytes travel with the image. They are what
                # lets choosing this tile, and a change of screen, avoid
                # asking the source for the same artwork twice.
                batch.append((index, data, raw))
                now = time.monotonic()
                if len(batch) >= BATCH_SIZE or (now - last) * 1000 >= BATCH_MS:
                    flush()
                    last = now
            flush()

        work.submit(pump)

    def _fill_tile(self, _index: int, payload: object, key: str) -> None:
        body, token = payload
        batch, generation = body
        if token.cancelled:
            return
        if self.selected is None or self.selected.entry.key != key:
            return
        if generation != self._preview_generation:
            # These bytes still belong to the current artwork request, but
            # their image was prepared for the screen we just left. Retain
            # the download and re-prepare it off-thread at the current ratio;
            # never flash the stale image and never ask the source again.
            pending = []
            doomed = []
            for index, _image, raw in batch:
                tile = self._tile_at.get(index)
                if tile is None:
                    continue
                if raw is None:
                    doomed.append(tile)
                    continue
                tile.preview_data = raw
                pending.append((index, raw))
            for tile in doomed:
                self._drop_tile(tile, reflow=False)
            if doomed:
                self._reflow_tiles()
            if pending:
                self._prepare_retained_tiles(pending, token, key)
            return
        # Drops are collected and the grid re-seated once. Dropping inside
        # the loop re-seated every surviving tile per drop, so a group where
        # nothing was usable cost one reflow per tile.
        doomed = []
        for index, data, raw in batch:
            tile = self._tile_at.get(index)
            if tile is None:
                continue
            # data is None when the preview could not be fetched at all.
            # Either way there is nothing to show, and an empty tile is worse
            # than none.
            if data is None:
                doomed.append(tile)
                continue
            tile.set_image(data, data=raw)
            if (tile is self.chosen_tile and self.proposed is tile.art):
                # `data` was prepared for a TILE and is 104 logical points;
                # this well is WELL_COMPARE and renders at 52, with a fixed
                # 64px frame that centre-cropped the difference. Rebuild from
                # the bytes we already hold, at this well's own size.
                self._show_proposal(raw, tile.art)
        for tile in doomed:
            self._drop_tile(tile, reflow=False)
        if doomed:
            self._reflow_tiles()

    def _prepare_retained_tiles(self, pending, token, key: str) -> None:
        """Rebuild downloaded previews for the current screen off-thread."""
        pending = list(pending)
        generation = self._preview_generation
        ratio = self._paint_ratio
        paint_token = self._paint_token
        if not pending or paint_token is None or paint_token.cancelled:
            return

        def prepare_batch():
            batch = []
            for index, raw in pending:
                if token.cancelled or paint_token.cancelled:
                    return []
                image = images.prepare(Q.TILE - 12, data=raw,
                                       min_edge=MIN_USABLE_EDGE,
                                       ratio=ratio)
                batch.append((index, image, raw))
            return batch

        def arrived(batch):
            if batch and not token.cancelled and not paint_token.cancelled:
                self._fill_tile(0, ((batch, generation), token), key)

        work.submit(prepare_batch, on_done=arrived,
                    on_failed=lambda _message: None)

    def _drop_tile(self, tile, *, reflow: bool = True) -> None:
        """Remove a tile and close the hole it leaves behind.

        ``reflow`` is deferred when several are dropped together, so the grid
        is re-seated once rather than once per tile.
        """
        if tile not in self.tiles:
            return
        if tile is self.chosen_tile:
            self._clear_proposal()
        self.tiles.remove(tile)
        for index, known in list(self._tile_at.items()):
            if known is tile:
                del self._tile_at[index]
        self.grid.removeWidget(tile)
        tile.setParent(None)
        tile.deleteLater()
        if reflow:
            self._reflow_tiles()

    def _follow_grid_scrollbar(self) -> None:
        """A scrollbar appearing narrows the viewport under a seated grid.

        Tiles are laid out, the grid becomes taller than the viewport, Qt
        adds a vertical scrollbar, and the width every column was measured
        against silently shrinks. Nothing else recomputes at that moment.
        """
        if not self.tiles:
            return
        if self._columns() != getattr(self, "_last_columns", None):
            self._reflow_tiles()

    def _reflow_tiles(self) -> None:
        """Re-seat the survivors so the grid has no gaps.

        This is the one place that acts on the column count, so it is the one
        place that records it. Reflowing from set_layout_mode without writing
        the count down left resizeEvent comparing against the geometry of the
        previous mode and skipping the next real reflow.
        """
        columns = self._columns()
        self._last_columns = columns
        for position, tile in enumerate(self.tiles):
            self.grid.removeWidget(tile)
            self.grid.addWidget(tile, position // columns, position % columns)
        if not self.tiles:
            self._grid_note("nothing here is large enough to use")

    # -- following the screen ----------------------------------------------

    def refresh_device_pixel_ratio(self) -> None:
        """Re-prepare what is on screen after the window changed displays.

        A window dragged from a 1x panel to a 2x one keeps every pixmap it
        already had, and each of those is now half the resolution the screen
        wants. Qt does not redecode anything on its own; the ratio simply
        changes underneath the images.

        Nothing here re-enters an artwork source. Every tile is rebuilt from
        the bytes it was already drawn from, so a lap of the desk costs no
        network at all - which is the reason those bytes are retained.
        """
        ratio = self.devicePixelRatioF()
        if math.isclose(ratio, self._paint_ratio, rel_tol=0.0,
                        abs_tol=0.001):
            return
        self._paint_ratio = ratio
        self._preview_generation += 1
        self._paint_token = self.tokens.start(
            f"{ACTIVITY_DPR}:{self.provider.id}")
        pending = [(index, tile.preview_data)
                   for index, tile in self._tile_at.items()
                   if tile.preview_data is not None]
        artwork_token = self.tokens.current(ACTIVITY_ARTWORK)
        key = (self.selected.entry.key
               if self.selected is not None else "")
        if pending and artwork_token is not None and key:
            self._prepare_retained_tiles(pending, artwork_token, key)
        # Rows read from files on disk, so they only need asking again. The
        # generation bump is what stops a page still in flight at the old
        # ratio from painting over the new one.
        self._icon_generation += 1
        self._bind_rows(self._filtered[:self._shown])

    def showEvent(self, event) -> None:
        # A widget has no screen until it is shown, so __init__ cannot know
        # the ratio and the first paint has to be corrected here.
        super().showEvent(event)
        self.refresh_device_pixel_ratio()

    # -- proposing ---------------------------------------------------------

    def _clear_proposal(self) -> None:
        self.proposed = None
        if self.chosen_tile is not None:
            try:
                self.chosen_tile.set_chosen(False)
            except RuntimeError:
                pass
            self.chosen_tile = None
        self.proposed_well.show_placeholder("—")
        self.proposal.setText("Choose artwork below")
        # Nothing proposed, nothing to apply — including when the tile that
        # was chosen has just been dropped for being too small.
        self.apply_btn.setEnabled(False)

    def _propose(self, art) -> None:
        if self.selected is None:
            return
        self._clear_proposal()
        self.proposed = art
        for tile in self.tiles:
            if tile.art is art:
                tile.set_chosen(True)
                self.chosen_tile = tile
                break
        label = art.label or art.name or "selected artwork"
        self.proposal.setText(f"{label}  ·  ready to apply")
        self.apply_btn.setEnabled(True)

        # The grid already downloaded, decoded and scaled this artwork to
        # draw the tile. Asking the source for it again was a second fetch of
        # bytes that were sitting in memory, and a decode back on the GUI
        # thread on top of it.
        retained = getattr(self.chosen_tile, "preview_data", None)
        if retained is not None:
            self._show_proposal(retained, art)
            return

        source = self.ctx.sources.get(art.source_id)
        if source is None:
            return

        def fetch():
            return source.preview(art)

        def arrived(data):
            if self.proposed is art:
                self._show_proposal(data, art)

        work.submit(fetch, on_done=arrived, on_failed=lambda _m: None)
