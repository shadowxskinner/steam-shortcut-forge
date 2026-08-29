"""The Kairo window: navigation, a content area, and a status line.

Three columns. The left names what Kairo can show you, the middle lists what
is inside the selected thing, and the right is the workspace. The shell itself
knows nothing about Steam, applications or emulators - it renders whatever
providers the registry hands it, grouped as those providers declare.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from kairo import APP_NAME, adoption
from kairo import config as config_store
from kairo import migration
from kairo.artwork.registry import default_registry as artwork_registry
from kairo.artwork.steamgriddb import CONFIG_KEY as SGDB_KEY
from kairo.ledger import Ledger
from kairo.matching import Matcher
from kairo.providers.registry import default_registry as provider_registry
from kairo.tasks import ActivityTokens
from kairo.ui import nav
from kairo.ui import theme as T
from kairo.ui.changes_pane import ChangesPane
from kairo.ui.context import UIContext
from kairo.ui.library import LibraryPane
from kairo.ui.review import ReviewWindow
from kairo.ui.settings_pane import SettingsPane

ACTIVITY_BULK = "bulk"


class KairoShell(ctk.CTk):
    def __init__(self):
        super().__init__(fg_color=T.C_BG)
        self.title(APP_NAME)
        self.geometry("1420x900")
        self.minsize(1120, 700)

        # Before anything reads config.
        try:
            self._migration = migration.migrate_if_needed()
        except Exception as exc:                       # pragma: no cover
            self._migration = migration.MigrationReport(failures=[str(exc)])

        self.config_data = config_store.load()
        self.providers = provider_registry()
        self.sources = artwork_registry(self.config_data)
        self.ledger = Ledger().load()
        self.tokens = ActivityTokens()
        self._review_window = None

        self.ctx = UIContext(providers=self.providers, sources=self.sources,
                             config=self.config_data, ledger=self.ledger,
                             tokens=self.tokens, on_changed=self._on_changed,
                             set_status=self.set_status)

        self.items = nav.build_items(self.providers)
        self.panes: dict[str, ctk.CTkFrame] = {}
        self.current_key: str | None = None

        self.protocol("WM_DELETE_WINDOW", self._quit)
        self._build()
        self._adopt()
        self._announce_migration()
        self._first_run()

        first = next((i for i in self.items if i.provider is not None), None)
        self._select(first or self.items[0])

    # -- layout -----------------------------------------------------------

    def _build(self):
        self.grid_columnconfigure(0, weight=0, minsize=T.W_NAV)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.nav = nav.NavColumn(self, self.items, on_select=self._select)
        self.nav.grid(row=0, column=0, sticky="nsew")

        content = ctk.CTkFrame(self, fg_color=T.C_BG, corner_radius=0)
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_rowconfigure(1, weight=1)
        content.grid_columnconfigure(0, weight=1)

        bar = ctk.CTkFrame(content, fg_color="transparent", height=56)
        bar.grid(row=0, column=0, sticky="ew", padx=26, pady=(14, 0))
        self.match_btn = ctk.CTkButton(
            bar, text="Auto Match", height=T.H_FIELD, width=130,
            corner_radius=T.R_WELL, fg_color=T.C_ACCENT,
            hover_color=T.C_ACCENT_HOVER, font=T.F_BUTTON,
            command=self._auto_match)
        self.match_btn.pack(side="right")
        self.cancel_btn = ctk.CTkButton(
            bar, text="Cancel", height=T.H_FIELD, width=110, corner_radius=T.R_WELL,
            fg_color=T.C_DANGER_BG, hover_color=T.C_DANGER_HOVER,
            text_color=T.C_DANGER, font=T.F_BUTTON, command=self._cancel_bulk)
        ctk.CTkButton(bar, text="Rescan", height=T.H_FIELD, width=100,
                      corner_radius=T.R_WELL, fg_color=T.C_CARD,
                      hover_color=T.C_CARD_HOVER, text_color=T.C_TEXT2,
                      font=T.F_BUTTON, command=self.rescan
                      ).pack(side="right", padx=(0, 8))
        self.progress = ctk.CTkProgressBar(bar, height=4,
                                           progress_color=T.C_ACCENT)

        self.body = ctk.CTkFrame(content, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.grid_rowconfigure(0, weight=1)
        self.body.grid_columnconfigure(0, weight=1)

        self.status = ctk.CTkLabel(content, text="", font=T.F_TINY,
                                   text_color=T.C_TEXT3, anchor="w")
        self.status.grid(row=2, column=0, sticky="ew", padx=26, pady=(0, 10))

    # -- navigation -------------------------------------------------------

    def _pane_for(self, item: nav.NavItem):
        pane = self.panes.get(item.key)
        if pane is not None:
            return pane
        if item.key == nav.VIEW_CHANGES:
            pane = ChangesPane(self.body, self.ctx)
        elif item.key == nav.VIEW_SETTINGS:
            pane = SettingsPane(self.body, self.ctx)
        else:
            pane = LibraryPane(self.body, item.provider, self.ctx)
        self.panes[item.key] = pane
        return pane

    def _select(self, item: nav.NavItem):
        if self.current_key == item.key:
            return
        current = self.panes.get(self.current_key) if self.current_key else None
        if current is not None:
            current.grid_forget()

        pane = self._pane_for(item)
        pane.grid(row=0, column=0, sticky="nsew")
        self.current_key = item.key
        self.nav.set_selected(item.key)

        if hasattr(pane, "refresh"):
            try:
                pane.refresh()
            except Exception:
                pass
        self._on_changed()

    def _on_changed(self):
        """Keep nav counts and the status line honest after any change."""
        for item in self.items:
            if item.provider is None:
                continue
            pane = self.panes.get(item.key)
            self.nav.set_count(item.key,
                               len(pane.entries) if pane is not None else None)
        self.nav.set_count(nav.VIEW_CHANGES, len(self.ledger) or None)

        pane = self.panes.get(self.current_key) if self.current_key else None
        if isinstance(pane, LibraryPane):
            self.set_status(
                f"{len(pane.entries)} {pane.provider.noun}  ·  "
                f"{pane.customized_count()} customized  ·  "
                f"{len(self.ledger)} change(s) recorded")

    def set_status(self, text: str) -> None:
        self.status.configure(text=text)

    # -- startup ----------------------------------------------------------

    def _adopt(self):
        """Pick up launcher entries Kairo owns but has no history for."""
        try:
            adopted = adoption.adopt_untracked(self.ledger, self.providers)
        except Exception:
            adopted = []
        if adopted:
            self.set_status(f"Found {len(adopted)} existing customization(s) "
                            "and added them to Changes.")

    def _announce_migration(self):
        report = getattr(self, "_migration", None)
        if report is None or not report.performed:
            return
        body = (f"{report.summary()}\n\nYour original Steam Shortcut Forge "
                "files have been left where they were, so nothing is lost.")
        detail = report.collisions + report.failures
        if detail:
            body += "\n\nNeeds your attention:\n" + "\n".join(detail[:10])
        messagebox.showinfo(f"Welcome to {APP_NAME}", body)

    def _first_run(self):
        steam = self.providers.get("steam")
        if steam and steam.available() and not self.config_data.get(SGDB_KEY):
            self.set_status("Steam artwork needs a free SteamGridDB API key — "
                            "add one under Settings. Everything else works "
                            "without it.")

    def rescan(self):
        self.ledger.prune()
        self._adopt()
        for pane in self.panes.values():
            if isinstance(pane, LibraryPane):
                pane.refresh_entries()
            elif hasattr(pane, "refresh"):
                pane.refresh()
        self._on_changed()

    # -- auto match -------------------------------------------------------

    def _all_entries(self):
        entries = []
        for provider in self.providers.available():
            pane = self.panes.get(f"provider:{provider.id}")
            if pane is not None:
                entries.extend(pane.entries)
                continue
            try:
                entries.extend(provider.scan())
            except Exception:
                continue
        return entries

    def _auto_match(self):
        if self._window_open(self._review_window):
            self._raise_window(self._review_window)
            self.set_status("Close the review window before matching again.")
            return

        entries = self._all_entries()
        if not entries:
            self.set_status("Nothing to match — try Rescan first.")
            return

        token = self.tokens.start(ACTIVITY_BULK)
        self._bulk_running(True)
        matcher = Matcher(self.providers, self.sources, self.config_data)

        def progress(index, total, entry):
            self.after(0, lambda: (
                self.progress.set((index + 1) / max(total, 1)),
                self.set_status(f"Matching ({index + 1}/{total}) {entry.name}…"),
            ))

        def work():
            report = matcher.match_all(entries, token=token, on_progress=progress)

            def finish():
                self._bulk_running(False)
                if report.cancelled:
                    # Cancelling means stop, not "show me a partial answer".
                    self.set_status(
                        f"Matching cancelled — nothing applied. "
                        f"({report.matched} match(es) had been found.)")
                    return
                self.set_status(report.headline())
                if not report.matches:
                    messagebox.showinfo(
                        "No confident matches",
                        "Kairo did not find artwork it is confident about.\n\n"
                        "It would rather find nothing than put the wrong icon "
                        "on an application. You can still pick artwork "
                        "yourself from the list.")
                    return
                self._review_window = ReviewWindow(
                    self, report, self.providers, self.sources, self.ledger,
                    on_applied=self.rescan)

            self.after(0, finish)

        threading.Thread(target=work, daemon=True).start()

    def _bulk_running(self, running: bool):
        if running:
            self.match_btn.pack_forget()
            self.cancel_btn.pack(side="right")
            self.progress.pack(side="left", fill="x", expand=True, padx=(0, 16))
            self.progress.set(0)
        else:
            self.cancel_btn.pack_forget()
            self.match_btn.pack(side="right")
            self.progress.pack_forget()

    def _cancel_bulk(self):
        self.tokens.cancel(ACTIVITY_BULK)
        self.set_status("Stopping…")

    # -- windows ----------------------------------------------------------

    @staticmethod
    def _window_open(window) -> bool:
        try:
            return window is not None and bool(window.winfo_exists())
        except tk.TclError:
            return False

    @staticmethod
    def _raise_window(window) -> None:
        try:
            window.deiconify()
            window.lift()
            window.focus_force()
        except tk.TclError:
            pass

    def _quit(self):
        self.tokens.cancel_all()
        self.destroy()
