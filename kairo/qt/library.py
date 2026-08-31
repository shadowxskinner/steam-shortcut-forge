"""The middle and right columns.

Read-only for this milestone. Scanning, browsing, searching, filtering,
selecting artwork and previewing a proposal all work against the real backend;
nothing writes. Apply, Reset and Remove are present so the layout can be judged
but are disabled, because the shell is being validated before behaviour is
wired to it.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from kairo import actions
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
        self._sources: dict[str, str] = {}
        self._streamer = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_list())
        layout.addWidget(self._build_workspace(), 1)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(lambda: self.refilter())

        self.rescan()

    # -- middle column -----------------------------------------------------

    def _build_list(self) -> QWidget:
        column = QWidget()
        column.setObjectName("list")
        column.setFixedWidth(Q.W_LIST)
        layout = QVBoxLayout(column)
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
        space.setObjectName("workspace")
        layout = QVBoxLayout(space)
        layout.setContentsMargins(Q.PAD_PANE, 0, Q.PAD_PANE, Q.PAD_PANE)
        layout.setSpacing(Q.GAP_WIDE)

        header = QWidget()
        header.setFixedHeight(Q.H_HEADER)
        head = QHBoxLayout(header)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(T.S2)
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
        head.addLayout(names)
        head.addStretch(1)
        self.rescan_btn = QPushButton("Rescan")
        self.rescan_btn.setObjectName("secondary")
        # clicked carries a checked flag; a zero-argument Signal cannot take it.
        self.rescan_btn.clicked.connect(
            lambda _checked: self.rescan_requested.emit())
        self.match_btn = QPushButton("Auto Match")
        self.match_btn.setObjectName("secondary")
        self.match_btn.setEnabled(False)
        self.match_btn.setToolTip("Not wired yet — this milestone is read-only")
        for button in (self.rescan_btn, self.match_btn):
            button.setFixedHeight(Q.H_BUTTON)
            head.addWidget(button, 0, Qt.AlignVCenter)
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
        """Secondary by design: small wells, quiet labels, one line of text."""
        row = QHBoxLayout()
        row.setContentsMargins(Q.PAD_CARD, Q.PAD_CARD, Q.PAD_CARD, Q.GAP)
        row.setSpacing(Q.GAP)
        self.current_well = IconWell(Q.WELL_COMPARE)
        self.proposed_well = IconWell(Q.WELL_COMPARE)
        for caption, well in (("CURRENT", self.current_well),
                              ("PROPOSED", self.proposed_well)):
            box = QVBoxLayout()
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(T.S2)
            label = QLabel(caption)
            label.setObjectName("micro")
            box.addWidget(label)
            box.addWidget(well)
            row.addLayout(box)
            if caption == "CURRENT":
                arrow = QLabel("→")
                arrow.setObjectName("meta")
                row.addSpacing(T.S1)
                row.addWidget(arrow, 0, Qt.AlignVCenter)
                row.addSpacing(T.S1)
        self.proposal = QLabel("Choose artwork below")
        self.proposal.setObjectName("meta")
        self.proposal.setWordWrap(True)
        row.addSpacing(Q.GAP)
        row.addWidget(self.proposal, 1, Qt.AlignVCenter)
        return row

    def _build_artwork_controls(self):
        row = QHBoxLayout()
        row.setContentsMargins(Q.PAD_CARD, Q.GAP, Q.PAD_CARD, Q.GAP)
        row.setSpacing(Q.GAP)
        heading = QLabel("ARTWORK")
        heading.setObjectName("micro")
        row.addWidget(heading, 0, Qt.AlignVCenter)
        row.addSpacing(T.S1)
        self.source_pills = Pills([])
        self.source_pills.changed.connect(self._source_changed)
        row.addWidget(self.source_pills, 0, Qt.AlignVCenter)
        row.addStretch(1)
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search artwork…")
        self.query.setFixedWidth(Q.W_QUERY)
        self.query.setClearButtonEnabled(True)
        self.query.returnPressed.connect(self._load_artwork)
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
        self.restore_btn.setText(writer.restore_label)
        supports_remove = bool(getattr(writer, "supports_remove", False))
        self.remove_btn.setVisible(supports_remove)
        if supports_remove:
            self.remove_btn.setText(writer.remove_label)

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
            self.refilter(auto_select=True)

        def scan_failed(message):
            if token.cancelled:
                return
            self.entries = []
            self.refilter(auto_select=True)
            self.status.emit(f"{provider.label}: {message}")

        work.submit(run, on_done=scanned, on_failed=scan_failed)

    def visible_entries(self):
        term = self.search.text().strip().lower()
        mode = FILTERS.get(self.filters.value(), "all")
        entries = self.entries
        if term:
            entries = [e for e in entries if term in e.name.lower()]
        if mode == "with":
            entries = [e for e in entries if e.customized]
        elif mode == "without":
            entries = [e for e in entries if not e.customized]
        return entries

    def refilter(self, auto_select: bool = False) -> None:
        entries = self.visible_entries()
        previous = self.selected.entry.key if self.selected else None
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

    def _shown_floor(self) -> int:
        """Keep at least a viewport's worth, however short the viewport is."""
        try:
            height = self.scroll.viewport().height()
        except Exception:
            return ROW_PAGE
        return max(1, height // max(1, Q.H_ROW + Q.GAP_ROW) + 4)

    def _bind_rows(self, entries) -> None:
        """Materialise exactly as many rows as are being shown."""
        while len(self.rows) < len(entries):
            row = EntryRow(self.grid_holder)
            row.clicked.connect(self.select)
            self.rows.append(row)
            self.rows_layout.insertWidget(len(self.rows) - 1, row)
        for index, entry in enumerate(entries):
            row = self.rows[index]
            row.bind(entry)
            row.set_selected(False)
            row.setVisible(True)
        for row in self.rows[len(entries):]:
            row.setVisible(False)

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

        entry = row.entry
        self.title.setText(T.ellipsize(entry.name, 46))
        self.subtitle.setText(entry.subtitle)
        self.current_well.show_path(entry.current_icon, "—")
        self._clear_proposal()
        self._update_actions()
        self._refresh_sources()
        if load:
            self._seed_query()
            self._load_artwork()

    def _empty_workspace(self) -> None:
        term = self.search.text().strip()
        if self.entries:
            self.title.setText("No matches")
            note = (f"Nothing here matches “{term}”." if term
                    else "Nothing matches the current filter.")
        else:
            self.title.setText(f"No {self.provider.noun} found")
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
        self.subtitle.setText("")
        self.current_well.show_placeholder("—")
        self._clear_grid()
        self._grid_note(note)

    # -- sources -----------------------------------------------------------

    def source(self):
        return self.ctx.sources.get(self._sources.get(self.source_pills.value(), ""))

    def _refresh_sources(self) -> None:
        """Keep every configured, browsable source available.

        An empty result describes one query, not the whole source. Hiding that
        source made its tab disappear before the user could correct a title or
        try a broader search.
        """
        available = self.ctx.sources.browsable_for(self.provider.id,
                                                   self.ctx.config)
        self._sources = {s.label: s.id for s in available}
        self.source_pills.set_values(list(self._sources))

    def _seed_query(self) -> None:
        source = self.source()
        if source is None or not source.needs_query or self.selected is None:
            self.query.setVisible(False)
            return
        self.query.setVisible(True)
        query = self.provider.artwork_query(self.selected.entry)
        self.query.setText(query.icon_name if source.id == "theme" else query.text)

    def _source_changed(self, _label: str) -> None:
        if self.selected is not None:
            self._seed_query()
            self._load_artwork()

    # -- artwork -----------------------------------------------------------

    def _clear_grid(self) -> None:
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
        # in-flight search when the selection or source becomes unavailable.
        token = self.tokens.start(ACTIVITY_ARTWORK)
        if self.selected is None:
            return
        entry = self.selected.entry
        source = self.source()
        if source is None:
            self._grid_note("No online source has artwork for this one.")
            return

        query = self.provider.artwork_query(entry)
        if source.needs_query:
            text = self.query.text().strip()
            if not text:
                self._grid_note(f"Type a term to search {source.label}.")
                return
            query = query.with_text(text)

        self._grid_note(f"Looking for artwork in {source.label}…")
        key = entry.key

        def search():
            return source.find(query)

        def arrived(results):
            if token.cancelled or self.selected is None:
                return
            if self.selected.entry.key != key:
                return
            self._clear_grid()
            if not results:
                self._grid_note(
                    f"{source.label} has nothing for {entry.name}.\n"
                    "Try a different search.")
                return
            self.subtitle.setText(
                f"{entry.subtitle}  ·  {len(results)} from {source.label}")
            self._build_tiles(results)
            self._stream_previews(source, results, token, key)

        def failed(message):
            # A temporary failure leaves the source available so the user can
            # retry without losing the tab they were using.
            if not token.cancelled:
                self._clear_grid()
                self._grid_note(f"Could not load artwork: {message}")

        work.submit(search, on_done=arrived, on_failed=failed)

    def _columns(self) -> int:
        return max(1, self.grid_scroll.viewport().width()
                   // (ArtworkTile.WIDTH + T.S1))

    def _build_tiles(self, results) -> None:
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        columns = self._columns()
        # Previews arrive by their index in `results`, and tiles get dropped
        # as they arrive, so position in self.tiles stops matching almost
        # immediately. Keyed lookup instead: drop one tile and the rest still
        # receive their own image.
        self._tile_at = {}
        for index, art in enumerate(results):
            tile = ArtworkTile(art, self.grid_holder)
            tile.picked.connect(self._propose)
            self.grid.addWidget(tile, index // columns, index % columns)
            self.tiles.append(tile)
            self._tile_at[index] = tile

    def _stream_previews(self, source, results, token, key) -> None:
        """Fetch each preview on a pool thread, painting them as they land.

        The streamer is held on the instance so it outlives this call; a signal
        whose sender has been collected delivers nothing.
        """
        streamer = work.Streamer()
        streamer.item.connect(self._fill_tile)
        self._streamer = streamer

        def pump():
            for index, art in enumerate(results):
                if token.cancelled:
                    return
                try:
                    data = source.preview(art)
                except Exception:
                    data = None         # say so, rather than leaving a blank
                if token.cancelled:
                    return
                streamer.item.emit(index, data, key)

        work.submit(pump)

    def _fill_tile(self, index: int, data: object, key: str) -> None:
        if self.selected is None or self.selected.entry.key != key:
            return
        tile = self._tile_at.get(index)
        if tile is None:
            return
        # data is None when the preview could not be fetched at all. Either
        # way there is nothing to show, and an empty tile is worse than none.
        if data is None or not images.is_usable_preview(data, MIN_USABLE_EDGE):
            self._drop_tile(tile)
            return
        tile.set_image(data)

    def _drop_tile(self, tile) -> None:
        """Remove a tile and close the hole it leaves behind."""
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
        self._reflow_tiles()

    def _reflow_tiles(self) -> None:
        """Re-seat the survivors so the grid has no gaps."""
        columns = self._columns()
        for position, tile in enumerate(self.tiles):
            self.grid.removeWidget(tile)
            self.grid.addWidget(tile, position // columns, position % columns)
        if not self.tiles:
            self._grid_note("nothing here is large enough to use")

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

        source = self.ctx.sources.get(art.source_id)
        if source is None:
            return

        def fetch():
            return source.preview(art)

        def arrived(data):
            if self.proposed is art:
                self.proposed_well.show_data(data)

        work.submit(fetch, on_done=arrived, on_failed=lambda _m: None)
