"""The left column: what Kairo can show you.

Navigation is built from the provider registry rather than hard-coded, so a
provider that declares ``group = "Emulators"`` appears under an Emulators
heading without this module knowing anything about emulators - or about Steam,
for that matter. The only entries this module names are the two that are not
providers at all.
"""

from __future__ import annotations

import customtkinter as ctk

from kairo.ui import theme as T
from kairo.ui.widgets import NavIcon

# The model - which providers appear, how they group, which icon each gets -
# lives in kairo.navmodel so both frontends build the same navigation from the
# same registry. Re-exported here so existing imports keep working.
from kairo.navmodel import (  # noqa: F401  (re-export)
    GROUP_MANAGEMENT, GROUP_ICONS, PROVIDER_ICONS, VIEW_CHANGES, VIEW_ICONS,
    VIEW_SETTINGS, NavItem, build_items, icon_for)


class NavButton(ctk.CTkFrame):
    def __init__(self, master, item: NavItem, on_click, **kw):
        super().__init__(master, corner_radius=T.R_MD, fg_color="transparent",
                         height=T.H_NAV_ITEM, **kw)
        self.item = item
        self._on_click = on_click
        self._selected = False
        self.grid_propagate(False)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.configure(cursor="hand2")

        self.icon = NavIcon(self, kind=icon_for(item), bg=T.C_NAV)
        self.icon.grid(row=0, column=0, padx=(T.S3, T.S3))
        # Kept for callers that referred to the old lettered chip.
        self.chip = self.icon

        self.label = ctk.CTkLabel(self, text=item.label, anchor="w",
                                  font=T.F_ROW, text_color=T.C_TEXT2)
        self.label.grid(row=0, column=1, sticky="w")

        # Fixed width so every count in the column shares one right edge.
        self.count = ctk.CTkLabel(self, text="", font=T.F_META,
                                  text_color=T.C_TEXT3, anchor="e", width=26)
        self.count.grid(row=0, column=2, sticky="e", padx=(0, T.S3))

        for widget in (self, self.icon, self.label, self.count):
            widget.bind("<Button-1>", lambda _event: self._on_click(self.item))
            widget.bind("<Enter>", self._enter)
            widget.bind("<Leave>", self._leave)

    def set_count(self, value) -> None:
        self.count.configure(text="" if value is None else str(value))

    def _enter(self, _event=None):
        if not self._selected:
            self.configure(fg_color=T.C_CARD)
            self.icon.set_state(T.C_TEXT2, T.C_CARD)

    def _leave(self, _event=None):
        if not self._selected:
            self.configure(fg_color="transparent")
            self.icon.set_state(T.C_TEXT3, T.C_NAV)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        fill = T.C_SELECTED_NAV if selected else "transparent"
        self.configure(fg_color=fill)
        self.label.configure(text_color=T.C_TEXT if selected else T.C_TEXT2,
                             font=T.F_ROW_STRONG if selected else T.F_ROW)
        self.count.configure(text_color=T.C_TEXT2 if selected else T.C_TEXT3)
        self.icon.set_state(T.C_ACCENT_TEXT if selected else T.C_TEXT3,
                            T.C_SELECTED_NAV if selected else T.C_NAV)


class NavColumn(ctk.CTkFrame):
    """Grouped navigation. Knows nothing about what any provider contains."""

    def __init__(self, master, items: list[NavItem], on_select, **kw):
        super().__init__(master, fg_color=T.C_NAV, corner_radius=0,
                         width=T.W_NAV, **kw)
        self._on_select = on_select
        self.buttons: dict[str, NavButton] = {}
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)

        row = 0
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=row, column=0, sticky="ew",
                    padx=T.PAD_COLUMN, pady=(T.S6, T.S5))
        ctk.CTkLabel(header, text="KAIRO", font=T.F_LOGO,
                     text_color=T.C_TEXT).pack(side="left")
        ctk.CTkLabel(header, text="回路", font=T.F_META,
                     text_color=T.C_TEXT3).pack(side="left", padx=(T.S2, 0))
        row += 1

        current_group = None
        for item in items:
            if item.group != current_group:
                current_group = item.group
                heading = "  ".join(item.group.upper())   # airy letterspacing
                ctk.CTkLabel(self, text=heading, anchor="w",
                             font=T.F_MICRO, text_color=T.C_TEXT3
                             ).grid(row=row, column=0, sticky="ew",
                                    padx=T.PAD_COLUMN + T.S2,
                                    pady=(T.S5, T.S1))
                row += 1
            button = NavButton(self, item, on_click=self._select)
            button.grid(row=row, column=0, sticky="ew",
                        padx=T.S2, pady=T.GAP_ROW // 2)
            self.buttons[item.key] = button
            row += 1

        self.grid_rowconfigure(row, weight=1)

    def _select(self, item: NavItem) -> None:
        self.set_selected(item.key)
        self._on_select(item)

    def set_selected(self, key: str) -> None:
        for button_key, button in self.buttons.items():
            button.set_selected(button_key == key)

    def set_count(self, key: str, value) -> None:
        button = self.buttons.get(key)
        if button is not None:
            button.set_count(value)
