"""Every visual value Kairo uses.

Widgets read tokens from here rather than carrying numbers of their own. That
is not tidiness for its own sake: things at the same level of the hierarchy
line up only if they are literally the same constant, and a one-off 14 next to
a 16 is exactly how an interface starts looking accidental.

The palette is layered rather than translucent. Tk cannot composite panels, so
depth is carried by value: the window is darkest, each column sits a step
above it, cards a step above that. One indigo accent carries selection and
primary action; pink appears only where something is destroyed.
"""

from __future__ import annotations

try:
    import customtkinter as ctk
except ImportError:                                     # pragma: no cover
    ctk = None

#: Global widget scaling.
UI_SCALE = 1.0

# ---------------------------------------------------------------------------
# Colour
# ---------------------------------------------------------------------------

C_BG = "#0B0918"             # window
C_NAV = "#100D22"            # navigation column
C_LIST = "#13102C"           # entry column
C_PANEL = "#171334"          # workspace surfaces
C_CARD = "#1E1943"           # rows, wells, fields
C_CARD_HOVER = "#262052"
C_SELECTED = "#4B32E0"       # selected row surface
C_BORDER = "#231E4C"         # barely there, on purpose
C_BORDER_STRONG = "#2E2865"

C_ACCENT = "#5B3DF5"
C_ACCENT_HOVER = "#6E52FF"
C_ACCENT_SOFT = "#211B52"    # accent at rest, for quiet fills
C_ACCENT_TEXT = "#B9AAFF"

C_DANGER = "#FF3D74"         # destructive only
C_DANGER_BG = "#2E1230"
C_DANGER_HOVER = "#3D1840"
C_SUCCESS = "#3DD8A0"

C_TEXT = "#F4F2FF"           # primary
C_TEXT2 = "#A79FD0"          # secondary, clearly quieter
C_TEXT3 = "#6B6499"          # tertiary: labels, metadata, placeholders

# Aliases kept so the classic window keeps working unchanged.
C_SIDEBAR = C_NAV
C_ROW = C_CARD
C_CARD_SELECTED = C_SELECTED
C_BORDER_ACCENT = C_ACCENT
C_ACCENT_DIM = C_ACCENT_SOFT

# ---------------------------------------------------------------------------
# Spacing
#
# A single 4px scale. Everything below is chosen from it; nothing in a widget
# should invent a value that is not here.
# ---------------------------------------------------------------------------

S1, S2, S3, S4, S5, S6, S8 = 4, 8, 12, 16, 20, 24, 32

PAD_WINDOW = S6              # outer margin of the workspace
PAD_COLUMN = S4              # inside the nav and entry columns
PAD_CARD = S4                # inside a card
PAD_CARD_TIGHT = S3
GAP_ROW = S1                 # between list rows
GAP_CONTROL = S2             # between adjacent controls
GAP_SECTION = S5             # between blocks of a pane
GAP_GROUP = S6               # between unrelated groups

# ---------------------------------------------------------------------------
# Shape and size
# ---------------------------------------------------------------------------

R_SM = 8
R_MD = 12
R_LG = 16
R_PILL = 999

R_CARD = R_LG                # aliases used by the classic window
R_WELL = R_MD
R_FIELD = R_MD

H_CONTROL = 34               # search fields, pills, toolbar buttons
H_ACTION = 40                # action-bar buttons
H_NAV_ITEM = 34
H_ROW = 62                   # entry row

THUMB_SIZE = 40              # icon inside an entry row
WELL_SIZE = 62               # current / proposed wells
TILE_SIZE = 112              # artwork tile
ROW_HEIGHT = H_ROW           # classic alias

W_NAV = 212
W_LIST = 392
LIST_NAME_CHARS = 32

#: Roughly four across at the default window width.
GRID_GUTTER = S2

# Aliases kept so the existing panes and the classic window keep working.
H_FIELD = H_CONTROL
H_PILL = H_CONTROL - 4

# ---------------------------------------------------------------------------
# Typography
#
# Bold carries hierarchy, not emphasis. Row titles are regular weight; only
# titles, primary values and controls are bold, which is what stops a dark
# interface looking shouty.
# ---------------------------------------------------------------------------

_FAMILY = "Inter"

F_LOGO = (_FAMILY, 19, "bold")          # KAIRO
F_TITLE = (_FAMILY, 25, "bold")         # selected entry, pane title
F_PANE = (_FAMILY, 17, "bold")          # column heading
F_ROW = (_FAMILY, 13)                   # entry name, regular on purpose
F_ROW_STRONG = (_FAMILY, 13, "bold")    # entry name when selected
F_BODY = (_FAMILY, 12)
F_BODY_B = (_FAMILY, 12, "bold")
F_META = (_FAMILY, 11)                  # ids, counts, dates
F_MICRO = (_FAMILY, 9, "bold")          # CURRENT / PROPOSED / LIBRARY
F_BUTTON = (_FAMILY, 12, "bold")
F_PILL = (_FAMILY, 11, "bold")

# Aliases for the classic window.
F_HEADING = F_PANE
F_SMALL = F_META
F_TINY = F_META
F_ITEM = F_ROW
F_ITEM_SUB = F_META
F_NAV_GROUP = F_MICRO
F_NAV_ITEM = F_ROW
F_SECTION = F_MICRO
F_WORKSPACE_TITLE = F_TITLE

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def apply() -> None:
    """Install appearance settings. Called once at startup.

    CustomTkinter draws rounded corners from a bundled OTF on Linux, but its
    FontManager.load_font() copies the file into ~/.fonts and returns True
    without checking Tk can use it, so corners silently render square.
    polygon_shapes draws them with canvas polygons instead.
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

    Tk clips mid-glyph with no indication that anything was cut, so a long
    title just looks broken. An explicit ellipsis reads as intentional.
    """
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def confidence_label(confidence: float) -> str:
    """Plain words for a match score.

    A number between 0 and 1 means nothing to someone who just wants nicer
    icons, and showing one invites the question of what 0.75 means.
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


def initial(text: str) -> str:
    """First letter of a provider name, for its navigation chip."""
    for char in (text or "").strip():
        if char.isalnum():
            return char.upper()
    return "•"
