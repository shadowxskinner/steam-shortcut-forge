"""The Changes destination: everything Kairo has done, and how to undo it."""

from __future__ import annotations

import threading
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from kairo import actions, housekeeping
from kairo.desktop.lookup import resolve_icon
from kairo.ledger import ChangeRecord, Ledger, deletes_launcher
from kairo.tasks import CancelToken
from kairo.ui import ambience
from kairo.ui import theme as T
from kairo.ui.context import UIContext
from kairo.ui.widgets import IconWell


def previous_icon_path(record: ChangeRecord) -> Path | None:
    """The original icon, resolved. Often a bare theme name, not a path."""
    if not record.original_icon:
        return None
    return resolve_icon(record.original_icon)


class ChangeRow(ctk.CTkFrame):
    def __init__(self, master, record: ChangeRecord, on_restore, on_remove, **kw):
        super().__init__(master, corner_radius=T.R_MD, fg_color=T.C_CARD, **kw)
        self.record = record
        self.grid_columnconfigure(3, weight=1)

        before = IconWell(self, size=T.THUMB_SIZE)
        before.configure(fg_color=T.C_PANEL)
        before.grid(row=0, column=0, rowspan=2, padx=(T.S3, T.S1), pady=T.S3)
        before.show(previous_icon_path(record), placeholder="—")
        ctk.CTkLabel(self, text="→", font=T.F_META, text_color=T.C_TEXT3
                     ).grid(row=0, column=1, rowspan=2, padx=T.S1)
        after = IconWell(self, size=T.THUMB_SIZE)
        after.configure(fg_color=T.C_PANEL)
        after.grid(row=0, column=2, rowspan=2, padx=(T.S1, T.S3), pady=T.S3)
        after.show(record.applied_icon_path)

        ctk.CTkLabel(self, text=T.ellipsize(record.name, 34), anchor="w",
                     font=T.F_ROW, text_color=T.C_TEXT
                     ).grid(row=0, column=3, sticky="sw", pady=(T.S3, 0))

        source = ("Existing customization" if record.adopted
                  else record.source_label or record.source_id or "a local file")
        allowed, reason = Ledger.restorable(record)
        detail = (f"{source}  ·  {T.format_date(record.applied_at)}"
                  if allowed else reason)
        ctk.CTkLabel(self, text=T.ellipsize(detail, 62), anchor="w",
                     font=T.F_META,
                     text_color=T.C_TEXT3 if allowed else T.C_DANGER
                     ).grid(row=1, column=3, sticky="nw", pady=(0, T.S3))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=0, column=4, rowspan=2, padx=(T.S2, T.S3))
        state = "normal" if allowed else "disabled"
        ctk.CTkButton(
            buttons, text="Reset" if deletes_launcher(record.action) else "Restore",
            width=94, height=28, corner_radius=T.R_SM, fg_color=T.C_CARD_HOVER,
            hover_color=T.C_ACCENT, text_color=T.C_TEXT, font=T.F_PILL,
            state=state, command=lambda: on_restore(record)).pack(pady=(0, T.S1))
        if deletes_launcher(record.action):
            ctk.CTkButton(
                buttons, text="Remove", width=94, height=28,
                corner_radius=T.R_SM, fg_color=T.C_DANGER_BG,
                hover_color=T.C_DANGER_HOVER, text_color=T.C_DANGER,
                font=T.F_PILL, state=state,
                command=lambda: on_remove(record)).pack()


