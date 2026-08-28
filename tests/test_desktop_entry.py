"""Tests for the one module that edits files in the user's launcher directory.

Every case here is a real shape found in the wild on a Linux desktop, not a
synthetic edge case: KDE ships entries with [Desktop Action] groups that carry
their own Icon=, Wine writes CRLF files, and plenty of packages ship entries
with no trailing newline.
"""

import pytest

from kairo.desktop import entry as de

BASIC = (
    "[Desktop Entry]\n"
    "Type=Application\n"
    "Name=Dolphin\n"
    "Icon=org.kde.dolphin\n"
    "Exec=dolphin %u\n"
    "MimeType=inode/directory;\n"
)


def rewrite(text, icon="/new/icon.png", original="org.kde.dolphin", **kw):
    return de.rewrite_entry_icon(text, icon, original, **kw)


def lines(text):
    """Exact lines, so an assertion cannot match a substring of a longer key.

    ``"Icon=firefox" in out`` is true when the file merely contains
    ``X-Kairo-OriginalIcon=firefox``, which is not what any of these tests
    mean to assert.
    """
    return [ln.strip() for ln in text.splitlines()]


# -- Icon replacement -------------------------------------------------------

def test_replaces_icon_in_desktop_entry():
    out = rewrite(BASIC)
    assert "Icon=/new/icon.png" in lines(out)
    assert "Icon=org.kde.dolphin" not in lines(out)


def test_preserves_every_other_key():
    out = rewrite(BASIC)
    for line in ("Type=Application", "Name=Dolphin", "Exec=dolphin %u",
                 "MimeType=inode/directory;"):
        assert line in out


def test_stamps_managed_and_original_icon():
    out = rewrite(BASIC)
    assert f"{de.MANAGED_KEYS[0]}=true" in out
    assert f"{de.ORIGINAL_ICON_KEYS[0]}=org.kde.dolphin" in out


def test_inserts_icon_when_absent():
    text = "[Desktop Entry]\nType=Application\nName=Thing\n"
    out = rewrite(text, original="")
    assert "Icon=/new/icon.png" in out
    assert "Name=Thing" in out


# -- [Desktop Action] must not be touched -----------------------------------

ACTIONS = (
    "[Desktop Entry]\n"
    "Type=Application\n"
    "Name=Firefox\n"
    "Icon=firefox\n"
    "Actions=new-window;new-private-window;\n"
    "\n"
    "[Desktop Action new-window]\n"
    "Name=New Window\n"
    "Icon=firefox-window\n"
    "Exec=firefox --new-window\n"
    "\n"
    "[Desktop Action new-private-window]\n"
    "Name=New Private Window\n"
    "Icon=firefox-private\n"
    "Exec=firefox --private-window\n"
)


def test_action_group_icons_are_untouched():
    out = rewrite(ACTIONS, original="firefox")
    assert "Icon=firefox-window" in lines(out)
    assert "Icon=firefox-private" in lines(out)
    assert "Icon=/new/icon.png" in lines(out)
    assert "Icon=firefox" not in lines(out)


def test_markers_land_in_desktop_entry_not_in_an_action():
    out = rewrite(ACTIONS, original="firefox")
    head = out.split("[Desktop Action")[0]
    assert f"{de.MANAGED_KEYS[0]}=true" in head


def test_read_entry_icon_ignores_action_groups(tmp_path):
    path = tmp_path / "firefox.desktop"
    path.write_text(ACTIONS)
    assert de.read_entry_icon(path) == "firefox"


def test_read_entry_icon_when_only_action_has_one(tmp_path):
    path = tmp_path / "x.desktop"
    path.write_text(
        "[Desktop Entry]\nType=Application\nName=X\n"
        "\n[Desktop Action a]\nName=A\nIcon=action-icon\n"
    )
    assert de.read_entry_icon(path) == ""


# -- Line endings -----------------------------------------------------------

def test_crlf_is_preserved():
    text = BASIC.replace("\n", "\r\n")
    out = rewrite(text)
    assert "\r\n" in out
    assert "\n\n" not in out.replace("\r\n", "\n\n").replace("\n\n", "\r\n")
    for line in out.splitlines(keepends=True):
        if line.strip():
            assert line.endswith("\r\n"), repr(line)


def test_crlf_generated_lines_use_crlf():
    text = "[Desktop Entry]\r\nType=Application\r\nName=Thing\r\n"
    out = rewrite(text, original="")
    assert "Icon=/new/icon.png\r\n" in out
    assert "Icon=/new/icon.png\n\r" not in out


def test_missing_trailing_newline_does_not_glue_keys():
    text = "[Desktop Entry]\nType=Application\nTerminal=false"
    out = rewrite(text, original="")
    assert "Terminal=falseIcon" not in out
    assert "Terminal=false\n" in out
    assert "Icon=/new/icon.png" in out


# -- Malformed input --------------------------------------------------------

def test_missing_desktop_entry_group_raises():
    with pytest.raises(de.DesktopEntryError):
        rewrite("[Desktop Action a]\nName=A\nIcon=x\n")


def test_empty_file_raises():
    with pytest.raises(de.DesktopEntryError):
        rewrite("")


