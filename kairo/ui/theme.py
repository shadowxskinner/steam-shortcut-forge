"""Visual tokens. One place to change how Kairo looks."""

from __future__ import annotations

try:
    import customtkinter as ctk
except ImportError:                                     # pragma: no cover
    ctk = None

#: Global size multiplier for every widget.
UI_SCALE = 1.1

# Fonts
F_LOGO = ("Inter", 20, "bold")
F_TITLE = ("Inter", 18, "bold")
F_HEADING = ("Inter", 15, "bold")
F_BODY = ("Inter", 13)
F_BODY_B = ("Inter", 13, "bold")
F_SMALL = ("Inter", 11)
F_TINY = ("Inter", 10)
F_BUTTON = ("Inter", 12, "bold")
F_ITEM = ("Inter", 15, "bold")
F_ITEM_SUB = ("Inter", 12)

# Colours - dark system palette
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

# Geometry
R_CARD = 18
R_WELL = 14
THUMB_SIZE = 64
TILE_SIZE = 152
ROW_HEIGHT = 84


def apply() -> None:
    """Install appearance settings. Called once at startup.

    CustomTkinter draws rounded corners from a bundled OTF on Linux, but its
    FontManager.load_font() copies the file into ~/.fonts and returns True
    without checking that Tk can use it, so corners silently render square.
    polygon_shapes draws them with canvas polygons instead, which is what
    macOS uses.
    """
    if ctk is None:
        return
    try:
        from customtkinter.windows.widgets.core_rendering import DrawEngine
        DrawEngine.preferred_drawing_method = "polygon_shapes"
    except ImportError:
        pass
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    ctk.set_widget_scaling(UI_SCALE)


def ellipsize(text: str, limit: int) -> str:
    """Trim a title with a trailing ellipsis.

    Tk labels clip mid-glyph with no indication that text was cut, so a long
    title just looks broken. An explicit ellipsis reads as intentional.
    """
    text = text.strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"
