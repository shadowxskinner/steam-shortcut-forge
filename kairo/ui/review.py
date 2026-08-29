"""The review screen — Current → Suggested, before anything is written.

Nothing in this window touches the launcher until Apply is pressed. That is
the point of it: the match pass has already worked out what Kairo believes,
and this is where the user agrees or disagrees.
"""

from __future__ import annotations

import threading
from tkinter import messagebox

import customtkinter as ctk

from kairo import actions
from kairo.matching import Match, MatchReport
from kairo.tasks import CancelToken
from kairo.ui import theme as T
from kairo.ui.widgets import IconWell


class ReviewRow(ctk.CTkFrame):
    def __init__(self, master, match: Match, on_change, **kw):
        super().__init__(master, corner_radius=T.R_CARD, fg_color=T.C_ROW, **kw)
        self.match = match
        # Nothing is ticked to begin with. A screen that opens with three
        # hundred rows pre-selected turns one misplaced click into three
        # hundred changes, and the point of a review step is that the user
        # chooses.
        self.selected = ctk.BooleanVar(value=False)
        self.skipped = False
        self._on_change = on_change
        self.grid_columnconfigure(4, weight=1)

        self.check = ctk.CTkCheckBox(
            self, text="", variable=self.selected, width=24,
            checkbox_width=20, checkbox_height=20, corner_radius=6,
            fg_color=T.C_ACCENT, hover_color=T.C_ACCENT_HOVER)
        self.check.grid(row=0, column=0, rowspan=2, padx=(14, 6))

        self.current = IconWell(self, size=52)
        self.current.grid(row=0, column=1, rowspan=2, padx=4, pady=12)
        self.current.show(match.entry.current_icon, placeholder="—")

        ctk.CTkLabel(self, text="→", font=T.F_BODY, text_color=T.C_TEXT3
                     ).grid(row=0, column=2, rowspan=2, padx=4)

        self.suggested = IconWell(self, size=52)
        self.suggested.grid(row=0, column=3, rowspan=2, padx=(4, 12), pady=12)

        ctk.CTkLabel(self, text=T.ellipsize(match.entry.name, 32), anchor="w",
                     font=T.F_BODY_B, text_color=T.C_TEXT
                     ).grid(row=0, column=4, sticky="sw", pady=(12, 0))

        detail = (f"{T.confidence_label(match.confidence)}  ·  "
                  f"{match.source_label}  ·  {match.reason}")
        self.detail = ctk.CTkLabel(self, text=T.ellipsize(detail, 64), anchor="w",
                                   font=T.F_ITEM_SUB, text_color=T.C_TEXT3)
        self.detail.grid(row=1, column=4, sticky="nw", pady=(0, 12))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=0, column=5, rowspan=2, padx=(8, 12))
        ctk.CTkButton(buttons, text="Change…", width=84, height=30,
                      corner_radius=15, fg_color=T.C_CARD,
                      hover_color=T.C_CARD_HOVER, text_color=T.C_TEXT,
                      font=T.F_TINY,
                      command=lambda: self._on_change(self.match)).pack(pady=(0, 4))
        self.skip_btn = ctk.CTkButton(buttons, text="Skip", width=84, height=30,
                                      corner_radius=15, fg_color="transparent",
                                      hover_color=T.C_CARD_HOVER,
                                      text_color=T.C_TEXT3, font=T.F_TINY,
                                      border_width=1, border_color=T.C_BORDER,
                                      command=self._skip)
        self.skip_btn.pack()

    def load_preview(self, data: bytes) -> None:
        try:
            from kairo import imaging
            self.suggested._photo = imaging.load_icon(40, data=data)
            self.suggested.label.configure(image=self.suggested._photo, text="")
        except Exception:
            self.suggested.label.configure(text="?", text_color=T.C_TEXT3)

    def _skip(self):
        self.skipped = True
        self.selected.set(False)
        self.check.configure(state="disabled")
        self.skip_btn.configure(state="disabled")
        self.detail.configure(text="Skipped — left as it is",
                              text_color=T.C_TEXT3)

    @property
    def wanted(self) -> bool:
        return bool(self.selected.get()) and not self.skipped


