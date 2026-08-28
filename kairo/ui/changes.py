"""The Changes window — everything Kairo has done, and how to undo it."""

from __future__ import annotations

import threading
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from kairo import actions
from kairo.desktop.lookup import resolve_icon
from kairo.ledger import ChangeRecord, Ledger
from kairo.tasks import CancelToken
from kairo.ui import theme as T
from kairo.ui.widgets import IconWell


def _previous_icon_path(record: ChangeRecord) -> Path | None:
    """Where the application's original icon lives, if it can still be found.

    The recorded value may be a bare theme name rather than a path, so it goes
    through the same resolution the scanner uses.
    """
    if not record.original_icon:
        return None
    return resolve_icon(record.original_icon)


class ChangeRow(ctk.CTkFrame):
    def __init__(self, master, record: ChangeRecord, on_restore, **kw):
        super().__init__(master, corner_radius=T.R_CARD, fg_color=T.C_ROW, **kw)
        self.record = record
        self._on_restore = on_restore
        self.grid_columnconfigure(3, weight=1)

        self.before = IconWell(self, size=48)
        self.before.grid(row=0, column=0, rowspan=2, padx=(12, 4), pady=12)
        self.before.show(_previous_icon_path(record), placeholder="—")

        ctk.CTkLabel(self, text="→", font=T.F_BODY, text_color=T.C_TEXT3
                     ).grid(row=0, column=1, rowspan=2, padx=2)

        self.after = IconWell(self, size=48)
        self.after.grid(row=0, column=2, rowspan=2, padx=(4, 12), pady=12)
        self.after.show(record.applied_icon_path)

        ctk.CTkLabel(self, text=T.ellipsize(record.name, 34), anchor="w",
                     font=T.F_BODY_B, text_color=T.C_TEXT
                     ).grid(row=0, column=3, sticky="sw", pady=(12, 0))

        source = record.source_label or record.source_id or "a local file"
        detail = f"{source}  ·  {T.format_date(record.applied_at)}"
        allowed, reason = Ledger.restorable(record)
        if not allowed:
            detail = reason
        ctk.CTkLabel(self, text=T.ellipsize(detail, 60), anchor="w",
                     font=T.F_ITEM_SUB,
                     text_color=T.C_TEXT3 if allowed else T.C_DANGER
                     ).grid(row=1, column=3, sticky="nw", pady=(0, 12))

        self.button = ctk.CTkButton(
            self, text="Restore", width=90, height=32, corner_radius=16,
            fg_color=T.C_CARD, hover_color=T.C_CARD_HOVER, text_color=T.C_TEXT,
            font=T.F_BUTTON, command=lambda: self._on_restore(self.record),
            state="normal" if allowed else "disabled")
        self.button.grid(row=0, column=4, rowspan=2, padx=(8, 12))


