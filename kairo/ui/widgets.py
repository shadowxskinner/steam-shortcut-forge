"""Sidebar rows and artwork tiles."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import customtkinter as ctk

from kairo import imaging
from kairo.models import AppEntry, Artwork
from kairo.ui import theme as T


def apply_image(label, owner, attribute: str, photo, **options) -> None:
    """Put an image on a label, releasing the previous one only afterwards.

    Rebinding the attribute first drops Python's last reference to the old
    image. Tk frees it, and the widget is left holding a handle to an image
    that no longer exists - after which *any* later configure() on that
    widget raises TclError, including one that only changes text. The failure
    surfaces far from its cause, which is what made it worth a helper rather
    than a comment.

    Configuring first keeps the old image alive for the duration of the call,
    because ``owner`` still references it. Only once the widget has stopped
    using it is the reference replaced.
    """
    try:
        label.configure(image=photo, **options)
    except tk.TclError:
        # The widget is already holding a stale handle. Clear it, then retry.
        try:
            label.configure(image=None)
            label.configure(image=photo, **options)
        except tk.TclError:
            setattr(owner, attribute, photo)
            return
    setattr(owner, attribute, photo)


class SegmentedPills(ctk.CTkFrame):
    """A rounded pill group.

    CTkSegmentedButton renders as flat rectangles that read as default Tk
    chrome next to everything else here. This is the same idea drawn to match
    the rest of the window, and it is used for both the source picker and the
    list filters so those two controls stop looking like different products.
    """

    def __init__(self, master, values=None, variable=None, command=None,
                 font=None, **kw):
        super().__init__(master, corner_radius=T.R_PILL, fg_color=T.C_CARD,
                         **kw)
        self._variable = variable
        self._command = command
        self._font = font or T.F_PILL
        self._buttons: dict[str, ctk.CTkButton] = {}
        # Own every attribute up front rather than leaning on getattr
        # defaults; the selection is this widget's state, not an optional.
        self._value = "" if variable is None else variable.get()
        self.set_values(list(values or []))

    # -- values -----------------------------------------------------------

    def values(self) -> list[str]:
        return list(self._buttons)

    def set_values(self, values: list[str]) -> None:
        for button in self._buttons.values():
            button.destroy()
        self._buttons.clear()

        for value in values:
            button = ctk.CTkButton(
                self, text=value, height=T.H_PILL - 6, corner_radius=T.R_PILL,
                fg_color="transparent", hover_color=T.C_CARD_HOVER,
                text_color=T.C_TEXT3, font=self._font,
                command=lambda v=value: self._pick(v))
            button.pack(side="left", padx=2, pady=3)
            self._buttons[value] = button

        # Selection has to survive the value set changing underneath it -
        # sources are pruned per application, so the chosen one can vanish.
        current = self.get()
        if not values:
            current = ""
        elif current not in values:
            current = values[0]
        if self._variable is not None:
            self._variable.set(current)
        else:
            self._value = current
        self._paint(current)

    def get(self) -> str:
        if self._variable is not None:
            return self._variable.get()
        return self._value

    def set(self, value: str) -> None:
        if self._variable is not None:
            self._variable.set(value)
        else:
            self._value = value
        self._paint(value)

    def _pick(self, value: str) -> None:
        self.set(value)
        if self._command is not None:
            self._command(value)

    def _paint(self, selected: str) -> None:
        for value, button in self._buttons.items():
            active = value == selected
            button.configure(
                fg_color=T.C_ACCENT if active else "transparent",
                hover_color=T.C_ACCENT_HOVER if active else T.C_CARD_HOVER,
                text_color=T.C_TEXT if active else T.C_TEXT3)


class SearchField(ctk.CTkFrame):
    """A rounded field with a leading glyph, so search looks designed."""

    def __init__(self, master, textvariable=None, placeholder="Search…", **kw):
        super().__init__(master, corner_radius=T.R_FIELD, fg_color=T.C_CARD,
                         border_width=1, border_color=T.C_BORDER,
                         height=T.H_FIELD, **kw)
        self.grid_propagate(False)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        ctk.CTkLabel(self, text="⌕", font=("Inter", 15),
                     text_color=T.C_TEXT3, width=18
                     ).grid(row=0, column=0, padx=(12, 0))
        self.entry = ctk.CTkEntry(
            self, textvariable=textvariable, placeholder_text=placeholder,
            font=T.F_BODY, fg_color="transparent", border_width=0,
            height=T.H_FIELD - 8)
        self.entry.grid(row=0, column=1, sticky="ew", padx=(4, 10))

    def bind_entry(self, sequence, callback, add="+"):
        """Bind on the inner entry, preserving CustomTkinter's own bindings.

        CTkEntry rejects any `add` other than "+" or True, because it relies
        on internal bindings for placeholder handling. Defaulting to None and
        forwarding it raised on the first keystroke binding.
        """
        self.entry.bind(sequence, callback, add=add)

    def configure_placeholder(self, text: str) -> None:
        self.entry.configure(placeholder_text=text)


class IconWell(ctk.CTkFrame):
    """A fixed-footprint square showing either artwork or a placeholder glyph.

    Two stacked labels rather than one, because CustomTkinter cannot empty a
    label. Its CTkLabel._update_image() only acts when the image is *not*
    None::

        if isinstance(self._image, CTkImage):   self._label.configure(image=...)
        elif self._image is not None:           self._label.configure(image=...)
        # None falls through and the Tk label keeps the previous image

    So configure(image=None) sets CustomTkinter's own bookkeeping to None
    while the underlying Tk label still points at the old image. Releasing our
    reference then frees an image the widget is still holding, and *every*
    later configure() on it raises - including one that only sets text,
    because configure() processes text before image. That is a placeholder
    that cannot clear artwork, followed by a cascade of TclErrors.

    Keeping one label for images and one for text sidesteps all of it: the
    image label is only ever handed a real image, and showing a placeholder
    hides it instead of trying to empty it. The last image stays referenced
    for as long as this widget lives, so nothing it points at is ever freed.
    """

    def __init__(self, master, size: int = 48, **kw):
        super().__init__(master, width=size, height=size,
                         corner_radius=T.R_WELL, fg_color=T.C_CARD, **kw)
        # Not self.size: tkinter.Grid already defines size() as an alias for
        # grid_size(), and shadowing a widget method with an int is the same
        # trap as assigning to self.config.
        self._size = size
        self._photo = None
        self._showing_image = False

        self.grid_propagate(False)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.image_label = ctk.CTkLabel(self, text="", width=1, height=1)
        self.text_label = ctk.CTkLabel(self, text="", width=1, height=1)
        self.text_label.grid(row=0, column=0)

        # Kept for callers that reach for a single label.
        self.label = self.text_label

    @property
    def size(self) -> int:
        return self._size

    # -- showing -----------------------------------------------------------

    def show_placeholder(self, text: str = "○") -> None:
        self.text_label.configure(text=text,
                                  font=("Inter", max(14, self._size // 3)),
                                  text_color=T.C_TEXT3)
        if self._showing_image:
            self.image_label.grid_remove()
        self.text_label.grid(row=0, column=0)
        self._showing_image = False

    def show_photo(self, photo) -> None:
        # Configure before releasing the previous reference: the widget must
        # stop using an image before Python frees it.
        apply_image(self.image_label, self, "_photo", photo, text="")
        if not self._showing_image:
            self.text_label.grid_remove()
        self.image_label.grid(row=0, column=0)
        self._showing_image = True

    def show(self, path=None, placeholder: str = "○") -> None:
        """Render an icon from a path. Never raises into the caller.

        This runs from selection handlers, so a bad icon must degrade to a
        placeholder rather than abort the click.
        """
        if path is None:
            self.show_placeholder(placeholder)
            return
        candidate = Path(str(path))
        if not candidate.is_file():
            self.show_placeholder(placeholder)
            return
        try:
            photo = imaging.load_icon(self._size - 12, path=candidate)
        except Exception:
            self.show_placeholder("?")
            return
        self.show_photo(photo)

    def show_data(self, data: bytes) -> None:
        """Render icon bytes that have already been fetched."""
        try:
            photo = imaging.load_icon(self._size - 12, data=data)
        except Exception:
            self.show_placeholder("?")
            return
        self.show_photo(photo)


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
        self.well = IconWell(self, size=self.THUMB)
        self.well.grid(row=0, column=0, rowspan=2, padx=(10, 0), pady=8)
        self.thumb = self.well.text_label
        self._load_thumb()

        self.name_lbl = ctk.CTkLabel(
            self, text=T.ellipsize(entry.name, T.LIST_NAME_CHARS), anchor="w",
            font=T.F_ITEM, text_color=T.C_TEXT)
        self.name_lbl.grid(row=0, column=2, sticky="sw", padx=(12, 10), pady=(10, 0))

        self.sub_lbl = ctk.CTkLabel(self, text=self._subtitle(), anchor="w",
                                    font=T.F_ITEM_SUB, text_color=self._sub_colour())
        self.sub_lbl.grid(row=1, column=2, sticky="nw", padx=(12, 10), pady=(1, 10))

        for widget in (self, self.well, self.well.image_label,
                       self.well.text_label, self.name_lbl, self.sub_lbl):
            widget.bind("<Button-1>", lambda _: self._on_click(self))
            widget.bind("<Enter>", self._enter)
            widget.bind("<Leave>", self._leave)

    def _subtitle(self) -> str:
        text = self.entry.subtitle or self.entry.local_id
        return f"{text}  ·  ●" if self.entry.customized else text

    def _sub_colour(self) -> str:
        return T.C_SUCCESS if self.entry.customized else T.C_TEXT3

    def _load_thumb(self):
        self.well.show(self.entry.current_icon, placeholder="○")

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

        # Placeholder, so the tile occupies its final footprint immediately and
        # the grid never reflows as images stream in.
        self.well = IconWell(self, size=T.TILE_SIZE)
        self.well.pack(padx=8, pady=(8, 6))
        self.well.show_placeholder("")
        self.holder = self.well.text_label

        size = art.dimensions or ""
        votes = f"▲{int(art.score)}" if art.score > 0 else ""
        meta = "  ".join(part for part in (size, votes) if part)
        if meta:
            ctk.CTkLabel(self, text=meta, font=T.F_TINY,
                         text_color=T.C_TEXT3).pack(pady=(0, 2))

        label = art.label or "custom"
        if art.kind == "logo":
            label = f"{label} logo"
        ctk.CTkLabel(
            self, text=T.ellipsize(label, 20), font=T.F_TINY,
            text_color=T.C_ACCENT if art.official else T.C_TEXT2,
            fg_color=T.C_ACCENT_DIM if art.official else T.C_CARD,
            corner_radius=8, height=18,
        ).pack(padx=8, pady=(0, 8), fill="x")

        self._bind_hover()

    def set_image(self, data: bytes) -> None:
        try:
            photo = imaging.load_icon(T.TILE_SIZE - 18, data=data)
        except Exception:
            if (self._on_svg_missing and data and imaging.looks_svg(data)
                    and not imaging.svg_available()):
                self._on_svg_missing()
            self.well.show_placeholder("?")
            return
        self.well.show_photo(photo)
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
