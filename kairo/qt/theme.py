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

    workspace: float = 0.62  # backdrop behind the cards
    nav: float = 0.94        # navigation column
    list: float = 0.93       # entry column
    panel: float = 0.92      # workspace cards
    card: float = 0.88       # rows, wells, fields
    tile: float = 0.84       # artwork tiles, lightest for depth
    line: float = 0.55       # borders and separators

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
#: never legible text. Dense exists because on a real display 0.92 still let
#: terminal text read through - kept as a preset rather than a new default so
#: the two can be compared side by side before either is baked in.
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

W_NAV = 240
W_LIST = 404

H_NAV_ITEM = 42
H_ROW = 76
H_CONTROL = 40
H_ACTION = 44

WELL_ROW = 44                # icon inside an entry row
WELL_COMPARE = 76            # current / proposed
TILE = 116                   # artwork tile

PAD_PANE = 28                # outer margin of a pane
PAD_COLUMN = 20              # inside the nav and entry columns
PAD_CARD = 24                # inside a card
GAP = 12                     # between related things
GAP_WIDE = 20                # between blocks
GAP_ROW = 6                  # between list rows

R_CARD = 18
R_CONTROL = 12
R_WELL = 14
R_PILL = 999

# Type. A wider spread than the Tk scale: the reference leans hard on size to
# carry hierarchy, so bold has less work to do.
FS_LOGO = 20
FS_TITLE = 30
FS_PANE = 18
FS_ROW = 14
FS_ROW_META = 12
FS_BODY = 13
FS_META = 12
FS_MICRO = 10
FS_BUTTON = 13
FS_PILL = 12


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

    return f"""
    /* ---------- surfaces ---------- */
    QWidget#root      {{ background: transparent; }}
    QWidget#nav       {{ background: {rgba(T.C_NAV, g.nav)};
                         border-right: 1px solid {rgba(T.C_BORDER, g.line)}; }}
    QWidget#list      {{ background: {rgba(T.C_LIST, g.list)};
                         border-right: 1px solid {rgba(T.C_BORDER, g.line)}; }}
    QWidget#workspace {{ background: {rgba(T.C_BG, g.workspace)}; }}
    QFrame#card       {{ background: {rgba(T.C_PANEL, g.panel)};
                         border: 1px solid {rgba(T.C_BORDER, g.line)};
                         border-radius: {R_CARD}px; }}
    QFrame#well       {{ background: {rgba(T.C_CARD, g.card)};
                         border-radius: {R_WELL}px; }}
    QFrame#divider    {{ background: {rgba(T.C_BORDER, g.line)};
                         border: none; max-height: 1px; }}

    /* ---------- type: never translucent ---------- */
    QLabel            {{ background: transparent; color: {T.C_TEXT2}; }}
    QLabel#logo       {{ color: {T.C_TEXT}; font-size: {FS_LOGO}px;
                         font-weight: 700; letter-spacing: 1px; }}
    QLabel#logoSub    {{ color: {T.C_TEXT3}; font-size: {FS_META}px; }}
    QLabel#title      {{ color: {T.C_TEXT}; font-size: {FS_TITLE}px;
                         font-weight: 700; }}
    QLabel#pane       {{ color: {T.C_TEXT}; font-size: {FS_PANE}px;
                         font-weight: 700; }}
    QLabel#meta       {{ color: {T.C_TEXT3}; font-size: {FS_META}px; }}
    QLabel#micro      {{ color: {T.C_TEXT3}; font-size: {FS_MICRO}px;
                         font-weight: 700; letter-spacing: 1px; }}
    QLabel#rowName    {{ color: {T.C_TEXT2}; font-size: {FS_ROW}px; }}
    QLabel#rowNameOn  {{ color: {T.C_TEXT}; font-size: {FS_ROW}px;
                         font-weight: 700; }}
    QLabel#rowMeta    {{ color: {T.C_TEXT3}; font-size: {FS_ROW_META}px; }}
    QLabel#rowMetaOn  {{ color: {T.C_ACCENT_TEXT}; font-size: {FS_ROW_META}px; }}
    QLabel#dot        {{ color: {T.C_SUCCESS}; font-size: {FS_META}px; }}
    QLabel#empty      {{ color: {T.C_TEXT3}; font-size: {FS_BODY}px; }}
    QLabel#banner     {{ color: {T.C_TEXT3}; font-size: {FS_META}px; }}
    QLabel#count      {{ color: {T.C_TEXT2}; font-size: {FS_META}px;
                         background: {rgba(T.C_CARD, g.card)};
                         border-radius: 11px; padding: 3px 10px; }}

    /* ---------- navigation ---------- */
    QPushButton#nav        {{ background: transparent; border: none;
                              border-radius: {R_CONTROL}px;
                              padding: 0px 14px; text-align: left;
                              color: {T.C_TEXT2}; font-size: {FS_ROW}px; }}
    QPushButton#nav:hover  {{ background: {rgba(T.C_CARD, g.card)}; }}
    QPushButton#nav:checked{{ background: {rgba(T.C_SELECTED_NAV, g.card)};
                              color: {T.C_TEXT}; font-weight: 700; }}

    /* ---------- entry rows ---------- */
    QFrame#row         {{ background: {rgba(T.C_CARD, g.card)};
                          border: 1px solid transparent;
                          border-radius: {R_CONTROL}px; }}
    QFrame#row:hover   {{ background: {rgba(T.C_CARD_HOVER, g.card)}; }}
    QFrame#rowOn       {{ background: {rgba(T.C_SELECTED, g.card)};
                          border: 1px solid {T.C_ACCENT};
                          border-radius: {R_CONTROL}px; }}

    /* ---------- artwork tiles ---------- */
    QFrame#tile        {{ background: {rgba(T.C_CARD, g.tile)};
                          border: 2px solid transparent;
                          border-radius: {R_CONTROL}px; }}
    QFrame#tile:hover  {{ border: 2px solid {T.C_BORDER_STRONG}; }}
    QFrame#tileOn      {{ background: {rgba(T.C_ACCENT_SOFT, g.card)};
                          border: 2px solid {T.C_ACCENT_BRIGHT};
                          border-radius: {R_CONTROL}px; }}

    /* ---------- controls ---------- */
    QLineEdit          {{ background: {rgba(T.C_CARD, g.card)};
                          border: 1px solid {rgba(T.C_BORDER, g.line)};
                          border-radius: {R_CONTROL}px;
                          padding: 10px 14px; min-height: {H_CONTROL - 22}px;
                          color: {T.C_TEXT}; font-size: {FS_BODY}px;
                          selection-background-color: {T.C_ACCENT}; }}
    QLineEdit:focus    {{ border: 1px solid {T.C_ACCENT}; }}

    QPushButton#pill        {{ background: transparent; border: none;
                               border-radius: {R_PILL}px; padding: 7px 16px;
                               color: {T.C_TEXT3}; font-size: {FS_PILL}px;
                               font-weight: 700; }}
    QPushButton#pill:hover  {{ background: {rgba(T.C_CARD_HOVER, g.card)}; }}
    QPushButton#pill:checked{{ background: {T.C_ACCENT_BRIGHT};
                               color: {T.C_TEXT}; }}
    QWidget#pillGroup       {{ background: {rgba(T.C_CARD, g.card)};
                               border-radius: {R_PILL}px; }}

    QPushButton#secondary       {{ background: {rgba(T.C_CARD, g.card)};
                                   border: 1px solid {rgba(T.C_BORDER, g.line)};
                                   border-radius: {R_CONTROL}px;
                                   padding: 11px 20px; color: {T.C_TEXT};
                                   font-size: {FS_BUTTON}px; font-weight: 700; }}
    QPushButton#secondary:hover {{ background: {rgba(T.C_CARD_HOVER, g.card)}; }}
    QPushButton#primary         {{ background: {T.C_ACCENT_BRIGHT};
                                   border: none; border-radius: {R_CONTROL}px;
                                   padding: 11px 26px; color: {T.C_TEXT};
                                   font-size: {FS_BUTTON}px; font-weight: 700; }}
    QPushButton#primary:hover   {{ background: {T.C_ACCENT_HOVER}; }}
    QPushButton#danger          {{ background: {rgba(T.C_DANGER_BG, g.card)};
                                   border: 1px solid {rgba(T.C_DANGER, 0.35)};
                                   border-radius: {R_CONTROL}px;
                                   padding: 11px 20px; color: {T.C_DANGER};
                                   font-size: {FS_BUTTON}px; font-weight: 700; }}
    /* Disabled reads as unavailable, not merely as dimmer text. */
    QPushButton:disabled        {{ background: {rgba(T.C_CARD, g.card)};
                                   border: 1px solid {rgba(T.C_BORDER, g.line)};
                                   color: {T.C_TEXT3}; }}

    QSlider::groove:horizontal  {{ height: 4px; border-radius: 2px;
                                   background: {rgba(T.C_CARD_HOVER, g.card)}; }}
    QSlider::sub-page:horizontal{{ background: {T.C_ACCENT}; border-radius: 2px; }}
    QSlider::handle:horizontal  {{ background: {T.C_ACCENT_BRIGHT};
                                   width: 14px; margin: -6px 0;
                                   border-radius: 7px; }}

    /* ---------- scrolling ---------- */
    QScrollArea            {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical    {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {rgba(T.C_CARD_HOVER, g.card)};
                                   border-radius: 5px; min-height: 36px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                                   background: transparent; }}
    """
