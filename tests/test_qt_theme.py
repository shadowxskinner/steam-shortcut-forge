

# ---------------------------------------------------------------------------
# The Qt shell has its own layout and type scale
#
# The Tk tokens were sized for a denser window. When the Qt panes borrowed
# them the result read as a port rather than a design: rows too short, cards
# too tight, type too flat. These lock the intent so a later edit that reaches
# back for T.H_ROW or T.TILE_SIZE fails loudly instead of quietly shrinking.
# ---------------------------------------------------------------------------

def test_qt_layout_is_roomier_than_the_tk_scale():
    from kairo.qt import theme as Q
    from kairo.ui import theme as T
    assert Q.H_ROW > T.H_ROW
    assert Q.W_NAV > T.W_NAV
    assert Q.W_LIST > T.W_LIST
    assert Q.WELL_ROW > T.THUMB_SIZE
    assert Q.TILE >= T.TILE_SIZE
    assert Q.PAD_PANE > T.PAD_WINDOW


def test_qt_type_scale_spreads_wider_than_tk():
    """Hierarchy carried by size, not by weight alone."""
    from kairo.qt import theme as Q
    assert Q.FS_TITLE > Q.FS_PANE > Q.FS_ROW > Q.FS_META > Q.FS_MICRO
    assert Q.FS_TITLE - Q.FS_ROW >= 14


def test_qt_panes_do_not_reach_back_for_tk_geometry():
    """Geometry comes from the Qt scale; only colour and helpers come from T."""
    import re
    from pathlib import Path
    banned = ("T.H_ROW", "T.W_NAV", "T.W_LIST", "T.TILE_SIZE", "T.WELL_SIZE",
              "T.THUMB_SIZE", "T.PAD_WINDOW", "T.PAD_COLUMN", "T.PAD_CARD",
              "T.H_CONTROL", "T.H_ACTION", "T.R_LG", "T.R_MD")
    root = Path(__file__).resolve().parent.parent / "kairo" / "qt"
    offenders = []
    for path in sorted(root.rglob("*.py")):
        body = path.read_text()
        for token in banned:
            if re.search(rf"(?<![\w.]){re.escape(token)}\b", body):
                offenders.append(f"{path.name}: {token}")
    assert not offenders, offenders


def test_divider_is_a_hairline_not_a_gap():
    """The workspace groups with rules; a fat divider would separate instead."""
    from kairo.qt import theme as Q
    sheet = Q.stylesheet("frosted")
    assert "QFrame#divider" in sheet
    assert "max-height: 1px" in sheet
