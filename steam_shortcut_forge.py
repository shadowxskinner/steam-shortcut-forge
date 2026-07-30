#!/usr/bin/env python3
"""
Steam Shortcut Forge
=====================

Scan installed Steam games and assign custom icons from SteamGridDB
or local files. Creates .desktop launcher entries so games appear in
your app launcher (KDE, GNOME, or any freedesktop desktop).

Requirements:
    python3 -m pip install customtkinter
    A free SteamGridDB API key: https://www.steamgriddb.com/profile/preferences/api

License: MIT
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

APP_NAME = "steam-shortcut-forge"
USER_AGENT = "SteamShortcutForge/1.0"
CONFIG_DIR = Path.home() / ".config" / APP_NAME
CONFIG_FILE = CONFIG_DIR / "config.json"
CACHE_DIR = CONFIG_DIR / "cache"
ICON_STORE = Path.home() / ".local" / "share" / APP_NAME / "icons"
APPLICATIONS_DIR = Path.home() / ".local" / "share" / "applications"
DESKTOP_PREFIX = "steam-shortcut-forge-"
VALID_ICON_EXTS = {".ico", ".png", ".svg", ".xpm"}
SGDB_BASE = "https://www.steamgriddb.com/api/v2"

# ---------------------------------------------------------------------------
# Appearance
# ---------------------------------------------------------------------------

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Typography
FONT_TITLE = ("Inter", 24, "bold")
FONT_HEADING = ("Inter", 16, "bold")
FONT_BODY = ("Inter", 14)
FONT_BODY_BOLD = ("Inter", 14, "bold")
FONT_SMALL = ("Inter", 12)
FONT_TINY = ("Inter", 10)
FONT_ICON = ("Inter", 18)
FONT_BUTTON = ("Inter", 13, "bold")

# Colors
C_BG = "#0f0f0f"
C_SURFACE = "#1a1a1a"
C_CARD = "#222222"
C_CARD_HOVER = "#2c2c2c"
C_CARD_SELECTED = "#2a2a45"
C_BORDER = "#333333"
C_BORDER_ACCENT = "#6c63ff"
C_TEXT = "#f0f0f0"
C_TEXT_SECONDARY = "#999999"
C_TEXT_MUTED = "#666666"
C_ACCENT = "#6c63ff"
C_ACCENT_HOVER = "#7f78ff"
C_SUCCESS = "#22c55e"
C_SUCCESS_DIM = "#166534"
C_DANGER = "#ef4444"
C_DANGER_BG = "#3a1a1a"
C_DANGER_HOVER = "#4a2020"
C_FILTER_ACTIVE = "#2a2a45"
C_FILTER_INACTIVE = "#1a1a1a"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config() -> dict:
    if CONFIG_FILE.is_file():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


# ---------------------------------------------------------------------------
# SteamGridDB client
# ---------------------------------------------------------------------------

@dataclass
class SGDBIcon:
    icon_id: int
    url: str
    thumb: str
    width: int
    height: int
    mime: str
    style: str


class SteamGridDBClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _api_get(self, path: str) -> dict:
        req = urllib.request.Request(f"{SGDB_BASE}{path}")
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("User-Agent", USER_AGENT)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise RuntimeError("Invalid API key — check Settings.") from e
            if e.code == 404:
                return {"data": None}
            if e.code == 429:
                raise RuntimeError("Rate-limited. Wait a moment.") from e
            raise RuntimeError(f"SteamGridDB HTTP {e.code}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error: {e.reason}") from e

    @staticmethod
    def _cdn_get(url: str, timeout: int = 30) -> bytes:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", USER_AGENT)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()

    def get_game_id(self, steam_appid: str) -> int | None:
        cache = CACHE_DIR / f"gameid_{steam_appid}.json"
        if cache.is_file():
            try:
                return json.loads(cache.read_text()).get("game_id")
            except (json.JSONDecodeError, OSError):
                pass
        data = self._api_get(f"/games/steam/{steam_appid}")
        gd = data.get("data")
        gid = gd["id"] if gd else None
        try:
            cache.write_text(json.dumps({"game_id": gid}))
        except OSError:
            pass
        return gid

    def get_icons(self, game_id: int) -> list[SGDBIcon]:
        cache = CACHE_DIR / f"icons_{game_id}.json"
        if cache.is_file():
            try:
                if time.time() - cache.stat().st_mtime < 86400:
                    return [SGDBIcon(**d) for d in json.loads(cache.read_text())]
            except (json.JSONDecodeError, OSError, TypeError):
                pass

        raw = (self._api_get(
            f"/icons/game/{game_id}?types=static&nsfw=false&mimes=image/png"
        ).get("data") or [])

        icons: list[SGDBIcon] = []
        for item in raw:
            try:
                icons.append(SGDBIcon(
                    icon_id=item["id"], url=item["url"], thumb=item["thumb"],
                    width=item.get("width", 0), height=item.get("height", 0),
                    mime=item.get("mime", ""), style=item.get("style", ""),
                ))
            except (KeyError, TypeError):
                continue
        icons.sort(key=lambda ic: ic.width * ic.height, reverse=True)

        try:
            cache.write_text(json.dumps([
                {"icon_id": i.icon_id, "url": i.url, "thumb": i.thumb,
                 "width": i.width, "height": i.height, "mime": i.mime, "style": i.style}
                for i in icons
            ]))
        except OSError:
            pass
        return icons

    def download_icon(self, url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self._cdn_get(url))

    def download_thumbnail(self, thumb_url: str) -> bytes:
        h = hashlib.md5(thumb_url.encode()).hexdigest()
        cache = CACHE_DIR / f"thumb_{h}.png"
        if cache.is_file():
            return cache.read_bytes()
        data = self._cdn_get(thumb_url, timeout=15)
        try:
            cache.write_bytes(data)
        except OSError:
            pass
        return data


# ---------------------------------------------------------------------------
# Steam library scanning
# ---------------------------------------------------------------------------

@dataclass
class SteamGame:
    appid: str
    name: str
    library_root: Path
    has_shortcut: bool = False
    icon_path: Path | None = None


_RE_APPID = re.compile(r'"appid"\s+"(\d+)"')
_RE_NAME = re.compile(r'"name"\s+"([^"]+)"')
_SKIP_NAMES = {"steamworks common redistributables", "steam linux runtime"}


def _candidate_roots() -> list[Path]:
    h = Path.home()
    return [p for p in [
        h / ".steam" / "steam",
        h / ".local" / "share" / "Steam",
        h / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
        h / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "Steam",
        Path("/usr/share/steam"),
    ] if (p / "steamapps").is_dir()]


def _extra_libraries(steamapps: Path) -> list[Path]:
    vdf = steamapps / "libraryfolders.vdf"
    if not vdf.is_file():
        return []
    try:
        text = vdf.read_text(errors="ignore")
    except OSError:
        return []
    out = []
    for p in re.findall(r'"path"\s+"([^"]+)"', text):
        sa = Path(p.replace("\\\\", "/")) / "steamapps"
        if sa.is_dir():
            out.append(sa)
    return out


def find_steamapps() -> list[Path]:
    dirs: list[Path] = []
    seen: set[str] = set()
    for root in _candidate_roots():
        sa = root / "steamapps"
        for d in [sa, *_extra_libraries(sa)]:
            key = str(d.resolve())
            if key not in seen:
                seen.add(key)
                dirs.append(d)
    return dirs


def scan_games() -> list[SteamGame]:
    games: dict[str, SteamGame] = {}
    for sa in find_steamapps():
        for mf in sa.glob("appmanifest_*.acf"):
            try:
                text = mf.read_text(errors="ignore")
            except OSError:
                continue
            am, nm = _RE_APPID.search(text), _RE_NAME.search(text)
            if not am or not nm:
                continue
            appid, name = am.group(1), nm.group(1)
            low = name.strip().lower()
            if low in _SKIP_NAMES or low.startswith("steam linux runtime"):
                continue
            if appid not in games:
                games[appid] = SteamGame(appid=appid, name=name, library_root=sa)

    existing = _existing_shortcuts()
    for aid, g in games.items():
        if aid in existing:
            g.has_shortcut = True
            g.icon_path = existing[aid]
    return sorted(games.values(), key=lambda g: g.name.lower())


# ---------------------------------------------------------------------------
# Launch command
# ---------------------------------------------------------------------------

def _flatpak_steam() -> bool:
    if not shutil.which("flatpak"):
        return False
    try:
        return subprocess.run(
            ["flatpak", "info", "com.valvesoftware.Steam"],
            capture_output=True, timeout=5,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def steam_cmd(appid: str) -> str:
    uri = f"steam://rungameid/{appid}"
    if shutil.which("steam"):
        return f"steam {uri}"
    if _flatpak_steam():
        return f"flatpak run com.valvesoftware.Steam {uri}"
    return f"xdg-open {uri}"


# ---------------------------------------------------------------------------
# .desktop management
# ---------------------------------------------------------------------------

def _desktop_path(appid: str) -> Path:
    return APPLICATIONS_DIR / f"{DESKTOP_PREFIX}{appid}.desktop"


def _existing_shortcuts() -> dict[str, Path | None]:
    out: dict[str, Path | None] = {}
    if not APPLICATIONS_DIR.is_dir():
        return out
    for f in APPLICATIONS_DIR.glob(f"{DESKTOP_PREFIX}*.desktop"):
        appid = f.stem[len(DESKTOP_PREFIX):]
        icon = None
        try:
            for line in f.read_text(errors="ignore").splitlines():
                if line.startswith("Icon="):
                    icon = Path(line.split("=", 1)[1].strip())
                    break
        except OSError:
            pass
        out[appid] = icon
    return out


def create_shortcut(game: SteamGame, icon_src: Path) -> None:
    if icon_src.suffix.lower() not in VALID_ICON_EXTS:
        raise ValueError(f"Unsupported icon type: {icon_src.suffix}")

    ICON_STORE.mkdir(parents=True, exist_ok=True)
    APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)

    if icon_src.parent.resolve() == ICON_STORE.resolve():
        stored = icon_src
    else:
        stored = ICON_STORE / f"{game.appid}_{hash(icon_src.name)}{icon_src.suffix.lower()}"
        shutil.copyfile(icon_src, stored)

    _desktop_path(game.appid).write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={game.name.replace(chr(10), ' ').strip()}\n"
        f"Exec={steam_cmd(game.appid)}\n"
        f"Icon={stored}\n"
        "Categories=Game;\n"
        "Terminal=false\n"
        "StartupNotify=true\n"
        f"X-SteamAppId={game.appid}\n"
    )
    game.has_shortcut = True
    game.icon_path = stored
    _refresh_db()


def remove_shortcut(game: SteamGame) -> None:
    dp = _desktop_path(game.appid)
    if dp.exists():
        dp.unlink()
    if game.icon_path and game.icon_path.exists() and game.icon_path.is_relative_to(ICON_STORE):
        game.icon_path.unlink(missing_ok=True)
    game.has_shortcut = False
    game.icon_path = None
    _refresh_db()


def _refresh_db() -> None:
    u = shutil.which("update-desktop-database")
    if u:
        try:
            subprocess.run([u, str(APPLICATIONS_DIR)], capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass


# ---------------------------------------------------------------------------
# GUI — Game row widget
# ---------------------------------------------------------------------------

class GameRow(ctk.CTkFrame):
    ICON_SIZE = 40

    def __init__(self, master, game: SteamGame, on_select, **kw):
        super().__init__(master, corner_radius=10, fg_color=C_CARD,
                         border_width=1, border_color=C_BORDER, height=64, **kw)
        self.game = game
        self._on_select = on_select
        self._selected = False
        self._photo_ref = None  # prevent GC

        self.configure(cursor="hand2")
        self.grid_columnconfigure(2, weight=1)

        # Icon preview (shows assigned icon or placeholder)
        self.icon_label = ctk.CTkLabel(
            self, text="", width=self.ICON_SIZE, height=self.ICON_SIZE,
        )
        self.icon_label.grid(row=0, column=0, rowspan=2, padx=(14, 0), pady=10)
        self._load_icon_preview()

        # Status dot
        dot = "●" if game.has_shortcut else "○"
        dot_color = C_SUCCESS if game.has_shortcut else C_TEXT_MUTED
        self.dot_label = ctk.CTkLabel(
            self, text=dot, width=20, font=FONT_SMALL, text_color=dot_color,
        )
        self.dot_label.grid(row=0, column=1, rowspan=2, padx=(8, 0), pady=10)

        # Game name
        self.name_label = ctk.CTkLabel(
            self, text=game.name, anchor="w",
            font=FONT_BODY_BOLD, text_color=C_TEXT,
        )
        self.name_label.grid(row=0, column=2, sticky="sw", padx=(8, 14), pady=(12, 0))

        # App ID + status text
        status_text = f"App ID: {game.appid}"
        if game.has_shortcut:
            status_text += "  ·  Shortcut active"
        self.info_label = ctk.CTkLabel(
            self, text=status_text, anchor="w",
            font=FONT_TINY, text_color=C_TEXT_SECONDARY,
        )
        self.info_label.grid(row=1, column=2, sticky="nw", padx=(8, 14), pady=(0, 12))

        # Click binding on all children
        for w in [self, self.icon_label, self.dot_label, self.name_label, self.info_label]:
            w.bind("<Button-1>", self._clicked)
            w.bind("<Enter>", self._hover_in)
            w.bind("<Leave>", self._hover_out)

    def _load_icon_preview(self):
        """Try to load and display the assigned icon as a thumbnail."""
        if not self.game.icon_path or not self.game.icon_path.exists():
            self.icon_label.configure(
                text="🎮", font=("Inter", 22), text_color=C_TEXT_MUTED,
            )
            return
        try:
            photo = tk.PhotoImage(file=str(self.game.icon_path))
            w, h = photo.width(), photo.height()
            scale = max(w // self.ICON_SIZE, h // self.ICON_SIZE, 1)
            if scale > 1:
                photo = photo.subsample(scale, scale)
            self._photo_ref = photo
            self.icon_label.configure(image=photo, text="")
        except tk.TclError:
            self.icon_label.configure(
                text="🎮", font=("Inter", 22), text_color=C_SUCCESS,
            )

    def _clicked(self, _e=None):
        self._on_select(self)

    def _hover_in(self, _e=None):
        if not self._selected:
            self.configure(fg_color=C_CARD_HOVER)

    def _hover_out(self, _e=None):
        if not self._selected:
            self.configure(fg_color=C_CARD)

    def set_selected(self, sel: bool):
        self._selected = sel
        self.configure(
            fg_color=C_CARD_SELECTED if sel else C_CARD,
            border_color=C_BORDER_ACCENT if sel else C_BORDER,
        )

    def refresh(self):
        dot = "●" if self.game.has_shortcut else "○"
        color = C_SUCCESS if self.game.has_shortcut else C_TEXT_MUTED
        self.dot_label.configure(text=dot, text_color=color)
        status = f"App ID: {self.game.appid}"
        if self.game.has_shortcut:
            status += "  ·  Shortcut active"
        self.info_label.configure(text=status)
        self._load_icon_preview()


# ---------------------------------------------------------------------------
# GUI — Icon picker dialog
# ---------------------------------------------------------------------------

class IconPickerDialog(ctk.CTkToplevel):
    COLS = 4

    def __init__(self, parent, game: SteamGame, client: SteamGridDBClient):
        super().__init__(parent)
        self.game = game
        self.client = client
        self.result_path: Path | None = None
        self._photo_refs: list = []

        self.title(f"Pick icon — {game.name}")
        self.geometry("540x500")
        self.minsize(420, 360)
        self.configure(fg_color=C_BG)
        self.transient(parent)
        self.grab_set()

        # Header
        ctk.CTkLabel(
            self, text=f"Icons for {game.name}",
            font=FONT_HEADING, text_color=C_TEXT,
        ).pack(padx=20, pady=(20, 4), anchor="w")

        self.status = ctk.CTkLabel(
            self, text="Fetching from SteamGridDB…",
            font=FONT_SMALL, text_color=C_TEXT_SECONDARY,
        )
        self.status.pack(padx=20, pady=(0, 12), anchor="w")

        # Scrollable grid
        self.grid_frame = ctk.CTkScrollableFrame(
            self, fg_color=C_SURFACE, corner_radius=10,
        )
        self.grid_frame.pack(fill="both", expand=True, padx=20, pady=(0, 12))

        # Cancel button
        ctk.CTkButton(
            self, text="Cancel", height=36,
            fg_color=C_CARD, hover_color=C_CARD_HOVER,
            text_color=C_TEXT, corner_radius=8, font=FONT_BUTTON,
            command=self.destroy,
        ).pack(padx=20, pady=(0, 20), anchor="e")

        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            gid = self.client.get_game_id(self.game.appid)
            if gid is None:
                self.after(0, lambda: self.status.configure(text="Game not found on SteamGridDB."))
                return
            icons = self.client.get_icons(gid)
            if not icons:
                self.after(0, lambda: self.status.configure(text="No icons available."))
                return
            self.after(0, lambda: self.status.configure(
                text=f"{len(icons)} icon(s) — click to apply"))
            for i, icon in enumerate(icons):
                try:
                    data = self.client.download_thumbnail(icon.thumb)
                    self.after(0, self._add_tile, i, icon, data)
                except Exception:
                    continue
        except RuntimeError as exc:
            msg = str(exc)
            self.after(0, lambda: self.status.configure(text=msg))
        except Exception as exc:
            msg = f"Error: {exc}"
            self.after(0, lambda: self.status.configure(text=msg))

    def _add_tile(self, idx: int, icon: SGDBIcon, thumb_data: bytes):
        row, col = divmod(idx, self.COLS)

        frame = ctk.CTkFrame(self.grid_frame, fg_color=C_CARD, corner_radius=10,
                             border_width=1, border_color=C_BORDER)
        frame.grid(row=row, column=col, padx=6, pady=6)

        try:
            photo = tk.PhotoImage(data=thumb_data)
            w, h = photo.width(), photo.height()
            scale = max(w // 80, h // 80, 1)
            if scale > 1:
                photo = photo.subsample(scale, scale)
            self._photo_refs.append(photo)

            btn = tk.Button(
                frame, image=photo, relief="flat", cursor="hand2",
                bg=C_CARD, activebackground=C_CARD_HOVER, bd=0,
                highlightthickness=0,
                command=lambda ic=icon: self._pick(ic),
            )
            btn.pack(padx=8, pady=(8, 2))
        except tk.TclError:
            ctk.CTkButton(
                frame, text=f"{icon.width}×{icon.height}",
                fg_color=C_ACCENT, corner_radius=8, width=80, height=60,
                font=FONT_SMALL, command=lambda ic=icon: self._pick(ic),
            ).pack(padx=8, pady=(8, 2))

        size = f"{icon.width}×{icon.height}" if icon.width else icon.style
        ctk.CTkLabel(frame, text=size, font=FONT_TINY,
                     text_color=C_TEXT_MUTED).pack(pady=(0, 8))

    def _pick(self, icon: SGDBIcon):
        self.status.configure(text="Downloading…")
        self.update_idletasks()

        def dl():
            try:
                ext = ".png" if ".png" in icon.url.lower() else (
                    ".ico" if ".ico" in icon.url.lower() else ".png")
                dest = ICON_STORE / f"{self.game.appid}_{icon.icon_id}{ext}"
                self.client.download_icon(icon.url, dest)
                self.result_path = dest
                self.after(0, self.destroy)
            except Exception as exc:
                msg = f"Download failed: {exc}"
                self.after(0, lambda: self.status.configure(text=msg))

        threading.Thread(target=dl, daemon=True).start()


# ---------------------------------------------------------------------------
# GUI — Settings dialog
# ---------------------------------------------------------------------------

class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent, config: dict):
        super().__init__(parent)
        self.config = config
        self.title("Settings")
        self.geometry("480x220")
        self.configure(fg_color=C_BG)
        self.transient(parent)
        self.grab_set()

        ctk.CTkLabel(
            self, text="Settings", font=FONT_HEADING, text_color=C_TEXT,
        ).pack(padx=24, pady=(24, 16), anchor="w")

        # API key section
        key_frame = ctk.CTkFrame(self, fg_color=C_SURFACE, corner_radius=10)
        key_frame.pack(fill="x", padx=24, pady=(0, 16))

        ctk.CTkLabel(
            key_frame, text="SteamGridDB API Key",
            font=FONT_BODY_BOLD, text_color=C_TEXT,
        ).pack(padx=16, pady=(16, 2), anchor="w")

        ctk.CTkLabel(
            key_frame, text="Free at steamgriddb.com → Profile → API",
            font=FONT_TINY, text_color=C_TEXT_MUTED,
        ).pack(padx=16, pady=(0, 8), anchor="w")

        self.key_entry = ctk.CTkEntry(
            key_frame, placeholder_text="Paste your API key",
            font=FONT_BODY, corner_radius=8, height=38,
        )
        self.key_entry.pack(fill="x", padx=16, pady=(0, 16))
        existing = config.get("steamgriddb_api_key", "")
        if existing:
            self.key_entry.insert(0, existing)

        # Buttons
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=24, pady=(0, 24))
        ctk.CTkButton(
            btn_row, text="Cancel", height=36,
            fg_color=C_CARD, hover_color=C_CARD_HOVER,
            text_color=C_TEXT, corner_radius=8, font=FONT_BUTTON,
            command=self.destroy,
        ).pack(side="right")
        ctk.CTkButton(
            btn_row, text="Save", height=36,
            fg_color=C_ACCENT, hover_color=C_ACCENT_HOVER,
            corner_radius=8, font=FONT_BUTTON, command=self._save,
        ).pack(side="right", padx=(0, 8))

    def _save(self):
        key = self.key_entry.get().strip()
        if key:
            self.config["steamgriddb_api_key"] = key
        else:
            self.config.pop("steamgriddb_api_key", None)
        save_config(self.config)
        self.destroy()


# ---------------------------------------------------------------------------
# GUI — Main application
# ---------------------------------------------------------------------------

class SteamShortcutForge(ctk.CTk):
    def __init__(self):
        super().__init__(fg_color=C_BG)
        self.title("Steam Shortcut Forge")
        self.geometry("760x680")
        self.minsize(560, 460)

        self.config_data = load_config()
        self.games: list[SteamGame] = []
        self.rows: list[GameRow] = []
        self.selected_row: GameRow | None = None
        self._filter_mode = "all"  # "all", "with", "without"

        self._build_ui()
        self._first_run()
        self._scan()

    def _build_ui(self):
        # ── Header ──────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(24, 0))

        ctk.CTkLabel(
            header, text="Steam Shortcut Forge", font=FONT_TITLE, text_color=C_TEXT,
        ).pack(side="left")

        # Header buttons (right side)
        ctk.CTkButton(
            header, text="⚙", width=38, height=38, corner_radius=10,
            fg_color=C_CARD, hover_color=C_CARD_HOVER,
            text_color=C_TEXT_SECONDARY, font=FONT_ICON,
            command=self._settings,
        ).pack(side="right")

        ctk.CTkButton(
            header, text="Rescan", width=80, height=38, corner_radius=10,
            fg_color=C_CARD, hover_color=C_CARD_HOVER,
            text_color=C_TEXT, font=FONT_BUTTON,
            command=self._scan,
        ).pack(side="right", padx=(0, 8))

        # ── Subtitle ───────────────────────────────────────────────────
        self.subtitle = ctk.CTkLabel(
            self, text="Manage launcher shortcuts for your Steam games",
            font=FONT_SMALL, text_color=C_TEXT_MUTED,
        )
        self.subtitle.pack(padx=24, pady=(4, 16), anchor="w")

        # ── Search + filter bar ────────────────────────────────────────
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=24, pady=(0, 12))
        bar.grid_columnconfigure(0, weight=1)

        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._filter())
        ctk.CTkEntry(
            bar, textvariable=self.search_var, height=42, corner_radius=10,
            placeholder_text="Search games…", font=FONT_BODY,
            border_width=1, border_color=C_BORDER,
        ).grid(row=0, column=0, sticky="ew")

        # Filter buttons
        filter_frame = ctk.CTkFrame(bar, fg_color="transparent")
        filter_frame.grid(row=0, column=1, padx=(10, 0))

        self.filter_all = ctk.CTkButton(
            filter_frame, text="All", width=50, height=42, corner_radius=10,
            fg_color=C_FILTER_ACTIVE, hover_color=C_CARD_HOVER,
            text_color=C_TEXT, font=FONT_BUTTON, border_width=1,
            border_color=C_BORDER_ACCENT,
            command=lambda: self._set_filter("all"),
        )
        self.filter_all.pack(side="left", padx=(0, 4))

        self.filter_with = ctk.CTkButton(
            filter_frame, text="● Has", width=64, height=42, corner_radius=10,
            fg_color=C_FILTER_INACTIVE, hover_color=C_CARD_HOVER,
            text_color=C_TEXT_SECONDARY, font=FONT_BUTTON, border_width=1,
            border_color=C_BORDER,
            command=lambda: self._set_filter("with"),
        )
        self.filter_with.pack(side="left", padx=(0, 4))

        self.filter_without = ctk.CTkButton(
            filter_frame, text="○ None", width=72, height=42, corner_radius=10,
            fg_color=C_FILTER_INACTIVE, hover_color=C_CARD_HOVER,
            text_color=C_TEXT_SECONDARY, font=FONT_BUTTON, border_width=1,
            border_color=C_BORDER,
            command=lambda: self._set_filter("without"),
        )
        self.filter_without.pack(side="left")

        # ── Game list ──────────────────────────────────────────────────
        self.list_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent", corner_radius=0,
        )
        self.list_frame.pack(fill="both", expand=True, padx=24, pady=(0, 8))
        self.list_frame.grid_columnconfigure(0, weight=1)

        # ── Action bar ─────────────────────────────────────────────────
        action_bar = ctk.CTkFrame(self, fg_color=C_SURFACE, corner_radius=12,
                                  border_width=1, border_color=C_BORDER)
        action_bar.pack(fill="x", padx=24, pady=(0, 8))

        inner = ctk.CTkFrame(action_bar, fg_color="transparent")
        inner.pack(padx=12, pady=12)

        self.sgdb_btn = ctk.CTkButton(
            inner, text="⬇  Fetch from SteamGridDB", height=40,
            corner_radius=10, fg_color=C_ACCENT,
            hover_color=C_ACCENT_HOVER, font=FONT_BUTTON,
            command=self._on_sgdb, state="disabled",
        )
        self.sgdb_btn.pack(side="left", padx=(0, 8))

        self.browse_btn = ctk.CTkButton(
            inner, text="📁  Browse", height=40,
            corner_radius=10, fg_color=C_CARD,
            hover_color=C_CARD_HOVER, text_color=C_TEXT,
            font=FONT_BUTTON, command=self._on_browse, state="disabled",
        )
        self.browse_btn.pack(side="left", padx=(0, 8))

        self.remove_btn = ctk.CTkButton(
            inner, text="Remove", height=40,
            corner_radius=10, fg_color=C_DANGER_BG,
            hover_color=C_DANGER_HOVER, text_color=C_DANGER,
            font=FONT_BUTTON, command=self._on_remove, state="disabled",
        )
        self.remove_btn.pack(side="left", padx=(0, 8))

        self.bulk_btn = ctk.CTkButton(
            inner, text="⬇  Auto-assign all", height=40,
            corner_radius=10, fg_color=C_CARD,
            hover_color=C_CARD_HOVER, text_color=C_ACCENT,
            font=FONT_BUTTON, command=self._on_bulk,
        )
        self.bulk_btn.pack(side="left")

        # ── Status bar ─────────────────────────────────────────────────
        self.status = ctk.CTkLabel(
            self, text="", font=FONT_SMALL, text_color=C_TEXT_MUTED,
        )
        self.status.pack(fill="x", padx=24, pady=(0, 16))

    # -- Data & filtering -----------------------------------------------

    def _first_run(self):
        if not self.config_data.get("steamgriddb_api_key"):
            from tkinter import messagebox
            if messagebox.askyesno(
                "Setup",
                "Steam Shortcut Forge can fetch icons from SteamGridDB.\n\n"
                "You need a free API key from steamgriddb.com.\n\n"
                "Enter your key now?",
            ):
                self._settings()

    def _scan(self):
        self.status.configure(text="Scanning Steam libraries…")
        self.update_idletasks()
        try:
            self.games = scan_games()
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("Scan failed", str(e))
            self.games = []
        self._filter()
        n = sum(1 for g in self.games if g.has_shortcut)
        self.status.configure(text=f"{len(self.games)} games  ·  {n} with shortcuts")

    def _set_filter(self, mode: str):
        self._filter_mode = mode

        # Update button styling
        for btn, m in [(self.filter_all, "all"), (self.filter_with, "with"),
                       (self.filter_without, "without")]:
            if m == mode:
                btn.configure(fg_color=C_FILTER_ACTIVE, text_color=C_TEXT,
                              border_color=C_BORDER_ACCENT)
            else:
                btn.configure(fg_color=C_FILTER_INACTIVE, text_color=C_TEXT_SECONDARY,
                              border_color=C_BORDER)
        self._filter()

    def _filter(self):
        q = self.search_var.get().strip().lower()
        filtered = self.games

        if q:
            filtered = [g for g in filtered if q in g.name.lower()]

        if self._filter_mode == "with":
            filtered = [g for g in filtered if g.has_shortcut]
        elif self._filter_mode == "without":
            filtered = [g for g in filtered if not g.has_shortcut]

        # Clear
        for row in self.rows:
            row.destroy()
        self.rows.clear()
        self.selected_row = None
        self._set_actions(False)

        for i, game in enumerate(filtered):
            row = GameRow(self.list_frame, game, on_select=self._select_row)
            row.grid(row=i, column=0, sticky="ew", pady=3)
            self.rows.append(row)

    def _select_row(self, row: GameRow):
        if self.selected_row:
            self.selected_row.set_selected(False)
        row.set_selected(True)
        self.selected_row = row
        self._set_actions(True)

    def _set_actions(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.sgdb_btn.configure(state=state)
        self.browse_btn.configure(state=state)
        self.remove_btn.configure(state=state)

    # -- Settings -------------------------------------------------------

    def _settings(self):
        SettingsDialog(self, self.config_data)
        self.config_data = load_config()

    # -- Single-game actions --------------------------------------------

    def _on_sgdb(self):
        if not self.selected_row:
            return
        key = self.config_data.get("steamgriddb_api_key")
        if not key:
            from tkinter import messagebox
            messagebox.showinfo("API Key Required",
                                "Set your SteamGridDB API key in Settings first.")
            return
        client = SteamGridDBClient(key)
        dialog = IconPickerDialog(self, self.selected_row.game, client)
        self.wait_window(dialog)
        if dialog.result_path:
            self._apply_icon(dialog.result_path)

    def _on_browse(self):
        if not self.selected_row:
            return
        path = filedialog.askopenfilename(
            title=f"Icon for {self.selected_row.game.name}",
            filetypes=[("Icon images", "*.ico *.png *.svg *.xpm"), ("All", "*.*")],
        )
        if path:
            self._apply_icon(Path(path))

    def _apply_icon(self, path: Path):
        if not self.selected_row:
            return
        try:
            create_shortcut(self.selected_row.game, path)
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("Error", str(e))
            return
        self.selected_row.refresh()
        self.status.configure(text=f"Shortcut created for {self.selected_row.game.name}")

    def _on_remove(self):
        if not self.selected_row or not self.selected_row.game.has_shortcut:
            return
        from tkinter import messagebox
        if messagebox.askyesno("Remove", f"Remove shortcut for {self.selected_row.game.name}?"):
            remove_shortcut(self.selected_row.game)
            self.selected_row.refresh()
            self.status.configure(text=f"Shortcut removed")

    # -- Bulk auto-assign -----------------------------------------------

    def _on_bulk(self):
        key = self.config_data.get("steamgriddb_api_key")
        if not key:
            from tkinter import messagebox
            messagebox.showinfo("API Key Required",
                                "Set your SteamGridDB API key in Settings first.")
            return

        games_todo = [g for g in self.games if not g.has_shortcut]
        if not games_todo:
            self.status.configure(text="All games already have shortcuts.")
            return

        from tkinter import messagebox
        if not messagebox.askyesno(
            "Auto-assign icons",
            f"Fetch and assign the best icon for {len(games_todo)} game(s)?\n\n"
            "This uses the highest-resolution PNG from SteamGridDB for each game.",
        ):
            return

        self.bulk_btn.configure(state="disabled", text="Working…")
        self.update_idletasks()

        def worker():
            client = SteamGridDBClient(key)
            done, fail = 0, 0
            for i, game in enumerate(games_todo):
                self.after(0, lambda g=game, n=i: self.status.configure(
                    text=f"({n + 1}/{len(games_todo)}) Fetching icon for {g.name}…"))
                try:
                    gid = client.get_game_id(game.appid)
                    if gid is None:
                        fail += 1
                        continue
                    icons = client.get_icons(gid)
                    if not icons:
                        fail += 1
                        continue
                    best = icons[0]
                    ext = ".png" if ".png" in best.url.lower() else ".ico"
                    dest = ICON_STORE / f"{game.appid}_{best.icon_id}{ext}"
                    client.download_icon(best.url, dest)
                    self.after(0, lambda g=game, d=dest: create_shortcut(g, d))
                    done += 1
                    time.sleep(0.3)  # be kind to the API
                except Exception:
                    fail += 1
                    continue

            def finish():
                self.bulk_btn.configure(state="normal", text="⬇  Auto-assign all")
                self.status.configure(text=f"Done — {done} assigned, {fail} skipped")
                self._filter()

            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    if sys.platform not in ("linux", "linux2"):
        print("Steam Shortcut Forge targets Linux desktops.")
        return 1
    SteamShortcutForge().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
