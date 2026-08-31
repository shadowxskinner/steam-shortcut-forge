

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
              "T.H_CONTROL", "T.H_ACTION", "T.R_LG", "T.R_MD",
              "T.LIST_NAME_CHARS")
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


def test_the_artwork_browser_is_the_largest_region():
    """Hierarchy in plan, not just in type.

    The entry list was widened on the theory that more room is always better.
    It is the thing you leave in order to go and work, so it gets less width
    than the thing you work in — even in the smallest window Kairo opens at.
    """
    from kairo.qt import theme as Q
    minimum_width = 1120                       # KairoWindow.setMinimumSize
    workspace = minimum_width - Q.W_NAV - Q.W_LIST
    assert workspace > Q.W_LIST
    assert workspace > Q.W_NAV


def test_one_header_band_across_all_three_columns():
    """The first hundred pixels are a register, not leftover container space."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "kairo" / "qt"
    users = {path.name for path in sorted(root.glob("*.py"))
             if "H_HEADER" in path.read_text()}
    assert {"library.py", "shell.py", "settings.py", "changes.py"} <= users, users


def test_weight_is_the_last_resort():
    """Size, spacing and colour carry hierarchy; nothing is heavier than 600."""
    import re
    from pathlib import Path
    from kairo.qt import theme as Q
    assert Q.WT_SEMI == 600
    source = Path(__file__).resolve().parent.parent / "kairo" / "qt" / "theme.py"
    sheet = source.read_text()
    assert "font-weight: 700" not in sheet
    assert "font-weight: bold" not in sheet
    weights = {int(v) for v in re.findall(r"font-weight: (\d{3})", sheet)}
    assert weights <= {400, 500, 600}, weights


def test_chrome_is_earned_not_default():
    """A row, a tile and the inspector carry no outline at rest."""
    from kairo.qt import theme as Q
    sheet = Q.stylesheet("frosted")
    for rule in ("QFrame#row ", "QFrame#tile ", "QFrame#card "):
        block = sheet.split(rule, 1)[1].split("}", 1)[0]
        assert "border: none" in block, (rule, block)


def test_no_one_off_geometry_in_the_panes():
    """Every dimension has a name on the scale, or it is not a dimension."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "kairo" / "qt"
    pattern = re.compile(r"setFixed(?:Width|Height|Size)\(\s*\d{2,}")
    offenders = []
    for path in sorted(root.glob("*.py")):
        if path.name == "theme.py":
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, offenders


def test_controls_share_one_height():
    """Search, query and every button line up; pills sit inside that line."""
    from kairo.qt import theme as Q
    assert Q.H_FIELD == Q.H_BUTTON
    assert Q.H_PILLS < Q.H_BUTTON


def test_letter_spacing_is_styled_not_typed():
    """Tracking belongs to the stylesheet.

    Spacing a heading out by hand and then tracking it in QSS applies the
    effect twice, which is how APPEARANCE came to occupy a third of a card.
    """
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "kairo" / "qt"
    spaced = re.compile(r'QLabel\(\s*"(?:[A-Z] ){3,}')
    offenders = [path.name for path in sorted(root.glob("*.py"))
                 if spaced.search(path.read_text())]
    assert not offenders, offenders



def test_a_translucent_surface_is_never_painted_twice():
    """Nesting #workspace inside #workspace doubles the fill.

    Every surface id carries an alpha, so a widget repeating its parent's id
    composites the same colour twice and reads as a lighter panel with a seam
    along the edge where it begins.
    """
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "kairo" / "qt"
    offenders = []
    for path in sorted(root.glob("*.py")):
        body = path.read_text()
        for surface in ("workspace", "nav", "list", "footer"):
            uses = re.findall(rf'setObjectName\("{surface}"\)', body)
            if len(uses) > 1:
                offenders.append(f"{path.name}: {surface} x{len(uses)}")
    assert not offenders, offenders




def test_the_logotype_is_the_mark_and_the_wordmark():
    """回路 was the second half of it and is now the mark itself.

    Three elements in a sidebar built around one per row made the header the
    busiest thing on screen, and typesetting CJK also meant depending on a
    font the machine might not have.
    """
    from pathlib import Path

    from kairo.qt import theme as Q

    shell = (Path(__file__).resolve().parent.parent / "kairo" / "qt"
             / "shell.py").read_text()
    assert "回路" not in shell.split('"""')[-1] or "logoSub" not in shell
    assert "logoSub" not in Q.stylesheet("frosted")
    assert "branding.mark(Q.MARK_SIZE)" in shell
    assert Q.MARK_SIZE > 0


def test_the_interface_font_is_a_stack_not_a_wish():
    """Asking for one family that is not installed lands anywhere at all.

    "Inter" alone resolved to whatever fontconfig picked — DejaVu Sans on a
    machine with no Inter — which is nothing like the intended face.
    """
    from kairo.qt import theme as Q

    assert len(Q.FONT_STACK) >= 4
    assert Q.FONT_STACK[0].startswith("SF Pro")
    assert "Inter" in Q.FONT_STACK
    assert Q.FONT_STACK[-1] == "DejaVu Sans", "the last entry must exist anywhere"

    from pathlib import Path

    main = (Path(__file__).resolve().parent.parent / "kairo" / "qt"
            / "__main__.py").read_text()
    assert "setFamilies(list(Q.FONT_STACK))" in main
    assert 'QFont("Inter"' not in main
