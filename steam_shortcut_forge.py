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
import io
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

# CustomTkinter draws rounded corners from a bundled OTF on Linux, but its
# FontManager.load_font() only copies the file into ~/.fonts and returns True
# without checking Tk can actually use it — so corners silently render square.
# polygon_shapes draws them with canvas polygons instead (what macOS uses).
try:
    from customtkinter.windows.widgets.core_rendering import DrawEngine
    DrawEngine.preferred_drawing_method = "polygon_shapes"
except ImportError:
    pass

try:
    from PIL import Image, ImageTk
    _LANCZOS = getattr(Image, "Resampling", Image).LANCZOS
except ImportError:
    Image = ImageTk = None
    _LANCZOS = None

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
# Global size multiplier for every widget — raise for a chunkier UI.
UI_SCALE = 1.1
ctk.set_widget_scaling(UI_SCALE)

# Fonts
F_LOGO = ("Inter", 20, "bold")
F_TITLE = ("Inter", 18, "bold")
F_HEADING = ("Inter", 15, "bold")
F_BODY = ("Inter", 13)
F_BODY_B = ("Inter", 13, "bold")
F_SMALL = ("Inter", 11)
F_TINY = ("Inter", 10)
F_BUTTON = ("Inter", 12, "bold")
F_GAME = ("Inter", 15, "bold")
F_GAME_SUB = ("Inter", 12)

# Colors — iOS dark system palette
C_BG = "#000000"
C_SIDEBAR = "#000000"
C_ROW = "#1c1c1e"
C_PANEL = "#1c1c1e"
C_CARD = "#2c2c2e"
C_CARD_HOVER = "#3a3a3c"
C_CARD_SELECTED = "#0A84FF"
C_BORDER = "#38383a"
C_BORDER_ACCENT = "#0A84FF"
C_TEXT = "#ffffff"
C_TEXT2 = "#aeaeb2"
C_TEXT3 = "#8e8e93"
C_ACCENT = "#0A84FF"
C_ACCENT_HOVER = "#409cff"
C_ACCENT_DIM = "#0a2540"
C_SUCCESS = "#30D158"
C_DANGER = "#FF453A"
C_DANGER_BG = "#2c1c1c"
C_BLUE = "#0A84FF"

# Geometry — bubbly / iOS
R_CARD = 18
R_WELL = 14
R_PILL = 999
THUMB_SIZE = 64
TILE_SIZE = 152
ROW_HEIGHT = 84


# Small source icons get enlarged to fill their slot, but only so far —
# past this multiple an upscale is more mush than detail, so it stops.
MAX_UPSCALE = 3.0


def _fit(img, size: int):
    """Scale an image to fill a size×size box, enlarging small art as well.

    Image.thumbnail() only ever shrinks, so a 64px icon dropped into a 152px
    tile stays 64px and reads as a speck. This scales in both directions,
    preserving aspect ratio and capping how far a low-res source is stretched.
    """
    w, h = img.size
    if not w or not h:
        return img
    factor = min(size / w, size / h)
    factor = min(factor, MAX_UPSCALE) if factor > 1 else factor
    if abs(factor - 1.0) < 0.01:
        return img
    return img.resize((max(1, round(w * factor)), max(1, round(h * factor))), _LANCZOS)