class ReviewWindow(ctk.CTkToplevel):
    def __init__(self, parent, report: MatchReport, registry, sources, ledger,
                 on_applied=None):
        super().__init__(parent)
        self.report = report
        self.registry = registry
        self.sources = sources
        self.ledger = ledger
        self.on_applied = on_applied
        self.rows: list[ReviewRow] = []
        self._token: CancelToken | None = None
        self._preview_token: CancelToken | None = None

        self.title("Review artwork")
        self.geometry("900x680")
        self.configure(fg_color=T.C_BG)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._close)
        # Modal: the main window must not be able to start a second matching
        # run behind this one and end up with two review workflows competing
        # over the same applications.
        self.after(120, self._make_modal)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(self, text=report.headline(), font=T.F_TITLE,
                     text_color=T.C_TEXT).grid(row=0, column=0, sticky="w",
                                               padx=24, pady=(24, 2))
        ctk.CTkLabel(
            self,
            text="Nothing is selected and nothing changes until you apply. "
                 f"{len(report.unmatched)} application(s) had no confident match "
                 "and were left out.",
            font=T.F_SMALL, text_color=T.C_TEXT3
        ).grid(row=1, column=0, sticky="w", padx=24, pady=(0, 12))

        self.list = ctk.CTkScrollableFrame(
            self, fg_color=T.C_PANEL, corner_radius=T.R_CARD,
            scrollbar_fg_color="transparent", scrollbar_button_color=T.C_CARD)
        self.list.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 8))
        self.list.grid_columnconfigure(0, weight=1)

        self.progress = ctk.CTkProgressBar(self, height=6,
                                           progress_color=T.C_ACCENT)
        self.progress.set(0)

        self.status = ctk.CTkLabel(self, text="", font=T.F_TINY,
                                   text_color=T.C_TEXT3)
        self.status.grid(row=4, column=0, sticky="w", padx=28)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=5, column=0, sticky="ew", padx=24, pady=(8, 20))
        ctk.CTkButton(footer, text="Select all", height=36, width=100,
                      corner_radius=18, fg_color=T.C_CARD,
                      hover_color=T.C_CARD_HOVER, text_color=T.C_TEXT2,
                      font=T.F_BUTTON,
                      command=lambda: self._set_all(True)).pack(side="left")
        ctk.CTkButton(footer, text="Select none", height=36, width=110,
                      corner_radius=18, fg_color=T.C_CARD,
                      hover_color=T.C_CARD_HOVER, text_color=T.C_TEXT2,
                      font=T.F_BUTTON,
                      command=lambda: self._set_all(False)).pack(side="left",
                                                                 padx=(8, 0))

        self.close_btn = ctk.CTkButton(
            footer, text="Close", height=40, corner_radius=20,
            fg_color=T.C_CARD, hover_color=T.C_CARD_HOVER, text_color=T.C_TEXT,
            font=T.F_BUTTON, command=self._close)
        self.close_btn.pack(side="right")
        self.apply_all_btn = ctk.CTkButton(
            footer, text="Apply all", height=40, corner_radius=20,
            fg_color=T.C_CARD, hover_color=T.C_CARD_HOVER, text_color=T.C_TEXT,
            font=T.F_BUTTON, command=self._apply_all)
        self.apply_all_btn.pack(side="right", padx=(0, 8))
        self.apply_btn = ctk.CTkButton(
            footer, text="Apply selected", height=40, corner_radius=20,
            fg_color=T.C_ACCENT, hover_color=T.C_ACCENT_HOVER,
            font=T.F_BUTTON, command=self._apply_selected)
        self.apply_btn.pack(side="right", padx=(0, 8))
        self.cancel_btn = ctk.CTkButton(
            footer, text="Cancel", height=40, corner_radius=20,
            fg_color=T.C_DANGER_BG, hover_color="#3a2020", text_color=T.C_DANGER,
            font=T.F_BUTTON, command=self._cancel)

        self._build_rows()
        self._stream_previews()

    def _make_modal(self):
        try:
            self.grab_set()
        except Exception:
            pass          # a grab is a nicety; never fail the window over it

    # -- rows ------------------------------------------------------------

    def _build_rows(self):
        if not self.report.matches:
            ctk.CTkLabel(
                self.list,
                text="No confident matches this time.\n\n"
                     "Kairo would rather find nothing than put the wrong icon "
                     "on an application.\nYou can still pick artwork yourself "
                     "from the main window.",
                font=T.F_BODY, text_color=T.C_TEXT3, justify="left"
            ).grid(row=0, column=0, sticky="w", padx=20, pady=28)
            self.apply_btn.configure(state="disabled")
            self.apply_all_btn.configure(state="disabled")
            return

        for index, match in enumerate(self.report.matches):
            row = ReviewRow(self.list, match, on_change=self._change_one)
            row.grid(row=index, column=0, sticky="ew", padx=8, pady=4)
            self.rows.append(row)

    def _stream_previews(self):
        """Fetch the suggested artwork for display only.

        Cancelled when the window closes, so shutting the review down does not
        leave a download loop running for artwork nobody will see.
        """
        self._preview_token = CancelToken()
        token = self._preview_token

        def work():
            for row in list(self.rows):
                if token.cancelled:
                    return
                source = self.sources.get(row.match.source_id)
                if source is None:
                    continue
                try:
                    data = source.preview(row.match.artwork)
                except Exception:
                    continue
                if token.cancelled:
                    return
                self.after(0, lambda r=row, d=data: r.load_preview(d))

        threading.Thread(target=work, daemon=True).start()

    def _set_all(self, value: bool):
        for row in self.rows:
            if not row.skipped:
                row.selected.set(value)

    def _change_one(self, match: Match):
        """Deferred to the main window's picker rather than duplicating a grid."""
        messagebox.showinfo(
            "Change artwork",
            f"Close this window and select {match.entry.name} in the main list "
            "to browse every available icon for it.",
            parent=self)

    # -- applying --------------------------------------------------------

    def _apply_all(self):
        """Explicitly select everything, then apply.

        Skipped rows stay skipped - _set_all leaves them alone.
        """
        candidates = [row for row in self.rows if not row.skipped]
        if not candidates:
            self.status.configure(text="Nothing to apply.")
            return
        if not messagebox.askyesno(
                "Apply all",
                f"Select and apply artwork to all {len(candidates)} matched "
                "application(s)?", parent=self):
            return
        self._set_all(True)
        self._apply_selected(confirmed=True)

    def _apply_selected(self, confirmed: bool = False):
        chosen = [row for row in self.rows if row.wanted]
        if not chosen:
            self.status.configure(text="Nothing selected — tick a row first.")
            return
        if not confirmed and not messagebox.askyesno(
                "Apply artwork",
                f"Apply artwork to {len(chosen)} application(s)?", parent=self):
            return

        plans = []
        for row in chosen:
            source = self.sources.get(row.match.source_id)
            if source is None:
                continue
            plans.append((row.match.entry, source, row.match.artwork))

        self._token = CancelToken()
        self.apply_btn.configure(state="disabled")
        self.apply_all_btn.configure(state="disabled")
        self.close_btn.pack_forget()
        self.cancel_btn.pack(side="right")
        self.progress.grid(row=3, column=0, sticky="ew", padx=28, pady=(4, 4))
        self.progress.set(0)

        def progress(index, total, plan):
            self.after(0, lambda: (
                self.progress.set((index + 1) / max(total, 1)),
                self.status.configure(text=f"({index + 1}/{total}) {plan[0].name}…"),
            ))

        def work():
            summary = actions.apply_many(plans, self.registry, ledger=self.ledger,
                                         token=self._token, on_progress=progress)

            def finish():
                self.progress.grid_remove()
                self.cancel_btn.pack_forget()
                self.close_btn.pack(side="right")
                self.apply_btn.configure(state="normal")
                self.apply_all_btn.configure(state="normal")
                self.status.configure(text=summary.describe())
                if self.on_applied is not None:
                    self.on_applied()
                detail = summary.failures + summary.skips
                messagebox.showinfo(
                    "Finished", summary.describe()
                    + (("\n\n" + "\n".join(detail[:20])) if detail else ""),
                    parent=self)

            self.after(0, finish)

        threading.Thread(target=work, daemon=True).start()

    def _cancel(self):
        if self._token is not None:
            self._token.cancel()
        self.status.configure(text="Stopping after the current application…")

    def _close(self):
        if self._preview_token is not None:
            self._preview_token.cancel()
        if self._token is not None:
            self._token.cancel()
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