class ChangesPane(ctk.CTkFrame):
    def __init__(self, master, context: UIContext, **kw):
        super().__init__(master, fg_color=T.C_BG, corner_radius=0, **kw)
        ambience.attach(self)
        self.ctx = context
        self._token: CancelToken | None = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew",
                  padx=T.PAD_WINDOW, pady=(T.S5, T.S3))
        titles = ctk.CTkFrame(head, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(titles, text="Changes", font=T.F_TITLE,
                     text_color=T.C_TEXT, anchor="w").pack(anchor="w")
        self.count = ctk.CTkLabel(titles, text="", font=T.F_META,
                                  text_color=T.C_TEXT3, anchor="w")
        self.count.pack(anchor="w", pady=(1, 0))

        self.restore_all_btn = ctk.CTkButton(
            head, text="Restore all", height=T.H_FIELD, corner_radius=T.R_WELL,
            fg_color=T.C_CARD, hover_color=T.C_CARD_HOVER, text_color=T.C_TEXT,
            font=T.F_BUTTON, command=self._restore_all)
        self.restore_all_btn.pack(side="right")
        self.cleanup_btn = ctk.CTkButton(
            head, text="Clean up unused artwork", height=38,
            corner_radius=T.R_WELL, fg_color=T.C_CARD,
            hover_color=T.C_CARD_HOVER, text_color=T.C_TEXT2, font=T.F_BUTTON,
            command=self._cleanup)
        self.cleanup_btn.pack(side="right", padx=(0, T.GAP_CONTROL))
        self.cancel_btn = ctk.CTkButton(
            head, text="Cancel", height=T.H_FIELD, corner_radius=T.R_WELL,
            fg_color=T.C_DANGER_BG, hover_color=T.C_DANGER_HOVER,
            text_color=T.C_DANGER, font=T.F_BUTTON, command=self._cancel)

        self.list = ctk.CTkScrollableFrame(
            self, fg_color=T.C_PANEL, corner_radius=T.R_LG,
            border_width=1, border_color=T.C_BORDER,
            scrollbar_fg_color="transparent", scrollbar_button_color=T.C_CARD)
        self.list.grid(row=1, column=0, sticky="nsew",
                       padx=T.PAD_WINDOW - T.S1, pady=(0, T.S3))
        self.list.grid_columnconfigure(0, weight=1)

        self.status = ctk.CTkLabel(self, text="", font=T.F_TINY,
                                   text_color=T.C_TEXT3)
        self.status.grid(row=2, column=0, sticky="w",
                         padx=T.PAD_WINDOW, pady=(0, T.S5))

        self.refresh()

    def refresh(self):
        for widget in self.list.winfo_children():
            widget.destroy()
        records = self.ctx.ledger.records()
        self.count.configure(
            text=f"{len(records)} application(s) customised by Kairo")
        self.restore_all_btn.configure(state="normal" if records else "disabled")

        if not records:
            ctk.CTkLabel(
                self.list,
                text="Kairo has not changed anything yet.\n\n"
                     "Artwork you apply appears here, and you can put any of "
                     "it back.",
                font=T.F_BODY, text_color=T.C_TEXT3, justify="left"
            ).grid(row=0, column=0, sticky="w", padx=T.S5, pady=T.S8)
            return

        for index, record in enumerate(records):
            ChangeRow(self.list, record, on_restore=self._restore_one,
                      on_remove=self._remove_one
                      ).grid(row=index, column=0, sticky="ew",
                             padx=T.S2, pady=T.GAP_ROW)

    # -- single record ----------------------------------------------------

    def _restore_one(self, record: ChangeRecord):
        if deletes_launcher(record.action):
            title, body = "Reset artwork", (
                f"Reset {record.name} to a default icon?\n\nThe shortcut stays "
                "where it is — only the custom artwork goes away.")
        else:
            title, body = "Restore original", (
                f"Put back the original icon for {record.name}?\n\n"
                "The application keeps its launcher entry.")
        if not messagebox.askyesno(title, body):
            return
        try:
            actions.restore_record(record, self.ctx.providers,
                                   ledger=self.ctx.ledger, refresh=True)
        except Exception as exc:
            messagebox.showerror("Could not undo", str(exc))
            self.status.configure(text=f"Could not undo {record.name}.")
            self.refresh()
            return
        self.status.configure(text=f"Undone: {record.name}.")
        self.refresh()
        self.ctx.on_changed()

    def _remove_one(self, record: ChangeRecord):
        if not messagebox.askyesno(
                "Remove shortcut",
                f"Delete the launcher shortcut Kairo created for "
                f"{record.name}?\n\nThe application itself is not affected."):
            return
        provider = self.ctx.providers.get(record.provider_id)
        try:
            actions.remove_entry(actions.entry_from_record(record), provider,
                                 ledger=self.ctx.ledger)
        except Exception as exc:
            messagebox.showerror("Could not remove", str(exc))
            self.status.configure(text=f"Could not remove {record.name}.")
            self.refresh()
            return
        self.status.configure(text=f"Removed the shortcut for {record.name}.")
        self.refresh()
        self.ctx.on_changed()

    # -- bulk -------------------------------------------------------------

    def _restore_all(self):
        records = self.ctx.ledger.records()
        if not records:
            return
        resets = [r for r in records if deletes_launcher(r.action)]
        reverts = [r for r in records if not deletes_launcher(r.action)]

        lines = [f"This affects {len(records)} application(s):", ""]
        if reverts:
            lines.append(f"  • {len(reverts)} go back to their original icon "
                         "and keep their launcher entry.")
        if resets:
            lines.append(f"  • {len(resets)} shortcut(s) Kairo created keep "
                         "their entry and go back to a default icon.")
        lines += ["", "No launcher shortcuts are deleted. To remove one, use "
                      "its own Remove button.",
                  "Anything Kairo no longer recognises is left alone."]
        if not messagebox.askyesno("Restore everything", "\n".join(lines)):
            return

        self._token = CancelToken()
        self.restore_all_btn.configure(state="disabled")
        self.cancel_btn.pack(side="right", padx=(0, T.GAP_CONTROL))

        def progress(index, total, record):
            self.after(0, lambda: self.status.configure(
                text=f"({index + 1}/{total}) {record.name}…"))

        def work():
            summary = actions.restore_all(self.ctx.ledger, self.ctx.providers,
                                          token=self._token, on_progress=progress)

            def finish():
                self.cancel_btn.pack_forget()
                self.restore_all_btn.configure(state="normal")
                self.status.configure(text=summary.describe())
                self.refresh()
                self.ctx.on_changed()
                detail = summary.skips + summary.failures
                if detail:
                    messagebox.showinfo(
                        "Finished",
                        summary.describe() + "\n\n" + "\n".join(detail[:20]))

            self.after(0, finish)

        threading.Thread(target=work, daemon=True).start()

    def _cancel(self):
        if self._token is not None:
            self._token.cancel()
        self.status.configure(text="Stopping…")

    def _cleanup(self):
        """Reference-based, never history-based."""
        preview = housekeeping.sweep(dry_run=True)
        if not preview.removed:
            messagebox.showinfo("Nothing to clean up",
                                "Every icon Kairo stores is still in use.")
            return
        megabytes = preview.freed_bytes / (1024 * 1024)
        if not messagebox.askyesno(
                "Clean up unused artwork",
                f"{preview.removed} icon(s) in Kairo's store are not used by "
                f"any launcher entry, taking {megabytes:.1f} MB.\n\n"
                "Delete them? Nothing currently in use is touched."):
            return
        result = housekeeping.sweep()
        self.status.configure(text=result.describe())
        if result.failures:
            messagebox.showwarning("Some files could not be removed",
                                   "\n".join(result.failures[:20]))
