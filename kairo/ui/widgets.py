"""Sidebar rows and artwork tiles."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import customtkinter as ctk

from kairo import imaging
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


def _glyph_steam(canvas, colour):
    canvas.create_oval(2, 2, 16, 16, outline=colour, width=1.4)
    canvas.create_oval(9, 9, 14, 14, fill=colour, outline=colour)


def _glyph_grid(canvas, colour):
    for x, y in ((2, 2), (10, 2), (2, 10), (10, 10)):
        canvas.create_rectangle(x, y, x + 6, y + 6, outline=colour, width=1.3)


def _glyph_history(canvas, colour):
    canvas.create_arc(2, 2, 16, 16, start=40, extent=280, style="arc",
                      outline=colour, width=1.4)
    canvas.create_polygon(13, 1, 17, 5, 12, 6, fill=colour, outline=colour)


def _glyph_sliders(canvas, colour):
    for index, y in enumerate((4, 9, 14)):
        canvas.create_line(2, y, 16, y, fill=colour, width=1.3)
        knob = (11, 5, 13)[index]
        canvas.create_oval(knob - 2, y - 2, knob + 2, y + 2,
                           fill=colour, outline=colour)


def _glyph_chip(canvas, colour):
    canvas.create_rectangle(4, 4, 14, 14, outline=colour, width=1.3)
    for offset in (6, 12):
        canvas.create_line(offset, 1, offset, 4, fill=colour, width=1.2)
        canvas.create_line(offset, 14, offset, 17, fill=colour, width=1.2)
        canvas.create_line(1, offset, 4, offset, fill=colour, width=1.2)
        canvas.create_line(14, offset, 17, offset, fill=colour, width=1.2)


GLYPHS = {
    "steam": _glyph_steam,
    "grid": _glyph_grid,
    "history": _glyph_history,
    "sliders": _glyph_sliders,
    "chip": _glyph_chip,
}


class NavIcon(ctk.CTkCanvas):
    """A small monochrome pictogram, drawn rather than shipped or fonted.

    Eighteen pixels of canvas primitives: no image assets to package, no glyph
    font to be missing on someone's machine, and no dependency beyond what Tk
    already provides. A provider may name one through ``nav_icon``; anything
    that does not gets a neutral chip.
    """

    SIZE = 18

    def __init__(self, master, kind: str = "chip", bg: str = T.C_NAV, **kw):
        super().__init__(master, width=self.SIZE, height=self.SIZE,
                         highlightthickness=0, borderwidth=0, bg=bg, **kw)
        self._kind = kind if kind in GLYPHS else "chip"
        self._colour = T.C_TEXT3
        self.redraw()

    def set_state(self, colour: str, bg: str) -> None:
        self._colour = colour
        try:
            self.configure(bg=bg)
        except Exception:
            pass
        self.redraw()

    def redraw(self) -> None:
        try:
            self.delete("all")
        except Exception:
            return
        GLYPHS.get(self._kind, _glyph_chip)(self, self._colour)


#: Roughly the advertised width of one character of the pill font, plus the
#: padding either side. CTkButton defaults to 140px regardless of its label,
#: which is how three filter pills came to need more room than the column had
#: and clipped "Untouched" to "touch...".
PILL_CHAR_WIDTH = 7
PILL_PADDING = 22


def pill_width(text: str) -> int:
    return max(44, len(text) * PILL_CHAR_WIDTH + PILL_PADDING)


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
                self, text=value, width=pill_width(value),
                height=T.H_PILL - 6, corner_radius=T.R_PILL,
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
                fg_color=T.C_ACCENT_BRIGHT if active else "transparent",
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
                                  font=("Inter", max(11, self._size // 5)),
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
    """One application in the entry column.

    Rebindable rather than disposable. Filtering used to destroy and recreate
    every row on each keystroke, which with a few hundred applications meant
    hundreds of widget teardowns and icon decodes per character typed. Rows are
    now reused: the pane keeps a pool and points each row at a different entry.
    """

    THUMB = T.THUMB_SIZE

    def __init__(self, master, entry=None, on_click=None, **kw):
        super().__init__(master, corner_radius=T.R_MD, fg_color=T.C_CARD,
                         height=T.H_ROW, **kw)
        self.entry = entry
        self._on_click = on_click
        self._selected = False

        self.grid_propagate(False)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.well = IconWell(self, size=self.THUMB)
        self.well.grid(row=0, column=0, rowspan=2, padx=(T.S3, 0), pady=T.S3)

        self.name_lbl = ctk.CTkLabel(self, text="", anchor="w", font=T.F_ROW,
                                     text_color=T.C_TEXT)
        self.name_lbl.grid(row=0, column=1, sticky="sw", padx=(T.S3, T.S2))

        self.sub_lbl = ctk.CTkLabel(self, text="", anchor="w", font=T.F_META,
                                    text_color=T.C_TEXT3)
        self.sub_lbl.grid(row=1, column=1, sticky="nw", padx=(T.S3, T.S2))

        self.dot = ctk.CTkLabel(self, text="", font=T.F_META,
                                text_color=T.C_SUCCESS, width=14)
        self.dot.grid(row=0, column=2, rowspan=2, padx=(0, T.S3))

        for widget in (self, self.well, self.well.image_label,
                       self.well.text_label, self.name_lbl, self.sub_lbl,
                       self.dot):
            widget.bind("<Button-1>", lambda _event: self._clicked())
            widget.bind("<Enter>", self._enter)
            widget.bind("<Leave>", self._leave)

        self.configure(cursor="hand2")
        if entry is not None:
            self.bind_entry(entry)

    # -- content ----------------------------------------------------------

    def bind_entry(self, entry) -> None:
        """Point this row at a different application."""
        self.entry = entry
        self.name_lbl.configure(text=T.ellipsize(entry.name, T.LIST_NAME_CHARS))
        self.sub_lbl.configure(text=T.ellipsize(entry.subtitle or entry.local_id, 38))
        self.dot.configure(text="●" if entry.customized else "")
        self.well.show(entry.current_icon, placeholder="○")

    def refresh(self) -> None:
        if self.entry is not None:
            self.bind_entry(self.entry)
            self.set_selected(self._selected)

    def _clicked(self):
        if self._on_click is not None and self.entry is not None:
            self._on_click(self)

    # -- state ------------------------------------------------------------

    def _enter(self, _event=None):
        if not self._selected:
            self.configure(fg_color=T.C_CARD_HOVER)

    def _leave(self, _event=None):
        if not self._selected:
            self.configure(fg_color=T.C_CARD)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.configure(fg_color=T.C_SELECTED if selected else T.C_CARD,
                       border_width=1 if selected else 0,
                       border_color=T.C_ACCENT if selected else T.C_CARD)
        self.well.configure(fg_color=T.C_PANEL)
        self.name_lbl.configure(font=T.F_ROW_STRONG if selected else T.F_ROW,
                                text_color=T.C_TEXT)
        self.sub_lbl.configure(
            text_color=T.C_ACCENT_TEXT if selected else T.C_TEXT3)


class ArtworkTile(ctk.CTkFrame):
    """One candidate icon. Image first, chrome barely there."""

    def __init__(self, master, art, on_pick=None, on_svg_missing=None, **kw):
        super().__init__(master, corner_radius=T.R_MD, fg_color=T.C_CARD,
                         border_width=2, border_color=T.C_CARD, **kw)
        self.art = art
        self._on_pick = on_pick
        self._on_svg_missing = on_svg_missing
        self._chosen = False

        self.configure(cursor="hand2")

        # Placeholder first, so the tile takes its final footprint immediately
        # and the grid never reflows as artwork streams in.
        self.well = IconWell(self, size=T.TILE_SIZE)
        self.well.configure(fg_color=T.C_PANEL)
        self.well.pack(padx=T.S2, pady=(T.S2, T.S1))
        self.well.show_placeholder("")
        self.holder = self.well.text_label

        caption = art.label or ("official" if art.official else "")
        if art.kind == "logo":
            caption = f"{caption} logo".strip()
        self.caption = ctk.CTkLabel(
            self, text=T.ellipsize(caption or art.dimensions or " ", 18),
            font=T.F_META,
            text_color=T.C_ACCENT_TEXT if art.official else T.C_TEXT3)
        self.caption.pack(padx=T.S2, pady=(0, T.S2))

        self._bind_hover()

    def set_image(self, data: bytes) -> None:
        try:
            photo = imaging.load_icon(T.TILE_SIZE - 16, data=data)
        except Exception:
            if (self._on_svg_missing and data and imaging.looks_svg(data)
                    and not imaging.svg_available()):
                self._on_svg_missing()
            self.well.show_placeholder("?")
            return
        self.well.show_photo(photo)
        self._bind_hover()

    def set_chosen(self, chosen: bool) -> None:
        """The tile currently proposed. Selection has to be unmistakable when
        choosing artwork is separate from applying it."""
        self._chosen = chosen
        self.configure(border_color=T.C_ACCENT_BRIGHT if chosen else T.C_CARD,
                       fg_color=T.C_ACCENT_SOFT if chosen else T.C_CARD)

    def _bind_hover(self):
        """Bind every descendant.

        Binding only the outer frame breaks as soon as the pointer reaches a
        child: Tk delivers <Leave> to the parent and the highlight drops out
        while the cursor is still visibly over the tile.
        """
        def walk(widget):
            yield widget
            for child in widget.winfo_children():
                yield from walk(child)

        for widget in walk(self):
            widget.bind("<Enter>", lambda _event: self._hover(True), add="+")
            widget.bind("<Leave>", lambda _event: self._maybe_unhover(), add="+")
            widget.bind("<Button-1>", lambda _event: self._pick(), add="+")

    def _pick(self):
        if self._on_pick is not None:
            self._on_pick(self.art)

    def _hover(self, on: bool):
        if self._chosen:
            return
        self.configure(border_color=T.C_BORDER_STRONG if on else T.C_CARD)

    def _maybe_unhover(self):
        """Only drop the highlight once the pointer has actually left."""
        if self._chosen:
            return
        try:
            x, y = self.winfo_pointerxy()
            inside = (self.winfo_rootx() <= x < self.winfo_rootx() + self.winfo_width()
                      and self.winfo_rooty() <= y < self.winfo_rooty() + self.winfo_height())
            if not inside:
                self.configure(border_color=T.C_CARD)
        except tk.TclError:
            pass


class NavChip(ctk.CTkLabel):
    """A small lettered square standing in for a provider icon.

    Deliberately generated rather than shipped as artwork: a future provider
    gets a chip that matches the rest without supplying an asset, and nothing
    depends on a glyph font being installed.
    """

    def __init__(self, master, text: str, **kw):
        super().__init__(master, text=T.initial(text), width=22, height=22,
                         corner_radius=T.R_SM, fg_color=T.C_CARD,
                         text_color=T.C_TEXT3, font=T.F_MICRO, **kw)

    def set_selected(self, selected: bool) -> None:
        self.configure(fg_color=T.C_ACCENT if selected else T.C_CARD,
                       text_color=T.C_TEXT if selected else T.C_TEXT3)
