"""The middle and right columns: entries in a provider, and their artwork.

This pane is deliberately ignorant of what a provider contains. It asks for
entries, asks the sources what artwork they have, and asks the writer to apply
it - so a Steam game, a Linux application and, later, a PS2 title all render
through exactly the same code.
"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from kairo import actions
from kairo.artwork.local import LocalFileSource
from kairo.models import AppEntry, Artwork
from kairo.ui import theme as T
from kairo.ui.context import UIContext
from kairo.ui.widgets import (AppRow, ArtworkTile, IconWell, SearchField,
                              SegmentedPills)

SEARCH_DEBOUNCE_MS = 400
GRID_GUTTER = 12
DEFAULT_COLS = 4

ACTIVITY_ARTWORK = "artwork"
ACTIVITY_PROBE = "probe"


class LibraryPane(ctk.CTkFrame):
    def __init__(self, master, provider, context: UIContext, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.provider = provider
        self.ctx = context

        self.entries: list[AppEntry] = []
        self.rows: list[AppRow] = []
        self.selected_row: AppRow | None = None
        self.proposed: Artwork | None = None

        self._tiles: list[ArtworkTile] = []
        self._grid_cols = 0
        self._resize_job = None
        self._query_job = None
        self._filter_mode = "all"
        self._visible = 0
        self._chosen_tile = None
        self._source_labels: dict[str, str] = {}
        self._probe_cache: dict[tuple[str, str], bool] = {}

        self.search_var = ctk.StringVar()
        self.source_var = ctk.StringVar(value="")
        self.query_var = ctk.StringVar()

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=0, minsize=T.W_LIST)
        self.grid_columnconfigure(1, weight=1)

        self._build_list()
        self._build_workspace()
        self.refresh_entries()

    # -- middle column ----------------------------------------------------

    def _build_list(self):
        column = ctk.CTkFrame(self, fg_color=T.C_LIST, corner_radius=0,
                              width=T.W_LIST)
        column.grid(row=0, column=0, sticky="nsew")
        column.grid_propagate(False)
        column.grid_rowconfigure(3, weight=1)
        column.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(column, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew",
                  padx=T.PAD_COLUMN, pady=(T.S6, T.S3))
        ctk.CTkLabel(head, text=self.provider.label, font=T.F_PANE,
                     text_color=T.C_TEXT).pack(side="left")
        self.count_pill = ctk.CTkLabel(head, text="0", font=T.F_META,
                                       text_color=T.C_TEXT2, fg_color=T.C_CARD,
                                       corner_radius=T.R_SM, width=34, height=20)
        self.count_pill.pack(side="right")

        self.search_var.trace_add("write", lambda *_: self._filter())
        SearchField(column, textvariable=self.search_var,
                    placeholder=f"Search {self.provider.noun}…"
                    ).grid(row=1, column=0, sticky="ew",
                           padx=T.PAD_COLUMN, pady=(0, T.S2))

        # Same control as the source picker, so filters and sources read as
        # one design system rather than two.
        self._filter_labels = {"All": "all", "Customized": "with",
                               "Untouched": "without"}
        self.filter_pills = SegmentedPills(
            column, values=list(self._filter_labels),
            command=lambda label: self._set_filter(self._filter_labels[label]))
        self.filter_pills.set("All")
        self.filter_pills.grid(row=2, column=0, sticky="w",
                               padx=T.PAD_COLUMN, pady=(0, T.S3))

        self.list = ctk.CTkScrollableFrame(
            column, fg_color="transparent", corner_radius=0,
            scrollbar_fg_color="transparent", scrollbar_button_color=T.C_CARD,
            scrollbar_button_hover_color=T.C_TEXT3)
        self.list.grid(row=3, column=0, sticky="nsew",
                       padx=T.S2, pady=(0, T.S3))
        self.list.grid_columnconfigure(0, weight=1)

    # -- right column -----------------------------------------------------

    def _build_workspace(self):
        space = ctk.CTkFrame(self, fg_color=T.C_BG, corner_radius=0)
        space.grid(row=0, column=1, sticky="nsew")
        space.grid_rowconfigure(3, weight=1)
        space.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(space, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew",
                    padx=T.PAD_WINDOW, pady=(T.S5, 0))
        titles = ctk.CTkFrame(header, fg_color="transparent")
        titles.pack(side="left", fill="x", expand=True)
        self.title = ctk.CTkLabel(titles, text="Select something",
                                  font=T.F_WORKSPACE_TITLE, text_color=T.C_TEXT,
                                  anchor="w")
        self.title.pack(anchor="w")
        self.subtitle = ctk.CTkLabel(titles, text="", font=T.F_SMALL,
                                     text_color=T.C_TEXT3, anchor="w")
        self.subtitle.pack(anchor="w", pady=(1, 0))

        # Current versus proposed, side by side. Choosing artwork below only
        # proposes it; nothing is written until Apply.
        compare = ctk.CTkFrame(space, fg_color=T.C_PANEL,
                               corner_radius=T.R_CARD)
        compare.grid(row=1, column=0, sticky="ew",
                     padx=T.PAD_WINDOW, pady=(T.S4, T.S3))
        for column_index in (0, 1, 2):
            compare.grid_columnconfigure(column_index, weight=0)
        compare.grid_columnconfigure(3, weight=1)

        current_box = ctk.CTkFrame(compare, fg_color="transparent")
        current_box.grid(row=0, column=0,
                         padx=(T.PAD_CARD, T.S3), pady=T.PAD_CARD_TIGHT)
        ctk.CTkLabel(current_box, text="CURRENT", font=T.F_SECTION,
                     text_color=T.C_TEXT3).pack(anchor="w", pady=(0, 4))
        self.current_well = IconWell(current_box, size=T.WELL_SIZE)
        self.current_well.pack()

        ctk.CTkLabel(compare, text="→", font=T.F_TITLE, text_color=T.C_TEXT3
                     ).grid(row=0, column=1, padx=T.S1)

        proposed_box = ctk.CTkFrame(compare, fg_color="transparent")
        proposed_box.grid(row=0, column=2,
                          padx=(T.S3, T.PAD_CARD), pady=T.PAD_CARD_TIGHT)
        ctk.CTkLabel(proposed_box, text="PROPOSED", font=T.F_SECTION,
                     text_color=T.C_TEXT3).pack(anchor="w", pady=(0, 4))
        self.proposed_well = IconWell(proposed_box, size=T.WELL_SIZE)
        self.proposed_well.pack()

        self.proposal_label = ctk.CTkLabel(
            compare, text="Choose artwork below", font=T.F_SMALL,
            text_color=T.C_TEXT3, anchor="w")
        self.proposal_label.grid(row=0, column=3, sticky="w",
                                 padx=(T.S1, T.PAD_CARD))

        # Source picker and its search box.
        controls = ctk.CTkFrame(space, fg_color="transparent")
        controls.grid(row=2, column=0, sticky="ew",
                      padx=T.PAD_WINDOW, pady=(0, T.S3))
        self.source_selector = SegmentedPills(
            controls, values=[], variable=self.source_var,
            command=self._on_source_changed)
        self.source_selector.pack(side="left")
        self.query_field = SearchField(controls, textvariable=self.query_var,
                                       placeholder="Search artwork…", width=280)
        self.query_field.bind_entry("<KeyRelease>", self._schedule_query)
        self.query_field.bind_entry("<Return>", self._run_query_now)

        self.grid_area = ctk.CTkScrollableFrame(
            space, fg_color=T.C_PANEL, corner_radius=T.R_CARD,
            scrollbar_fg_color="transparent", scrollbar_button_color=T.C_CARD,
            scrollbar_button_hover_color=T.C_TEXT3)
        self.grid_area.grid(row=3, column=0, sticky="nsew",
                            padx=T.PAD_WINDOW - T.S1, pady=(0, T.S3))
        # add="+" is essential: CTkScrollableFrame binds <Configure> on itself
        # to recompute the scrollregion; replacing it stops the wheel working.
        self.grid_area.bind("<Configure>", self._on_resize, add="+")

        # Three tiers, left to right: secondary actions, then a gap, then the
        # destructive one, then the primary alone on the right.
        bar = ctk.CTkFrame(space, fg_color="transparent")
        bar.grid(row=4, column=0, sticky="ew",
                 padx=T.PAD_WINDOW, pady=(0, T.S5))
        self.browse_btn = ctk.CTkButton(
            bar, text="Browse local file…", height=T.H_ACTION,
            corner_radius=T.R_WELL, fg_color=T.C_CARD,
            hover_color=T.C_CARD_HOVER, text_color=T.C_TEXT,
            font=T.F_BUTTON, command=self._on_browse, state="disabled")
        self.browse_btn.pack(side="left")
        self.restore_btn = ctk.CTkButton(
            bar, text="Restore original", height=T.H_ACTION,
            corner_radius=T.R_WELL, fg_color=T.C_CARD,
            hover_color=T.C_CARD_HOVER, text_color=T.C_TEXT,
            font=T.F_BUTTON, command=self._on_restore, state="disabled")
        self.restore_btn.pack(side="left", padx=(T.GAP_CONTROL, 0))
        # Held away from the secondary pair so it cannot be hit by momentum.
        self.remove_btn = ctk.CTkButton(
            bar, text="Remove shortcut", height=T.H_ACTION,
            corner_radius=T.R_WELL, fg_color=T.C_DANGER_BG,
            hover_color=T.C_DANGER_HOVER, text_color=T.C_DANGER,
            font=T.F_BUTTON, command=self._on_remove)
        self.apply_btn = ctk.CTkButton(
            bar, text="Apply", height=T.H_ACTION, width=132,
            corner_radius=T.R_WELL, fg_color=T.C_ACCENT,
            hover_color=T.C_ACCENT_HOVER, font=T.F_BUTTON,
            command=self._on_apply, state="disabled")
        self.apply_btn.pack(side="right")

    # -- entries ----------------------------------------------------------

    def refresh_entries(self):
        try:
            self.entries = (self.provider.scan()
                            if self.provider.available() else [])
        except Exception as exc:
            self.entries = []
            messagebox.showerror("Scan failed", f"{self.provider.label}: {exc}")
        self._probe_cache.clear()
        self._filter()

    def _set_filter(self, mode: str):
        self._filter_mode = mode
        self._filter()

    def visible_entries(self) -> list[AppEntry]:
        term = self.search_var.get().strip().lower()
        entries = self.entries
        if term:
            entries = [e for e in entries if term in e.name.lower()]
        if self._filter_mode == "with":
            entries = [e for e in entries if e.customized]
        elif self._filter_mode == "without":
            entries = [e for e in entries if not e.customized]
        return entries

    def _filter(self):
        """Repoint the row pool at the visible entries.

        Rows are reused rather than rebuilt. Destroying and recreating them on
        every keystroke meant hundreds of widget teardowns and icon decodes per
        character typed once a library got large.
        """
        entries = self.visible_entries()

        while len(self.rows) < len(entries):
            self.rows.append(AppRow(self.list, on_click=self._select))

        for index, entry in enumerate(entries):
            row = self.rows[index]
            row.bind_entry(entry)
            row.set_selected(False)
            row.grid(row=index, column=0, sticky="ew",
                     padx=T.S2, pady=T.GAP_ROW)
        for row in self.rows[len(entries):]:
            row.grid_remove()

        self._visible = len(entries)
        self.selected_row = None
        self._clear_proposal()
        self._set_actions(False)
        self.count_pill.configure(text=str(len(entries)))
        self.ctx.on_changed()

    def visible_rows(self):
        return self.rows[:self._visible]

    def customized_count(self) -> int:
        return sum(1 for e in self.entries if e.customized)

    def _row_for(self, entry: AppEntry) -> AppRow | None:
        for row in self.visible_rows():
            if row.entry.key == entry.key:
                return row
        return None

    def _select(self, row: AppRow):
        if self.selected_row:
            self.selected_row.set_selected(False)
        row.set_selected(True)
        self.selected_row = row

        entry = row.entry
        self.title.configure(text=entry.name)
        self.subtitle.configure(text=entry.subtitle)
        self.current_well.show(entry.current_icon, placeholder="—")
        self._clear_proposal()
        self._set_actions(True)
        self._refresh_sources()
        self._seed_query(entry)
        self._load_artwork(entry)

    def _set_actions(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.browse_btn.configure(state=state)
        writer = self._writer()
        self.restore_btn.configure(
            state=state, text=writer.restore_label if writer else "Restore original")
        if enabled and writer is not None and writer.supports_remove:
            if not self.remove_btn.winfo_ismapped():
                self.remove_btn.pack(side="left", padx=(T.S8, 0))
            self.remove_btn.configure(text=writer.remove_label, state="normal")
        else:
            self.remove_btn.pack_forget()
        self.apply_btn.configure(
            state="normal" if (enabled and self.proposed) else "disabled")

    def _writer(self):
        return self.provider.writer() if self.provider else None

    # -- sources ----------------------------------------------------------

    def source(self):
        return self.ctx.sources.get(self._source_labels.get(self.source_var.get(), ""))

    def _refresh_sources(self) -> bool:
        """Offer only sources that can help the selected entry.

        A source is hidden once it has been asked and had nothing. Never
        because it has not been asked yet, and never because it failed.
        """
        entry = self.selected_row.entry if self.selected_row else None
        candidates = self.ctx.sources.browsable_for(self.provider.id, self.ctx.config)
        if entry is not None:
            usable = [s for s in candidates
                      if self._probe_cache.get((entry.key, s.id)) is not False]
        else:
            usable = candidates

        previous = self.source_var.get()
        self._source_labels = {s.label: s.id for s in usable}
        labels = list(self._source_labels)
        self.source_selector.set_values(labels)
        if previous not in labels:
            self.source_var.set(labels[0] if labels else "")
            self.source_selector.set(self.source_var.get())

        self._refresh_query_row()

        if entry is not None:
            unasked = [s for s in candidates
                       if (entry.key, s.id) not in self._probe_cache
                       and s.id != self._source_labels.get(self.source_var.get())]
            if unasked:
                self._probe_sources(entry, unasked)
        return previous != self.source_var.get()

    def _refresh_query_row(self):
        source = self.source()
        if source is not None and source.needs_query:
            self.query_field.configure_placeholder(source.query_placeholder)
            if not self.query_field.winfo_ismapped():
                self.query_field.pack(side="left", padx=(T.S3, 0))
        else:
            self.query_field.pack_forget()
            self._cancel_query_job()

    def _probe_sources(self, entry: AppEntry, sources):
        query = self.provider.artwork_query(entry)
        token = self.ctx.tokens.start(ACTIVITY_PROBE)

        def work():
            for source in sources:
                if token.cancelled:
                    return
                try:
                    has_results = source.probe(query)
                except Exception:
                    # Briefly unreachable is not the same as having nothing.
                    has_results = True
                self._probe_cache[(entry.key, source.id)] = has_results
                if not has_results and not token.cancelled:
                    self.after(0, self._sources_changed, entry)

        threading.Thread(target=work, daemon=True).start()

    def _sources_changed(self, entry: AppEntry):
        if not self._showing(entry):
            return
        if self._refresh_sources():
            self._seed_query(entry)
            self._load_artwork(entry)

    def _seed_query(self, entry: AppEntry):
        source = self.source()
        if source is None or not source.needs_query:
            return
        query = self.provider.artwork_query(entry)
        self.query_var.set(query.icon_name if source.id == "theme" else query.text)

    def _on_source_changed(self, _value=None):
        self._refresh_query_row()
        if self.selected_row:
            self._seed_query(self.selected_row.entry)
            self._load_artwork(self.selected_row.entry)

    def _cancel_query_job(self):
        if self._query_job is not None:
            self.after_cancel(self._query_job)
            self._query_job = None

    def _schedule_query(self, event=None):
        if event is not None and getattr(event, "keysym", "") == "Return":
            return None
        source = self.source()
        if source is None or not source.needs_query or not self.selected_row:
            return None
        self._cancel_query_job()
        self._query_job = self.after(SEARCH_DEBOUNCE_MS, self._run_query)
        return None

    def _run_query_now(self, _event=None):
        self._cancel_query_job()
        self._run_query()
        return "break"

    def _run_query(self):
        self._query_job = None
        if self.selected_row:
            self._load_artwork(self.selected_row.entry)

    # -- artwork grid -----------------------------------------------------

    def _showing(self, entry: AppEntry) -> bool:
        return bool(self.selected_row) and self.selected_row.entry.key == entry.key

    def _status_if_current(self, entry: AppEntry, text: str):
        if self._showing(entry):
            self.subtitle.configure(text=text)

    def _clear_grid(self):
        for widget in self.grid_area.winfo_children():
            widget.destroy()
        self._tiles.clear()
        self._chosen_tile = None
        self._grid_cols = 0

    def _load_artwork(self, entry: AppEntry):
        self._clear_grid()
        source = self.source()
        if source is None:
            self._status_if_current(
                entry, "No online source has artwork for this one — "
                       "use Browse local file.")
            return
        query = self.provider.artwork_query(entry)
        if source.needs_query:
            query = query.with_text(self.query_var.get().strip())
            if not query.text:
                self._status_if_current(entry, f"Type a term to search {source.label}.")
                return

        token = self.ctx.tokens.start(ACTIVITY_ARTWORK)

        def work():
            try:
                results = source.find(query)
                if token.cancelled:
                    return
                if not results:
                    self._probe_cache[(entry.key, source.id)] = False
                    self.after(0, self._status_if_current, entry,
                               f"{entry.subtitle}  ·  nothing in {source.label}")
                    self.after(0, self._sources_changed, entry)
                    return
                self._probe_cache[(entry.key, source.id)] = True
                self.after(0, self._status_if_current, entry,
                           f"{entry.subtitle}  ·  {len(results)} from {source.label}")
                self.after(0, self._build_tiles, results, entry)
                for index, art in enumerate(results):
                    if token.cancelled:
                        return
                    try:
                        data = source.preview(art)
                    except Exception:
                        continue
                    if token.cancelled:
                        return
                    self.after(0, self._fill_tile, index, data, entry)
            except Exception as exc:
                if not token.cancelled:
                    self.after(0, self._status_if_current, entry, str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _fit_columns(self) -> int:
        try:
            available = self.grid_area.winfo_width()
        except tk.TclError:
            return DEFAULT_COLS
        if available <= 1:
            return DEFAULT_COLS
        if self._tiles:
            try:
                cell = self._tiles[0].winfo_reqwidth() + T.GRID_GUTTER
            except tk.TclError:
                cell = (T.TILE_SIZE + T.S6) * T.UI_SCALE
        else:
            cell = (T.TILE_SIZE + T.S6) * T.UI_SCALE
        return max(1, int((available + 4) // cell))

    def _regrid(self, cols: int | None = None):
        cols = cols or self._fit_columns()
        if cols == self._grid_cols or not self._tiles:
            return
        self._grid_cols = cols
        for index, tile in enumerate(self._tiles):
            row, col = divmod(index, cols)
            tile.grid_configure(row=row, column=col)

    def _on_resize(self, _event=None):
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(120, self._regrid)

    def _build_tiles(self, results, entry: AppEntry):
        if not self._showing(entry):
            return
        self._tiles = []
        cols = self._fit_columns()
        self._grid_cols = cols
        for index, art in enumerate(results):
            row, col = divmod(index, cols)
            tile = ArtworkTile(self.grid_area, art, on_pick=self._propose)
            tile.grid(row=row, column=col, padx=T.S1, pady=T.S1, sticky="n")
            self._tiles.append(tile)
        self.after_idle(lambda: self._regrid(self._fit_columns()))

    def _fill_tile(self, index: int, data: bytes, entry: AppEntry):
        if not self._showing(entry) or index >= len(self._tiles):
            return
        try:
            self._tiles[index].set_image(data)
        except tk.TclError:
            pass

    # -- proposing and applying -------------------------------------------

    def _clear_proposal(self):
        self.proposed = None
        if self._chosen_tile is not None:
            try:
                self._chosen_tile.set_chosen(False)
            except tk.TclError:
                pass
            self._chosen_tile = None
        self.proposed_well.show(None, placeholder="—")
        self.proposal_label.configure(text="Choose artwork below",
                                      text_color=T.C_TEXT3)
        self.apply_btn.configure(state="disabled")

    def _propose(self, art: Artwork):
        """Selecting artwork only proposes it. Apply writes it."""
        if not self.selected_row:
            return
        self.proposed = art
        if self._chosen_tile is not None:
            try:
                self._chosen_tile.set_chosen(False)
            except tk.TclError:
                pass
            self._chosen_tile = None
        for tile in self._tiles:
            if tile.art is art:
                tile.set_chosen(True)
                self._chosen_tile = tile
                break
        label = art.label or art.name or "selected artwork"
        self.proposal_label.configure(text=f"{label}  ·  press Apply to use it",
                                      text_color=T.C_TEXT2)
        self.apply_btn.configure(state="normal")

        source = self.ctx.sources.get(art.source_id)
        if source is None:
            return

        def work():
            try:
                data = source.preview(art)
            except Exception:
                return
            self.after(0, self._show_proposal, art, data)

        threading.Thread(target=work, daemon=True).start()

    def _show_proposal(self, art: Artwork, data: bytes):
        if self.proposed is not art:
            return
        self.proposed_well.show_data(data)

    def _on_apply(self):
        if not self.selected_row or not self.proposed:
            return
        entry = self.selected_row.entry
        art = self.proposed
        source = self.ctx.sources.get(art.source_id)
        if source is None:
            return
        self.apply_btn.configure(state="disabled", text="Applying…")

        def work():
            try:
                actions.fetch_and_apply(entry, self.provider, source, art,
                                        ledger=self.ctx.ledger)
                self.after(0, self._after_change, entry, "Artwork applied")
            except Exception as exc:
                self.after(0, self._apply_failed, entry, str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _apply_failed(self, entry: AppEntry, message: str):
        self.apply_btn.configure(state="normal", text="Apply")
        messagebox.showerror("Could not apply artwork", message)
        self._status_if_current(entry, message)

    def _after_change(self, entry: AppEntry, message: str):
        self.apply_btn.configure(text="Apply")
        row = self._row_for(entry)
        if row:
            row.refresh()
        if self._showing(entry):
            self.current_well.show(entry.current_icon, placeholder="—")
            self.subtitle.configure(text=f"{entry.subtitle}  ·  {message}")
        self._clear_proposal()
        self._set_actions(bool(self.selected_row))
        self.ctx.on_changed()

    def _on_browse(self):
        if not self.selected_row:
            return
        chosen = filedialog.askopenfilename(
            title=f"Icon for {self.selected_row.entry.name}",
            filetypes=[("Icon images", "*.ico *.png *.svg *.xpm"), ("All", "*.*")])
        if chosen:
            self._propose(LocalFileSource.artwork_for(Path(chosen)))

    # -- undo -------------------------------------------------------------

    def _on_restore(self):
        if not self.selected_row:
            return
        entry = self.selected_row.entry
        writer = self._writer()
        allowed, reason = writer.can_restore(entry)
        if not allowed:
            messagebox.showinfo("Nothing to do", reason)
            return
        if not messagebox.askyesno(writer.restore_label, writer.restore_prompt(entry)):
            return
        try:
            actions.restore_entry(entry, self.provider, ledger=self.ctx.ledger)
        except Exception as exc:
            messagebox.showerror("Could not undo", str(exc))
            return
        self._after_change(entry, "Artwork reset" if writer.action == "created"
                           else "Original icon restored")

    def _on_remove(self):
        if not self.selected_row:
            return
        entry = self.selected_row.entry
        writer = self._writer()
        allowed, reason = writer.can_remove(entry)
        if not allowed:
            messagebox.showinfo("Nothing to remove", reason)
            return
        if not messagebox.askyesno(writer.remove_label, writer.remove_prompt(entry)):
            return
        try:
            actions.remove_entry(entry, self.provider, ledger=self.ctx.ledger)
        except Exception as exc:
            messagebox.showerror("Could not remove", str(exc))
            return
        self._after_change(entry, "Shortcut removed")
