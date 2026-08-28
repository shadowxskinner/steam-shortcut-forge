"""Sidebar rows and artwork tiles."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import customtkinter as ctk

from kairo import imaging
from kairo.models import AppEntry, Artwork
from kairo.ui import theme as T


class IconWell(ctk.CTkFrame):
    """A fixed-footprint rounded square holding one icon.

    Used wherever icons sit beside each other and must line up: the sidebar,
    the Changes list, and the current-to-suggested pairs in review.
    """

    def __init__(self, master, size: int = 48, **kw):
        super().__init__(master, width=size, height=size,
                         corner_radius=T.R_WELL, fg_color=T.C_CARD, **kw)
        self.size = size
        self._photo = None
        self.grid_propagate(False)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.label = ctk.CTkLabel(self, text="", width=1, height=1)
        self.label.grid(row=0, column=0)

    def show(self, path=None, placeholder: str = "○") -> None:
        if path is None or not Path(str(path)).is_file():
            self.label.configure(image=None, text=placeholder,
                                 font=("Inter", max(14, self.size // 3)),
                                 text_color=T.C_TEXT3)
            return
        try:
            self._photo = imaging.load_icon(self.size - 12, path=Path(str(path)))
            self.label.configure(image=self._photo, text="")
        except (tk.TclError, OSError, ValueError):
            self.label.configure(image=None, text="?", text_color=T.C_TEXT3)


class AppRow(ctk.CTkFrame):
    """One application in the sidebar list."""

    THUMB = T.THUMB_SIZE

    def __init__(self, master, entry: AppEntry, on_click, **kw):
        super().__init__(master, corner_radius=T.R_CARD, fg_color=T.C_ROW,
                         height=T.ROW_HEIGHT, **kw)
        self.entry = entry
        self._on_click = on_click
        self._selected = False
        self._photo = None

        self.configure(cursor="hand2")
        self.grid_columnconfigure(2, weight=1)

        # Rounded square that keeps every icon the same footprint.
        self.well = ctk.CTkFrame(self, width=self.THUMB, height=self.THUMB,
                                 corner_radius=T.R_WELL, fg_color=T.C_CARD)
        self.well.grid(row=0, column=0, rowspan=2, padx=(10, 0), pady=10)
        self.well.grid_propagate(False)
        self.well.grid_rowconfigure(0, weight=1)
        self.well.grid_columnconfigure(0, weight=1)

        self.thumb = ctk.CTkLabel(self.well, text="", width=1, height=1)
        self.thumb.grid(row=0, column=0)
        self._load_thumb()

        self.name_lbl = ctk.CTkLabel(self, text=T.ellipsize(entry.name, 22),
                                     anchor="w", font=T.F_ITEM, text_color=T.C_TEXT)
        self.name_lbl.grid(row=0, column=2, sticky="sw", padx=(14, 12), pady=(12, 0))

        self.sub_lbl = ctk.CTkLabel(self, text=self._subtitle(), anchor="w",
                                    font=T.F_ITEM_SUB, text_color=self._sub_colour())
        self.sub_lbl.grid(row=1, column=2, sticky="nw", padx=(14, 12), pady=(2, 12))

        for widget in (self, self.well, self.thumb, self.name_lbl, self.sub_lbl):
            widget.bind("<Button-1>", lambda _: self._on_click(self))
            widget.bind("<Enter>", self._enter)
            widget.bind("<Leave>", self._leave)

    def _subtitle(self) -> str:
        text = self.entry.subtitle or self.entry.local_id
        return f"{text}  ·  ●" if self.entry.customized else text

    def _sub_colour(self) -> str:
        return T.C_SUCCESS if self.entry.customized else T.C_TEXT3

    def _load_thumb(self):
        icon = self.entry.current_icon
        if not icon or not icon.exists():
            self.thumb.configure(image=None, text="○", font=("Inter", 26),
                                 text_color=T.C_TEXT3)
            return
        try:
            self._photo = imaging.load_icon(self.THUMB - 16, path=icon)
            self.thumb.configure(image=self._photo, text="")
        except (tk.TclError, OSError, ValueError):
            self.thumb.configure(image=None, text="○", font=("Inter", 24),
                                 text_color=T.C_TEXT3)

    def _enter(self, _=None):
        if not self._selected:
            self.configure(fg_color=T.C_CARD_HOVER)

    def _leave(self, _=None):
        if not self._selected:
            self.configure(fg_color=T.C_ROW)

    def set_selected(self, selected: bool):
        self._selected = selected
        self.configure(fg_color=T.C_CARD_SELECTED if selected else T.C_ROW)
        self.well.configure(fg_color=T.C_ROW if selected else T.C_CARD)
        self.name_lbl.configure(text_color=T.C_TEXT)
        if not self.entry.customized:
            self.sub_lbl.configure(text_color="#cfe6ff" if selected else T.C_TEXT3)

    def refresh(self):
        self.sub_lbl.configure(text=self._subtitle(), text_color=self._sub_colour())
        self._load_thumb()


class ArtworkTile(ctk.CTkFrame):
    """One candidate icon in the main grid."""

    def __init__(self, master, art: Artwork, on_pick, on_svg_missing=None, **kw):
        super().__init__(master, corner_radius=T.R_CARD, fg_color=T.C_ROW,
                         border_width=2, border_color=T.C_ROW, **kw)
        self.art = art
        self._on_pick = on_pick
        self._on_svg_missing = on_svg_missing
        self._photo = None

        self.configure(cursor="hand2")

        self.well = ctk.CTkFrame(self, width=T.TILE_SIZE, height=T.TILE_SIZE,
                                 corner_radius=T.R_WELL, fg_color=T.C_CARD)
        self.well.pack(padx=10, pady=(10, 8))
        self.well.pack_propagate(False)

        # Placeholder, so the tile occupies its final footprint immediately and
        # the grid never reflows as images stream in.
        self.holder = ctk.CTkLabel(self.well, text="",
                                   width=T.TILE_SIZE - 24, height=T.TILE_SIZE - 24)
        self.holder.place(relx=0.5, rely=0.5, anchor="center")

        size = art.dimensions or "—"
        votes = f"▲{int(art.score)}" if art.score > 0 else ""
        ctk.CTkLabel(self, text=f"{size}  {votes}".strip(), font=T.F_TINY,
                     text_color=T.C_TEXT3).pack(pady=(0, 4))

        label = art.label or "custom"
        if art.kind == "logo":
            label = f"{label} logo"
        ctk.CTkLabel(
            self, text=T.ellipsize(label, 22), font=T.F_TINY,
            text_color=T.C_ACCENT if art.official else T.C_TEXT2,
            fg_color=T.C_ACCENT_DIM if art.official else T.C_CARD,
            corner_radius=10, height=20,
        ).pack(padx=12, pady=(0, 12), fill="x")

        self._bind_hover()

    def set_image(self, data: bytes) -> None:
        try:
            self._photo = imaging.load_icon(T.TILE_SIZE - 24, data=data)
        except (tk.TclError, OSError, ValueError):
            if (self._on_svg_missing and data and imaging.looks_svg(data)
                    and not imaging.svg_available()):
                self._on_svg_missing()
            self.holder.configure(text="?", font=T.F_HEADING, text_color=T.C_TEXT3)
            return
        self.holder.configure(image=self._photo, text="")
        self._bind_hover()

    def _bind_hover(self):
        """Highlight the whole tile, including its children.

        Binding only the outer frame breaks as soon as the pointer reaches a
        child: Tk delivers <Leave> to the parent and the border drops out while
        the cursor is still visibly over the tile.
        """
        def walk(widget):
            yield widget
            for child in widget.winfo_children():
                yield from walk(child)

        for widget in walk(self):
            widget.bind("<Enter>",
                        lambda _: self.configure(border_color=T.C_ACCENT), add="+")
            widget.bind("<Leave>", lambda _: self._maybe_unhighlight(), add="+")
            widget.bind("<Button-1>", lambda _: self._on_pick(self.art), add="+")

    def _maybe_unhighlight(self):
        try:
            x, y = self.winfo_pointerxy()
            inside = (self.winfo_rootx() <= x < self.winfo_rootx() + self.winfo_width()
                      and self.winfo_rooty() <= y < self.winfo_rooty() + self.winfo_height())
            if not inside:
                self.configure(border_color=T.C_ROW)
        except tk.TclError:
            pass
