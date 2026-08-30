"""Qt styling, built from the same tokens the Tk shell uses.

``kairo.ui.theme`` holds the palette, the spacing scale and the type scale, and
none of that is toolkit-specific. Importing it here rather than restating it
means the two frontends cannot drift apart while both exist - change a colour
once and both shells move.

Alpha is the one thing Qt adds. Surfaces carry an alpha component so the
compositor can show the desktop through them; text, icons and borders stay
fully opaque, which is the whole reason for moving.
"""

from __future__ import annotations

from kairo.ui import theme as T

#: How see-through the surfaces are when transparency is on. Chosen so text
#: contrast stays comfortable over a mid-tone wallpaper rather than for maximum
#: effect.
DEFAULT_ALPHA = 0.82
MIN_ALPHA, MAX_ALPHA = 0.40, 1.0


def rgba(colour: str, alpha: float = 1.0) -> str:
    colour = colour.lstrip("#")
    red, green, blue = (int(colour[index:index + 2], 16) for index in (0, 2, 4))
    if alpha >= 1.0:
        return f"rgb({red}, {green}, {blue})"
    return f"rgba({red}, {green}, {blue}, {alpha:.3f})"


def stylesheet(alpha: float = DEFAULT_ALPHA) -> str:
    """The whole application's appearance, as one sheet.

    Panels take ``alpha``; the columns sit slightly denser so the reading
    surfaces are the most legible thing on screen; text takes none at all.
    """
    nav = min(1.0, alpha + 0.06)
    card = min(1.0, alpha + 0.08)

    return f"""
    /* ---------- surfaces ---------- */
    QWidget#root      {{ background: transparent; }}
    QWidget#nav       {{ background: {rgba(T.C_NAV, nav)};
                         border-right: 1px solid {rgba(T.C_BORDER, alpha)}; }}
    QWidget#list      {{ background: {rgba(T.C_LIST, nav)};
                         border-right: 1px solid {rgba(T.C_BORDER, alpha)}; }}
    QWidget#workspace {{ background: transparent; }}
    QFrame#card       {{ background: {rgba(T.C_PANEL, alpha)};
                         border: 1px solid {rgba(T.C_BORDER, alpha)};
                         border-radius: {T.R_LG}px; }}
    QFrame#well       {{ background: {rgba(T.C_CARD, card)};
                         border-radius: {T.R_MD}px; }}

    /* ---------- type ---------- */
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

    /* ---------- navigation ---------- */
    QPushButton#nav        {{ background: transparent; border: none;
                              border-radius: {T.R_MD}px; padding: 7px 12px;
                              color: {T.C_TEXT2}; font-size: 13px;
                              text-align: left; }}
    QPushButton#nav:hover  {{ background: {rgba(T.C_CARD, card)}; }}
    QPushButton#nav:checked{{ background: {rgba(T.C_SELECTED_NAV, card)};
                              color: {T.C_TEXT}; font-weight: 700; }}

    /* ---------- entry rows ---------- */
    QFrame#row         {{ background: {rgba(T.C_CARD, card)};
                          border: 1px solid transparent;
                          border-radius: {T.R_MD}px; }}
    QFrame#row:hover   {{ background: {rgba(T.C_CARD_HOVER, card)}; }}
    QFrame#rowOn       {{ background: {rgba(T.C_SELECTED, card)};
                          border: 1px solid {rgba(T.C_ACCENT, 1.0)};
                          border-radius: {T.R_MD}px; }}

    /* ---------- artwork tiles ---------- */
    QFrame#tile        {{ background: {rgba(T.C_CARD, card)};
                          border: 2px solid transparent;
                          border-radius: {T.R_MD}px; }}
    QFrame#tile:hover  {{ border: 2px solid {rgba(T.C_BORDER_STRONG, 1.0)}; }}
    QFrame#tileOn      {{ background: {rgba(T.C_ACCENT_SOFT, card)};
                          border: 2px solid {T.C_ACCENT_BRIGHT};
                          border-radius: {T.R_MD}px; }}

    /* ---------- controls ---------- */
    QLineEdit          {{ background: {rgba(T.C_CARD, card)};
                          border: 1px solid {rgba(T.C_BORDER, alpha)};
                          border-radius: {T.R_MD}px; padding: 7px 12px;
                          color: {T.C_TEXT}; font-size: 12px;
                          selection-background-color: {T.C_ACCENT}; }}
    QPushButton#pill        {{ background: transparent; border: none;
                               border-radius: {T.R_PILL}px; padding: 6px 14px;
                               color: {T.C_TEXT3}; font-size: 11px;
                               font-weight: 700; }}
    QPushButton#pill:hover  {{ background: {rgba(T.C_CARD_HOVER, card)}; }}
    QPushButton#pill:checked{{ background: {T.C_ACCENT_BRIGHT};
                               color: {T.C_TEXT}; }}
    QWidget#pillGroup       {{ background: {rgba(T.C_CARD, card)};
                               border-radius: {T.R_PILL}px; }}

    QPushButton#secondary       {{ background: {rgba(T.C_CARD, card)};
                                   border: 1px solid {rgba(T.C_BORDER, alpha)};
                                   border-radius: {T.R_MD}px; padding: 9px 16px;
                                   color: {T.C_TEXT}; font-size: 12px;
                                   font-weight: 700; }}
    QPushButton#secondary:hover {{ background: {rgba(T.C_CARD_HOVER, card)}; }}
    QPushButton#primary         {{ background: {T.C_ACCENT_BRIGHT};
                                   border: none; border-radius: {T.R_MD}px;
                                   padding: 9px 22px; color: {T.C_TEXT};
                                   font-size: 12px; font-weight: 700; }}
    QPushButton#primary:hover   {{ background: {T.C_ACCENT_HOVER}; }}
    QPushButton#danger          {{ background: {rgba(T.C_DANGER_BG, card)};
                                   border: 1px solid {rgba(T.C_DANGER, 0.35)};
                                   border-radius: {T.R_MD}px; padding: 9px 16px;
                                   color: {T.C_DANGER}; font-size: 12px;
                                   font-weight: 700; }}
    /* Disabled has to read as unavailable, not merely as dimmer text - the
       mistake the Tk build made with its primary action. */
    QPushButton:disabled        {{ background: {rgba(T.C_CARD, card)};
                                   border: 1px solid {rgba(T.C_BORDER, alpha)};
                                   color: {T.C_TEXT3}; }}

    /* ---------- scrolling ---------- */
    QScrollArea            {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical    {{ background: transparent; width: 9px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {rgba(T.C_CARD_HOVER, card)};
                                   border-radius: 4px; min-height: 30px; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                                   background: transparent; }}
    """
