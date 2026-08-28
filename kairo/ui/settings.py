"""The settings dialog."""

from __future__ import annotations

import customtkinter as ctk

from kairo import config as config_store
from kairo.artwork.steamgriddb import CONFIG_KEY as SGDB_KEY
from kairo.ui import theme as T


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent, config: dict):
        super().__init__(parent)
        # Deliberately not self.config: that shadows tkinter.Misc.config(),
        # which CustomTkinter calls internally on every widget.
        self.cfg = config

        self.title("Settings")
        self.geometry("480x230")
        self.configure(fg_color=T.C_BG)
        self.transient(parent)
        self.grab_set()

        ctk.CTkLabel(self, text="Settings", font=T.F_HEADING,
                     text_color=T.C_TEXT).pack(padx=24, pady=(24, 16), anchor="w")

        box = ctk.CTkFrame(self, fg_color=T.C_PANEL, corner_radius=T.R_CARD)
        box.pack(fill="x", padx=24, pady=(0, 16))

        ctk.CTkLabel(box, text="SteamGridDB API Key", font=T.F_BODY_B,
                     text_color=T.C_TEXT).pack(padx=16, pady=(16, 2), anchor="w")
        ctk.CTkLabel(box, text="Optional — only needed for Steam game artwork",
                     font=T.F_TINY, text_color=T.C_TEXT3).pack(padx=16, anchor="w")
        ctk.CTkLabel(box, text="Free at steamgriddb.com → Profile → API",
                     font=T.F_TINY, text_color=T.C_TEXT3).pack(padx=16, pady=(0, 8),
                                                               anchor="w")

        self.key_entry = ctk.CTkEntry(box, placeholder_text="Paste API key",
                                      font=T.F_BODY, corner_radius=19, height=38)
        self.key_entry.pack(fill="x", padx=16, pady=(0, 16))
        if config.get(SGDB_KEY):
            self.key_entry.insert(0, config[SGDB_KEY])

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=(0, 24))
        ctk.CTkButton(row, text="Cancel", height=34, fg_color=T.C_CARD,
                      hover_color=T.C_CARD_HOVER, text_color=T.C_TEXT,
                      corner_radius=17, font=T.F_BUTTON,
                      command=self.destroy).pack(side="right")
        ctk.CTkButton(row, text="Save", height=34, fg_color=T.C_ACCENT,
                      hover_color=T.C_ACCENT_HOVER, corner_radius=17,
                      font=T.F_BUTTON, command=self._save).pack(side="right", padx=(0, 8))

    def _save(self):
        key = self.key_entry.get().strip()
        if key:
            self.cfg[SGDB_KEY] = key
        else:
            self.cfg.pop(SGDB_KEY, None)
        config_store.save(self.cfg)
        self.destroy()