def test_garbage_file_raises():
    with pytest.raises(de.DesktopEntryError):
        rewrite("this is not a desktop file at all\n\x00\x01\n")


def test_duplicate_desktop_entry_group_leaves_the_second_alone():
    text = (
        "[Desktop Entry]\nType=Application\nIcon=first\n"
        "\n[Desktop Entry]\nIcon=second\n"
    )
    out = rewrite(text, original="first")
    assert "Icon=/new/icon.png\n" in out
    # The second group is malformed per spec; we must not silently delete
    # lines from it.
    assert "Icon=second\n" in out


def test_comments_and_blank_lines_survive():
    text = (
        "# a leading comment\n"
        "[Desktop Entry]\n"
        "; another comment\n"
        "\n"
        "Type=Application\n"
        "Icon=old\n"
    )
    out = rewrite(text, original="old")
    assert "# a leading comment\n" in out
    assert "; another comment\n" in out
    assert "\n\n" in out


def test_localised_keys_are_not_rewritten():
    text = (
        "[Desktop Entry]\nType=Application\nName=Files\nName[de]=Dateien\n"
        "Icon=files\nIcon[de]=dateien\n"
    )
    out = rewrite(text, original="files")
    assert "Name[de]=Dateien\n" in out
    assert "Icon[de]=dateien\n" in out
    assert "Icon=/new/icon.png\n" in out


def test_parse_returns_none_for_missing_group(tmp_path):
    path = tmp_path / "bad.desktop"
    path.write_text("[Something Else]\nkey=value\n")
    assert de.parse(path) is None


def test_parse_returns_none_for_non_utf8(tmp_path):
    path = tmp_path / "bin.desktop"
    path.write_bytes(b"[Desktop Entry]\nName=\xff\xfe\xfd\n")
    assert de.parse(path) is None


def test_parse_survives_duplicate_keys(tmp_path):
    path = tmp_path / "dup.desktop"
    path.write_text("[Desktop Entry]\nType=Application\nName=A\nName=B\n")
    assert de.parse(path) is not None


# -- Idempotency ------------------------------------------------------------

def test_rewriting_twice_is_stable():
    once = rewrite(BASIC)
    twice = de.rewrite_entry_icon(once, "/new/icon.png", "org.kde.dolphin")
    assert once == twice


def test_second_rewrite_keeps_the_first_original_icon():
    once = rewrite(BASIC)
    twice = de.rewrite_entry_icon(once, "/other.png", "org.kde.dolphin")
    assert f"{de.ORIGINAL_ICON_KEYS[0]}=org.kde.dolphin" in twice
    assert twice.count(f"{de.ORIGINAL_ICON_KEYS[0]}=") == 1


def test_markers_are_not_duplicated():
    out = rewrite(rewrite(BASIC))
    assert out.count(f"{de.MANAGED_KEYS[0]}=true") == 1
    assert out.count("Icon=/new/icon.png") == 1


# -- Ownership markers ------------------------------------------------------

def test_is_managed_true_for_our_file(tmp_path):
    path = tmp_path / "a.desktop"
    path.write_text(rewrite(BASIC))
    assert de.is_managed(path) is True


def test_is_managed_false_for_hand_written_file(tmp_path):
    path = tmp_path / "b.desktop"
    path.write_text(BASIC)
    assert de.is_managed(path) is False


def test_is_managed_false_when_marker_is_false(tmp_path):
    path = tmp_path / "c.desktop"
    path.write_text(f"[Desktop Entry]\nType=Application\n{de.MANAGED_KEYS[0]}=false\n")
    assert de.is_managed(path) is False


def test_is_managed_ignores_marker_in_an_action_group(tmp_path):
    path = tmp_path / "d.desktop"
    path.write_text(
        "[Desktop Entry]\nType=Application\nName=X\n"
        f"\n[Desktop Action a]\n{de.MANAGED_KEYS[0]}=true\n"
    )
    assert de.is_managed(path) is False


def test_extra_managed_keys_are_preserved():
    text = BASIC.replace("Icon=org.kde.dolphin\n",
                         "Icon=org.kde.dolphin\nX-Legacy-Managed=true\n")
    out = de.rewrite_entry_icon(text, "/n.png", "org.kde.dolphin",
                                extra_managed_keys=("X-Legacy-Managed",))
    assert "X-Legacy-Managed=true" in out


# -- Atomic write -----------------------------------------------------------

def test_atomic_write_leaves_no_temp_files(tmp_path):
    target = tmp_path / "out.desktop"
    de.atomic_write_text(target, BASIC)
    assert target.read_text() == BASIC
    assert list(tmp_path.glob(".kairo-*")) == []


def test_atomic_write_preserves_crlf(tmp_path):
    target = tmp_path / "out.desktop"
    text = BASIC.replace("\n", "\r\n")
    de.atomic_write_text(target, text)
    assert target.read_bytes().count(b"\r\n") == text.count("\r\n")


def test_atomic_write_creates_parent(tmp_path):
    target = tmp_path / "deep" / "nested" / "out.desktop"
    de.atomic_write_text(target, BASIC)
    assert target.is_file()


def test_escape_value():
    assert de.escape_value("a\nb") == "a\\nb"
    assert de.escape_value("c\\d") == "c\\\\d"
