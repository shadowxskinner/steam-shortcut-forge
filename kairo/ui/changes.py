"""The Changes window — everything Kairo has done, and how to undo it."""

from __future__ import annotations

import threading
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from kairo import actions, housekeeping
from kairo.desktop.lookup import resolve_icon
from kairo.ledger import ChangeRecord, Ledger, deletes_launcher
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
    def __init__(self, master, record: ChangeRecord, on_restore, on_remove, **kw):
        super().__init__(master, corner_radius=T.R_CARD, fg_color=T.C_ROW, **kw)
        self.record = record
        self._on_restore = on_restore
        self._on_remove = on_remove
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

        if record.adopted:
            source = "Existing customization"
        else:
            source = record.source_label or record.source_id or "a local file"
        detail = f"{source}  ·  {T.format_date(record.applied_at)}"
        allowed, reason = Ledger.restorable(record)
        if not allowed:
            detail = reason
        ctk.CTkLabel(self, text=T.ellipsize(detail, 60), anchor="w",
                     font=T.F_ITEM_SUB,
                     text_color=T.C_TEXT3 if allowed else T.C_DANGER
                     ).grid(row=1, column=3, sticky="nw", pady=(0, 12))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=0, column=4, rowspan=2, padx=(8, 12))

        # A generated shortcut has no earlier artwork, so its ordinary undo is
        # a reset rather than a restore. Deleting it is a separate button.
        verb = "Reset" if deletes_launcher(record.action) else "Restore"
        self.button = ctk.CTkButton(
            buttons, text=verb, width=94, height=30, corner_radius=15,
            fg_color=T.C_CARD, hover_color=T.C_CARD_HOVER, text_color=T.C_TEXT,
            font=T.F_BUTTON, command=lambda: self._on_restore(self.record),
            state="normal" if allowed else "disabled")
        self.button.pack(pady=(0, 4))

        if deletes_launcher(record.action):
            self.remove_button = ctk.CTkButton(
                buttons, text="Remove", width=94, height=30, corner_radius=15,
                fg_color=T.C_DANGER_BG, hover_color="#3a2020",
                text_color=T.C_DANGER, font=T.F_BUTTON,
                command=lambda: self._on_remove(self.record),
                state="normal" if allowed else "disabled")
            self.remove_button.pack()


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
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(120, self._make_modal)

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
        self.cleanup_btn = ctk.CTkButton(
            footer, text="Clean up unused artwork", height=40, corner_radius=20,
            fg_color=T.C_CARD, hover_color=T.C_CARD_HOVER, text_color=T.C_TEXT2,
            font=T.F_BUTTON, command=self._cleanup)
        self.cleanup_btn.pack(side="left")
        self.cancel_btn = ctk.CTkButton(
            footer, text="Cancel", height=40, corner_radius=20,
            fg_color=T.C_CARD, hover_color=T.C_CARD_HOVER, text_color=T.C_TEXT,
            font=T.F_BUTTON, command=self._cancel)

        self.refresh()

    def _make_modal(self):
        try:
            self.grab_set()
        except Exception:
            pass

    def _cleanup(self):
        """Delete artwork no launcher entry points at.

        Reference-based, never history-based: an icon survives if anything at
        all in the applications directory still names it.
        """
        preview = housekeeping.sweep(dry_run=True)
        if not preview.removed:
            messagebox.showinfo("Nothing to clean up",
                                "Every icon Kairo stores is still in use.",
                                parent=self)
            return
        megabytes = preview.freed_bytes / (1024 * 1024)
        if not messagebox.askyesno(
                "Clean up unused artwork",
                f"{preview.removed} icon(s) in Kairo's own store are not used "
                f"by any launcher entry, taking {megabytes:.1f} MB.\n\n"
                "Delete them? Nothing currently in use is touched.",
                parent=self):
            return
        result = housekeeping.sweep()
        self.status.configure(text=result.describe())
        if result.failures:
            messagebox.showwarning("Some files could not be removed",
                                   "\n".join(result.failures[:20]), parent=self)

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
            row = ChangeRow(self.list, record, on_restore=self._restore_one,
                            on_remove=self._remove_one)
            row.grid(row=index, column=0, sticky="ew", padx=8, pady=4)

    # -- actions ---------------------------------------------------------

    def _remove_one(self, record: ChangeRecord):
        """Delete a shortcut Kairo created. The destructive path."""
        from kairo import actions
        if not messagebox.askyesno(
                "Remove shortcut",
                f"Delete the launcher shortcut Kairo created for "
                f"{record.name}?\n\nThe application itself is not affected.",
                parent=self):
            return
        provider = self.registry.get(record.provider_id)
        try:
            actions.remove_entry(actions.entry_from_record(record), provider,
                                 ledger=self.ledger)
        except Exception as exc:
            messagebox.showerror("Could not remove", str(exc), parent=self)
            self.status.configure(text=f"Could not remove {record.name}.")
            self.refresh()
            return
        self.status.configure(text=f"Removed the shortcut for {record.name}.")
        self.refresh()
        self._notify()

    def _restore_one(self, record: ChangeRecord):
        if deletes_launcher(record.action):
            title = "Reset artwork"
            body = (f"Reset {record.name} to a default icon?\n\n"
                    "The shortcut stays where it is — only the custom "
                    "artwork goes away.")
        else:
            title = "Restore original"
            body = (f"Put back the original icon for {record.name}?\n\n"
                    "The application keeps its launcher entry.")
        if not messagebox.askyesno(title, body, parent=self):
            return
        try:
            actions.restore_record(record, self.registry,
                                   ledger=self.ledger, refresh=True)
        except Exception as exc:
            messagebox.showerror("Could not restore", str(exc), parent=self)
            self.status.configure(text=f"Could not restore {record.name}.")
            self.refresh()
            return
        self.status.configure(text=f"Restored {record.name}.")
        self.refresh()
        self._notify()

    def _restore_all(self):
        records = self.ledger.records()
        if not records:
            return

        resets = [r for r in records if deletes_launcher(r.action)]
        reverts = [r for r in records if not deletes_launcher(r.action)]

        # Nothing here deletes a launcher entry. Two different outcomes still
        # hide behind one button, so both are spelled out.
        lines = [f"This affects {len(records)} application(s):", ""]
        if reverts:
            lines.append(f"  • {len(reverts)} will go back to their original "
                         "icon and keep their launcher entry.")
        if resets:
            lines.append(f"  • {len(resets)} shortcut(s) Kairo created will "
                         "keep their entry and go back to a default icon.")
        lines.append("")
        lines.append("No launcher shortcuts are deleted. To remove one, use "
                     "its own Remove button.")
        lines.append("Anything Kairo no longer recognises is left alone.")

        if not messagebox.askyesno("Restore everything", "\n".join(lines),
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
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
