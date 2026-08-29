"""The Settings destination."""

from __future__ import annotations

import customtkinter as ctk

from kairo import APP_ID, APP_NAME, TAGLINE, __version__
from kairo import config as config_store
from kairo import migration, paths
from kairo.artwork.steamgriddb import CONFIG_KEY as SGDB_KEY
from kairo.ui import theme as T
from kairo.ui.context import UIContext


class SettingsPane(ctk.CTkFrame):
    def __init__(self, master, context: UIContext, **kw):
        super().__init__(master, fg_color=T.C_BG, corner_radius=0, **kw)
        self.ctx = context
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Settings", font=T.F_WORKSPACE_TITLE,
                     text_color=T.C_TEXT, anchor="w"
                     ).grid(row=0, column=0, sticky="w", padx=28, pady=(24, 16))

        card = ctk.CTkFrame(self, fg_color=T.C_PANEL, corner_radius=T.R_CARD)
        card.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 16))
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(card, text="SteamGridDB API key", font=T.F_BODY_B,
                     text_color=T.C_TEXT, anchor="w"
                     ).grid(row=0, column=0, sticky="w", padx=20, pady=(18, 2))
        ctk.CTkLabel(card,
                     text="Optional. Only needed for Steam game artwork — "
                          "icon themes, Iconify and your own files work without it.",
                     font=T.F_TINY, text_color=T.C_TEXT3, anchor="w"
                     ).grid(row=1, column=0, sticky="w", padx=20)
        ctk.CTkLabel(card, text="Free at steamgriddb.com → Profile → API",
                     font=T.F_TINY, text_color=T.C_TEXT3, anchor="w"
                     ).grid(row=2, column=0, sticky="w", padx=20, pady=(0, 8))

        self.key_entry = ctk.CTkEntry(card, placeholder_text="Paste API key",
                                      font=T.F_BODY, corner_radius=T.R_WELL,
                                      height=38, fg_color=T.C_CARD,
                                      border_width=1, border_color=T.C_BORDER)
        self.key_entry.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 12))
        if context.config.get(SGDB_KEY):
            self.key_entry.insert(0, context.config[SGDB_KEY])

        buttons = ctk.CTkFrame(card, fg_color="transparent")
        buttons.grid(row=4, column=0, sticky="e", padx=20, pady=(0, 18))
        ctk.CTkButton(buttons, text="Save", height=36, width=110,
                      corner_radius=T.R_WELL, fg_color=T.C_ACCENT,
                      hover_color=T.C_ACCENT_HOVER, font=T.F_BUTTON,
                      command=self._save).pack(side="right")
        self.saved = ctk.CTkLabel(buttons, text="", font=T.F_TINY,
                                  text_color=T.C_SUCCESS)
        self.saved.pack(side="right", padx=(0, 12))

        where = ctk.CTkFrame(self, fg_color=T.C_PANEL, corner_radius=T.R_CARD)
        where.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 16))
        ctk.CTkLabel(where, text="WHERE THINGS LIVE", font=T.F_SECTION,
                     text_color=T.C_TEXT3, anchor="w"
                     ).pack(anchor="w", padx=20, pady=(16, 8))
        for label, value in (
                ("Settings", paths.config_file()),
                ("Cache (safe to delete)", paths.cache_dir()),
                ("Artwork", paths.icon_store()),
                ("Launcher entries", paths.applications_dir())):
            line = ctk.CTkFrame(where, fg_color="transparent")
            line.pack(fill="x", padx=20, pady=1)
            ctk.CTkLabel(line, text=label, font=T.F_ITEM_SUB,
                         text_color=T.C_TEXT3, width=170, anchor="w").pack(side="left")
            ctk.CTkLabel(line, text=str(value), font=T.F_ITEM_SUB,
                         text_color=T.C_TEXT2, anchor="w").pack(side="left")
        leftovers = migration.legacy_leftovers()
        if leftovers:
            ctk.CTkLabel(
                where,
                text="Steam Shortcut Forge files are still on disk and can be "
                     "removed by hand once you are happy:\n  "
                     + "\n  ".join(str(p) for p in leftovers),
                font=T.F_ITEM_SUB, text_color=T.C_TEXT3, justify="left",
                anchor="w").pack(anchor="w", padx=20, pady=(10, 0))
        ctk.CTkLabel(where, text="", height=6).pack()

        ctk.CTkLabel(self, text=f"{APP_NAME} {__version__}  ·  {TAGLINE}\n{APP_ID}",
                     font=T.F_TINY, text_color=T.C_TEXT3, justify="left",
                     anchor="w").grid(row=3, column=0, sticky="w", padx=28)

    def _save(self):
        key = self.key_entry.get().strip()
        if key:
            self.ctx.config[SGDB_KEY] = key
        else:
            self.ctx.config.pop(SGDB_KEY, None)
        config_store.save(self.ctx.config)
        self.saved.configure(text="Saved")
        self.after(2000, lambda: self.saved.configure(text=""))
        self.ctx.on_changed()
