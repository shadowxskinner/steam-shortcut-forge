"""The left column: what Kairo can show you.

Navigation is built from the provider registry rather than hard-coded, so a
provider that declares ``group = "Emulators"`` appears under an Emulators
heading without this module knowing anything about emulators - or about Steam,
for that matter. The only entries this module names are the two that are not
providers at all.
"""

from __future__ import annotations

from dataclasses import dataclass

import customtkinter as ctk

from kairo.ui import theme as T
from kairo.ui.widgets import NavIcon

VIEW_CHANGES = "view:changes"
VIEW_SETTINGS = "view:settings"

GROUP_MANAGEMENT = "Management"

#: Icons for the destinations this module owns.
VIEW_ICONS = {VIEW_CHANGES: "history", VIEW_SETTINGS: "sliders"}

#: Icons for providers that shipped before nav_icon existed. A provider may
#: name its own through a ``nav_icon`` attribute; anything unrecognised falls
#: back by group, so a future emulator gets the chip without supplying
#: anything at all.
PROVIDER_ICONS = {"steam": "steam", "desktop": "grid"}
GROUP_ICONS = {"Emulators": "chip"}


def icon_for(item: "NavItem") -> str:
    if item.provider is not None:
        named = getattr(item.provider, "nav_icon", None)
        if named:
            return named
        return PROVIDER_ICONS.get(item.provider.id,
                                  GROUP_ICONS.get(item.group, "chip"))
    return VIEW_ICONS.get(item.key, "chip")


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    group: str
    provider: object | None = None
    subtitle: str = ""


def build_items(registry) -> list[NavItem]:
    """Providers first, grouped as they declare, then the fixed destinations."""
    providers = registry.available() or registry.all()

    groups: dict[str, list] = {}
    for provider in providers:
        groups.setdefault(provider.group, []).append(provider)

    items: list[NavItem] = []
    for group, members in groups.items():
        for provider in sorted(members, key=lambda p: (p.order, p.label)):
            items.append(NavItem(key=f"provider:{provider.id}",
                                 label=provider.label, group=group,
                                 provider=provider))

    items.append(NavItem(key=VIEW_CHANGES, label="Changes",
                         group=GROUP_MANAGEMENT))
    items.append(NavItem(key=VIEW_SETTINGS, label="Settings",
                         group=GROUP_MANAGEMENT))
    return items


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
