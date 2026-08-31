"""Qt styling, built from the same tokens the Tk shell uses.

``kairo.ui.theme`` holds the palette, the spacing scale and the type scale, and
none of that is toolkit-specific. Importing it here rather than restating it
means the two frontends cannot drift while both exist.

Alpha is what Qt adds, and it is applied per surface rather than to the window.
A single window-wide opacity is what Tk offered and it is the wrong model: it
fades text along with everything else, and it makes every surface equally
see-through whether it is holding content or not. Here the reading surfaces are
nearly solid, the small tiles are a little lighter for depth, and only the
background is genuinely open - which is what makes it read as frosted glass
rather than tinted glass.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from kairo.ui import theme as T


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

    workspace: float = 0.78  # backdrop behind the cards
    nav: float = 0.97        # navigation column
    list: float = 0.96       # entry column
    panel: float = 0.95      # workspace cards
    card: float = 0.92       # rows, wells, fields
    tile: float = 0.88       # artwork tiles, lightest for depth
    line: float = 0.62       # borders and separators

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


#: Frosted is the default: content behind a panel should be shape and colour,
#: never legible text. The live shell-6 screenshots showed that the original
#: tint left terminal text competing with the interface, so the reading layers
#: are denser while the workspace still admits wallpaper colour. Dense remains
#: available for especially high-contrast backgrounds.
PRESETS = {
    "frosted": Glass(),
    "dense": Glass(workspace=0.86, nav=0.985, list=0.98, panel=0.975,
                   card=0.95, tile=0.92, line=0.70),
    "clear": Glass(workspace=0.30, nav=0.78, list=0.76, panel=0.74, card=0.70,
                   tile=0.66, line=0.45),
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

W_NAV = 244
W_LIST = 372                 # narrower than the workspace: artwork is the work

H_HEADER = 88                # the header band, shared by all three columns
H_NAV_ITEM = 40
H_ROW = 76
H_FIELD = 36                 # search, artwork query
H_BUTTON = 36                # every button, everywhere
H_PILLS = 30

WELL_ROW = 44                # icon inside an entry row
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
MARK_SIZE = 28               # the application mark in the sidebar header
FS_TITLE = 28
FS_PANE = 15
FS_ROW = 13
FS_ROW_META = 11
FS_BODY = 13
FS_META = 11
FS_MICRO = 10
FS_BUTTON = 13
FS_PILL = 12

WT_REGULAR = 400
WT_MEDIUM = 500
WT_SEMI = 600                # the heaviest weight in the product

# Truncation. Sized to the column rather than inherited, so a narrower list
# does not clip mid-glyph — an explicit ellipsis reads as a choice.
LIST_NAME_CHARS = 30
LIST_META_CHARS = 34

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
    hair = rgba(T.C_BORDER_STRONG, max(g.line, 0.5))
    edge = rgba(T.C_BORDER, g.line * 0.30)

    return f"""
    /* ---------- surfaces ---------- */
    QWidget#root      {{ background: transparent; }}
    QWidget#nav       {{ background: {rgba(T.C_NAV, g.nav)};
                         border-right: 1px solid {edge}; }}
    QWidget#list      {{ background: {rgba(T.C_LIST, g.list)};
                         border-right: 1px solid {edge}; }}
    QWidget#workspace {{ background: {rgba(T.C_BG, g.workspace)}; }}
    /* A dialog is its own top-level window, so it gets its own surface id
       rather than borrowing the pane's: two #workspace widgets in one file
       usually means one nested inside the other, which double-paints. */
    QDialog#dialog    {{ background: {rgba(T.C_NAV, 1.0)}; }}
    QWidget#footer    {{ background: {rgba(T.C_NAV, g.nav)};
                         border-top: 1px solid {edge}; }}
    /* The inspector is a surface, not a box: no outline, just a lift. */
    QFrame#card       {{ background: {rgba(T.C_PANEL, g.panel)};
                         border: none; border-radius: {R_CARD}px; }}
    QFrame#well       {{ background: {rgba(T.C_CARD, g.card)};
                         border-radius: {R_WELL}px; }}
    QFrame#divider    {{ background: {hair}; border: none; max-height: 1px; }}

    /* ---------- type ---------- */
    QLabel            {{ background: transparent; color: {T.C_TEXT2}; }}
    QLabel#badge      {{ background: transparent; }}
    QLabel#logo       {{ color: {T.C_TEXT}; font-size: {FS_LOGO}px;
                         font-weight: {WT_SEMI}; letter-spacing: 2.5px; }}
    QLabel#title      {{ color: {T.C_TEXT}; font-size: {FS_TITLE}px;
                         font-weight: {WT_SEMI}; letter-spacing: -0.4px; }}
    QLabel#pane       {{ color: {T.C_TEXT}; font-size: {FS_PANE}px;
                         font-weight: {WT_SEMI}; letter-spacing: -0.1px; }}
    QLabel#meta       {{ color: {T.C_TEXT3}; font-size: {FS_META}px; }}
    QLabel#subtitle   {{ color: {rgba(T.C_TEXT2, 0.62)};
                         font-size: {FS_BODY}px; }}
    QLabel#count      {{ color: {T.C_TEXT3}; font-size: {FS_META}px; }}
    QLabel#micro      {{ color: {T.C_TEXT3}; font-size: {FS_MICRO}px;
                         font-weight: {WT_MEDIUM}; letter-spacing: 1.4px; }}
    QLabel#rowName    {{ color: {T.C_TEXT2}; font-size: {FS_ROW}px; }}
    QLabel#rowNameOn  {{ color: {T.C_TEXT}; font-size: {FS_ROW}px;
                         font-weight: {WT_MEDIUM}; }}
    QLabel#rowMeta    {{ color: {T.C_TEXT3}; font-size: {FS_ROW_META}px; }}
    QLabel#rowMetaOn  {{ color: {T.C_TEXT2}; font-size: {FS_ROW_META}px; }}
    QLabel#navName    {{ color: {T.C_TEXT2}; font-size: {FS_ROW}px; }}
    QLabel#navNameOn  {{ color: {T.C_TEXT}; font-size: {FS_ROW}px;
                         font-weight: {WT_MEDIUM}; }}
    QLabel#navCount   {{ color: {T.C_TEXT3}; font-size: {FS_META}px; }}
    QLabel#wellMark   {{ color: {rgba(T.C_TEXT3, 0.75)};
                         font-size: {FS_PANE}px; font-weight: {WT_MEDIUM}; }}
    QLabel#dot        {{ color: {rgba(T.C_SUCCESS, 0.55)};
                         font-size: {FS_MICRO}px; }}
    QLabel#empty      {{ color: {T.C_TEXT3}; font-size: {FS_BODY}px; }}
    QLabel#status     {{ color: {T.C_TEXT3}; font-size: {FS_META}px; }}

    /* ---------- navigation ---------- */
    /* A destination, not a button: no border, no bold, a soft fill when it
       is the one you are looking at. */
    QPushButton#nav        {{ background: transparent; border: none;
                              border-radius: {R_CONTROL}px; text-align: left;
                              padding: 0px; }}
    QPushButton#nav:hover  {{ background: {rgba(T.C_CARD, g.card * 0.5)}; }}
    QPushButton#nav:checked{{ background: {rgba(T.C_SELECTED_NAV, g.card)}; }}

    /* ---------- entry rows ---------- */
    /* At rest a row is nothing at all — the icon and the name are the row.
       Chrome appears on hover, and selection is a filled surface. */
    QFrame#row         {{ background: transparent; border: none;
                          border-radius: {R_CONTROL}px; }}
    QFrame#row:hover   {{ background: {rgba(T.C_CARD, g.card * 0.55)}; }}
    QFrame#rowOn       {{ background: {rgba(T.C_SELECTED, g.card)};
                          border: none; border-radius: {R_CONTROL}px; }}

    /* ---------- artwork tiles ---------- */
    QFrame#tile        {{ background: transparent; border: none;
                          border-radius: {R_CONTROL}px; }}
    QFrame#tile:hover  {{ background: {rgba(T.C_CARD, g.tile * 0.6)}; }}
    QFrame#tileOn      {{ background: {rgba(T.C_ACCENT_SOFT, g.card)};
                          border: none; border-radius: {R_CONTROL}px; }}

    /* ---------- fields ---------- */
    QLineEdit          {{ background: {rgba(T.C_CARD, g.card * 0.8)};
                          border: none; border-radius: {R_CONTROL}px;
                          padding: 0px 12px; min-height: {H_FIELD}px;
                          max-height: {H_FIELD}px;
                          color: {T.C_TEXT}; font-size: {FS_BODY}px;
                          selection-background-color: {T.C_ACCENT}; }}
    QLineEdit:focus    {{ background: {rgba(T.C_CARD_HOVER, g.card)}; }}

    /* ---------- pills ---------- */
    QWidget#pillGroup       {{ background: {rgba(T.C_CARD, g.card * 0.7)};
                               border-radius: {R_PILL}px; }}
    QPushButton#pill        {{ background: transparent; border: none;
                               border-radius: {R_PILL}px; padding: 0px 14px;
                               min-height: {H_PILLS - 6}px;
                               color: {T.C_TEXT3}; font-size: {FS_PILL}px; }}
    QPushButton#pill:hover  {{ color: {T.C_TEXT2}; }}
    QPushButton#pill:checked{{ background: {rgba(T.C_SELECTED, 0.95)};
                               color: {T.C_TEXT}; font-weight: {WT_MEDIUM}; }}

    /* ---------- buttons: one family, three volumes ---------- */
    QPushButton#secondary       {{ background: {rgba(T.C_CARD, g.card * 0.8)};
                                   border: none; border-radius: {R_CONTROL}px;
                                   padding: 0px 16px; min-height: {H_BUTTON}px;
                                   color: {T.C_TEXT2};
                                   font-size: {FS_BUTTON}px; }}
    QPushButton#secondary:hover {{ background: {rgba(T.C_CARD_HOVER, g.card)};
                                   color: {T.C_TEXT}; }}
    QPushButton#primary         {{ background: {T.C_ACCENT_BRIGHT};
                                   border: none; border-radius: {R_CONTROL}px;
                                   padding: 0px 22px; min-height: {H_BUTTON}px;
                                   color: {T.C_TEXT}; font-size: {FS_BUTTON}px;
                                   font-weight: {WT_MEDIUM}; }}
    QPushButton#primary:hover   {{ background: {T.C_ACCENT_HOVER}; }}
    /* Destructive, and quiet until you reach for it. */
    QPushButton#danger          {{ background: transparent; border: none;
                                   border-radius: {R_CONTROL}px;
                                   padding: 0px 16px; min-height: {H_BUTTON}px;
                                   color: {T.C_TEXT3};
                                   font-size: {FS_BUTTON}px; }}
    QPushButton#danger:hover    {{ background: {rgba(T.C_DANGER_BG, g.card)};
                                   color: {T.C_DANGER}; }}
    /* An id selector outranks a bare pseudo-class, so #primary:disabled has
       to be named or a disabled Apply keeps its accent and reads as live. */
    QPushButton:disabled,
    QPushButton#secondary:disabled,
    QPushButton#primary:disabled {{ background: {rgba(T.C_CARD, g.card * 0.55)};
                                   color: {rgba(T.C_TEXT3, 0.8)};
                                   font-weight: {WT_REGULAR}; }}
    QPushButton#danger:disabled {{ background: transparent;
                                   color: {rgba(T.C_TEXT3, 0.6)}; }}

    QSlider::groove:horizontal  {{ height: 3px; border-radius: 2px;
                                   background: {rgba(T.C_CARD_HOVER, g.card)}; }}
    QSlider::sub-page:horizontal{{ background: {T.C_ACCENT}; border-radius: 2px; }}
    QSlider::handle:horizontal  {{ background: {T.C_TEXT}; width: 13px;
                                   margin: -5px 0; border-radius: 6px; }}

    /* ---------- scrolling ---------- */
    QScrollArea            {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical    {{ background: transparent; width: 8px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {rgba(T.C_CARD_HOVER, 0.30)};
                                   border-radius: 4px; min-height: 40px; }}
    QScrollBar::handle:vertical:hover {{ background: {rgba(T.C_CARD_HOVER, 0.7)}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                                   background: transparent; }}
    """
