"""The middle and right columns.

Read-only for this milestone. Scanning, browsing, searching, filtering,
selecting artwork and previewing a proposal all work against the real backend;
nothing writes. Apply, Reset and Remove are present so the layout can be judged
but are disabled, because the shell is being validated before behaviour is
wired to it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from kairo.qt import work
from kairo.qt.widgets import ArtworkTile, EntryRow, IconWell, Pills
from kairo.tasks import ActivityTokens
from kairo.ui import theme as T

FILTERS = {"All": "all", "Customized": "with", "Untouched": "without"}
SEARCH_DEBOUNCE_MS = 250
ACTIVITY_ARTWORK = "artwork"


class LibraryPane(QWidget):
    """One provider's entries, and the artwork workspace for the selected one."""

    changed = Signal()
    status = Signal(str)

    def __init__(self, provider, context, parent=None):
        super().__init__(parent)
        self.provider = provider
        self.ctx = context
        self.tokens: ActivityTokens = context.tokens

        self.entries = []
        self.rows: list[EntryRow] = []
        self.visible = 0
        self.selected: EntryRow | None = None
        self.proposed = None
        self.tiles: list[ArtworkTile] = []
        self.chosen_tile = None
        self._sources: dict[str, str] = {}
        self._probe_cache: dict[tuple, bool] = {}
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
        column.setFixedWidth(T.W_LIST)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(T.PAD_COLUMN, T.S6, T.PAD_COLUMN, T.S3)
        layout.setSpacing(T.S2)

        head = QHBoxLayout()
        title = QLabel(self.provider.label)
        title.setObjectName("pane")
        self.count = QLabel("0")
        self.count.setObjectName("meta")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.count)
        layout.addLayout(head)

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
        self.rows_layout.setSpacing(T.GAP_ROW)
        self.rows_layout.addStretch(1)
        self.scroll.setWidget(holder)
        layout.addWidget(self.scroll, 1)
        return column

    # -- right column ------------------------------------------------------

    def _build_workspace(self) -> QWidget:
        space = QWidget()
        space.setObjectName("workspace")
        layout = QVBoxLayout(space)
        layout.setContentsMargins(T.PAD_WINDOW, T.S5, T.PAD_WINDOW, T.S5)
        layout.setSpacing(T.S3)

        self.title = QLabel("")
        self.title.setObjectName("title")
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("meta")
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)

        compare = QFrame()
        compare.setObjectName("card")
        compare_layout = QHBoxLayout(compare)
        compare_layout.setContentsMargins(T.PAD_CARD, T.PAD_CARD_TIGHT,
                                          T.PAD_CARD, T.PAD_CARD_TIGHT)
        compare_layout.setSpacing(T.S3)
        self.current_well = IconWell(T.WELL_SIZE)
        self.proposed_well = IconWell(T.WELL_SIZE)
        for caption, well in (("CURRENT", self.current_well),
                              ("PROPOSED", self.proposed_well)):
            box = QVBoxLayout()
            box.setSpacing(T.S1)
            label = QLabel(caption)
            label.setObjectName("micro")
            box.addWidget(label)
            box.addWidget(well)
            compare_layout.addLayout(box)
            if caption == "CURRENT":
                arrow = QLabel("→")
                arrow.setObjectName("meta")
                compare_layout.addWidget(arrow)
        self.proposal = QLabel("Choose artwork below")
        self.proposal.setObjectName("meta")
        compare_layout.addWidget(self.proposal)
        compare_layout.addStretch(1)
        layout.addWidget(compare)

        panel = QFrame()
        panel.setObjectName("card")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(T.PAD_CARD, T.PAD_CARD_TIGHT,
                                        T.PAD_CARD, T.S2)
        panel_layout.setSpacing(T.S2)

        controls = QHBoxLayout()
        controls.setSpacing(T.S3)
        heading = QLabel("A R T W O R K")
        heading.setObjectName("micro")
        controls.addWidget(heading)
        self.source_pills = Pills([])
        self.source_pills.changed.connect(self._source_changed)
        controls.addWidget(self.source_pills)
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search artwork…")
        self.query.setFixedWidth(240)
        self.query.setClearButtonEnabled(True)
        self.query.returnPressed.connect(self._load_artwork)
        controls.addWidget(self.query)
        controls.addStretch(1)
        panel_layout.addLayout(controls)

        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid_holder = QWidget()
        self.grid = QGridLayout(self.grid_holder)
        self.grid.setContentsMargins(0, 0, T.S2, 0)
        self.grid.setSpacing(T.S2)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.grid_scroll.setWidget(self.grid_holder)
        panel_layout.addWidget(self.grid_scroll, 1)
        layout.addWidget(panel, 1)

        # Three tiers: secondary actions, a gap, the destructive one, then the
        # primary alone on the right.
        bar = QHBoxLayout()
        bar.setSpacing(T.GAP_CONTROL)
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
            # Read-only milestone: the layout is being judged, not the wiring.
            button.setEnabled(False)
            button.setToolTip("Not wired yet — this milestone is read-only")
        bar.addWidget(self.browse_btn)
        bar.addWidget(self.restore_btn)
        bar.addSpacing(T.S8)
        bar.addWidget(self.remove_btn)
        bar.addStretch(1)
        bar.addWidget(self.apply_btn)
        layout.addLayout(bar)
        self._update_actions()
        return space

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

    # -- entries -----------------------------------------------------------

    def rescan(self) -> None:
        try:
            self.entries = (self.provider.scan()
                            if self.provider.available() else [])
        except Exception as exc:
            self.entries = []
            self.status.emit(f"{self.provider.label}: {exc}")
        self._probe_cache.clear()
        self.refilter(auto_select=True)

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

        self.visible = len(entries)
        self.selected = None
        self.count.setText(str(len(entries)))

        if previous is not None:
            for row in self.rows[:self.visible]:
                if row.entry.key == previous:
                    self.select(row, load=False)
                    break
        if self.selected is None:
            if auto_select and entries:
                self.select(self.rows[0])
            else:
                self._empty_workspace()
        self.changed.emit()

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
        """Offer only sources that can help the selected entry.

        A source is hidden once it has been asked and had nothing. Never
        because it has not been asked yet, and never because a lookup failed:
        being briefly unreachable is not evidence of having nothing.
        """
        entry = self.selected.entry if self.selected else None
        available = self.ctx.sources.browsable_for(self.provider.id,
                                                   self.ctx.config)
        if entry is None:
            self._sources = {s.label: s.id for s in available}
            self.source_pills.set_values(list(self._sources))
            return

        usable = [s for s in available
                  if self._probe_cache.get((entry.key, s.id)) is not False]
        before = self.source_pills.value()
        self._sources = {s.label: s.id for s in usable}
        self.source_pills.set_values(list(self._sources))

        unasked = [s for s in available
                   if (entry.key, s.id) not in self._probe_cache
                   and s.id != self._sources.get(self.source_pills.value())]
        if unasked:
            self._probe_sources(entry, unasked)

        if before and before != self.source_pills.value() and self.selected:
            self._seed_query()
            self._load_artwork()

    def _probe_sources(self, entry, sources) -> None:
        """Ask each source in the background whether it has anything at all."""
        query = self.provider.artwork_query(entry)
        key = entry.key

        def ask():
            answers = []
            for source in sources:
                try:
                    answers.append((source.id, bool(source.probe(query))))
                except Exception:
                    # Unreachable is not empty. Leave it visible.
                    answers.append((source.id, True))
            return answers

        def arrived(answers):
            changed = False
            for source_id, has_results in answers:
                if self._probe_cache.get((key, source_id)) != has_results:
                    self._probe_cache[(key, source_id)] = has_results
                    changed = not has_results or changed
            if changed and self.selected is not None \
                    and self.selected.entry.key == key:
                self._refresh_sources()

        work.submit(ask, on_done=arrived, on_failed=lambda _m: None)

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
                widget.deleteLater()
        self.tiles.clear()
        self.chosen_tile = None

    def _grid_note(self, text: str) -> None:
        label = QLabel(text)
        label.setObjectName("empty")
        label.setWordWrap(True)
        self.grid.addWidget(label, 0, 0)

    def _load_artwork(self) -> None:
        self._clear_grid()
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
        token = self.tokens.start(ACTIVITY_ARTWORK)
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
                self._probe_cache[(key, source.id)] = False
                self._grid_note(f"{source.label} has nothing for {entry.name}.")
                self._refresh_sources()
                return
            self._probe_cache[(key, source.id)] = True
            self.subtitle.setText(
                f"{entry.subtitle}  ·  {len(results)} from {source.label}")
            self._build_tiles(results)
            self._stream_previews(source, results, token, key)

        def failed(message):
            # Deliberately does not touch the probe cache: a source that failed
            # once has not told us it has nothing.
            if not token.cancelled:
                self._clear_grid()
                self._grid_note(f"Could not load artwork: {message}")

        work.submit(search, on_done=arrived, on_failed=failed)

    def _build_tiles(self, results) -> None:
        columns = max(1, self.grid_scroll.viewport().width()
                      // (T.TILE_SIZE + 16 + T.S2))
        for index, art in enumerate(results):
            tile = ArtworkTile(art, self.grid_holder)
            tile.picked.connect(self._propose)
            self.grid.addWidget(tile, index // columns, index % columns)
            self.tiles.append(tile)

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
                    continue
                if token.cancelled:
                    return
                streamer.item.emit(index, data, key)

        work.submit(pump)

    def _fill_tile(self, index: int, data: object, key: str) -> None:
        if self.selected is None or self.selected.entry.key != key:
            return
        if 0 <= index < len(self.tiles):
            self.tiles[index].set_image(data)

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
        self.proposal.setText(f"{label}  ·  Apply is not wired in this milestone")

        source = self.ctx.sources.get(art.source_id)
        if source is None:
            return

        def fetch():
            return source.preview(art)

        def arrived(data):
            if self.proposed is art:
                self.proposed_well.show_data(data)

        work.submit(fetch, on_done=arrived, on_failed=lambda _m: None)
