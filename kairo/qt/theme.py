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

    ``window`` is not a surface: the root stays fully transparent so the
    compositor's blur of the wallpaper is what fills the gaps. The rest are
    real alphas on real panels.
    """

    nav: float = 0.94        # navigation column
    list: float = 0.93       # entry column
    panel: float = 0.92      # workspace cards
    card: float = 0.88       # rows, wells, fields
    tile: float = 0.84       # artwork tiles, lightest for depth
    line: float = 0.55       # borders and separators

    def shifted(self, delta: float) -> "Glass":
        clamp = lambda value: max(0.30, min(1.0, value + delta))
        return replace(self, nav=clamp(self.nav), list=clamp(self.list),
                       panel=clamp(self.panel), card=clamp(self.card),
                       tile=clamp(self.tile), line=clamp(self.line))


#: Frosted is the default: content behind a panel should be shape and colour,
#: never legible text.
PRESETS = {
    "frosted": Glass(),
    "clear": Glass(nav=0.78, list=0.76, panel=0.74, card=0.70, tile=0.66,
                   line=0.45),
    "solid": Glass(nav=1.0, list=1.0, panel=1.0, card=1.0, tile=1.0, line=1.0),
}
DEFAULT_PRESET = "frosted"

# Kept so older callers and the entry point keep working.
DEFAULT_ALPHA = PRESETS[DEFAULT_PRESET].panel
MIN_ALPHA, MAX_ALPHA = 0.30, 1.0


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
    QWidget#workspace {{ background: transparent; }}
    QFrame#card       {{ background: {rgba(T.C_PANEL, g.panel)};
                         border: 1px solid {rgba(T.C_BORDER, g.line)};
                         border-radius: {T.R_LG}px; }}
    QFrame#well       {{ background: {rgba(T.C_CARD, g.card)};
                         border-radius: {T.R_MD}px; }}

    /* ---------- type: never translucent ---------- */
    QLabel            {{ background: transparent; color: {T.C_TEXT2}; }}
    QLabel#logo       {{ color: {T.C_TEXT}; font-size: 19px; font-weight: 700; }}
    QLabel#logoSub    {{ color: {T.C_TEXT3}; font-size: 11px; }}
    QLabel#title      {{ color: {T.C_TEXT}; font-size: 25px; font-weight: 700; }}
    QLabel#pane       {{ color: {T.C_TEXT}; font-size: 17px; font-weight: 700; }}
    QLabel#meta       {{ color: {T.C_TEXT3}; font-size: 11px; }}
    QLabel#micro      {{ color: {T.C_TEXT3}; font-size: 9px; font-weight: 700; }}
    QLabel#rowName    {{ color: {T.C_TEXT}; font-size: 13px; }}
    QLabel#rowNameOn  {{ color: {T.C_TEXT}; font-size: 13px; font-weight: 700; }}
    QLabel#rowMeta    {{ color: {T.C_TEXT3}; font-size: 11px; }}
    QLabel#rowMetaOn  {{ color: {T.C_ACCENT_TEXT}; font-size: 11px; }}
    QLabel#dot        {{ color: {T.C_SUCCESS}; font-size: 11px; }}
    QLabel#empty      {{ color: {T.C_TEXT3}; font-size: 12px; }}
    QLabel#banner     {{ color: {T.C_TEXT3}; font-size: 11px; }}

    /* ---------- navigation ---------- */
    QPushButton#nav        {{ background: transparent; border: none;
                              border-radius: {T.R_MD}px; padding: 7px 12px;
                              color: {T.C_TEXT2}; font-size: 13px;
                              text-align: left; }}
    QPushButton#nav:hover  {{ background: {rgba(T.C_CARD, g.card)}; }}
    QPushButton#nav:checked{{ background: {rgba(T.C_SELECTED_NAV, g.card)};
                              color: {T.C_TEXT}; font-weight: 700; }}

    /* ---------- entry rows ---------- */
    QFrame#row         {{ background: {rgba(T.C_CARD, g.card)};
                          border: 1px solid transparent;
                          border-radius: {T.R_MD}px; }}
    QFrame#row:hover   {{ background: {rgba(T.C_CARD_HOVER, g.card)}; }}
    QFrame#rowOn       {{ background: {rgba(T.C_SELECTED, g.card)};
                          border: 1px solid {T.C_ACCENT};
                          border-radius: {T.R_MD}px; }}

    /* ---------- artwork tiles ---------- */
    QFrame#tile        {{ background: {rgba(T.C_CARD, g.tile)};
                          border: 2px solid transparent;
                          border-radius: {T.R_MD}px; }}
    QFrame#tile:hover  {{ border: 2px solid {T.C_BORDER_STRONG}; }}
    QFrame#tileOn      {{ background: {rgba(T.C_ACCENT_SOFT, g.card)};
                          border: 2px solid {T.C_ACCENT_BRIGHT};
                          border-radius: {T.R_MD}px; }}

    /* ---------- controls ---------- */
    QLineEdit          {{ background: {rgba(T.C_CARD, g.card)};
                          border: 1px solid {rgba(T.C_BORDER, g.line)};
                          border-radius: {T.R_MD}px; padding: 7px 12px;
                          color: {T.C_TEXT}; font-size: 12px;
                          selection-background-color: {T.C_ACCENT}; }}
    QPushButton#pill        {{ background: transparent; border: none;
                               border-radius: {T.R_PILL}px; padding: 6px 14px;
                               color: {T.C_TEXT3}; font-size: 11px;
                               font-weight: 700; }}
    QPushButton#pill:hover  {{ background: {rgba(T.C_CARD_HOVER, g.card)}; }}
    QPushButton#pill:checked{{ background: {T.C_ACCENT_BRIGHT};
                               color: {T.C_TEXT}; }}
    QWidget#pillGroup       {{ background: {rgba(T.C_CARD, g.card)};
                               border-radius: {T.R_PILL}px; }}

    QPushButton#secondary       {{ background: {rgba(T.C_CARD, g.card)};
                                   border: 1px solid {rgba(T.C_BORDER, g.line)};
                                   border-radius: {T.R_MD}px; padding: 9px 16px;
                                   color: {T.C_TEXT}; font-size: 12px;
                                   font-weight: 700; }}
    QPushButton#secondary:hover {{ background: {rgba(T.C_CARD_HOVER, g.card)}; }}
    QPushButton#primary         {{ background: {T.C_ACCENT_BRIGHT};
                                   border: none; border-radius: {T.R_MD}px;
                                   padding: 9px 22px; color: {T.C_TEXT};
                                   font-size: 12px; font-weight: 700; }}
    QPushButton#primary:hover   {{ background: {T.C_ACCENT_HOVER}; }}
    QPushButton#danger          {{ background: {rgba(T.C_DANGER_BG, g.card)};
                                   border: 1px solid {rgba(T.C_DANGER, 0.35)};
                                   border-radius: {T.R_MD}px; padding: 9px 16px;
                                   color: {T.C_DANGER}; font-size: 12px;
                                   font-weight: 700; }}
    /* Disabled reads as unavailable, not merely as dimmer text - the mistake
       the Tk build made with its primary action. */
    QPushButton:disabled        {{ background: {rgba(T.C_CARD, g.card)};
                                   border: 1px solid {rgba(T.C_BORDER, g.line)};
                                   color: {T.C_TEXT3}; }}

    /* ---------- scrolling ---------- */
    QScrollArea            {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical    {{ background: transparent; width: 9px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {rgba(T.C_CARD_HOVER, g.card)};
                                   border-radius: 4px; min-height: 30px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                                   background: transparent; }}
    """
