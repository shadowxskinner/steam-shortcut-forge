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

# Colours
#
# Deep navy surfaces at distinct elevations rather than transparency, because
# Tk cannot composite translucent panels. Elevation is carried by value
# instead: the window is darkest, each column sits a step above it, and cards
# a step above that. One indigo accent for selection and primary actions, one
# pink for destructive ones, and three levels of text so secondary
# information recedes without disappearing.
C_BG = "#0E0B1E"            # window
C_NAV = "#14102C"           # left column
C_LIST = "#171332"          # middle column
C_PANEL = "#1B1640"         # workspace surface
C_CARD = "#221C4E"          # rows, wells, fields
C_CARD_HOVER = "#2A2360"
C_SELECTED = "#2E2668"
C_BORDER = "#2C2657"
C_BORDER_ACCENT = "#5B3DF5"

C_ACCENT = "#5B3DF5"        # primary actions, selection
C_ACCENT_HOVER = "#7059FF"
C_ACCENT_DIM = "#241B54"
C_DANGER = "#FF2D6F"        # destructive only
C_DANGER_BG = "#3A1030"
C_DANGER_HOVER = "#4A1540"
C_SUCCESS = "#35D6A0"

C_TEXT = "#FFFFFF"
C_TEXT2 = "#A9A3C9"
C_TEXT3 = "#6F6A93"

# Kept so the classic window keeps working while the new shell is proven.
C_SIDEBAR = C_NAV
C_ROW = C_CARD
C_CARD_SELECTED = C_ACCENT

# Geometry
R_CARD = 16
R_WELL = 12
R_FIELD = 10
R_PILL = 999
THUMB_SIZE = 56
TILE_SIZE = 124
ROW_HEIGHT = 68

# Column widths. The middle column carries the longest strings in the
# application - full game titles - so it gets the space, taken from the
# navigation, which only ever holds short labels.
W_NAV = 206
W_LIST = 398

#: Characters before an entry name is ellipsized in the middle column.
LIST_NAME_CHARS = 34

# Control heights, so fields and pills line up wherever they appear.
H_FIELD = 36
H_PILL = 30
H_ACTION = 40

# Fonts specific to the shell
F_NAV_GROUP = ("Inter", 10, "bold")
F_NAV_ITEM = ("Inter", 13)
F_WORKSPACE_TITLE = ("Inter", 24, "bold")
F_SECTION = ("Inter", 10, "bold")
F_PILL = ("Inter", 11, "bold")


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


def confidence_label(confidence: float) -> str:
    """Plain words for a match score.

    A number between 0 and 1 means nothing to someone who just wants nicer
    icons, and showing one invites the question of what 0.75 is supposed to
    mean.
    """
    if confidence >= 1.0:
        return "Exact match"
    if confidence >= 0.9:
        return "Exact name"
    if confidence >= 0.75:
        return "Strong match"
    return "Good match"


def format_date(iso: str) -> str:
    """2026-08-27T14:02:11Z -> 27 Aug 2026."""
    import time
    try:
        parsed = time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return iso or ""
    return time.strftime("%d %b %Y", parsed)