class ChangesWindow(ctk.CTkToplevel):
    """A window rather than a panel: it is consulted occasionally, and it must
    not compete with the browsing UI for space."""

    def __init__(self, parent, ledger: Ledger, registry, on_finished=None):
        super().__init__(parent)
        self.ledger = ledger
        self.registry = registry
        self.on_finished = on_finished
        self._token: CancelToken | None = None

        self.title("Changes made by Kairo")
        self.geometry("820x620")
        self.configure(fg_color=T.C_BG)
        self.transient(parent)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=24, pady=(24, 8))
        ctk.CTkLabel(head, text="Changes", font=T.F_TITLE,
                     text_color=T.C_TEXT).pack(side="left")
        self.count = ctk.CTkLabel(head, text="", font=T.F_SMALL,
                                  text_color=T.C_TEXT3)
        self.count.pack(side="left", padx=(12, 0))

        self.list = ctk.CTkScrollableFrame(
            self, fg_color=T.C_PANEL, corner_radius=T.R_CARD,
            scrollbar_fg_color="transparent", scrollbar_button_color=T.C_CARD)
        self.list.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 8))
        self.list.grid_columnconfigure(0, weight=1)

        self.status = ctk.CTkLabel(self, text="", font=T.F_TINY,
                                   text_color=T.C_TEXT3)
        self.status.grid(row=2, column=0, sticky="w", padx=28)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=24, pady=(8, 20))
        self.close_btn = ctk.CTkButton(
            footer, text="Close", height=40, corner_radius=20,
            fg_color=T.C_CARD, hover_color=T.C_CARD_HOVER, text_color=T.C_TEXT,
            font=T.F_BUTTON, command=self._close)
        self.close_btn.pack(side="right")
        self.restore_all_btn = ctk.CTkButton(
            footer, text="Restore all", height=40, corner_radius=20,
            fg_color=T.C_DANGER_BG, hover_color="#3a2020", text_color=T.C_DANGER,
            font=T.F_BUTTON, command=self._restore_all)
        self.restore_all_btn.pack(side="right", padx=(0, 8))
        self.cancel_btn = ctk.CTkButton(
            footer, text="Cancel", height=40, corner_radius=20,
            fg_color=T.C_CARD, hover_color=T.C_CARD_HOVER, text_color=T.C_TEXT,
            font=T.F_BUTTON, command=self._cancel)

        self.refresh()

    # -- list ------------------------------------------------------------

    def refresh(self):
        for widget in self.list.winfo_children():
            widget.destroy()

        records = self.ledger.records()
        self.count.configure(
            text=f"{len(records)} application(s) customised by Kairo")
        self.restore_all_btn.configure(
            state="normal" if records else "disabled")

        if not records:
            ctk.CTkLabel(
                self.list,
                text="Kairo has not changed anything yet.\n\n"
                     "Artwork you apply will be listed here, and you can "
                     "put any of it back.",
                font=T.F_BODY, text_color=T.C_TEXT3, justify="left"
            ).grid(row=0, column=0, sticky="w", padx=20, pady=28)
            return

        for index, record in enumerate(records):
            row = ChangeRow(self.list, record, on_restore=self._restore_one)
            row.grid(row=index, column=0, sticky="ew", padx=8, pady=4)

    # -- actions ---------------------------------------------------------

    def _restore_one(self, record: ChangeRecord):
        if not messagebox.askyesno(
                "Restore original",
                f"Put back the original icon for {record.name}?", parent=self):
            return
        try:
            actions.restore_record(record, self.registry,
                                   ledger=self.ledger, refresh=True)
        except Exception as exc:
            messagebox.showerror("Could not restore", str(exc), parent=self)
        self.status.configure(text=f"Restored {record.name}.")
        self.refresh()
        self._notify()

    def _restore_all(self):
        total = len(self.ledger.records())
        if not messagebox.askyesno(
                "Restore everything",
                f"Put back the original icons for all {total} application(s)?\n\n"
                "Anything Kairo no longer recognises will be left alone.",
                parent=self):
            return

        self._token = CancelToken()
        self.restore_all_btn.configure(state="disabled")
        self.cancel_btn.pack(side="right", padx=(0, 8))

        def progress(index, count, record):
            self.after(0, lambda: self.status.configure(
                text=f"({index + 1}/{count}) {record.name}…"))

        def work():
            summary = actions.restore_all(self.ledger, self.registry,
                                          token=self._token,
                                          on_progress=progress)

            def finish():
                self.cancel_btn.pack_forget()
                self.restore_all_btn.configure(state="normal")
                self.status.configure(text=summary.describe())
                self.refresh()
                self._notify()
                if summary.skips or summary.failures:
                    messagebox.showinfo(
                        "Restore finished",
                        summary.describe() + "\n\n"
                        + "\n".join((summary.skips + summary.failures)[:20]),
                        parent=self)

            self.after(0, finish)

        threading.Thread(target=work, daemon=True).start()

    def _cancel(self):
        if self._token is not None:
            self._token.cancel()
        self.status.configure(text="Stopping…")

    def _notify(self):
        if self.on_finished is not None:
            self.on_finished()

    def _close(self):
        self._cancel()
        self.destroy()
