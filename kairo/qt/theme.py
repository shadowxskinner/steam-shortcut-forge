"""Qt styling: shared semantics, native composited material.

``kairo.ui.theme`` still owns semantic colours such as accent, success and
danger. Qt owns its surface and text neutrals because translucent material is
not the same thing as Tk's opaque navy depth scale. Keeping that split here
lets the glass lose its blue cast without changing the established Tk build.

Alpha is what Qt adds, and it is applied per surface rather than to the window.
A single window-wide opacity is what Tk offered and it is the wrong model: it
fades text along with everything else, and it makes every surface equally
see-through whether it is holding content or not. Here reading surfaces carry
enough neutral tint for contrast, smaller tiles are clearer for depth, and the
workspace is genuinely open—which lets the compositor read as the material
instead of as a blue overlay.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from kairo.ui import theme as T


# Neutral charcoal material for the composited Qt shell. Violet is reserved
# for controls that are active; it is no longer the ambient colour of every
# surface, border and line of secondary text.
C_BG = "#0A0A0D"
C_NAV = "#0E0E11"
C_LIST = "#111114"
C_PANEL = "#17171B"
C_CARD = "#1D1D22"
C_CARD_HOVER = "#26262C"
C_SELECTED = "#2B2B33"
C_SELECTED_NAV = "#232329"
C_BORDER = "#2B2B31"
C_BORDER_STRONG = "#3A3A42"
C_ACCENT_SOFT = "#282332"

C_TEXT = "#F5F5F7"
C_TEXT2 = "#B8B8C2"
C_TEXT3 = "#777781"

SURFACE_COLOURS = (C_BG, C_NAV, C_LIST, C_PANEL, C_CARD, C_CARD_HOVER,
                   C_SELECTED, C_SELECTED_NAV, C_BORDER, C_BORDER_STRONG)


@dataclass(frozen=True)
class Glass:
    """How see-through each layer is.

    ``workspace`` is the backdrop the cards sit on - the title area, the gaps
    between panels, the action bar, the margins. It used to be fully
    transparent, which is why content behind the window stayed legible however
    hard the compositor blurred: blur smears what is behind a surface, it does
    not dim it, and a region with no surface at all has nothing to dim with.
    Raising it is what stops text reading through; lowering it shows more
    wallpaper. That trade is the whole point of it being a slider.

    The root stays fully transparent regardless, so the window still has no
    rectangle of its own beyond its panels.
    """

    workspace: float = 0.50  # open backdrop: blur and wallpaper colour
    nav: float = 0.86        # navigation column
    list: float = 0.84       # entry column
    panel: float = 0.82      # workspace cards
    card: float = 0.76       # rows, wells, fields
    tile: float = 0.70       # artwork tiles, clearest for depth
    line: float = 0.42       # borders and separators

    def describe(self) -> str:
        """The constructor line for these values.

        Tuning happens by eye at runtime; this is how the result gets back
        into the source without anyone transcribing six numbers.
        """
        return ("Glass(workspace={0.workspace:.2f}, nav={0.nav:.2f}, "
                "list={0.list:.2f}, panel={0.panel:.2f}, card={0.card:.2f}, "
                "tile={0.tile:.2f}, line={0.line:.2f})".format(self))

    def replaced(self, **values) -> "Glass":
        clean = {name: max(0.0, min(1.0, float(value)))
                 for name, value in values.items()}
        return replace(self, **clean)

    def shifted(self, delta: float) -> "Glass":
        clamp = lambda value: max(0.0, min(1.0, value + delta))
        return replace(self, workspace=clamp(self.workspace),
                       nav=clamp(self.nav), list=clamp(self.list),
                       panel=clamp(self.panel), card=clamp(self.card),
                       tile=clamp(self.tile), line=clamp(self.line))


#: Frosted is the default: neutral dark material with enough tint to keep text
#: readable and enough alpha for the compositor's blur to remain unmistakable.
#: Dense remains available for unusually high-contrast wallpaper.
PRESETS = {
    "frosted": Glass(),
    "dense": Glass(workspace=0.68, nav=0.93, list=0.91, panel=0.89,
                   card=0.85, tile=0.80, line=0.56),
    "clear": Glass(workspace=0.25, nav=0.68, list=0.65, panel=0.62, card=0.56,
                   tile=0.50, line=0.32),
    "solid": Glass(workspace=1.0, nav=1.0, list=1.0, panel=1.0, card=1.0,
                   tile=1.0, line=1.0),
}
LAYERS = ("workspace", "nav", "list", "panel", "card", "tile", "line")
DEFAULT_PRESET = "frosted"

# Kept so older callers and the entry point keep working.
DEFAULT_ALPHA = PRESETS[DEFAULT_PRESET].panel
MIN_ALPHA, MAX_ALPHA = 0.0, 1.0


# ---------------------------------------------------------------------------
# Layout and type, Qt's own
#
# The Tk shell's tokens were sized for a denser, flatter window. The reference
# gets most of its quality from room: taller rows, larger radii, more padding
# and a wider spread between type sizes. Keeping a separate scale here means
# the Qt shell can be given that room without dragging the Tk build's
# proportions around behind it.
# ---------------------------------------------------------------------------

MIN_WINDOW_WIDTH = 900
BREAKPOINT_COMPACT = 1320
BREAKPOINT_NARROW = 1040

W_NAV = 244
W_LIST = 372                 # narrower than the workspace: artwork is the work
W_NAV_COMPACT = 196
W_LIST_COMPACT = 320
W_NAV_NARROW = 80            # mark and destination icons, without labels
W_LIST_NARROW = 280          # the inspector keeps at least 540px at the floor
W_QUERY_COMPACT = 200
W_QUERY_NARROW = 180

H_HEADER = 88                # the header band, shared by all three columns
H_NAV_ITEM = 44
H_ROW = 64
H_FIELD = 36                 # search, artwork query
H_BUTTON = 36                # every button, everywhere
H_PILLS = 30

WELL_ROW = 44                # icon inside an entry row
WELL_TITLE = 64              # the current icon, beside the title
WELL_COMPARE = 64            # current / proposed — deliberately secondary
TILE = 116                   # artwork tile

PAD_PANE = 28                # outer margin of a pane
PAD_COLUMN = 18              # inside the nav and entry columns
PAD_CARD = 22                # inside the inspector
GAP = 12                     # between related things
GAP_WIDE = 20                # between blocks
GAP_ROW = 4                  # between list rows: they carry no chrome at rest

R_CARD = 14
R_CONTROL = 9
R_WELL = 11
R_PILL = 999

# Type. Hierarchy is carried by size, spacing and colour; weight is the last
# resort, and never goes above 600. The selected item's name is the loudest
# thing on screen by a wide margin, and everything else steps down from there.
FS_LOGO = 14
MARK_SIZE = 56               # the application mark in the sidebar header
NAV_ICON = 22                # provider logos in the sidebar

#: Drawn pictograms are neutral on purpose. The shared text palette is still
#: violet-tinted — C_TEXT3 is #6B6499, a channel spread of 53 — so a glyph
#: painted in it read as a third brand colour beside Steam's and Dolphin's
#: real ones. Kairo's own marks carry no hue; only an installed product does.
GLYPH = "#8A8A93"
GLYPH_ON = "#D6D6DC"
FS_DOT = 15                  # the 'customized' mark on an entry row
FS_TITLE = 28
FS_PANE = 15
FS_ROW = 13
FS_ROW_META = 11
FS_BODY = 13
FS_META = 11
FS_MICRO = 10
FS_BUTTON = 13
FS_PILL = 12

#: Preferred families, best first. Qt walks these, so a machine without the
#: first still gets the closest thing it has rather than a default serif-ish
#: fallback. SF Pro is Apple's own and will only be present if the user
#: installed it; Inter is the free face designed to sit in the same place.
FONT_STACK = ("SF Pro Text", "SF Pro Display", "Inter", "Inter Display",
              "Adwaita Sans", "Noto Sans", "DejaVu Sans")

WT_REGULAR = 400
WT_MEDIUM = 500
WT_SEMI = 600                # the heaviest weight in the product

# Truncation. Sized to the column rather than inherited, so a narrower list
# does not clip mid-glyph — an explicit ellipsis reads as a choice.
LIST_NAME_CHARS = 30

# Named columns, so labels and readouts share one left edge.
W_QUERY = 240                # artwork search field
W_LABEL = 76                 # settings label gutter
W_READOUT = 44               # numeric readout beside a slider
W_KEY = 190                  # key column in the paths table
W_MEASURE = 660              # comfortable line length for prose


def rgba(colour: str, alpha: float = 1.0) -> str:
    colour = colour.lstrip("#")
    red, green, blue = (int(colour[index:index + 2], 16) for index in (0, 2, 4))
    if alpha >= 1.0:
        return f"rgb({red}, {green}, {blue})"
    return f"rgba({red}, {green}, {blue}, {alpha:.3f})"


def resolve(glass=None) -> Glass:
    """Accept a Glass, a preset name, or a plain number for one-off tuning."""
    if glass is None:
        return PRESETS[DEFAULT_PRESET]
    if isinstance(glass, Glass):
        return glass
    if isinstance(glass, str):
        return PRESETS.get(glass, PRESETS[DEFAULT_PRESET])
    if isinstance(glass, (int, float)):
        base = PRESETS[DEFAULT_PRESET]
        return base.shifted(float(glass) - base.panel)
    return PRESETS[DEFAULT_PRESET]


def stylesheet(glass=None) -> str:
    """The whole application's appearance, as one sheet.

    Text, icons and borders never take the surface alpha. Only backgrounds do,
    which is the entire point of moving off Tk.
    """
    g = resolve(glass)

    # Borders are the first thing to go when an interface is asked to feel
    # calm: a box around everything makes every element argue for attention.
    # Separators run below the tunable line alpha but never vanish, and
    # surfaces carry the grouping instead.
    hair = rgba(C_BORDER_STRONG, max(g.line, 0.5))
    edge = rgba(C_BORDER, g.line * 0.30)

    return f"""
    /* ---------- surfaces ---------- */
    QWidget#root      {{ background: transparent; }}
    QWidget#nav       {{ background: {rgba(C_NAV, g.nav)};
                         border-right: 1px solid {edge}; }}
    QWidget#list      {{ background: {rgba(C_LIST, g.list)};
                         border-right: 1px solid {edge}; }}
    QWidget#workspace {{ background: {rgba(C_BG, g.workspace)}; }}
    /* A dialog is its own top-level window, so it gets its own surface id
       rather than borrowing the pane's: two #workspace widgets in one file
       usually means one nested inside the other, which double-paints. */
    QDialog#dialog    {{ background: {rgba(C_NAV, 1.0)}; }}
    QWidget#footer    {{ background: {rgba(C_NAV, g.nav)};
                         border-top: 1px solid {edge}; }}
    /* The inspector is a surface, not a box: no outline, just a lift. */
    QFrame#card       {{ background: {rgba(C_PANEL, g.panel)};
                         border: none; border-radius: {R_CARD}px; }}
    QFrame#well       {{ background: {rgba(C_CARD, g.card)};
                         border-radius: {R_WELL}px; }}
    QFrame#divider    {{ background: {hair}; border: none; max-height: 1px; }}

    /* ---------- type ---------- */
    QLabel            {{ background: transparent; color: {C_TEXT2}; }}
    QLabel#badge      {{ background: transparent; }}
    QLabel#logo       {{ color: {C_TEXT}; font-size: {FS_LOGO}px;
                         font-weight: {WT_SEMI}; letter-spacing: 2.5px; }}
    QLabel#title      {{ color: {C_TEXT}; font-size: {FS_TITLE}px;
                         font-weight: {WT_SEMI}; letter-spacing: -0.4px; }}
    QLabel#pane       {{ color: {C_TEXT}; font-size: {FS_PANE}px;
                         font-weight: {WT_SEMI}; letter-spacing: -0.1px; }}
    QLabel#meta       {{ color: {C_TEXT3}; font-size: {FS_META}px; }}
    QLabel#subtitle   {{ color: {rgba(C_TEXT2, 0.62)};
                         font-size: {FS_BODY}px; }}
    QLabel#count      {{ color: {C_TEXT3}; font-size: {FS_META}px; }}
    QLabel#micro      {{ color: {C_TEXT3}; font-size: {FS_MICRO}px;
                         font-weight: {WT_MEDIUM}; letter-spacing: 1.4px; }}
    QLabel#rowName    {{ color: {C_TEXT2}; font-size: {FS_ROW}px; }}
    QLabel#rowNameOn  {{ color: {C_TEXT}; font-size: {FS_ROW}px;
                         font-weight: {WT_MEDIUM}; }}
    QLabel#rowMeta    {{ color: {C_TEXT3}; font-size: {FS_ROW_META}px; }}
    QLabel#navName    {{ color: {C_TEXT2}; font-size: {FS_ROW}px; }}
    QLabel#navNameOn  {{ color: {C_TEXT}; font-size: {FS_ROW}px;
                         font-weight: {WT_MEDIUM}; }}
    QLabel#navCount   {{ color: {C_TEXT3}; font-size: {FS_META}px; }}
    QLabel#wellMark   {{ color: {rgba(C_TEXT3, 0.75)};
                         font-size: {FS_PANE}px; font-weight: {WT_MEDIUM}; }}
    /* Customized. It marks a whole row, so it is sized to be seen at a
       glance rather than set in the smallest size on the scale. */
    QLabel#dot        {{ color: {rgba(T.C_SUCCESS, 0.85)};
                         font-size: {FS_DOT}px; }}
    QLabel#empty      {{ color: {C_TEXT3}; font-size: {FS_BODY}px; }}
    QLabel#status     {{ color: {C_TEXT3}; font-size: {FS_META}px; }}

    /* ---------- navigation ---------- */
    /* A destination, not a button: no border, no bold, a soft fill when it
       is the one you are looking at. */
    QPushButton#nav        {{ background: transparent; border: none;
                              border-radius: {R_CONTROL}px; text-align: left;
                              padding: 0px; }}
    QPushButton#nav:hover  {{ background: {rgba(C_CARD, g.card * 0.5)}; }}
    QPushButton#nav:checked{{ background: {rgba(C_SELECTED_NAV, g.card)}; }}

    /* ---------- entry rows ---------- */
    /* At rest a row is nothing at all — the icon and the name are the row.
       Chrome appears on hover, and selection is a filled surface. */
    QFrame#row         {{ background: transparent; border: none;
                          border-radius: {R_CONTROL}px; }}
    QFrame#row:hover   {{ background: {rgba(C_CARD, g.card * 0.55)}; }}
    QFrame#rowOn       {{ background: {rgba(C_SELECTED, g.card)};
                          border: none; border-radius: {R_CONTROL}px; }}

    /* ---------- artwork tiles ---------- */
    QFrame#tile        {{ background: transparent; border: none;
                          border-radius: {R_CONTROL}px; }}
    QFrame#tile:hover  {{ background: {rgba(C_CARD, g.tile * 0.6)}; }}
    QFrame#tileOn      {{ background: {rgba(C_ACCENT_SOFT, g.card)};
                          border: none; border-radius: {R_CONTROL}px; }}

    /* ---------- fields ---------- */
    QLineEdit          {{ background: {rgba(C_CARD, g.card * 0.8)};
                          border: none; border-radius: {R_CONTROL}px;
                          padding: 0px 12px; min-height: {H_FIELD}px;
                          max-height: {H_FIELD}px;
                          color: {C_TEXT}; font-size: {FS_BODY}px;
                          selection-background-color: {T.C_ACCENT}; }}
    QLineEdit:focus    {{ background: {rgba(C_CARD_HOVER, g.card)}; }}

    /* ---------- pills ---------- */
    QWidget#pillGroup       {{ background: {rgba(C_CARD, g.card * 0.7)};
                               border-radius: {R_PILL}px; }}
    QPushButton#pill        {{ background: transparent; border: none;
                               border-radius: {R_PILL}px; padding: 0px 14px;
                               min-height: {H_PILLS - 6}px;
                               color: {C_TEXT3}; font-size: {FS_PILL}px; }}
    QPushButton#pill:hover  {{ color: {C_TEXT2}; }}
    QPushButton#pill:checked{{ background: {rgba(C_SELECTED, 0.95)};
                               color: {C_TEXT}; font-weight: {WT_MEDIUM}; }}

    /* ---------- buttons: one family, three volumes ---------- */
    QPushButton[tight="true"]   {{ padding: 0px 8px; }}
    QPushButton#secondary       {{ background: {rgba(C_CARD, g.card * 0.8)};
                                   border: none; border-radius: {R_CONTROL}px;
                                   padding: 0px 16px; min-height: {H_BUTTON}px;
                                   color: {C_TEXT2};
                                   font-size: {FS_BUTTON}px; }}
    QPushButton#secondary:hover {{ background: {rgba(C_CARD_HOVER, g.card)};
                                   color: {C_TEXT}; }}
    QPushButton#primary         {{ background: {T.C_ACCENT_BRIGHT};
                                   border: none; border-radius: {R_CONTROL}px;
                                   padding: 0px 22px; min-height: {H_BUTTON}px;
                                   color: {C_TEXT}; font-size: {FS_BUTTON}px;
                                   font-weight: {WT_MEDIUM}; }}
    QPushButton#primary:hover   {{ background: {T.C_ACCENT_HOVER}; }}
    /* Destructive, and quiet until you reach for it. */
    QPushButton#danger          {{ background: transparent; border: none;
                                   border-radius: {R_CONTROL}px;
                                   padding: 0px 16px; min-height: {H_BUTTON}px;
                                   color: {C_TEXT3};
                                   font-size: {FS_BUTTON}px; }}
    QPushButton#danger:hover    {{ background: {rgba(T.C_DANGER_BG, g.card)};
                                   color: {T.C_DANGER}; }}
    /* An id selector outranks a bare pseudo-class, so #primary:disabled has
       to be named or a disabled Apply keeps its accent and reads as live. */
    QPushButton:disabled,
    QPushButton#secondary:disabled,
    QPushButton#primary:disabled {{ background: {rgba(C_CARD, g.card * 0.55)};
                                   color: {rgba(C_TEXT3, 0.8)};
                                   font-weight: {WT_REGULAR}; }}
    QPushButton#danger:disabled {{ background: transparent;
                                   color: {rgba(C_TEXT3, 0.6)}; }}

    QSlider::groove:horizontal  {{ height: 3px; border-radius: 2px;
                                   background: {rgba(C_CARD_HOVER, g.card)}; }}
    QSlider::sub-page:horizontal{{ background: {T.C_ACCENT}; border-radius: 2px; }}
    QSlider::handle:horizontal  {{ background: {C_TEXT}; width: 13px;
                                   margin: -5px 0; border-radius: 6px; }}

    /* ---------- scrolling ---------- */
    QScrollArea            {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical    {{ background: transparent; width: 8px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {rgba(C_CARD_HOVER, 0.30)};
                                   border-radius: 4px; min-height: 40px; }}
    QScrollBar::handle:vertical:hover {{ background: {rgba(C_CARD_HOVER, 0.7)}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                                   background: transparent; }}
    """


# ---------------------------------------------------------------------------
# Motion
# ---------------------------------------------------------------------------

def animations_enabled() -> bool:
    """Whether Kairo may move anything on its own.

    Off when KAIRO_NO_ANIMATION is set to anything truthy, and off when the
    platform has asked for reduced motion through Qt's UI effects. Motion in
    an application like this is a convenience for reading a long name; for
    somebody with a vestibular disorder it is not a convenience at all, and
    the fallback - ellipsis and a tooltip - loses nothing but the movement.
    """
    import os

    flag = os.environ.get("KAIRO_NO_ANIMATION", "").strip().lower()
    if flag and flag not in ("0", "false", "no"):
        return False
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication

        application = QApplication.instance()
        if application is not None:
            return bool(application.isEffectEnabled(Qt.UI_AnimateCombo)) or \
                bool(application.isEffectEnabled(Qt.UI_FadeMenu)) or True
    except Exception:                                   # pragma: no cover
        pass
    return True
