"""The main window."""

from __future__ import annotations

import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from kairo import config as config_store
from kairo import migration, paths
from kairo.artwork.local import LocalFileSource
from kairo.artwork.registry import default_registry as artwork_registry
from kairo.artwork.steamgriddb import CONFIG_KEY as SGDB_KEY
from kairo.desktop import database
from kairo.models import AppEntry, Artwork
from kairo.providers.registry import default_registry as provider_registry
from kairo.ui import theme as T
from kairo.ui.settings import SettingsDialog
from kairo.ui.widgets import AppRow, ArtworkTile

from kairo import APP_NAME

WINDOW_TITLE = APP_NAME
SEARCH_DEBOUNCE_MS = 400
GRID_GUTTER = 12
DEFAULT_COLS = 3


class KairoApp(ctk.CTk):
    def __init__(self):
        super().__init__(fg_color=T.C_BG)
        self.title(WINDOW_TITLE)
        self.geometry("1320x860")
        self.minsize(1040, 620)

        # Before anything reads config: an older installation's settings,
        # icons and launcher entries are moved into place first. Never fatal -
        # a failed migration records itself and Kairo starts normally.
        try:
            self._migration = migration.migrate_if_needed()
        except Exception as exc:                       # pragma: no cover
            self._migration = migration.MigrationReport(failures=[str(exc)])

        self.config_data = config_store.load()
        self.providers = provider_registry()
        self.sources = artwork_registry(self.config_data)

        self.entries: dict[str, list[AppEntry]] = {}
        self.rows: list[AppRow] = []
        self.selected_row: AppRow | None = None
        self._tiles: list[ArtworkTile] = []
        self._grid_cols = 0
        self._resize_job = None
        self._query_job = None
        self._filter_mode = "all"
        self._svg_hint_shown = False
        self._source_labels: dict[str, str] = {}

        available = self.providers.available() or self.providers.all()
        self.provider_var = ctk.StringVar(value=available[0].label)
        self.source_var = ctk.StringVar(value="")
        self.query_var = ctk.StringVar()
        self.search_var = ctk.StringVar()

        self._build(available)
        self._announce_migration()
        self._first_run()
        self.scan()

    # -- current selection ------------------------------------------------

    def provider(self):
        label = self.provider_var.get()
        for provider in self.providers.all():
            if provider.label == label:
                return provider
        return self.providers.all()[0]

    def source(self):
        return self.sources.get(self._source_labels.get(self.source_var.get(), ""))

    def current_entries(self) -> list[AppEntry]:
        return self.entries.get(self.provider().id, [])

    # -- layout -----------------------------------------------------------

    def _build(self, available):
        self.grid_columnconfigure(0, weight=0, minsize=380)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, fg_color=T.C_SIDEBAR, corner_radius=0, width=380)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(4, weight=1)
        sidebar.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(sidebar, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(18, 6))
        ctk.CTkLabel(header, text="Apps", font=T.F_LOGO,
                     text_color=T.C_TEXT).pack(side="left")
        self.count_pill = ctk.CTkLabel(header, text="0", font=T.F_SMALL,
                                       text_color=T.C_TEXT2, fg_color=T.C_ROW,
                                       corner_radius=11, width=40, height=22)
        self.count_pill.pack(side="right")

        self.provider_selector = ctk.CTkSegmentedButton(
            sidebar, values=[p.label for p in available], variable=self.provider_var,
            command=self._on_provider_changed,
            selected_color=T.C_ACCENT_DIM, selected_hover_color=T.C_CARD_HOVER,
            unselected_color=T.C_CARD, unselected_hover_color=T.C_CARD_HOVER,
            text_color=T.C_TEXT, height=30)
        self.provider_selector.grid(row=1, column=0, sticky="ew", padx=16, pady=(6, 8))

        self.search_var.trace_add("write", lambda *_: self._filter())
        ctk.CTkEntry(sidebar, textvariable=self.search_var, height=40,
                     corner_radius=20, placeholder_text="Search…", font=T.F_BODY,
                     border_width=1, border_color=T.C_BORDER
                     ).grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))

        chips = ctk.CTkFrame(sidebar, fg_color="transparent")
        chips.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 8))
        self.chips = {}
        for mode, text, width in (("all", "All", 52), ("with", "● Active", 70),
                                  ("without", "○ None", 66)):
            button = ctk.CTkButton(
                chips, text=text, width=width, height=30, corner_radius=15,
                fg_color=T.C_ACCENT_DIM if mode == "all" else "transparent",
                hover_color=T.C_CARD_HOVER,
                text_color=T.C_TEXT if mode == "all" else T.C_TEXT3,
                font=T.F_TINY, border_width=1,
                border_color=T.C_BORDER_ACCENT if mode == "all" else T.C_BORDER,
                command=lambda m=mode: self._set_filter(m))
            button.pack(side="left", padx=(0, 4))
            self.chips[mode] = button

        self.app_list = ctk.CTkScrollableFrame(
            sidebar, fg_color="transparent", corner_radius=0,
            scrollbar_fg_color="transparent", scrollbar_button_color=T.C_CARD,
            scrollbar_button_hover_color=T.C_TEXT3)
        self.app_list.grid(row=4, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.app_list._scrollbar.configure(width=8, corner_radius=4, border_spacing=3)
        self.app_list.grid_columnconfigure(0, weight=1)

        bottom = ctk.CTkFrame(sidebar, fg_color="transparent")
        bottom.grid(row=5, column=0, sticky="ew", padx=16, pady=(0, 16))
        ctk.CTkButton(bottom, text="⚙  Settings", height=36, corner_radius=18,
                      fg_color=T.C_CARD, hover_color=T.C_CARD_HOVER,
                      text_color=T.C_TEXT2, font=T.F_BUTTON, anchor="w",
                      command=self._open_settings).pack(fill="x", pady=(0, 6))
        ctk.CTkButton(bottom, text="↻  Rescan", height=36, corner_radius=18,
                      fg_color=T.C_CARD, hover_color=T.C_CARD_HOVER,
                      text_color=T.C_TEXT2, font=T.F_BUTTON, anchor="w",
                      command=self.scan).pack(fill="x")

        # -- main panel ---------------------------------------------------
        main = ctk.CTkFrame(self, fg_color=T.C_BG, corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(4, weight=1)
        main.grid_columnconfigure(0, weight=1)

        self.head = ctk.CTkLabel(main, text="Select an app", font=T.F_TITLE,
                                 text_color=T.C_TEXT)
        self.head.grid(row=0, column=0, sticky="w", padx=28, pady=(28, 4))
        self.sub = ctk.CTkLabel(main, text="Choose an app from the sidebar to browse icons",
                                font=T.F_SMALL, text_color=T.C_TEXT3)
        self.sub.grid(row=1, column=0, sticky="w", padx=28, pady=(0, 16))

        self.source_row = ctk.CTkFrame(main, fg_color="transparent")
        self.source_row.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 10))
        ctk.CTkLabel(self.source_row, text="Icon source", font=T.F_TINY,
                     text_color=T.C_TEXT3).pack(side="left", padx=(0, 10))
        self.source_selector = ctk.CTkSegmentedButton(
            self.source_row, values=[], variable=self.source_var,
            command=self._on_source_changed,
            selected_color=T.C_ACCENT_DIM, selected_hover_color=T.C_CARD_HOVER,
            unselected_color=T.C_CARD, unselected_hover_color=T.C_CARD_HOVER,
            text_color=T.C_TEXT, height=30)
        self.source_selector.pack(side="left")
        self.source_row.grid_remove()

        self.query_row = ctk.CTkFrame(main, fg_color="transparent")
        self.query_row.grid(row=3, column=0, sticky="ew", padx=28, pady=(0, 10))
        self.query_label = ctk.CTkLabel(self.query_row, text="Search", font=T.F_TINY,
                                        text_color=T.C_TEXT3)
        self.query_label.pack(side="left", padx=(0, 10))
        self.query_entry = ctk.CTkEntry(
            self.query_row, textvariable=self.query_var, height=34, corner_radius=17,
            font=T.F_BODY, border_width=1, border_color=T.C_BORDER)
        self.query_entry.pack(side="left", fill="x", expand=True)
        self.query_entry.bind("<KeyRelease>", self._schedule_query)
        self.query_entry.bind("<Return>", self._run_query_now)
        self.query_row.grid_remove()

        self.grid_area = ctk.CTkScrollableFrame(
            main, fg_color=T.C_PANEL, corner_radius=T.R_CARD,
            scrollbar_fg_color="transparent", scrollbar_button_color=T.C_CARD,
            scrollbar_button_hover_color=T.C_TEXT3)
        self.grid_area.grid(row=4, column=0, sticky="nsew", padx=24, pady=(0, 8))
        self.grid_area._scrollbar.configure(width=8, corner_radius=4, border_spacing=3)
        # add="+" is essential: CTkScrollableFrame binds <Configure> on itself to
        # recompute the scrollregion. Replacing that binding leaves the region
        # stale and the mouse wheel silently stops working.
        self.grid_area.bind("<Configure>", self._on_resize, add="+")

        actions = ctk.CTkFrame(main, fg_color="transparent")
        actions.grid(row=5, column=0, sticky="ew", padx=28, pady=(8, 16))
        self.browse_btn = ctk.CTkButton(
            actions, text="📁  Browse local file", height=42, corner_radius=21,
            fg_color=T.C_CARD, hover_color=T.C_CARD_HOVER, text_color=T.C_TEXT,
            font=T.F_BUTTON, command=self._on_browse, state="disabled")
        self.browse_btn.pack(side="left", padx=(0, 8))
        self.restore_btn = ctk.CTkButton(
            actions, text="Restore original", height=42, corner_radius=21,
            fg_color=T.C_DANGER_BG, hover_color="#3a2020", text_color=T.C_DANGER,
            font=T.F_BUTTON, command=self._on_restore, state="disabled")
        self.restore_btn.pack(side="left", padx=(0, 8))
        self.bulk_btn = ctk.CTkButton(
            actions, text="⬇  Auto-assign all", height=42, corner_radius=21,
            fg_color=T.C_ACCENT_DIM, hover_color=T.C_CARD_HOVER, text_color=T.C_ACCENT,
            font=T.F_BUTTON, command=self._on_bulk)
        self.bulk_btn.pack(side="right")

        self.status = ctk.CTkLabel(main, text="", font=T.F_TINY, text_color=T.C_TEXT3)
        self.status.grid(row=6, column=0, sticky="w", padx=28, pady=(0, 12))

    # -- scanning ---------------------------------------------------------

    def _announce_migration(self):
        """Tell the user once that their files moved.

        Paths changing under people without explanation is how a rename turns
        into a bug report.
        """
        report = getattr(self, "_migration", None)
        if report is None or not report.performed:
            return
        self.status.configure(text=report.summary())
        body = (f"{report.summary()}\n\n"
                "Your original Steam Shortcut Forge files have been left where "
                "they were, so nothing is lost.")
        if report.failures:
            body += ("\n\nCould not migrate:\n"
                     + "\n".join(report.failures[:10]))
        messagebox.showinfo("Welcome to Kairo", body)

    def _first_run(self):
        steam = self.providers.get("steam")
        if steam and steam.available() and not self.config_data.get(SGDB_KEY):
            if messagebox.askyesno(
                    "Setup",
                    "Steam artwork needs a free SteamGridDB API key.\n\n"
                    "Get one at steamgriddb.com → Profile → API.\n\n"
                    "Everything else works without it. Enter a key now?"):
                self._open_settings()

    def scan(self):
        self.status.configure(text="Scanning…")
        self.update_idletasks()
        for provider in self.providers.all():
            try:
                self.entries[provider.id] = provider.scan() if provider.available() else []
            except Exception as exc:
                self.entries[provider.id] = []
                messagebox.showerror("Scan failed", f"{provider.label}: {exc}")
        self._filter()
        self._update_summary()

    # -- list -------------------------------------------------------------

    def _set_filter(self, mode: str):
        self._filter_mode = mode
        for key, button in self.chips.items():
            active = key == mode
            button.configure(
                fg_color=T.C_ACCENT_DIM if active else "transparent",
                text_color=T.C_TEXT if active else T.C_TEXT3,
                border_color=T.C_BORDER_ACCENT if active else T.C_BORDER)
        self._filter()

    def _filter(self):
        term = self.search_var.get().strip().lower()
        entries = self.current_entries()
        if term:
            entries = [e for e in entries if term in e.name.lower()]
        if self._filter_mode == "with":
            entries = [e for e in entries if e.customized]
        elif self._filter_mode == "without":
            entries = [e for e in entries if not e.customized]

        for row in self.rows:
            row.destroy()
        self.rows.clear()
        self.selected_row = None
        self._set_actions(False)

        for index, entry in enumerate(entries):
            row = AppRow(self.app_list, entry, on_click=self._select)
            row.grid(row=index, column=0, sticky="ew", padx=4, pady=4)
            self.rows.append(row)

        self.count_pill.configure(text=str(len(entries)))

    def _on_provider_changed(self, _value=None):
        self.search_var.set("")
        self.selected_row = None
        self._set_actions(False)
        self._clear_grid()
        self.head.configure(text="Select an app")
        self.sub.configure(text="Choose an app from the sidebar to browse icons")
        self._refresh_sources()
        self._filter()
        self._update_summary()

    def _select(self, row: AppRow):
        if self.selected_row:
            self.selected_row.set_selected(False)
        row.set_selected(True)
        self.selected_row = row
        self._set_actions(True)

        entry = row.entry
        self.head.configure(text=entry.name)
        self.sub.configure(text=f"{entry.subtitle}  ·  Loading icons…")
        self._refresh_sources()
        self._seed_query(entry)
        self._load_artwork(entry)

    def _set_actions(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.browse_btn.configure(state=state)
        self.restore_btn.configure(state=state)
        # Bulk assignment needs a source that can match without user input.
        if self.provider().id == "steam":
            if not self.bulk_btn.winfo_ismapped():
                self.bulk_btn.pack(side="right")
        else:
            self.bulk_btn.pack_forget()

    def _update_summary(self):
        entries = self.current_entries()
        done = sum(1 for e in entries if e.customized)
        self.status.configure(
            text=f"{len(entries)} {self.provider().noun}  ·  {done} customized")
        self.count_pill.configure(text=str(len(self.rows)))

    # -- sources ----------------------------------------------------------

    def _refresh_sources(self):
        provider_id = self.provider().id
        browsable = self.sources.browsable_for(provider_id, self.config_data)
        self._source_labels = {s.label: s.id for s in browsable}
        labels = list(self._source_labels)

        self.source_selector.configure(values=labels)
        if self.source_var.get() not in labels:
            self.source_var.set(labels[0] if labels else "")

        # A picker with one option is just a label taking up space.
        if len(labels) > 1:
            self.source_row.grid()
        else:
            self.source_row.grid_remove()

        self._refresh_query_row()

    def _refresh_query_row(self):
        source = self.source()
        if source is not None and source.needs_query:
            self.query_label.configure(text=source.query_label)
            self.query_entry.configure(placeholder_text=source.query_placeholder)
            self.query_row.grid()
        else:
            self.query_row.grid_remove()
            self._cancel_query_job()

    def _seed_query(self, entry: AppEntry):
        source = self.source()
        if source is None or not source.needs_query:
            return
        provider = self.providers.for_entry(entry)
        query = provider.artwork_query(entry)
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

    def _clear_grid(self):
        for widget in self.grid_area.winfo_children():
            widget.destroy()
        self._tiles.clear()
        self._grid_cols = 0

    def _showing(self, entry: AppEntry) -> bool:
        """Namespaced keys, so a Steam appid cannot alias a .desktop name."""
        return bool(self.selected_row) and self.selected_row.entry.key == entry.key

    def _sub_if_current(self, entry: AppEntry, text: str):
        if self._showing(entry):
            self.sub.configure(text=text)

    def _scroll_top(self):
        """Destroying tiles leaves the canvas scrolled where the previous,
        longer list was, so a shorter list renders above the visible area."""
        try:
            canvas = self.grid_area._parent_canvas
            canvas.update_idletasks()
            canvas.yview_moveto(0.0)
        except (AttributeError, tk.TclError):
            pass

    def _load_artwork(self, entry: AppEntry):
        self._clear_grid()
        self._scroll_top()
        self.after_idle(self._scroll_top)

        source = self.source()
        if source is None:
            self._sub_if_current(entry, "No icon source available.")
            return
        if not source.available(self.config_data):
            self._sub_if_current(entry, source.unavailable_reason(self.config_data))
            return

        provider = self.providers.for_entry(entry)
        query = provider.artwork_query(entry)
        if source.needs_query:
            query = query.with_text(self.query_var.get().strip())
            if not query.text:
                self._sub_if_current(entry, f"Type a term to search {source.label}.")
                return

        def work():
            try:
                results = source.find(query)
                if not results:
                    self.after(0, self._sub_if_current, entry,
                               f"{entry.subtitle}  ·  Nothing found in {source.label}")
                    return
                self.after(0, self._sub_if_current, entry,
                           f"{entry.subtitle}  ·  {len(results)} icons  ·  {source.label}")
                # Lay the full grid out first so it settles into its final
                # shape, then stream artwork into the placeholders.
                self.after(0, self._build_tiles, results, entry)
                for index, art in enumerate(results):
                    try:
                        data = source.preview(art)
                    except Exception:
                        continue
                    self.after(0, self._fill_tile, index, data, entry)
            except Exception as exc:
                self.after(0, self._sub_if_current, entry, str(exc))

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
                cell = self._tiles[0].winfo_reqwidth() + GRID_GUTTER
            except tk.TclError:
                cell = (T.TILE_SIZE + 36) * T.UI_SCALE
        else:
            cell = (T.TILE_SIZE + 36) * T.UI_SCALE
        # Tolerate a few pixels of slop so a near-exact fit still counts.
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

    def _build_tiles(self, results: list[Artwork], entry: AppEntry):
        if not self._showing(entry):
            return
        self._tiles = []
        cols = self._fit_columns()
        self._grid_cols = cols
        for index, art in enumerate(results):
            row, col = divmod(index, cols)
            tile = ArtworkTile(self.grid_area, art, on_pick=self._pick,
                               on_svg_missing=self._svg_hint)
            tile.grid(row=row, column=col, padx=6, pady=6, sticky="n")
            self._tiles.append(tile)
        self.after_idle(self._scroll_top)
        self.after_idle(lambda: self._regrid(self._fit_columns()))

    def _fill_tile(self, index: int, data: bytes, entry: AppEntry):
        if not self._showing(entry) or index >= len(self._tiles):
            return
        try:
            self._tiles[index].set_image(data)
        except tk.TclError:
            pass

    def _svg_hint(self):
        if not self._svg_hint_shown:
            self._svg_hint_shown = True
            self.status.configure(
                text="Install cairosvg to preview SVG icons; they still apply correctly.")

    # -- applying ---------------------------------------------------------

    def _pick(self, art: Artwork):
        if not self.selected_row:
            return
        entry = self.selected_row.entry
        source = self.sources.get(art.source_id)
        if source is None:
            return
        self.sub.configure(text="Downloading icon…")

        def work():
            try:
                stem = f"{entry.local_id.replace('/', '_')}_{art.id}"
                path = source.fetch(art, paths.icon_store(), stem)
                self.after(0, self._apply, entry, path)
            except Exception as exc:
                self.after(0, self._sub_if_current, entry, f"Download failed: {exc}")

        threading.Thread(target=work, daemon=True).start()

    def _apply(self, entry: AppEntry, icon: Path):
        provider = self.providers.for_entry(entry)
        try:
            provider.writer().apply(entry, icon)
        except Exception as exc:
            messagebox.showerror("Could not apply icon", str(exc))
            return
        database.refresh()
        row = self._row_for(entry)
        if row:
            row.refresh()
        if self._showing(entry):
            self.sub.configure(text=f"{entry.subtitle}  ·  Icon applied")
        self._update_summary()

    def _row_for(self, entry: AppEntry) -> AppRow | None:
        for row in self.rows:
            if row.entry.key == entry.key:
                return row
        return None

    def _on_browse(self):
        if not self.selected_row:
            return
        entry = self.selected_row.entry
        chosen = filedialog.askopenfilename(
            title=f"Icon for {entry.name}",
            filetypes=[("Icon images", "*.ico *.png *.svg *.xpm"), ("All", "*.*")])
        if not chosen:
            return
        art = LocalFileSource.artwork_for(Path(chosen))
        self._pick(art)

    def _on_restore(self):
        if not self.selected_row:
            return
        entry = self.selected_row.entry
        provider = self.providers.for_entry(entry)
        writer = provider.writer()

        allowed, reason = writer.can_restore(entry)
        if not allowed:
            messagebox.showinfo("Nothing to restore", reason)
            return
        if not messagebox.askyesno("Restore original",
                                   f"Restore the original icon for {entry.name}?"):
            return
        try:
            writer.restore(entry)
        except Exception as exc:
            messagebox.showerror("Restore refused", str(exc))
            return
        database.refresh()
        provider.refresh(entry)
        row = self._row_for(entry)
        if row:
            row.refresh()
        self.sub.configure(text=f"{entry.subtitle}  ·  Restored")
        self._update_summary()

    # -- bulk -------------------------------------------------------------

    def _on_bulk(self):
        provider = self.provider()
        source = self.sources.get("steamgriddb")
        if provider.id != "steam" or source is None:
            self.status.configure(text="Auto-assign is only available for Steam games.")
            return
        if not source.available(self.config_data):
            messagebox.showinfo("API key required",
                                source.unavailable_reason(self.config_data))
            return

        todo = [e for e in self.current_entries() if not e.customized]
        if not todo:
            self.status.configure(text="Every game already has artwork.")
            return
        if not messagebox.askyesno(
                "Auto-assign", f"Fetch the best icon for {len(todo)} game(s)?"):
            return

        self.bulk_btn.configure(state="disabled", text="Working…")
        writer = provider.writer()

        def work():
            done = 0
            failures: list[str] = []
            for index, entry in enumerate(todo):
                self.after(0, lambda e=entry, n=index: self.status.configure(
                    text=f"({n + 1}/{len(todo)}) {e.name}…"))
                try:
                    results = source.find(provider.artwork_query(entry))
                    if not results:
                        failures.append(f"{entry.name}: no artwork found")
                        continue
                    best = results[0]
                    stem = f"{entry.local_id}_{best.id}"
                    path = source.fetch(best, paths.icon_store(), stem)
                    writer.apply(entry, path)
                    done += 1
                except Exception as exc:
                    failures.append(f"{entry.name}: {exc}")
                finally:
                    time.sleep(0.3)      # stay under the API rate limit

            database.refresh()

            def finish():
                self.bulk_btn.configure(state="normal", text="⬇  Auto-assign all")
                self.status.configure(
                    text=f"Done — {done} assigned, {len(failures)} skipped")
                self._filter()
                self._update_summary()
                if failures:
                    messagebox.showwarning(
                        "Some games were skipped",
                        "\n".join(failures[:40])
                        + ("\n…" if len(failures) > 40 else ""))

            self.after(0, finish)

        threading.Thread(target=work, daemon=True).start()

    # -- settings ---------------------------------------------------------

    def _open_settings(self):
        dialog = SettingsDialog(self, self.config_data)
        # Wait for the dialog to close before reloading. Without this the
        # reload ran against the file as it was *before* the user saved, and
        # only worked at all because the dialog mutates the same dict.
        self.wait_window(dialog)
        self.config_data = config_store.load()
        self.sources = artwork_registry(self.config_data)
        self._refresh_sources()