def _scaled_photo(size: int, *, path: Path | None = None, data: bytes | None = None):
    """Return a PhotoImage fitted to size×size, smoothly resampled when Pillow is present."""
    if ImageTk is not None:
        src = str(path) if path is not None else io.BytesIO(data)
        with Image.open(src) as img:
            return ImageTk.PhotoImage(_fit(img.convert("RGBA"), size))
    photo = tk.PhotoImage(file=str(path)) if path is not None else tk.PhotoImage(data=data)
    s = max(photo.width() // size, photo.height() // size, 1)
    if s > 1:
        return photo.subsample(s, s)
    z = max(1, min(int(size // max(photo.width(), photo.height(), 1)), int(MAX_UPSCALE)))
    return photo.zoom(z, z) if z > 1 else photo


def _ctk_icon(size: int, path: Path):
    """CTkImage for CustomTkinter widgets — respects HiDPI widget scaling."""
    if Image is None:
        return None
    with Image.open(path) as img:
        fitted = _fit(img.convert("RGBA"), size)
        return ctk.CTkImage(light_image=fitted, dark_image=fitted, size=fitted.size)


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
    upvotes: int = 0
    downvotes: int = 0
    source: str = "icon"


# A launcher slot is square. Anything wider than this letterboxes into a
# sliver once scaled down, so it is not worth offering as a shortcut icon.
LOGO_MAX_ASPECT = 2.0


def _ellipsize(text: str, limit: int) -> str:
    """Trim a title to `limit` characters with a trailing ellipsis.

    Tk labels clip mid-glyph with no indication that text was cut, so a long
    title just looks broken. An explicit ellipsis reads as intentional.
    """
    text = text.strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _fits_as_icon(asset: SGDBIcon) -> bool:
    """True if the artwork is square enough to read as a launcher icon."""
    if not asset.width or not asset.height:
        return True  # dimensions unknown — let the user judge from the tile
    long_side = max(asset.width, asset.height)
    short_side = min(asset.width, asset.height)
    return long_side / short_side <= LOGO_MAX_ASPECT


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

    def _fetch_assets(self, endpoint: str, game_id: int, source: str) -> list[SGDBIcon]:
        """Page through one SteamGridDB asset endpoint and normalise the results."""
        cache = CACHE_DIR / f"{source}s_{game_id}.json"
        if cache.is_file():
            try:
                if time.time() - cache.stat().st_mtime < 86400:
                    return [SGDBIcon(**d) for d in json.loads(cache.read_text())]
            except (json.JSONDecodeError, OSError, TypeError):
                pass

        raw = []
        page = 0
        while True:
            resp = self._api_get(
                f"/{endpoint}/game/{game_id}?types=static&nsfw=false&page={page}")
            batch = resp.get("data") or []
            if not batch:
                break
            raw.extend(batch)
            total = resp.get("total", 0)
            if len(raw) >= total:
                break
            page += 1

        icons: list[SGDBIcon] = []
        for item in raw:
            try:
                icons.append(SGDBIcon(
                    icon_id=item["id"], url=item["url"], thumb=item["thumb"],
                    width=item.get("width", 0), height=item.get("height", 0),
                    mime=item.get("mime", ""), style=item.get("style", ""),
                    upvotes=item.get("upvotes", 0),
                    downvotes=item.get("downvotes", 0),
                    source=source,
                ))
            except (KeyError, TypeError):
                continue

        try:
            cache.write_text(json.dumps([
                {"icon_id": i.icon_id, "url": i.url, "thumb": i.thumb,
                 "width": i.width, "height": i.height, "mime": i.mime,
                 "style": i.style, "upvotes": i.upvotes, "downvotes": i.downvotes,
                 "source": i.source}
                for i in icons
            ]))
        except OSError:
            pass
        return icons

    def get_icons(self, game_id: int) -> list[SGDBIcon]:
        """Icons first, then logos square enough to pass as launcher icons.

        SteamGridDB serves icons and logos from separate endpoints. Icons alone
        are often only a handful per game, so logos supply the rest — but a
        desktop launcher renders a square, and a 4:1 wordmark letterboxes into
        an unreadable sliver. Only logos within LOGO_MAX_ASPECT survive, and
        icons always outrank them so auto-assign never picks a logo while a
        real icon exists. Within each group, most popular first.
        """
        assets = self._fetch_assets("icons", game_id, "icon")
        try:
            logos = self._fetch_assets("logos", game_id, "logo")
            assets += [lg for lg in logos if _fits_as_icon(lg)]
        except RuntimeError:
            pass  # logos are a bonus — never fail the whole lookup over them

        assets.sort(
            key=lambda ic: (
                ic.source == "icon",              # icons before logos
                ic.upvotes - ic.downvotes,        # then net votes
                ic.width * ic.height,             # then resolution
            ),
            reverse=True,
        )
        return assets

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

    def download_preview(self, icon: SGDBIcon) -> bytes:
        """Bytes for the grid tile — full-resolution art, cached on disk.

        The `thumb` URL is small enough to look soft in a large tile, so prefer
        the real asset and fall back to the thumbnail if it won't fetch.
        """
        h = hashlib.md5(icon.url.encode()).hexdigest()
        cache = CACHE_DIR / f"preview_{h}"
        if cache.is_file():
            return cache.read_bytes()
        try:
            data = self._cdn_get(icon.url, timeout=20)
        except Exception:
            return self.download_thumbnail(icon.thumb)
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


def _desktop_icon(path: Path) -> Path | None:
    try:
        for line in path.read_text(errors="ignore").splitlines():
            if line.startswith("Icon="):
                return Path(line.split("=", 1)[1].strip())
    except OSError:
        pass
    return None


def _existing_shortcuts() -> dict[str, Path | None]:
    out: dict[str, Path | None] = {}
    if not APPLICATIONS_DIR.is_dir():
        return out
    for f in APPLICATIONS_DIR.glob(f"{DESKTOP_PREFIX}*.desktop"):
        appid = f.stem[len(DESKTOP_PREFIX):]
        out[appid] = _desktop_icon(f)
    return out


def create_shortcut(game: SteamGame, icon_src: Path, skip_refresh: bool = False) -> None:
    if icon_src.suffix.lower() not in VALID_ICON_EXTS:
        raise ValueError(f"Unsupported icon type: {icon_src.suffix}")

    ICON_STORE.mkdir(parents=True, exist_ok=True)
    APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)

    if icon_src.parent.resolve() == ICON_STORE.resolve():
        stored = icon_src
    else:
        digest = hashlib.md5(icon_src.name.encode()).hexdigest()[:8]
        stored = ICON_STORE / f"{game.appid}_{digest}{icon_src.suffix.lower()}"
        shutil.copyfile(icon_src, stored)

    desktop_path = _desktop_path(game.appid)
    previous_icon = _desktop_icon(desktop_path)

    desktop_path.write_text(
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
    if previous_icon:
        try:
            icon_store = ICON_STORE.resolve()
            previous_resolved = previous_icon.resolve()
            stored_resolved = stored.resolve()
            if (previous_resolved != stored_resolved
                    and previous_resolved.is_relative_to(icon_store)):
                previous_icon.unlink(missing_ok=True)
        except OSError:
            pass
    if not skip_refresh:
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
# GUI — Sidebar game item
# ---------------------------------------------------------------------------

class GameItem(ctk.CTkFrame):
    THUMB = THUMB_SIZE

    def __init__(self, master, game: SteamGame, on_click, **kw):
        super().__init__(master, corner_radius=R_CARD, fg_color=C_ROW,
                         height=ROW_HEIGHT, **kw)
        self.game = game
        self._on_click = on_click
        self._selected = False
        self._photo = None

        self.configure(cursor="hand2")
        self.grid_columnconfigure(2, weight=1)

        # Icon well — rounded square that keeps every icon the same footprint
        self.well = ctk.CTkFrame(
            self, width=self.THUMB, height=self.THUMB,
            corner_radius=R_WELL, fg_color=C_CARD,
        )
        self.well.grid(row=0, column=0, rowspan=2, padx=(10, 0), pady=10)
        self.well.grid_propagate(False)
        self.well.grid_rowconfigure(0, weight=1)
        self.well.grid_columnconfigure(0, weight=1)

        self.thumb_label = ctk.CTkLabel(self.well, text="", width=1, height=1)
        self.thumb_label.grid(row=0, column=0)
        self._load_thumb()

        # Game name
        self.name_lbl = ctk.CTkLabel(
            self, text=_ellipsize(game.name, 22), anchor="w", font=F_GAME,
            text_color=C_TEXT,
        )
        self.name_lbl.grid(row=0, column=2, sticky="sw", padx=(14, 12), pady=(12, 0))

        # Subtitle
        sub = f"{game.appid}"
        if game.has_shortcut:
            sub += "  ·  ●"
        self.sub_lbl = ctk.CTkLabel(
            self, text=sub, anchor="w", font=F_GAME_SUB,
            text_color=C_SUCCESS if game.has_shortcut else C_TEXT3,
        )
        self.sub_lbl.grid(row=1, column=2, sticky="nw", padx=(14, 12), pady=(2, 12))

        for w in [self, self.well, self.thumb_label, self.name_lbl, self.sub_lbl]:
            w.bind("<Button-1>", lambda _: self._on_click(self))
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)

    def _load_thumb(self):
        if not self.game.icon_path or not self.game.icon_path.exists():
            self.thumb_label.configure(text="🎮", font=("Inter", 26), text_color=C_TEXT3)
            return
        inner = self.THUMB - 16
        try:
            photo = _ctk_icon(inner, self.game.icon_path)
            if photo is None:
                photo = _scaled_photo(inner, path=self.game.icon_path)
            self._photo = photo
            self.thumb_label.configure(image=photo, text="")
        except (tk.TclError, OSError, ValueError):
            self.thumb_label.configure(text="🎮", font=("Inter", 24), text_color=C_SUCCESS)

    def _enter(self, _=None):
        if not self._selected:
            self.configure(fg_color=C_CARD_HOVER)

    def _leave(self, _=None):
        if not self._selected:
            self.configure(fg_color=C_ROW)

    def set_selected(self, sel: bool):
        self._selected = sel
        self.configure(fg_color=C_CARD_SELECTED if sel else C_ROW)
        self.well.configure(fg_color=C_ROW if sel else C_CARD)
        self.name_lbl.configure(text_color=C_TEXT)
        if not self.game.has_shortcut:
            self.sub_lbl.configure(text_color="#cfe6ff" if sel else C_TEXT3)

    def refresh(self):
        sub = f"{self.game.appid}"
        if self.game.has_shortcut:
            sub += "  ·  ●"
        self.sub_lbl.configure(
            text=sub,
            text_color=C_SUCCESS if self.game.has_shortcut else C_TEXT3,
        )
        self._load_thumb()


# ---------------------------------------------------------------------------
# GUI — Icon tile in main panel
# ---------------------------------------------------------------------------

class IconTile(ctk.CTkFrame):
    def __init__(self, master, icon: SGDBIcon, on_pick, **kw):
        super().__init__(master, corner_radius=R_CARD, fg_color=C_ROW,
                         border_width=2, border_color=C_ROW, **kw)
        self.icon = icon
        self._on_pick = on_pick
        self._photo = None

        self.configure(cursor="hand2")

        # Icon well — uniform rounded square behind every thumbnail
        self.well = ctk.CTkFrame(self, width=TILE_SIZE, height=TILE_SIZE,
                                 corner_radius=R_WELL, fg_color=C_CARD)
        self.well.pack(padx=10, pady=(10, 8))
        self.well.pack_propagate(False)

        # Placeholder until the artwork arrives — the tile occupies its final
        # footprint immediately so the grid never reflows as images stream in.
        self.img_holder = ctk.CTkLabel(
            self.well, text="", width=TILE_SIZE - 24, height=TILE_SIZE - 24,
        )
        self.img_holder.place(relx=0.5, rely=0.5, anchor="center")
        self.img_holder.bind("<Button-1>", lambda _: self._on_pick(self.icon))

        # Info line
        size = f"{icon.width}×{icon.height}" if icon.width else "—"
        votes = f"▲{icon.upvotes}" if icon.upvotes else ""
        ctk.CTkLabel(self, text=f"{size}  {votes}".strip(), font=F_TINY,
                     text_color=C_TEXT3).pack(pady=(0, 4))

        # Style pill — accent for official artwork, neutral for everything else
        label = icon.style or "custom"
        if icon.source == "logo":
            label = f"{label} logo"
        official = (icon.style or "").lower() == "official"
        ctk.CTkLabel(
            self, text=label, font=F_TINY,
            text_color=C_ACCENT if official else C_TEXT2,
            fg_color=C_ACCENT_DIM if official else C_CARD,
            corner_radius=10, height=20,
        ).pack(padx=12, pady=(0, 12), fill="x")

        self._bind_hover()

    def set_image(self, data: bytes) -> None:
        """Swap the placeholder for real artwork once it has downloaded."""
        try:
            photo = _scaled_photo(TILE_SIZE - 24, data=data)
        except (tk.TclError, OSError, ValueError):
            self.img_holder.configure(text="?", font=F_HEADING, text_color=C_TEXT3)
            return
        self._photo = photo
        self.img_holder.configure(image=photo, text="")
        self._bind_hover()

    def _bind_hover(self):
        """Highlight the border for the whole tile.

        Binding only the outer frame breaks as soon as the pointer reaches a
        child widget: Tk delivers <Leave> to the parent and the border drops
        out while the cursor is still visibly over the tile. Binding every
        descendant keeps the highlight stable, and clicking anywhere picks.
        """
        def walk(widget):
            yield widget
            for child in widget.winfo_children():
                yield from walk(child)

        for w in walk(self):
            w.bind("<Enter>", lambda _: self.configure(border_color=C_ACCENT), add="+")
            w.bind("<Leave>", lambda _: self._maybe_unhighlight(), add="+")
            if w is not self:
                w.bind("<Button-1>", lambda _: self._on_pick(self.icon), add="+")

    def _maybe_unhighlight(self):
        """Only clear the border once the pointer has actually left the tile."""
        try:
            x, y = self.winfo_pointerxy()
            inside = (self.winfo_rootx() <= x < self.winfo_rootx() + self.winfo_width()
                      and self.winfo_rooty() <= y < self.winfo_rooty() + self.winfo_height())
            if not inside:
                self.configure(border_color=C_ROW)
        except tk.TclError:
            pass


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

        ctk.CTkLabel(self, text="Settings", font=F_HEADING, text_color=C_TEXT,
                      ).pack(padx=24, pady=(24, 16), anchor="w")

        box = ctk.CTkFrame(self, fg_color=C_PANEL, corner_radius=R_CARD)
        box.pack(fill="x", padx=24, pady=(0, 16))

        ctk.CTkLabel(box, text="SteamGridDB API Key", font=F_BODY_B,
                      text_color=C_TEXT).pack(padx=16, pady=(16, 2), anchor="w")
        ctk.CTkLabel(box, text="Free at steamgriddb.com → Profile → API",
                      font=F_TINY, text_color=C_TEXT3).pack(padx=16, pady=(0, 8), anchor="w")

        self.key_entry = ctk.CTkEntry(box, placeholder_text="Paste API key",
                                       font=F_BODY, corner_radius=19, height=38)
        self.key_entry.pack(fill="x", padx=16, pady=(0, 16))
        if config.get("steamgriddb_api_key"):
            self.key_entry.insert(0, config["steamgriddb_api_key"])

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=(0, 24))
        ctk.CTkButton(row, text="Cancel", height=34, fg_color=C_CARD,
                       hover_color=C_CARD_HOVER, text_color=C_TEXT, corner_radius=17,
                       font=F_BUTTON, command=self.destroy).pack(side="right")
        ctk.CTkButton(row, text="Save", height=34, fg_color=C_ACCENT,
                       hover_color=C_ACCENT_HOVER, corner_radius=17, font=F_BUTTON,
                       command=self._save).pack(side="right", padx=(0, 8))

    def _save(self):
        key = self.key_entry.get().strip()
        if key:
            self.config["steamgriddb_api_key"] = key
        else:
            self.config.pop("steamgriddb_api_key", None)
        save_config(self.config)
        self.destroy()


# ---------------------------------------------------------------------------
# GUI — Main application (dashboard layout)
# ---------------------------------------------------------------------------

class SteamShortcutForge(ctk.CTk):
    ICON_COLS = 3

    def __init__(self):
        super().__init__(fg_color=C_BG)
        self.title("Steam Shortcut Forge")
        self.geometry("1320x860")
        self.minsize(1040, 620)

        self.config_data = load_config()
        self.games: list[SteamGame] = []
        self.items: list[GameItem] = []
        self.selected_item: GameItem | None = None
        self._icon_photos: list = []
        self._tiles: list = []
        self._grid_cols = 0
        self._resize_job = None
        self._filter_mode = "all"

        self._build()
        self._first_run()
        self._scan()

    def _build(self):
        # ── Root grid: sidebar | main ──────────────────────────────────
        self.grid_columnconfigure(0, weight=0, minsize=380)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── SIDEBAR ───────────────────────────────────────────────────
        sidebar = ctk.CTkFrame(self, fg_color=C_SIDEBAR, corner_radius=0, width=380)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(3, weight=1)
        sidebar.grid_columnconfigure(0, weight=1)

        # Header — title on the left, live count pill on the right
        logo_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        logo_frame.grid(row=0, column=0, sticky="ew", padx=16, pady=(18, 6))
        ctk.CTkLabel(logo_frame, text="Games", font=F_LOGO,
                     text_color=C_TEXT).pack(side="left")
        self.count_pill = ctk.CTkLabel(
            logo_frame, text="0", font=F_SMALL, text_color=C_TEXT2,
            fg_color=C_ROW, corner_radius=11, width=40, height=22,
        )
        self.count_pill.pack(side="right")

        # Search
        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._filter())
        ctk.CTkEntry(
            sidebar, textvariable=self.search_var, height=40, corner_radius=20,
            placeholder_text="Search…", font=F_BODY,
            border_width=1, border_color=C_BORDER,
        ).grid(row=1, column=0, sticky="ew", padx=16, pady=(12, 8))

        # Filter chips
        chip_row = ctk.CTkFrame(sidebar, fg_color="transparent")
        chip_row.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))

        self.chip_all = ctk.CTkButton(
            chip_row, text="All", width=52, height=30, corner_radius=15,
            fg_color=C_ACCENT_DIM, hover_color=C_CARD_HOVER,
            text_color=C_TEXT, font=F_TINY, border_width=1,
            border_color=C_BORDER_ACCENT,
            command=lambda: self._set_filter("all"),
        )
        self.chip_all.pack(side="left", padx=(0, 4))

        self.chip_has = ctk.CTkButton(
            chip_row, text="● Active", width=70, height=30, corner_radius=15,
            fg_color="transparent", hover_color=C_CARD_HOVER,
            text_color=C_TEXT3, font=F_TINY, border_width=1,
            border_color=C_BORDER,
            command=lambda: self._set_filter("with"),
        )
        self.chip_has.pack(side="left", padx=(0, 4))

        self.chip_none = ctk.CTkButton(
            chip_row, text="○ None", width=66, height=30, corner_radius=15,
            fg_color="transparent", hover_color=C_CARD_HOVER,
            text_color=C_TEXT3, font=F_TINY, border_width=1,
            border_color=C_BORDER,
            command=lambda: self._set_filter("without"),
        )
        self.chip_none.pack(side="left")

        # Game list
        self.game_list = ctk.CTkScrollableFrame(
            sidebar, fg_color="transparent", corner_radius=0,
            scrollbar_fg_color="transparent",
            scrollbar_button_color=C_CARD, scrollbar_button_hover_color=C_TEXT3,
        )
        self.game_list.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.game_list._scrollbar.configure(width=8, corner_radius=4, border_spacing=3)
        self.game_list.grid_columnconfigure(0, weight=1)

        # Sidebar bottom buttons
        sb_bottom = ctk.CTkFrame(sidebar, fg_color="transparent")
        sb_bottom.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 16))

        ctk.CTkButton(
            sb_bottom, text="⚙  Settings", height=36, corner_radius=18,
            fg_color=C_CARD, hover_color=C_CARD_HOVER, text_color=C_TEXT2,
            font=F_BUTTON, anchor="w", command=self._settings,
        ).pack(fill="x", pady=(0, 6))

        ctk.CTkButton(
            sb_bottom, text="↻  Rescan", height=36, corner_radius=18,
            fg_color=C_CARD, hover_color=C_CARD_HOVER, text_color=C_TEXT2,
            font=F_BUTTON, anchor="w", command=self._scan,
        ).pack(fill="x")

        # ── MAIN PANEL ────────────────────────────────────────────────
        main = ctk.CTkFrame(self, fg_color=C_BG, corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_rowconfigure(2, weight=1)
        main.grid_columnconfigure(0, weight=1)

        # Header area
        self.main_header = ctk.CTkLabel(
            main, text="Select a game", font=F_TITLE, text_color=C_TEXT,
        )
        self.main_header.grid(row=0, column=0, sticky="w", padx=28, pady=(28, 4))

        self.main_sub = ctk.CTkLabel(
            main, text="Choose a game from the sidebar to browse icons",
            font=F_SMALL, text_color=C_TEXT3,
        )
        self.main_sub.grid(row=1, column=0, sticky="w", padx=28, pady=(0, 16))

        # Icon grid area
        self.icon_area = ctk.CTkScrollableFrame(
            main, fg_color=C_PANEL, corner_radius=R_CARD,
            scrollbar_fg_color="transparent",
            scrollbar_button_color=C_CARD, scrollbar_button_hover_color=C_TEXT3,
        )
        self.icon_area.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 8))
        self.icon_area._scrollbar.configure(width=8, corner_radius=4, border_spacing=3)
        # add="+" is essential: CTkScrollableFrame binds <Configure> on itself to
        # recompute the canvas scrollregion. Replacing that binding leaves the
        # region stale, the canvas believes everything fits, and the mouse wheel
        # silently stops working.
        self.icon_area.bind("<Configure>", self._on_icon_area_resize, add="+")

        # Action bar at bottom
        action_bar = ctk.CTkFrame(main, fg_color="transparent")
        action_bar.grid(row=3, column=0, sticky="ew", padx=28, pady=(8, 16))

        self.browse_btn = ctk.CTkButton(
            action_bar, text="📁  Browse local file", height=42, corner_radius=21,
            fg_color=C_CARD, hover_color=C_CARD_HOVER, text_color=C_TEXT,
            font=F_BUTTON, command=self._on_browse, state="disabled",
        )
        self.browse_btn.pack(side="left", padx=(0, 8))

        self.remove_btn = ctk.CTkButton(
            action_bar, text="Remove shortcut", height=42, corner_radius=21,
            fg_color=C_DANGER_BG, hover_color="#3a2020", text_color=C_DANGER,
            font=F_BUTTON, command=self._on_remove, state="disabled",
        )
        self.remove_btn.pack(side="left", padx=(0, 8))

        self.bulk_btn = ctk.CTkButton(
            action_bar, text="⬇  Auto-assign all", height=42, corner_radius=21,
            fg_color=C_ACCENT_DIM, hover_color=C_CARD_HOVER, text_color=C_ACCENT,
            font=F_BUTTON, command=self._on_bulk,
        )
        self.bulk_btn.pack(side="right")

        # Status
        self.status = ctk.CTkLabel(
            main, text="", font=F_TINY, text_color=C_TEXT3,
        )
        self.status.grid(row=4, column=0, sticky="w", padx=28, pady=(0, 12))

    # -- Data -----------------------------------------------------------

    def _first_run(self):
        if not self.config_data.get("steamgriddb_api_key"):
            from tkinter import messagebox
            if messagebox.askyesno("Setup",
                "Steam Shortcut Forge needs a SteamGridDB API key.\n\n"
                "Get one free at steamgriddb.com → Profile → API.\n\nEnter now?"):
                self._settings()

    def _scan(self):
        self.status.configure(text="Scanning…")
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
        self.count_pill.configure(text=str(len(self.games)))

    def _set_filter(self, mode: str):
        self._filter_mode = mode
        for btn, m in [(self.chip_all, "all"), (self.chip_has, "with"),
                       (self.chip_none, "without")]:
            if m == mode:
                btn.configure(fg_color=C_ACCENT_DIM, text_color=C_TEXT,
                              border_color=C_BORDER_ACCENT)
            else:
                btn.configure(fg_color="transparent", text_color=C_TEXT3,
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

        for it in self.items:
            it.destroy()
        self.items.clear()
        self.selected_item = None
        self._set_actions(False)

        for i, game in enumerate(filtered):
            item = GameItem(self.game_list, game, on_click=self._select_game)
            item.grid(row=i, column=0, sticky="ew", padx=4, pady=4)
            self.items.append(item)

    def _select_game(self, item: GameItem):
        if self.selected_item:
            self.selected_item.set_selected(False)
        item.set_selected(True)
        self.selected_item = item
        self._set_actions(True)

        # Update header
        self.main_header.configure(text=item.game.name)
        self.main_sub.configure(text=f"App ID: {item.game.appid}  ·  Loading icons…")

        # Auto-fetch icons
        self._load_icons(item.game)

    def _set_actions(self, on: bool):
        s = "normal" if on else "disabled"
        self.browse_btn.configure(state=s)
        self.remove_btn.configure(state=s)

    # -- Icon loading ---------------------------------------------------

    def _scroll_icons_to_top(self):
        """Reset the icon grid viewport. Destroying tiles leaves the canvas
        scrolled where the previous game's longer list was, so a shorter list
        renders above the visible area and the panel looks empty."""
        try:
            canvas = self.icon_area._parent_canvas
            canvas.update_idletasks()
            canvas.yview_moveto(0.0)
        except (AttributeError, tk.TclError):
            pass

    def _load_icons(self, game: SteamGame):
        # Clear existing
        for w in self.icon_area.winfo_children():
            w.destroy()
        self._icon_photos.clear()
        self._tiles.clear()
        self._scroll_icons_to_top()
        self.after_idle(self._scroll_icons_to_top)

        key = self.config_data.get("steamgriddb_api_key")
        if not key:
            self.main_sub.configure(text="Set API key in Settings to browse icons")
            return

        client = SteamGridDBClient(key)

        def fetch():
            try:
                gid = client.get_game_id(game.appid)
                if gid is None:
                    self.after(0, lambda: self.main_sub.configure(
                        text=f"App ID: {game.appid}  ·  Not found on SteamGridDB"))
                    return
                icons = client.get_icons(gid)
                if not icons:
                    self.after(0, lambda: self.main_sub.configure(
                        text=f"App ID: {game.appid}  ·  No icons available"))
                    return

                self.after(0, lambda: self.main_sub.configure(
                    text=f"App ID: {game.appid}  ·  {len(icons)} icons  ·  Most popular first"))

                # Lay the full grid out first so it settles into its final
                # shape immediately, then stream artwork into the placeholders.
                self.after(0, self._build_tiles, icons, game)

                for i, icon in enumerate(icons):
                    try:
                        data = client.download_preview(icon)
                        self.after(0, self._fill_tile, i, data, game)
                    except Exception:
                        continue

            except RuntimeError as exc:
                msg = str(exc)
                self.after(0, lambda: self.main_sub.configure(text=msg))
            except Exception as exc:
                msg = f"Error: {exc}"
                self.after(0, lambda: self.main_sub.configure(text=msg))

        threading.Thread(target=fetch, daemon=True).start()

    def _still_showing(self, game: SteamGame) -> bool:
        return bool(self.selected_item) and self.selected_item.game.appid == game.appid

    GRID_GUTTER = 12   # grid padx=6 on each side

    def _fit_columns(self) -> int:
        """How many tiles fit across the icon panel at its current width.

        Measures a real tile once one exists — an estimate was landing at
        ~3.97 columns on a panel that comfortably holds 4, and floor() threw
        the extra column away. Falls back to an estimate for the first build.
        """
        try:
            avail = self.icon_area.winfo_width()
        except tk.TclError:
            return self.ICON_COLS
        if avail <= 1:                       # not laid out yet
            return self.ICON_COLS

        if self._tiles:
            try:
                cell = self._tiles[0].winfo_reqwidth() + self.GRID_GUTTER
            except tk.TclError:
                cell = (TILE_SIZE + 36) * UI_SCALE
        else:
            cell = (TILE_SIZE + 36) * UI_SCALE

        # Tolerate a couple of pixels of slop so a near-exact fit still counts.
        return max(1, int((avail + 4) // cell))

    def _regrid_tiles(self, cols: int | None = None):
        """Re-flow the existing tiles into `cols` columns."""
        cols = cols or self._fit_columns()
        if cols == self._grid_cols or not self._tiles:
            return
        self._grid_cols = cols
        for idx, tile in enumerate(self._tiles):
            row, col = divmod(idx, cols)
            tile.grid_configure(row=row, column=col)

    def _on_icon_area_resize(self, _event=None):
        """Debounced re-flow — Configure fires continuously while dragging."""
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(120, self._regrid_tiles)

    def _build_tiles(self, icons: list[SGDBIcon], game: SteamGame):
        """Place every tile as an empty placeholder before any art downloads."""
        if not self._still_showing(game):
            return
        self._tiles = []
        cols = self._fit_columns()
        self._grid_cols = cols
        for idx, icon in enumerate(icons):
            row, col = divmod(idx, cols)
            tile = IconTile(self.icon_area, icon, on_pick=self._pick_icon)
            tile.grid(row=row, column=col, padx=6, pady=6, sticky='n')
            self._tiles.append(tile)
        self.after_idle(self._scroll_icons_to_top)
        # Width is often still stale on first layout — re-check once settled.
        self.after_idle(lambda: self._regrid_tiles(self._fit_columns()))

    def _fill_tile(self, idx: int, data: bytes, game: SteamGame):
        """Drop artwork into an already-placed tile."""
        if not self._still_showing(game):
            return
        if idx < len(self._tiles):
            try:
                self._tiles[idx].set_image(data)
            except tk.TclError:
                pass

    def _pick_icon(self, icon: SGDBIcon):
        if not self.selected_item:
            return
        game = self.selected_item.game
        self.main_sub.configure(text=f"Downloading icon…")
        self.update_idletasks()

        def dl():
            try:
                ext = Path(urllib.parse.urlparse(icon.url).path).suffix.lower()
                if ext not in VALID_ICON_EXTS:
                    ext = ".png"
                dest = ICON_STORE / f"{game.appid}_{icon.icon_id}{ext}"
                client = SteamGridDBClient(self.config_data["steamgriddb_api_key"])
                client.download_icon(icon.url, dest)
                self.after(0, lambda: self._apply_icon(game, dest))
            except Exception as exc:
                msg = f"Download failed: {exc}"
                self.after(0, lambda: self.main_sub.configure(text=msg))

        threading.Thread(target=dl, daemon=True).start()

    # -- Actions --------------------------------------------------------

    def _settings(self):
        SettingsDialog(self, self.config_data)
        self.config_data = load_config()

    def _apply_icon(self, game: SteamGame, path: Path):
        if not self._still_showing(game):
            return
        item = self.selected_item
        if item is None:
            return
        try:
            create_shortcut(game, path)
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("Error", str(e))
            return
        item.refresh()
        self.main_sub.configure(text=f"App ID: {game.appid}  ·  Shortcut created!")
        self.status.configure(
            text=f"{len(self.games)} games  ·  "
                 f"{sum(1 for g in self.games if g.has_shortcut)} with shortcuts")

    def _on_browse(self):
        if not self.selected_item:
            return
        path = filedialog.askopenfilename(
            title=f"Icon for {self.selected_item.game.name}",
            filetypes=[("Icon images", "*.ico *.png *.svg *.xpm"), ("All", "*.*")],
        )
        if path:
            self._apply_icon(self.selected_item.game, Path(path))

    def _on_remove(self):
        if not self.selected_item or not self.selected_item.game.has_shortcut:
            return
        from tkinter import messagebox
        if messagebox.askyesno("Remove", f"Remove shortcut for {self.selected_item.game.name}?"):
            remove_shortcut(self.selected_item.game)
            self.selected_item.refresh()
            self.main_sub.configure(text=f"App ID: {self.selected_item.game.appid}  ·  Shortcut removed")
            self.status.configure(
                text=f"{len(self.games)} games  ·  "
                     f"{sum(1 for g in self.games if g.has_shortcut)} with shortcuts")

    def _on_bulk(self):
        key = self.config_data.get("steamgriddb_api_key")
        if not key:
            from tkinter import messagebox
            messagebox.showinfo("API Key Required", "Set your API key in Settings first.")
            return
        todo = [g for g in self.games if not g.has_shortcut]
        if not todo:
            self.status.configure(text="All games already have shortcuts.")
            return
        from tkinter import messagebox
        if not messagebox.askyesno("Auto-assign",
            f"Fetch the best icon for {len(todo)} game(s)?"):
            return

        self.bulk_btn.configure(state="disabled", text="Working…")

        def worker():
            client = SteamGridDBClient(key)
            done, fail = 0, 0
            failures: list[str] = []
            for i, game in enumerate(todo):
                self.after(0, lambda g=game, n=i: self.status.configure(
                    text=f"({n+1}/{len(todo)}) {g.name}…"))
                try:
                    gid = client.get_game_id(game.appid)
                    if not gid:
                        fail += 1
                        failures.append(f"{game.name}: not found on SteamGridDB")
                        continue
                    icons = client.get_icons(gid)
                    if not icons:
                        fail += 1
                        failures.append(f"{game.name}: no icons available")
                        continue
                    best = icons[0]
                    ext = Path(urllib.parse.urlparse(best.url).path).suffix.lower()
                    if ext not in VALID_ICON_EXTS:
                        ext = ".png"
                    dest = ICON_STORE / f"{game.appid}_{best.icon_id}{ext}"
                    client.download_icon(best.url, dest)
                    create_shortcut(game, dest, skip_refresh=True)
                    done += 1
                except Exception as exc:
                    fail += 1
                    failures.append(f"{game.name}: {exc}")
                    msg = str(exc)
                    self.after(0, lambda g=game, m=msg: self.status.configure(
                        text=f"Skipped {g.name}: {m}"))
                finally:
                    time.sleep(0.3)
            _refresh_db()
            summary = f"Done — {done} assigned, {fail} skipped"
            def finish():
                self.bulk_btn.configure(state="normal", text="⬇  Auto-assign all")
                self.status.configure(text=summary)
                self._filter()
                if failures:
                    from tkinter import messagebox
                    messagebox.showwarning(
                        "Auto-assign skipped games",
                        "Some games could not be assigned:\n\n" + "\n".join(failures),
                    )
            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def main() -> int:
    if sys.platform not in ("linux", "linux2"):
        print("Steam Shortcut Forge targets Linux desktops.")
        return 1
    SteamShortcutForge().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
