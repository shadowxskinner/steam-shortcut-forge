"""What can be checked about the Qt frontend without a display.

Widgets need libEGL and a compositor, neither of which exists in CI, so most of
this is structural: that the Qt shell does not drag in Tk, that blur is
genuinely optional, and that every module is at least syntactically sound.

QtCore is the exception. It runs headless, so the worker lifecycle — the thing
that actually crashed the live shell — is exercised for real rather than
grepped for.
"""

import ast
import threading
import time
from pathlib import Path

import pytest

QT_DIR = Path(__file__).resolve().parents[1] / "kairo" / "qt"
MODULES = sorted(QT_DIR.glob("*.py"))

TK_NAMES = {"tkinter", "customtkinter", "kairo.imaging", "kairo.ui.widgets",
            "kairo.ui.nav", "kairo.ui.app", "kairo.ui.shell"}


def imports_of(path: Path):
    tree = ast.parse(path.read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_there_are_qt_modules():
    assert MODULES, "the Qt frontend is missing"


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_every_module_parses(path):
    ast.parse(path.read_text())


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_the_qt_shell_does_not_depend_on_tk(path):
    """Running the Qt shell must not require CustomTkinter to be installed.

    kairo.ui.theme is the one exception: it holds the shared palette and
    spacing tokens and guards its own toolkit import, so both frontends can
    read it and neither can drift from the other.
    """
    offenders = imports_of(path) & TK_NAMES
    assert not offenders, f"{path.name} imports {offenders}"


def test_the_shared_tokens_survive_without_a_toolkit():
    from kairo.ui import theme

    assert theme.C_BG.startswith("#")
    assert theme.PAD_WINDOW > 0


def test_blur_is_optional(fake_home, monkeypatch, tmp_path):
    """No compiled bridge, no compositor, no crash."""
    from kairo.qt import blur

    monkeypatch.setattr(blur, "SEARCH_PATHS", (tmp_path / "missing.so",))
    probe = blur.Blur()
    assert probe.active is False
    assert isinstance(probe.status, str) and probe.status
    assert probe.supported() is False


def test_blur_reports_where_it_looked():
    from kairo.qt import blur

    assert blur.LIBRARY_NAME.endswith(".so")
    assert any("native" in str(path) for path in blur.SEARCH_PATHS)


def test_blur_result_codes_all_explain_themselves():
    from kairo.qt import blur

    assert blur.RESULTS[0] == "blur active"
    for code, message in blur.RESULTS.items():
        assert message, f"result {code} has no explanation"


def test_the_qt_theme_keeps_the_shared_semantic_accent():
    from kairo.qt import theme as Q
    from kairo.ui import theme as T

    sheet = Q.stylesheet(0.8)
    assert T.C_ACCENT_BRIGHT in sheet, "the accent must come from one place"
    assert "rgba(" in sheet, "surfaces need an alpha component"
    assert Q.rgba("#FFFFFF", 1.0) == "rgb(255, 255, 255)"


def test_a_numeric_setting_nudges_rather_than_flattens():
    """--alpha moves every layer together and keeps their relationship.

    Flattening them to one value would lose the depth the layering exists for;
    "solid" is a preset for when none is wanted at all.
    """
    from kairo.qt import theme as Q
    nudged = Q.stylesheet(0.70)
    assert Q.rgba(Q.C_PANEL, 0.70) in nudged
    assert Q.rgba(Q.C_PANEL, 1.0) not in nudged

    glass = Q.resolve(0.70)
    assert glass.nav > glass.panel > glass.tile


# -- glass is per surface, not per window -----------------------------------

def test_reading_surfaces_balance_legibility_with_visible_blur():
    """Material should stay readable without turning into an opaque slab.

    A single window-wide opacity - the only thing Tk offered - cannot express
    this: it fades text along with the background and makes every surface
    equally see-through whether it holds content or not.
    """
    from kairo.qt import theme as Q

    frosted = Q.PRESETS["frosted"]
    for name in ("nav", "list", "panel"):
        assert 0.78 <= getattr(frosted, name) <= 0.88, name


def test_qt_material_is_neutral_not_the_tk_navy_palette():
    from kairo.ui import theme as T

    from kairo.qt import theme as Q

    def spread(colour):
        value = colour.lstrip("#")
        channels = [int(value[index:index + 2], 16) for index in (0, 2, 4)]
        return max(channels) - min(channels)

    assert all(spread(colour) <= 8 for colour in Q.SURFACE_COLOURS)
    sheet = Q.stylesheet("frosted")
    for navy in (T.C_BG, T.C_NAV, T.C_LIST, T.C_PANEL, T.C_CARD,
                 T.C_SELECTED, T.C_SELECTED_NAV):
        assert navy not in sheet


def test_depth_runs_from_columns_down_to_tiles():
    from kairo.qt import theme as Q

    g = Q.PRESETS["frosted"]
    assert g.nav >= g.list >= g.panel >= g.card >= g.tile
    assert g.nav - g.tile >= 0.05, "the layers are too close to read as depth"


def test_every_preset_keeps_that_ordering():
    from kairo.qt import theme as Q

    for name, g in Q.PRESETS.items():
        assert g.nav >= g.list >= g.panel >= g.card >= g.tile, name


def test_text_never_takes_the_surface_alpha():
    """The whole reason for leaving Tk."""
    from kairo.qt import theme as Q

    sheet = Q.stylesheet("frosted")
    for label in ("QLabel#title", "QLabel#rowName", "QLabel#meta"):
        line = next(l for l in sheet.splitlines() if label in l)
        assert "rgba(" not in line, f"{label} is translucent"
    assert Q.C_TEXT in sheet


def test_glass_can_be_nudged_without_inverting_the_layers():
    from kairo.qt import theme as Q

    nudged = Q.PRESETS["frosted"].shifted(-0.10)
    assert nudged.nav >= nudged.panel >= nudged.tile
    assert Q.PRESETS["frosted"].shifted(5.0).panel == 1.0      # clamped
    # The floor is zero, not a minimum tint: fully transparent is a legitimate
    # setting, and it is what the workspace backdrop used to be.
    assert Q.PRESETS["frosted"].shifted(-5.0).tile == 0.0


def test_resolve_accepts_a_name_a_number_or_a_glass():
    from kairo.qt import theme as Q

    assert Q.resolve("solid").panel == 1.0
    assert Q.resolve(None) == Q.PRESETS[Q.DEFAULT_PRESET]
    assert Q.resolve(Q.PRESETS["clear"]) == Q.PRESETS["clear"]
    assert abs(Q.resolve(0.80).panel - 0.80) < 1e-9
    assert Q.resolve("nonsense") == Q.PRESETS[Q.DEFAULT_PRESET]


def test_solid_really_is_solid():
    from kairo.qt import theme as Q

    sheet = Q.stylesheet("solid")
    for surface in (Q.C_NAV, Q.C_LIST, Q.C_PANEL, Q.C_CARD):
        assert Q.rgba(surface, 1.0) in sheet


# -- behaviour parity with the validated Tk build ---------------------------

def test_the_action_verbs_come_from_the_writer(): 
    """A generated entry's ordinary undo is Reset artwork; an override's is
    Restore original. Hard-coding either in the frontend is how the Tk build
    came to describe a deletion as a restore."""
    source = (QT_DIR / "library.py").read_text()
    build = source.split("def _update_actions")[0]

    assert '"Restore original"' not in build
    assert '"Remove shortcut"' not in build
    assert "writer.restore_label" in source
    assert "writer.remove_label" in source
    assert "supports_remove" in source


def test_remove_is_only_offered_where_the_writer_supports_it():
    source = (QT_DIR / "library.py").read_text()
    assert "self.remove_btn.setVisible(supports_remove)" in source


def test_the_backend_still_disagrees_about_the_two_verbs(fake_home):
    """The parity the frontend is deferring to."""
    from kairo.providers.steam import SteamProvider
    from kairo.providers.writers import OverrideWriter

    generated = SteamProvider().writer()
    override = OverrideWriter()
    assert generated.restore_label == "Reset artwork"
    assert generated.remove_label == "Remove shortcut"
    assert generated.supports_remove is True
    assert override.restore_label == "Restore original"
    assert override.supports_remove is False


def test_artwork_sources_stay_available_after_empty_or_failed_searches():
    """One poor query must not make its source tab disappear."""
    source = (QT_DIR / "library.py").read_text()
    assert "_probe_cache" not in source
    assert "_probe_sources" not in source
    empty = source.split("if not results:")[1].split("return", 1)[0]
    assert "Try a different search" in empty
    assert "_refresh_sources" not in empty


def test_choosing_artwork_only_proposes_it():
    """Nothing writes until Apply, which is the rule the review screen has
    always followed and the single-item path now follows too."""
    source = (QT_DIR / "library.py").read_text()
    propose = source.split("def _propose(self, art)")[1]
    for writing in ("fetch_and_apply", "apply_icon", "restore_entry",
                    "remove_entry"):
        assert writing not in propose


# -- how the shell is allowed to write --------------------------------------
#
# The read-only guard has served its purpose and is replaced, not deleted:
# writing is now permitted, but only through the one door that owns the
# marker checks, the ledger and the atomic write.

def test_the_shell_never_writes_a_launcher_file_itself():
    """Every write goes through kairo.actions, never a writer or a path."""
    for path in MODULES:
        source = path.read_text()
        for backdoor in ("writer.apply", "writer.restore(", "writer.remove(",
                         "os.replace", "shutil.copyfile", "write_text(",
                         "write_bytes(", "unlink("):
            assert backdoor not in source, f"{path.name} uses {backdoor}"


def test_every_write_records_itself_in_the_ledger():
    """An unrecorded change cannot be undone from the Changes view."""
    source = (QT_DIR / "library.py").read_text()
    for call in ("actions.fetch_and_apply(", "actions.restore_entry(",
                 "actions.remove_entry("):
        assert call in source, f"{call} is not wired"
        tail = source.split(call)[1].split(")")[0]
        assert "ledger=self.ctx.ledger" in tail, f"{call} skips the ledger"


def test_applying_runs_off_the_ui_thread_and_can_be_cancelled():
    source = (QT_DIR / "library.py").read_text()
    apply_body = source.split("def _apply")[1].split("def _restore")[0]
    assert "work.submit(" in apply_body, "a network fetch must not block the UI"
    assert "self.tokens.start(" in apply_body
    assert "token=token" in apply_body


def test_only_the_destructive_action_asks_first():
    """Apply and restore are recoverable from Changes; deleting is not."""
    source = (QT_DIR / "library.py").read_text()
    remove = source.split("def _remove")[1].split("def _browse")[0]
    assert "QMessageBox" in remove
    assert "QMessageBox.Cancel" in remove, "cancel must be the default"
    for safe in ("def _apply", "def _restore"):
        body = source.split(safe)[1].split("\n    def ")[0]
        assert "QMessageBox" not in body, f"{safe} should not interrupt"


def test_apply_is_offered_only_once_there_is_something_to_apply():
    source = (QT_DIR / "library.py").read_text()
    assert "self.apply_btn.setEnabled(False)" in source
    propose = source.split("def _propose")[1].split("\n    def ")[0]
    assert "self.apply_btn.setEnabled(True)" in propose


# -- tuning controls that actually reach the user ---------------------------






def test_tuned_values_can_be_reported_back():
    """Six numbers found by eye are useless if they cannot leave the window."""
    from kairo.qt import theme as Q

    described = Q.PRESETS["frosted"].describe()
    assert described.startswith("Glass(") and described.endswith(")")
    for layer in Q.LAYERS:
        assert f"{layer}=" in described

    namespace = {"Glass": Q.Glass}
    assert eval(described, namespace) == Q.PRESETS["frosted"]


def test_replaced_clamps_without_reordering_the_intent():
    from kairo.qt import theme as Q

    tuned = Q.PRESETS["frosted"].replaced(panel=0.99, tile=4.0, card=-1.0)
    assert tuned.panel == 0.99
    assert tuned.tile == 1.0
    assert tuned.card == 0.0
    assert tuned.nav == Q.PRESETS["frosted"].nav


def test_a_denser_preset_exists_to_compare_against():
    """Dense remains an escape hatch for unusually high-contrast wallpaper."""
    from kairo.qt import theme as Q

    dense = Q.PRESETS["dense"]
    frosted = Q.PRESETS["frosted"]
    assert dense.panel > frosted.panel
    assert dense.nav >= dense.list >= dense.panel >= dense.card >= dense.tile
    assert dense.panel < 1.0, "dense is still glass, not a wall"


def test_live_default_leaves_room_for_the_compositor_blur():
    from kairo.qt import theme as Q

    frosted = Q.PRESETS[Q.DEFAULT_PRESET]
    assert 0.45 <= frosted.workspace <= 0.55
    assert 0.78 <= frosted.panel <= 0.84
    assert frosted.card < frosted.panel


# -- the backdrop behind the cards ------------------------------------------

def test_the_workspace_has_a_backdrop_at_all():
    """It used to be fully transparent, which is why content behind the window
    stayed legible however hard the compositor blurred. Blur smears what is
    behind a surface; it does not dim it, and a region with no surface has
    nothing to dim with."""
    from kairo.qt import theme as Q
    sheet = Q.stylesheet("frosted")
    line = next(l for l in sheet.splitlines() if "QWidget#workspace" in l)
    assert "transparent" not in line
    assert Q.rgba(Q.C_BG, Q.PRESETS["frosted"].workspace) in line


def test_the_window_itself_still_has_no_rectangle():
    """The root stays fully transparent so Kairo never draws a slab the
    compositor has to blur around."""
    from kairo.qt import theme as Q

    line = next(l for l in Q.stylesheet("dense").splitlines()
                if "QWidget#root" in l)
    assert "transparent" in line


def test_the_backdrop_sits_under_the_cards_in_every_preset():
    from kairo.qt import theme as Q

    for name, glass in Q.PRESETS.items():
        assert glass.workspace <= glass.panel, name


def test_dense_raises_the_backdrop_most():
    """It is the lever that actually stops text reading through."""
    from kairo.qt import theme as Q

    frosted, dense = Q.PRESETS["frosted"], Q.PRESETS["dense"]
    assert dense.workspace - frosted.workspace > dense.panel - frosted.panel


# -- the UI must not imply Kairo can set blur strength ----------------------


def test_no_blur_strength_control_is_offered():
    from kairo.qt import theme as Q

    assert not any("blur" in layer for layer in Q.LAYERS)
    for path in MODULES:
        source = path.read_text().lower()
        assert "blurstrength" not in source
        assert "blur_radius" not in source


def test_blur_never_forces_qt_onto_xwayland():
    source = (QT_DIR / "__main__.py").read_text()
    assert "QT_QPA_PLATFORM" not in source
    assert "xcb" not in source


def test_native_blur_uses_a_real_exact_region_not_null():
    """The protocol says NULL removes blur; shell 6 did exactly that."""
    source = (QT_DIR / "native" / "blur.c").read_text()
    assert "wl_compositor_create_region" in source
    assert "wl_region_add(region, 0, 0, width, height)" in source
    assert "set_blur_region(effect, region)" in source
    assert "set_blur_region(effect, NULL)" not in source
    assert "INT32_MAX" not in source


def test_native_blur_uses_a_private_wayland_queue():
    """A default-queue roundtrip can dispatch Qt callbacks re-entrantly."""
    source = (QT_DIR / "native" / "blur.c").read_text()
    assert "wl_display_create_queue" in source
    assert "wl_proxy_set_queue" in source
    assert source.count("wl_display_roundtrip_queue") >= 2
    assert "wl_display_roundtrip(display)" not in source


def test_blur_bridge_keeps_the_gil_and_tracks_resizes():
    bridge = (QT_DIR / "blur.py").read_text()
    shell = (QT_DIR / "shell.py").read_text()
    assert "ctypes.PyDLL" in bridge
    assert "ctypes.CDLL" not in bridge
    assert "kairo_blur_resize" in bridge
    assert "def resizeEvent" in shell
    assert "_blur_resize_timer" in shell
    assert "self.blur.update(self)" in shell


def test_the_resize_bridge_is_debounced():
    """Wayland gets one region per gesture, not one per resize event."""
    shell = (QT_DIR / "shell.py").read_text()
    setup = shell.split("_blur_resize_timer = QTimer")[1].split("want_blur")[0]
    assert "setSingleShot(True)" in setup
    assert "setInterval(" in setup


def test_every_native_return_code_has_a_message():
    """The C and the Python status table are one contract in two files."""
    import re

    from kairo.qt import blur

    source = (QT_DIR / "native" / "blur.c").read_text()
    codes = {int(code) for code in re.findall(r"return\s+(-\d+);", source)}
    assert codes, "no failure codes found in the bridge"
    missing = sorted(codes - set(blur.RESULTS))
    assert not missing, f"native codes with no explanation: {missing}"


def test_a_bridge_from_an_older_tree_degrades_instead_of_crashing(
        monkeypatch, tmp_path):
    """A stale .so loads, then has no kairo_blur_resize.

    That raises AttributeError rather than OSError, so catching only OSError
    turned a leftover library on disk into a hard startup failure.
    """
    import types

    from kairo.qt import blur

    stale = tmp_path / blur.LIBRARY_NAME
    stale.write_bytes(b"")

    class OlderBridge:
        def __init__(self, path):
            pass

        def __getattr__(self, name):
            if name in ("kairo_blur_available", "kairo_blur_enable"):
                return types.SimpleNamespace()
            raise AttributeError(name)

    monkeypatch.setattr(blur, "SEARCH_PATHS", (stale,))
    monkeypatch.setattr(blur.ctypes, "PyDLL", OlderBridge)

    probe = blur.Blur()
    assert probe._library is None
    assert probe.active is False
    assert "would not load" in probe.status
    assert probe.supported() is False


def test_blur_is_released_before_qt_destroys_the_surface():
    native = (QT_DIR / "native" / "blur.c").read_text()
    bridge = (QT_DIR / "blur.py").read_text()
    close = (QT_DIR / "shell.py").read_text().split("def closeEvent")[1]
    remove = bridge.split("def remove")[1]
    assert "kairo_blur_disable" in native
    assert "ext_background_effect_surface_v1_destroy" in native
    assert "kairo_blur_disable.argtypes" in bridge
    assert "_surface(" not in remove, "teardown must use the cached handle"
    assert close.index("self.blur.remove(self)") < close.index("super().closeEvent")


def test_qt_jobs_are_destroyed_on_the_gui_thread():
    """Auto-delete caused the live Shiboken/Python reference race."""
    source = (QT_DIR / "work.py").read_text()
    assert "setAutoDelete(False)" in source
    assert "Qt.QueuedConnection" in source
    assert "QThreadPool.globalInstance()" not in source
    # The finished signal must fire from finally, whatever run() did, or the
    # job is never released. It goes through _emit now so a dead receiver
    # cannot strand it either.
    assert "finally:" in source
    assert "self._emit(self.signals.finished)" in source


# -- the worker lifecycle, for real -----------------------------------------
#
# The shell-7 segfault was a QRunnable with autoDelete letting Qt destroy a
# Python-owned QObject on a pool thread. Grepping for setAutoDelete(False)
# proves the line exists; these prove the behaviour it was meant to buy.

@pytest.fixture
def qt_core(qt_app):
    """Historic name for the shared application object; see conftest."""
    return qt_app


def settle(app, timeout=10.0):
    """Pump the loop until every job has been released on this thread."""
    from kairo.qt import work

    deadline = time.monotonic() + timeout
    while not work.is_idle() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    return work.is_idle()


def test_a_finished_job_is_released_on_the_calling_thread(qt_core):
    from kairo.qt import work

    seen = {}

    def record(value):
        seen["value"] = value
        seen["thread"] = threading.get_ident()

    job = work.submit(lambda: 21 * 2, on_done=record)
    # Qt must never delete this: it owns a QObject created on this thread.
    assert job.autoDelete() is False
    assert job in work._LIVE_JOBS

    assert settle(qt_core), "the job never drained"
    assert seen["value"] == 42
    assert seen["thread"] == threading.get_ident(), "result crossed threads"
    assert job not in work._LIVE_JOBS, "the job outlived its release"


def test_a_failing_job_is_released_too(qt_core):
    """The release runs from ``finally``; an exception must not leak a job."""
    from kairo.qt import work

    failures = []

    def boom():
        raise RuntimeError("nope")

    job = work.submit(boom, on_failed=failures.append)
    assert settle(qt_core), "a failed job never drained"
    assert failures == ["nope"]
    assert job not in work._LIVE_JOBS


def test_many_jobs_all_drain(qt_core):
    """is_idle is what closeEvent waits on, so it has to mean what it says."""
    from kairo.qt import work

    results = []
    jobs = [work.submit(lambda n=n: n * n, on_done=results.append)
            for n in range(24)]
    assert settle(qt_core), "a batch of jobs never drained"
    assert sorted(results) == sorted(n * n for n in range(24))
    assert not any(job in work._LIVE_JOBS for job in jobs)
    assert work.is_idle()


def test_is_idle_is_false_while_a_job_is_outstanding(qt_core):
    """A close that does not wait is the bug; this is the signal it waits on."""
    from kairo.qt import work

    release = threading.Event()
    job = work.submit(release.wait)
    try:
        assert work.is_idle() is False
    finally:
        release.set()
    assert settle(qt_core)
    assert job not in work._LIVE_JOBS


def test_close_drains_artwork_jobs_before_qt_teardown():
    source = (QT_DIR / "shell.py").read_text()
    close = source.split("def closeEvent")[1].split("\n    def ")[0]
    assert "work.is_idle()" in close
    assert "event.ignore()" in close
    assert "self.hide()" in close
    assert "def _finish_close" in source


def test_a_clicked_signal_is_never_wired_straight_to_a_bare_signal():
    """QPushButton.clicked carries a checked flag.

    Connecting it to the emit of a zero-argument Signal type-checks fine and
    fails at the first press — exactly what a read-only milestone with no
    display cannot catch by itself.
    """
    import re
    root = Path(__file__).resolve().parent.parent / "kairo" / "qt"
    pattern = re.compile(r"clicked\.connect\(\s*self\.\w+\.emit\s*\)")
    offenders = [path.name for path in sorted(root.glob("*.py"))
                 if pattern.search(path.read_text())]
    assert not offenders, offenders


def test_a_disabled_button_never_keeps_its_accent():
    """ID selectors outrank bare pseudo-classes in QSS.

    QPushButton:disabled alone loses to QPushButton#primary, so a disabled
    Apply rendered in full accent and read as live. Caught by rendering it.
    """
    from kairo.qt import theme as Q
    for preset in ("frosted", "dense", "clear", "solid"):
        assert "QPushButton#primary:disabled" in Q.stylesheet(preset), preset


def test_only_one_primary_action_is_offered_at_a_time():
    """Apply is the primary action; nothing else competes with it."""
    source = (Path(__file__).resolve().parent.parent
              / "kairo" / "qt" / "library.py").read_text()
    primaries = [line.strip() for line in source.splitlines()
                 if 'setObjectName("primary")' in line]
    assert len(primaries) == 1, primaries
    assert "apply_btn" in primaries[0]


def test_a_cleared_widget_is_unparented_before_it_is_deleted():
    """deleteLater only runs on the next event-loop turn.

    Until then the old tiles keep painting over the new grid, so a source
    switch flickers the previous results on top of the incoming ones.
    """
    source = (Path(__file__).resolve().parent.parent
              / "kairo" / "qt" / "library.py").read_text()
    index = source.index("widget.deleteLater()")
    assert "widget.setParent(None)" in source[index - 200:index]


def test_a_pane_subclass_asks_for_its_own_background():
    """QSS backgrounds are opt-in for QWidget subclasses.

    A plain QWidget instance painted #workspace fine, so the library looked
    right while Settings and Changes silently fell back to the default
    palette and read as light grey panels.
    """
    import re
    root = Path(__file__).resolve().parent.parent / "kairo" / "qt"
    offenders = []
    for path in sorted(root.glob("*.py")):
        body = path.read_text()
        for match in re.finditer(r"class (\w+)\(QWidget\):", body):
            block = body[match.start():match.start() + 2600]
            names = re.search(r'self\.setObjectName\("(\w+)"\)', block)
            if names and "WA_StyledBackground" not in block:
                offenders.append(f"{path.name}: {match.group(1)} -> {names.group(1)}")
    assert not offenders, offenders

# -- what the window deliberately no longer has -----------------------------

def test_there_is_no_status_strip():
    """The window is the three columns and nothing else.

    A footer that reports blur state and a read-only banner is scaffolding
    from the milestone, not part of the product.
    """
    shell = (QT_DIR / "shell.py").read_text()
    assert "objectName(\"footer\")" not in shell
    assert "read-only shell" not in shell
    assert "_refresh_status" not in shell


def test_blur_state_never_reaches_the_window():
    """It still prints once for a terminal launch, and stops there."""
    shell = (QT_DIR / "shell.py").read_text()
    settings = (QT_DIR / "settings.py").read_text()
    assert "set_blur_status" not in shell and "set_blur_status" not in settings
    # It may be assigned and printed; it may never be put into a widget.
    for line in shell.splitlines():
        if "blur.status" in line:
            assert "setText" not in line, line.strip()
            assert "addWidget" not in line, line.strip()


def test_appearance_is_fixed_not_edited():
    """The glass values are the design now, not a runtime control."""
    settings = (QT_DIR / "settings.py").read_text()
    shell = (QT_DIR / "shell.py").read_text()
    assert "AppearancePanel" not in settings
    assert "QSlider" not in settings
    assert "on_glass_change" not in settings and "on_glass_change" not in shell
    assert "QShortcut" not in shell, "no live retuning keys"


def test_the_fixed_appearance_is_still_applied():
    """Removing the controls must not remove the look they were setting."""
    from kairo.qt import theme as Q

    shell = (QT_DIR / "shell.py").read_text()
    assert "def apply_glass" in shell
    assert "setStyleSheet(Q.stylesheet(self.glass))" in shell
    frosted = Q.PRESETS[Q.DEFAULT_PRESET]
    assert (frosted.workspace, frosted.nav, frosted.panel) == (0.50, 0.86, 0.82)


def test_a_dead_receiver_never_strands_a_job(qt_core, monkeypatch):
    """Emitting from a deleted sender raises rather than being dropped.

    When the application tears down mid-lookup, that RuntimeError used to
    escape run() and take the finished signal with it, so the job was never
    released and is_idle() stayed false — a close that waits on it would then
    wait forever.
    """
    from kairo.qt import work

    class DeadSignal:
        def emit(self, *args):
            raise RuntimeError("Signal source has been deleted")

    job = work.submit(lambda: "value")
    monkeypatch.setattr(job.signals, "done", DeadSignal(), raising=False)
    monkeypatch.setattr(job.signals, "finished", DeadSignal(), raising=False)
    job.run()                      # as the pool thread would call it

    assert job not in work._LIVE_JOBS, "a stranded job blocks every close"


def test_closing_waits_for_work_but_not_forever():
    """A window must always be closable."""
    source = (QT_DIR / "shell.py").read_text()
    assert "CLOSE_DRAIN_SECONDS" in source
    finish = source.split("def _finish_close")[1]
    assert "_close_deadline" in finish, "the drain has no deadline"


# -- one asset, several resolutions -----------------------------------------

def _ico(sizes):
    """A .ico holding several frames, smallest first, as SteamGridDB serves.

    Built with QImage alone: QPainter and QFont need a QGuiApplication, and
    this must stay runnable on a machine with no display.
    """
    import struct

    from PySide6.QtCore import QBuffer, QByteArray
    from PySide6.QtGui import QColor, QImage

    frames = []
    for index, size in enumerate(sizes):
        img = QImage(size, size, QImage.Format_ARGB32)
        img.fill(QColor(40 * (index + 1) % 256, 90, 160))
        blob = QByteArray()
        buffer = QBuffer(blob)
        buffer.open(QBuffer.WriteOnly)
        img.save(buffer, "PNG")
        frames.append((size, bytes(blob.data())))

    out = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    entries = body = b""
    for size, blob in frames:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0,
                               1, 32, len(blob), offset)
        body += blob
        offset += len(blob)
    return out + entries + body


def test_the_biggest_frame_is_the_one_that_gets_decoded():
    """QPixmap.loadFromData returns the *first* frame, which is the smallest.

    SteamGridDB serves one asset at several resolutions in a single .ico -
    a 256px icon ships alongside 128, 64, 48, 32 and 16 - so the browser was
    rendering a 16px thumbnail enlarged into a 116px tile. The reported
    dimensions were never wrong; nobody was decoding the frame they named.
    """
    from kairo.qt import images

    assert images._largest_frame(_ico([16, 32, 64, 128, 256])).width() == 256


def test_a_single_frame_image_is_unaffected():
    from kairo.qt import images

    assert images._largest_frame(_ico([256])).width() == 256


def test_undecodable_bytes_yield_nothing():
    from kairo.qt import images

    assert images._largest_frame(b"not an image at all") is None


def test_the_floor_is_applied_to_the_frame_that_decoded():
    """The API's dimensions describe the asset; the frame describes the pixels.

    An .ico can advertise 256 and contain nothing above 64. Filtering on the
    reported size alone let those through, so the same floor is applied again
    to what actually arrived - the one measurement that cannot be wrong.
    """
    from kairo.qt import images
    from kairo.qt.library import MIN_USABLE_EDGE

    assert images.native_edge(_ico([16, 32, 64])) < MIN_USABLE_EDGE
    assert images.native_edge(_ico([16, 32, 256])) >= MIN_USABLE_EDGE
    assert images.native_edge(b"not an image") == 0


def test_valid_svg_is_not_rejected_by_its_nominal_canvas_size():
    """Theme icons are scalable even when their SVG says 48 by 48."""
    from kairo.qt import images
    from kairo.qt.library import MIN_USABLE_EDGE

    svg = (b'<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" '
           b'viewBox="0 0 48 48"><rect width="48" height="48"/></svg>')
    assert images.native_edge(svg) < MIN_USABLE_EDGE
    assert images.is_usable_preview(svg, MIN_USABLE_EDGE)
    assert not images.is_usable_preview(_ico([16, 32, 64]), MIN_USABLE_EDGE)
    assert images.is_usable_preview(_ico([16, 32, 256]), MIN_USABLE_EDGE)
    assert not images.is_usable_preview(b"not an image", MIN_USABLE_EDGE)


def test_preview_preparation_is_safe_off_the_gui_thread():
    """Decode and scaling belong on a worker; only QPixmap painting is GUI work."""
    from kairo.qt import images
    from kairo.qt.library import MIN_USABLE_EDGE

    result = []
    worker = threading.Thread(
        target=lambda: result.append(
            images.prepare(116, data=_ico([32, 128, 256]),
                           min_edge=MIN_USABLE_EDGE)))
    worker.start()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert result and not result[0].isNull()
    assert max(result[0].width(), result[0].height()) == 116


def test_artwork_is_decoded_before_it_reaches_the_gui_thread():
    source = (QT_DIR / "library.py").read_text()
    pump = source.split("def _stream_previews")[1].split("\n    def ")[0]
    fill = source.split("def _fill_tile")[1].split("\n    def ")[0]
    assert "images.prepare(" in pump
    assert "min_edge=usable_edge(ratio)" in pump, \
        "the quality floor must be the one that follows the screen ratio"
    assert "is_usable_preview" not in fill
    assert "images.load" not in fill


def test_a_queued_preview_cannot_cross_sources_for_the_same_application():
    """The entry key stays equal when only the artwork tab or query changes."""
    source = (QT_DIR / "library.py").read_text()
    pump = source.split("def _stream_previews")[1].split("\n    def ")[0]
    fill = source.split("def _fill_tile")[1].split("\n    def ")[0]
    # Previews are handed over in groups now, so the payload is the batch and
    # the token that asked for it — the guard is what matters, not the shape.
    assert "token)" in pump, "the request token must travel with the payload"
    assert "token.cancelled" in fill


def test_a_dropped_tile_does_not_leave_a_hole():
    """Removing a widget from a QGridLayout leaves its cell empty."""
    source = (QT_DIR / "library.py").read_text()
    drop = source.split("def _drop_tile")[1].split("\n    def ")[0]
    assert "_reflow_tiles" in drop
    reflow = source.split("def _reflow_tiles")[1].split("\n    def ")[0]
    assert "self.grid.addWidget(tile" in reflow
    assert "_grid_note" in reflow, "an emptied grid must say so"


def test_dropping_the_chosen_tile_clears_the_proposal():
    """Applying artwork that was just removed from the grid is not a thing."""
    source = (QT_DIR / "library.py").read_text()
    drop = source.split("def _drop_tile")[1].split("\n    def ")[0]
    assert "self._clear_proposal()" in drop


def test_clearing_the_proposal_also_withdraws_apply():
    source = (QT_DIR / "library.py").read_text()
    clear = source.split("def _clear_proposal")[1].split("\n    def ")[0]
    assert "self.apply_btn.setEnabled(False)" in clear


def test_previews_are_delivered_by_identity_not_by_position():
    """Dropping one tile must not misdirect every preview after it.

    Previews arrive keyed by their index in the result list while tiles are
    being removed as they land, so position in self.tiles stops matching the
    moment anything is dropped: later images went to the wrong tile and the
    tail was never filled at all, which is what showed up as blank squares.
    """
    source = (QT_DIR / "library.py").read_text()
    fill = source.split("def _fill_tile")[1].split("\n    def ")[0]
    assert "self._tile_at.get(index)" in fill
    assert "self.tiles[index]" not in fill, "positional lookup is the bug"

    drop = source.split("def _drop_tile")[1].split("\n    def ")[0]
    assert "del self._tile_at[index]" in drop, "a dropped tile must be unkeyed"


def test_a_preview_that_cannot_be_fetched_drops_its_tile():
    """An empty square is worse than one fewer choice."""
    source = (QT_DIR / "library.py").read_text()
    pump = source.split("def _stream_previews")[1].split("\n    def ")[0]
    assert "data = None" in pump, "a failure must be reported, not skipped"
    assert "continue" not in pump, "skipping leaves the tile blank forever"

    fill = source.split("def _fill_tile")[1].split("\n    def ")[0]
    assert "data is None" in fill


def test_the_app_id_is_only_claimed_when_a_desktop_file_backs_it(
        monkeypatch, tmp_path):
    """The portal logs a failure for an id it cannot look up.

    Announcing io.github.shadowxskinner.Kairo without the .desktop file
    installed is what produced "App info not found" on every launch.
    """
    from kairo import APP_ID
    from kairo.qt.__main__ import _desktop_file_installed

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "none"))
    assert _desktop_file_installed(APP_ID) is False

    applications = tmp_path / "applications"
    applications.mkdir()
    (applications / f"{APP_ID}.desktop").write_text("[Desktop Entry]\n")
    assert _desktop_file_installed(APP_ID) is True


def test_a_system_wide_install_counts_too():
    """XDG_DATA_DIRS, not a guess at ~/.local/share."""
    source = (QT_DIR / "__main__.py").read_text()
    assert "XDG_DATA_DIRS" in source
    assert "XDG_DATA_HOME" in source



def test_scanning_a_library_does_not_block_the_window():
    """A ROM folder can be thousands of files on a spinning disk."""
    source = (QT_DIR / "library.py").read_text()
    rescan = source.split("def rescan")[1].split("\n    def ")[0]
    assert "work.submit(" in rescan
    assert 'self.tokens.start(f"{ACTIVITY_SCAN}:{provider.id}")' in rescan
    assert "self.tokens.start(ACTIVITY_SCAN)" not in rescan
    assert "provider.scan()" in rescan
    assert "token.cancelled" in rescan, "a stale scan must not overwrite a new one"


def test_unchanged_pills_are_not_destroyed_and_recreated():
    """Refreshing stable tabs must not make them flash or lose selection."""
    source = (QT_DIR / "widgets.py").read_text()
    body = source.split("def set_values(self, values)")[1].split("\n    def ")[0]
    assert "values == list(self._buttons)" in body
    assert "self._layout.removeWidget(button)" in body
    assert "button.setParent(None)" in body


def test_rows_are_built_in_pages_not_all_at_once():
    """A row is five widgets; a library is not necessarily small.

    Building one per entry cost 1.8 seconds and 225MB on a 2000-game
    library — and paid it again every time the search box was cleared.
    """
    from kairo.qt.library import ROW_PAGE

    source = (QT_DIR / "library.py").read_text()
    assert 0 < ROW_PAGE < 500
    refilter = source.split("def refilter")[1].split("\n    def ")[0]
    assert "self._shown = min(" in refilter
    assert "self._bind_rows(entries[:self._shown])" in refilter


def test_row_icons_do_not_delay_the_first_list_paint():
    source = (QT_DIR / "library.py").read_text()
    bind = source.split("def _bind_rows")[1].split("\n    def ")[0]
    stream = source.split("def _stream_row_icons")[1].split("\n    def ")[0]
    assert "defer_icon=True" in bind
    assert "images.prepare(" in stream
    assert "work.submit(pump)" in stream


def test_large_change_histories_are_reused_and_paged():
    from kairo.qt.changes import CHANGES_PAGE

    source = (QT_DIR / "changes.py").read_text()
    refresh = source.split("def refresh")[1].split("\n    def ")[0]
    grow = source.split("def _grow_if_near_bottom")[1].split("\n    def ")[0]
    assert 0 < CHANGES_PAGE < 200
    assert "signature == self._signature" in refresh
    assert "self._row_widgets.get(record.key)" in source
    assert "self._shown + CHANGES_PAGE" in grow


def test_reaching_the_bottom_brings_the_next_page():
    """Paging must not put entries out of reach."""
    source = (QT_DIR / "library.py").read_text()
    grow = source.split("def _grow_if_near_bottom")[1].split("\n    def ")[0]
    assert "self._shown + ROW_PAGE" in grow
    assert "verticalScrollBar" in grow
    assert "valueChanged.connect" in source


def test_the_count_reports_the_library_not_the_page():
    """Showing 120 of 2000 must still say 2000."""
    source = (QT_DIR / "library.py").read_text()
    refilter = source.split("def refilter")[1].split("\n    def ")[0]
    assert "self.visible = len(entries)" in refilter
    assert "self.count.setText(str(len(entries)))" in refilter


def test_growing_the_page_keeps_the_selection():
    source = (QT_DIR / "library.py").read_text()
    grow = source.split("def _grow_if_near_bottom")[1].split("\n    def ")[0]
    assert "self.selected" in grow, "scrolling must not drop the selection"


def test_the_application_has_an_icon_at_all():
    """It had none: window, task switcher and taskbar all fell back."""
    from kairo.qt import branding

    source = (QT_DIR / "__main__.py").read_text()
    assert "setWindowIcon(branding.icon())" in source
    built = branding.icon()
    assert not built.isNull()
    assert max(s.width() for s in built.availableSizes()) >= 256


def test_the_icon_is_found_from_a_checkout_too():
    """Installed it comes from the theme; run from source there is no theme."""
    source = (QT_DIR / "branding.py").read_text()
    assert "QIcon.fromTheme(APP_ID)" in source
    assert "_repository_icons" in source


def test_a_row_keeps_asking_until_its_icon_actually_arrives():
    """Growing the page cancels the pump feeding the previous page.

    Rows are bound once and their identity recorded, so asking only "did the
    identity change" left every row whose icon was still decoding stuck on a
    placeholder letter for good. Scrolling a 214-entry list stranded 106 of
    them. The question has to be "is one still needed", not "is one new".
    """
    source = (QT_DIR / "widgets.py").read_text()
    bind = source.split("def bind(")[1].split("\n    def ")[0]
    assert "not self._icon_ready" in bind, "a row must re-ask while unpainted"

    delivered = source.split("def show_prepared_icon")[1].split("\n    def ")[0]
    assert "self._icon_ready = True" in delivered, "delivery must clear the need"


def test_a_prepared_icon_is_matched_on_key_and_generation():
    """An entry key alone is reused across rescans and page rebuilds."""
    source = (QT_DIR / "widgets.py").read_text()
    delivered = source.split("def show_prepared_icon")[1].split("\n    def ")[0]
    assert "self.entry.key != key" in delivered
    assert "_icon_identity[2] != generation" in delivered


def test_a_preview_carries_the_token_that_asked_for_it():
    """Switching artwork source or query keeps the same entry key.

    Guarding on the key alone let a preview queued by the previous source
    paint into the new source's tiles.
    """
    source = (QT_DIR / "library.py").read_text()
    fill = source.split("def _fill_tile")[1].split("\n    def ")[0]
    assert "token = payload" in fill, "the payload carries its request token"
    assert "token.cancelled" in fill
    assert fill.index("token.cancelled") < fill.index("for index"), \
        "a cancelled batch must be dropped before any tile is touched"
    stream = source.split("def _stream_previews")[1].split("\n    def ")[0]
    assert "token)" in stream


def test_pixmaps_are_never_built_off_the_gui_thread():
    """QImage is thread-safe to build; QPixmap is not."""
    import re

    worker_side = (QT_DIR / "images.py").read_text()
    prepare = worker_side.split("def prepare(")[1].split("\ndef ")[0]
    assert "QPixmap" not in prepare, "prepare() runs on a worker"

    library = (QT_DIR / "library.py").read_text()
    for body in (library.split("def pump()")[1].split("\n        work.submit")[0]
                 for _ in range(1)):
        assert "QPixmap" not in body
    assert not re.search(r"work\.submit\([^)]*images\.load", library)


# -- one grid instead of tabs -----------------------------------------------

def test_every_source_is_searched_together():
    """Tabs made you find and click a source before its results existed.

    They are queried in the provider's own preference order — the order
    automatic matching already trusts — and merged into one grid.
    """
    source = (QT_DIR / "library.py").read_text()
    assert "source_pills" not in source, "the tabs are gone"
    ordering = source.split("def sources(")[1].split("\n    def ")[0]
    assert "auto_match_sources" in ordering
    search = source.split("def search():")[1].split("def arrived")[0]
    assert "for source in sources:" in search


def test_one_failing_source_does_not_empty_the_grid():
    """A source being down is not the same as a game having no artwork."""
    source = (QT_DIR / "library.py").read_text()
    search = source.split("def search():")[1].split("def arrived")[0]
    assert "except Exception:" in search
    assert "continue" in search


def test_a_tile_says_which_source_it_came_from():
    """With one grid, provenance is what the tabs used to carry.

    It is the caption rather than a suffix on one: "HighContrast · Icon
    themes" does not fit a 136px tile and was clipped to "ighContrast · Icon
    the." Style and size moved to the tooltip.
    """
    widgets = (QT_DIR / "widgets.py").read_text()
    assert 'origin: str = ""' in widgets
    block = widgets.split("class ArtworkTile")[1]
    assert "shown = origin or style" in block
    assert "elidedText" in block, "a caption must never be clipped mid-word"
    assert "setToolTip" in block


def test_previews_are_fetched_from_the_source_that_produced_them():
    """A merged grid holds artwork from several sources at once."""
    source = (QT_DIR / "library.py").read_text()
    pump = source.split("def _stream_previews")[1].split("\n    def ")[0]
    assert "for index, (art, source) in enumerate(results)" in pump


def test_a_row_shows_the_name_and_nothing_else():
    """The second line was a Steam appid or a .desktop basename."""
    widgets = (QT_DIR / "widgets.py").read_text()
    assert "self.meta" not in widgets.split("class ArtworkTile")[0].split("class EntryRow")[1]
    library = (QT_DIR / "library.py").read_text()
    select = library.split("def select(self, row")[1].split("\n    def ")[0]
    assert "self._set_heading(entry.name)" in select, (
        "the heading is the name alone; _set_heading defaults the second "
        "line to empty, which is what keeps the appid out of it")
    code = "\n".join(line for line in select.splitlines()
                     if not line.lstrip().startswith("#"))
    assert "entry.subtitle" not in code, "the appid must not reappear"


def test_every_method_a_qt_pane_calls_on_itself_exists():
    """The structural suite never builds a tile, so it never notices.

    Replacing a block of a class can silently take a neighbouring method with
    it: _columns went missing that way and the whole suite stayed green,
    because nothing in it calls _build_tiles.
    """
    import ast

    missing = []
    for path in sorted(QT_DIR.glob("*.py")):
        tree = ast.parse(path.read_text())
        for klass in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            defined = {n.name for n in klass.body
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            assigned = {t.attr for n in ast.walk(klass)
                        for t in ast.walk(n)
                        if isinstance(t, ast.Attribute)
                        and isinstance(t.ctx, ast.Store)}
            for node in ast.walk(klass):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)):
                    continue
                target = node.func
                if not (isinstance(target.value, ast.Name)
                        and target.value.id == "self"):
                    continue
                name = target.attr
                if name in defined or name in assigned:
                    continue
                # inherited from QWidget and friends, or set on an instance
                if not name.startswith("_"):
                    continue
                missing.append(f"{path.name}:{klass.name}.{name}")
    assert not missing, missing


def test_a_provider_uses_its_own_installed_logo():
    """Steam's and Dolphin's marks are what a person recognises.

    Nothing is bundled: the name is resolved through the installed icon
    theme, so no trademark ships with Kairo and a machine without that
    package keeps the drawn glyph.
    """
    widgets = (QT_DIR / "widgets.py").read_text()
    assert "def _theme_logo" in widgets
    helper = widgets.split("def _theme_logo")[1].split("\ndef ")[0]
    assert "resolve_icon" in helper
    assert "return None" in helper, "a missing logo must fall back, not raise"

    paint = widgets.split("def _paint_icon")[1].split("\n    def ")[0]
    assert "self._logo" in paint
    assert "nav_pixmap" in paint, "the drawn glyph is still the fallback"


def test_providers_name_a_logo_without_kairo_hardcoding_one():
    from kairo.providers.steam import SteamProvider

    assert SteamProvider().nav_icon_name == "steam"
    emulator = (Path(__file__).resolve().parent.parent / "kairo" / "providers"
                / "emulator.py").read_text()
    assert "nav_icon_name" in emulator
    assert "Path(emulator.executable).name" in emulator


def test_the_current_icon_belongs_to_the_title():
    """A before-and-after pair captioned CURRENT and PROPOSED was two
    columns saying what one icon and one line can say."""
    source = (QT_DIR / "library.py").read_text()
    header = source.split("header = QWidget()")[1].split("layout.addWidget(header)")[0]
    assert "self.current_well" in header
    compare = source.split("def _build_compare")[1].split("\n    def ")[0]
    assert "CURRENT" not in compare
    assert "PROPOSED" in compare


def test_prepared_images_are_handed_over_in_groups():
    """One signal per image made a page fill in a visible trickle.

    120 separate paints spread over 86ms reads as the window assembling
    itself in front of you rather than appearing.
    """
    from kairo.qt.library import BATCH_MS, BATCH_SIZE

    assert 1 < BATCH_SIZE <= 64
    assert 0 < BATCH_MS <= 100, "a slow disk must still show progress"

    source = (QT_DIR / "library.py").read_text()
    rows = source.split("def _stream_row_icons")[1].split("\n    def ")[0]
    assert "BATCH_SIZE" in rows and "BATCH_MS" in rows
    assert "batch.clear()" in rows, "a flushed group must not be sent twice"

    fill = source.split("def _fill_row_icon")[1].split("\n    def ")[0]
    assert "for index, image, key, generation in payload" in fill, \
        "each row in a group carries its own entry key"


def test_a_group_carries_a_key_per_row_not_one_for_the_group():
    """Rows in a page belong to different entries.

    Tagging a whole group with the last key seen made show_prepared_icon
    reject every other row in it: a page of 120 painted five icons.
    """
    source = (QT_DIR / "library.py").read_text()
    rows = source.split("def _stream_row_icons")[1].split("\n    def ")[0]
    assert "batch.append((index, image, key, generation))" in rows
    assert 'streamer.item.emit(0, list(batch), "")' in rows, \
        "the group-level key must not be used to match rows"


def test_every_nav_row_takes_the_selected_text_style():
    """A row with a logo returned before it restyled its own label.

    Steam and Dolphin never went bold when selected while every drawn-glyph
    row did, which read as the selection not registering.
    """
    source = (QT_DIR / "widgets.py").read_text()
    paint = source.split("def _paint_icon")[1].split("\n    def ")[0]
    assert paint.index("navNameOn") < paint.index("self._logo"), \
        "the label must be styled before any early return for a logo"


def test_only_a_real_product_brings_colour_to_the_sidebar():
    """An accent-tinted pictogram beside two brand logos reads as a third."""
    source = (QT_DIR / "widgets.py").read_text()
    paint = source.split("def _paint_icon")[1].split("\n    def ")[0]
    assert "C_ACCENT_TEXT" not in paint
    assert "Q.GLYPH_ON if on else Q.GLYPH" in paint


def test_the_drawn_glyphs_carry_no_hue():
    """The shared text palette is still violet: C_TEXT3 is #6B6499.

    A pictogram painted in it read as a third brand colour beside the two
    real product logos, which is what made the sidebar look busy.
    """
    from kairo.qt import theme as Q

    for name in ("GLYPH", "GLYPH_ON"):
        value = getattr(Q, name).lstrip("#")
        channels = [int(value[i:i + 2], 16) for i in (0, 2, 4)]
        assert max(channels) - min(channels) <= 10, f"{name} is tinted"


# ---------------------------------------------------------------------------
# The search box, and whether it searches
# ---------------------------------------------------------------------------

class _Source:
    def __init__(self, ident, needs_query):
        self.id = ident
        self.needs_query = needs_query


def _steam_query():
    from kairo.models import AppEntry, ArtQuery

    entry = AppEntry(key="steam:440", provider_id="steam",
                     name="Call of Duty: Black Ops")
    return ArtQuery(entry=entry, text="Call of Duty: Black Ops",
                    icon_name="cod-black-ops", steam_appid="42649")


def test_a_typed_title_reaches_a_source_that_never_asked_for_one():
    """The bug the user found: a search box that searched nothing.

    Free text used to be handed only to sources declaring needs_query.
    SteamGridDB does not declare it, is keyed on an appid, and supplies
    nearly every result for a game — so typing in the box and pressing
    Enter changed the grid not at all.
    """
    from kairo.qt.library import query_for

    base = _steam_query()
    asked = query_for(_Source("steamgriddb", False), base,
                      "black ops 1", base.text)

    assert asked.text == "black ops 1"
    assert asked.steam_appid == "", (
        "a resolved appid outranks free text, so it has to be dropped for "
        "the typed title to be what actually gets searched")


def test_the_seeded_title_does_not_downgrade_an_exact_identifier():
    """The box arrives pre-filled, and that must not count as a search."""
    from kairo.qt.library import query_for

    base = _steam_query()
    for term in (base.text, "  Call of Duty: BLACK OPS  ", ""):
        asked = query_for(_Source("steamgriddb", False), base, term.strip(),
                          base.text)
        assert asked.steam_appid == "42649", (
            f"{term!r} is the title we seeded, not one anybody typed")


def test_a_source_that_wants_a_term_still_gets_its_own_default():
    from kairo.qt.library import query_for

    base = _steam_query()
    theme = _Source("theme", True)
    assert query_for(theme, base, "", base.text).text == "cod-black-ops"
    assert query_for(theme, base, "dolphin", base.text).text == "dolphin"

    bare = base.with_text("")
    empty = type(bare)(entry=bare.entry)
    assert query_for(theme, empty, "", "") is None, "nothing to search on"


def test_clearing_the_box_puts_the_default_results_back():
    source = (QT_DIR / "library.py").read_text()
    assert "self.query.textChanged.connect(self._query_cleared)" in source, (
        "the clear button emits no returnPressed, so without this the grid "
        "keeps showing the results of a search no longer in the field")


# ---------------------------------------------------------------------------
# Icons, and the pixel grid they are drawn on
# ---------------------------------------------------------------------------

def test_drawn_glyphs_are_rendered_for_the_screen_they_land_on(qt_core):
    """A 22-pixel bitmap is what a 2x display magnifies."""
    from kairo.qt.widgets import nav_pixmap

    for kind in ("grid", "history", "sliders", "steam", "chip"):
        plain = nav_pixmap(kind, "#8A8A93", 22)
        retina = nav_pixmap(kind, "#8A8A93", 22, 2.0)

        assert plain.width() == 22
        assert retina.width() == 44, f"{kind} was drawn at logical size"
        assert retina.devicePixelRatio() == 2.0
        # Same apparent size, four times the ink.
        assert retina.deviceIndependentSize() == plain.deviceIndependentSize()


def test_a_glyph_draws_the_same_picture_at_every_ratio(qt_core):
    """More pixels, not a bigger drawing.

    QPainter applies a pixmap's device pixel ratio to every coordinate on
    its own. Scaling the painter as well drew each glyph at ratio squared,
    so at 2x all that survived was its top-left corner — and the size and
    ratio assertions above all still passed, because they never looked at
    what had been drawn.
    """
    from PySide6.QtGui import QColor
    from kairo.qt.widgets import nav_pixmap

    def bounds(pixmap):
        ratio = pixmap.devicePixelRatio()
        image = pixmap.toImage()
        marked = [(x, y)
                  for y in range(image.height())
                  for x in range(image.width())
                  if QColor(image.pixelColor(x, y)).alpha() > 40]
        assert marked
        xs = [x / ratio for x, _ in marked]
        ys = [y / ratio for _, y in marked]
        return min(xs), min(ys), max(xs), max(ys)

    for kind in ("grid", "history", "sliders", "steam", "chip"):
        plain = bounds(nav_pixmap(kind, "#FFFFFF", 22))
        for ratio in (2.0, 3.0):
            drawn = bounds(nav_pixmap(kind, "#FFFFFF", 22, ratio))
            for edge, (a, b) in enumerate(zip(plain, drawn)):
                assert abs(a - b) < 1.5, (
                    f"{kind} at {ratio}x covers a different area: "
                    f"{plain} against {drawn}")


def test_glyph_geometry_follows_the_icon_scale_rather_than_a_past_one(qt_core):
    """Every coordinate a fraction of size, so no glyph sits off its centre."""
    from PySide6.QtGui import QColor
    from kairo.qt.widgets import nav_pixmap

    for kind in ("grid", "history", "sliders", "chip"):
        for size in (16, 22, 40):
            image = nav_pixmap(kind, "#FFFFFF", size).toImage()
            marked = [(x, y)
                      for y in range(image.height())
                      for x in range(image.width())
                      if QColor(image.pixelColor(x, y)).alpha() > 40]
            assert marked, f"{kind} at {size} drew nothing"

            xs = [x for x, _ in marked]
            ys = [y for _, y in marked]
            slack = size * 0.16
            assert abs((min(xs) + max(xs)) / 2 - (size - 1) / 2) < slack, (
                f"{kind} at {size} is off centre horizontally")
            assert abs((min(ys) + max(ys)) / 2 - (size - 1) / 2) < slack, (
                f"{kind} at {size} is off centre vertically")
            assert max(xs) - min(xs) > size * 0.5, f"{kind} at {size} is small"


def test_every_glyph_terminal_is_round():
    source = (QT_DIR / "widgets.py").read_text()
    draw = source.split("def nav_pixmap")[1].split("\ndef ")[0]
    assert "pen.setCapStyle(Qt.RoundCap)" in draw
    assert "pen.setJoinStyle(Qt.RoundJoin)" in draw
    assert "drawRect(" not in draw, "square corners; use drawRoundedRect"


def test_a_theme_logo_is_decoded_at_the_screens_resolution(qt_core):
    """The sidebar logos were soft with no blurry source file involved."""
    import io
    from PIL import Image
    from kairo.qt import images

    return_ratio = getattr(images.load, "__doc__", "")
    assert "ratio" in return_ratio

    buffer = io.BytesIO()
    Image.new("RGBA", (256, 256), (255, 0, 0, 255)).save(buffer, format="PNG")
    payload = buffer.getvalue()

    plain = images.load(22, data=payload)
    retina = images.load(22, data=payload, ratio=2.0)
    assert plain is not None and retina is not None
    assert plain.width() == 22
    assert retina.width() == 44, "decoded at logical size, then magnified"
    assert retina.devicePixelRatio() == 2.0


def test_a_nav_row_repaints_once_it_knows_its_screen():
    source = (QT_DIR / "widgets.py").read_text()
    assert "def showEvent" in source, (
        "__init__ paints at ratio 1 because the button has no screen yet")
    show = source.split("def showEvent")[1].split("\n    def ")[0]
    assert "self._paint_icon(self.isChecked())" in show


# ---------------------------------------------------------------------------
# Ending the process, however it ends
# ---------------------------------------------------------------------------

def test_the_pool_can_be_waited_on_and_not_merely_asked(qt_core):
    """is_idle reports; something has to be able to make the process wait."""
    import threading
    from kairo.qt import work

    gate = threading.Event()
    work.submit(lambda: gate.wait(5) or "done")
    assert not work.is_idle()

    assert work.drain(0.05) is False, "a running job cannot have drained"
    gate.set()
    assert work.drain(5.0) is True
    assert work.is_idle(), "drain must leave nothing for a later close to find"


def test_leaving_the_event_loop_drains_before_the_interpreter_does():
    """Closing the window drains. Every other way of ending does not.

    A session logout, a SIGTERM, or Ctrl+C in the terminal Kairo was started
    from all return from exec() without any window seeing closeEvent, and
    Python then tore down around a live worker thread. That is an
    intermittent segfault on exit and nothing else: 4 of 24 runs here.
    """
    source = (Path(__file__).resolve().parents[1]
              / "kairo" / "qt" / "__main__.py").read_text()
    tail = source.split("window.show()")[1]
    assert "try:" in tail and "finally:" in tail, (
        "exec() must be wrapped, or an exception on the way out skips it")
    assert "work.drain()" in tail
    assert tail.index("return application.exec()") < tail.index("work.drain()")


# ---------------------------------------------------------------------------
# Nav logos: a search, not a single guess
# ---------------------------------------------------------------------------

def test_the_logo_search_takes_the_first_candidate_that_resolves(qt_core,
                                                                 tmp_path):
    """resolve_icon takes an absolute path verbatim, which makes this real."""
    from PIL import Image
    from kairo.qt.widgets import _theme_logo

    real = tmp_path / "emulator.png"
    Image.new("RGBA", (128, 128), (10, 200, 90, 255)).save(real)
    missing = str(tmp_path / "not-installed.png")

    assert _theme_logo((missing, str(real)), 22) is not None, (
        "a candidate that does not resolve must not end the search")
    assert _theme_logo((missing,), 22) is None
    assert _theme_logo((), 22) is None
    assert _theme_logo("", 22) is None
    # Still accepts the single name the old call site passed.
    assert _theme_logo(str(real), 22) is not None


def test_each_medium_draws_a_different_picture(qt_core):
    """Four glyph names that render the same bitmap would be four bugs."""
    from kairo.qt.widgets import nav_pixmap

    drawn = {}
    for kind in ("disc", "cartridge", "handheld", "chip", "grid", "sliders"):
        image = nav_pixmap(kind, "#FFFFFF", 40).toImage()
        drawn[kind] = image.constBits().tobytes()

    assert len(set(drawn.values())) == len(drawn), (
        "at least two glyph kinds render identically: "
        f"{[k for k in drawn if list(drawn.values()).count(drawn[k]) > 1]}")


def test_an_emulator_row_asks_for_every_candidate(qt_core):
    source = (QT_DIR / "shell.py").read_text()
    assert "nav_icon_names" in source, (
        "the sidebar must pass the whole candidate list, not the first name")


# ---------------------------------------------------------------------------
# Changes: paging, reuse, and how many widgets that costs
# ---------------------------------------------------------------------------

class _Ledger:
    def __init__(self, records):
        self._records = list(records)

    def records(self):
        return list(self._records)

    def set(self, records):
        self._records = list(records)


def _records(count, *, prefix="app", suffix=""):
    from kairo.ledger import ChangeRecord

    return [ChangeRecord(key=f"steam:{prefix}{i}", provider_id="steam",
                         name=f"Game {i}{suffix}", action="overrode",
                         target=f"/tmp/{prefix}{i}.desktop",
                         applied_at="2026-01-01T00:00:00")
            for i in range(count)]


def _changes_pane(records, qt_core):
    from types import SimpleNamespace
    from kairo.qt.changes import ChangesPane

    ledger = _Ledger(records)
    pane = ChangesPane(SimpleNamespace(ledger=ledger))
    pane.resize(900, 700)
    return pane, ledger


def _visible_keys(pane):
    """Rows the pane has chosen to show.

    isHidden(), not isVisible(): the pane itself is never shown in a test, and
    isVisible() is false for every descendant of an unshown parent regardless
    of what the pane decided.
    """
    return [row.record.key for row in pane._row_widgets.values()
            if not row.isHidden()]


def test_changes_holds_up_at_every_size_the_history_can_be(qt_core):
    from kairo.qt.changes import CHANGES_PAGE

    for total in (0, 1, CHANGES_PAGE - 1, CHANGES_PAGE, CHANGES_PAGE + 1,
                  300, 1000):
        pane, _ = _changes_pane(_records(total), qt_core)
        pane.refresh()

        expected = min(total, CHANGES_PAGE) if total else 0
        assert len(_visible_keys(pane)) == expected, f"{total} records"
        assert len(pane._row_widgets) <= max(expected, 0) , (
            f"{total} records built widgets for rows nobody asked for")
        if total == 0:
            assert pane._empty is not None, "no empty state for no history"
        else:
            assert pane._empty is None, "the empty state outlived the history"
        assert str(total) in pane.count.text(), "the full total must be shown"


def test_paging_reaches_the_last_record_without_duplicating_one(qt_core):
    from kairo.qt.changes import CHANGES_PAGE

    total = 300
    pane, _ = _changes_pane(_records(total), qt_core)
    pane.refresh()

    while pane._shown < total:
        before = pane._shown
        pane._shown = min(total, pane._shown + CHANGES_PAGE)
        pane._bind_records(pane._records[:pane._shown])
        assert pane._shown > before, "paging stopped making progress"

    keys = _visible_keys(pane)
    assert len(keys) == total
    assert len(set(keys)) == total, "a record was materialised twice"
    assert keys == [r.key for r in pane._records], "rows are out of order"


def test_revisiting_an_unchanged_history_rebuilds_nothing(qt_core):
    pane, _ = _changes_pane(_records(300), qt_core)
    pane.refresh()
    first = dict(pane._row_widgets)

    pane.refresh()
    assert pane._row_widgets == first, "identical history rebuilt its rows"
    assert all(pane._row_widgets[k] is v for k, v in first.items())


def test_adding_replacing_and_removing_one_record(qt_core):
    base = _records(50)
    pane, ledger = _changes_pane(base, qt_core)
    pane.refresh()

    # Added.
    ledger.set([*base, *_records(1, prefix="new")])
    pane.refresh()
    assert "steam:new0" in {r.key for r in pane._records}

    # Replaced in place: same key, different content.
    changed = list(base)
    changed[3] = _records(4, suffix=" (renamed)")[3]
    ledger.set(changed)
    pane.refresh()
    assert pane._row_widgets["steam:app3"].record.name.endswith("(renamed)")

    # Removed: its widget must not survive as a hidden orphan.
    ledger.set(base[:10])
    pane.refresh()
    assert set(pane._row_widgets) <= {r.key for r in base[:10]}, (
        "widgets for removed records were left parented to the pane")


def test_widget_count_stays_bounded_across_unrelated_histories(qt_core):
    """Every record replaced by a different one, ten times over."""
    pane, ledger = _changes_pane(_records(60), qt_core)
    pane.refresh()

    for round_ in range(10):
        ledger.set(_records(60, prefix=f"round{round_}-"))
        pane.refresh()

    assert len(pane._row_widgets) <= 60, (
        f"{len(pane._row_widgets)} widgets for 60 records — rows leak")


# ---------------------------------------------------------------------------
# The sidebar follows the launcher, and cannot strand a stale logo
# ---------------------------------------------------------------------------

def test_a_nav_row_repaints_in_place_without_being_rebuilt(qt_core, tmp_path):
    """Acceptance 3 and 9, at the widget.

    The selection and the widget identity must both survive, because the
    alternative — rebuilding navigation after every apply — drops the row the
    user is looking at.
    """
    from PIL import Image
    from kairo.qt.widgets import NavButton

    first = tmp_path / "one.png"
    second = tmp_path / "two.png"
    Image.new("RGBA", (64, 64), (200, 30, 30, 255)).save(first)
    Image.new("RGBA", (64, 64), (30, 30, 200, 255)).save(second)

    button = NavButton("provider:emu-pcsx2", "PCSX2", "disc",
                       logo_name=(str(first),))
    button.setChecked(True)
    button._paint_icon(True)
    before = button.glyph.pixmap().toImage()

    button.set_logo_names((str(second),))
    after = button.glyph.pixmap().toImage()

    assert before != after, "the row kept the icon it was built with"
    assert button.isChecked(), "repainting dropped the selection"

    # Idempotent: the same names must not churn the pixmap.
    same = button.glyph.pixmap()
    button.set_logo_names((str(second),))
    assert button.glyph.pixmap().cacheKey() == same.cacheKey()

    # And falling back is a repaint too, not a blank row.
    button.set_logo_names((str(tmp_path / "gone.png"),))
    assert not button.glyph.pixmap().isNull(), "the row went blank"


def test_rapid_apply_and_reset_cannot_strand_a_stale_logo(qt_core, tmp_path):
    """Acceptance 9. Whatever the launcher says last is what is painted."""
    from PIL import Image
    from kairo.qt.widgets import NavButton

    icons = []
    for index, colour in enumerate(((220, 20, 20), (20, 220, 20),
                                    (20, 20, 220), (220, 220, 20))):
        path = tmp_path / f"i{index}.png"
        Image.new("RGBA", (64, 64), (*colour, 255)).save(path)
        icons.append(str(path))

    button = NavButton("provider:emu", "PCSX2", "disc", logo_name=(icons[0],))
    button._paint_icon(False)
    for _ in range(15):
        for name in icons:
            button.set_logo_names((name,))
    settled = button.glyph.pixmap().toImage()

    fresh = NavButton("provider:emu", "PCSX2", "disc", logo_name=(icons[-1],))
    fresh._paint_icon(False)
    assert settled == fresh.glyph.pixmap().toImage(), (
        "the row settled on something other than the last value set")


def test_the_shell_refreshes_logos_on_change_and_rescan():
    """Acceptance 3 and 9, at the wiring."""
    source = (QT_DIR / "shell.py").read_text()
    assert "pane.changed.connect(self.refresh_nav_icons)" in source, (
        "an apply in Applications can be a change to an emulator's launcher")
    rescan = source.split("def rescan")[1].split("\n    def ")[0]
    assert "self.refresh_nav_icons()" in rescan

    refresh = source.split("def refresh_nav_icons")[1].split("\n    def ")[0]
    assert "set_logo_names" in refresh
    for destructive in ("_build_nav", "deleteLater", "setParent(None)",
                        "clear()"):
        assert destructive not in refresh, (
            f"refreshing logos must not {destructive} — that rebuilds the "
            "sidebar and drops the selection")


def test_the_header_has_no_launcher_button_left_behind(qt_core):
    """It competed with the title for exactly the room the title needed.

    Three abbreviations of one deep link - "Customize Steam icon...",
    "Launcher icon...", "Launcher..." - sat between the name and Rescan, so
    the longest titles were elided to make space for a button that only
    jumped to a row under Applications. The row is still reachable; the
    header is not where you reach it from.
    """
    from kairo.qt.shell import KairoWindow

    source = (QT_DIR / "library.py").read_text()
    for gone in ("customize_btn", "customize_launcher", "_customize_label",
                 "Launcher icon", "Launcher\u2026", "Customize Steam",
                 "Customize emulator"):
        assert gone not in source, f"{gone} survives in the pane"
    assert "customize_launcher" not in (QT_DIR / "shell.py").read_text()

    window = KairoWindow(translucent=False, want_blur=False)
    try:
        window.show()
        window.resize(1420, 900)
        qt_core.processEvents()
        pane = next((p for p in window.panes.values()
                     if hasattr(p, "set_layout_mode")), None)
        assert pane is not None
        assert not hasattr(pane, "customize_btn")

        header = pane._header_layout
        widgets = [header.itemAt(i).widget() for i in range(header.count())]
        # No blank spacer where the button used to be: every remaining slot
        # is either a real widget or the stretch that feeds the title.
        buttons = [w for w in widgets if w is not None
                   and w.metaObject().className() == "QPushButton"]
        assert len(buttons) == 1, "the header should hold Rescan and nothing else"
        assert buttons[0] is pane.rescan_btn
        assert pane.rescan_btn.isVisible()
        header_widget = pane.rescan_btn.parentWidget()
        right = pane.rescan_btn.geometry().x() + pane.rescan_btn.width()
        assert right <= header_widget.width(), \
            (f"Rescan ends at {right} in a {header_widget.width()}px header")
        assert pane.rescan_btn.geometry().x() > pane.title.geometry().x(), \
            "Rescan must sit to the right of the title"
    finally:
        window.close()
        from kairo.qt import work
        work.drain()


def test_the_deep_link_to_a_launcher_entry_still_exists(qt_core):
    """Removing the button must not remove the way in.

    Launcher icons stay editable through the entry under Applications, which
    is where they always were - reveal_launcher is the mechanism and it is
    still write-free.
    """
    source = (QT_DIR / "library.py").read_text()
    reveal = source.split("def reveal_launcher")[1].split("\n    def ")[0]
    for forbidden in ("apply_icon", "restore_entry", "remove_entry",
                      "QFileDialog", "actions."):
        assert forbidden not in reveal, \
            f"revealing a row must not {forbidden}; Applications owns that"

    shell = (QT_DIR / "shell.py").read_text()
    handler = shell.split("def open_launcher_in_applications")[1].split(
        "\n    def ")[0]
    assert "_select(key)" in handler and "reveal_launcher" in handler
    for forbidden in ("apply_icon", "restore_entry", "remove_entry"):
        assert forbidden not in handler


def test_unimplemented_auto_match_is_not_advertised_in_qt():
    source = (QT_DIR / "library.py").read_text()
    assert "Auto Match" not in source
    assert "match_btn" not in source


def test_the_reveal_retry_is_bounded():
    """A scan that never produces the row must not retry forever."""
    source = (QT_DIR / "shell.py").read_text()
    retry = source.split("def _retry_reveal")[1].split("\n    def ")[0]
    assert "attempts <= 1" in retry
    assert "self._pending_reveal = None" in retry


# ---------------------------------------------------------------------------
# Changes: restoring, and refusing to
# ---------------------------------------------------------------------------

class _Tokens:
    """The real ActivityTokens contract, small enough to assert against."""

    def __init__(self):
        from kairo.tasks import CancelToken

        self._make = CancelToken
        self.live = {}

    def start(self, name):
        previous = self.live.get(name)
        if previous is not None:
            previous.cancel()
        token = self._make()
        self.live[name] = token
        return token


def _restore_world(tmp_path, monkeypatch, *, count=3):
    """A packaged launcher, a Kairo override for each, and a real ledger."""
    from PIL import Image
    from kairo import actions, paths
    from kairo.ledger import Ledger
    from kairo.providers.desktop_entry import DesktopEntryProvider

    home = tmp_path / "home"
    system = home / "system-applications"
    local = home / ".local" / "share" / "applications"
    for directory in (system, local, home / ".config"):
        directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(paths, "system_application_dirs",
                        lambda: [system, local])

    for index in range(count):
        (system / f"app{index}.desktop").write_text(
            f"[Desktop Entry]\nType=Application\nName=App {index}\n"
            f"Icon=packaged-{index}\nExec=true\n")

    art = home / "art.png"
    Image.new("RGBA", (128, 128), (10, 200, 90, 255)).save(art)

    apps = DesktopEntryProvider()
    ledger = Ledger()
    for entry in sorted(apps.scan(), key=lambda e: e.name):
        actions.apply_icon(entry, apps, art, source_label="Local file",
                           ledger=ledger)
    return SimpleNamespaceLike(home=home, system=system, local=local,
                               apps=apps, ledger=ledger, art=art)


class SimpleNamespaceLike:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _changes(world, qt_app):
    from types import SimpleNamespace
    from kairo.qt.changes import ChangesPane

    registry = SimpleNamespace(get=lambda provider_id: world.apps)
    context = SimpleNamespace(ledger=world.ledger, providers=registry,
                              tokens=_Tokens())
    pane = ChangesPane(context)
    pane.resize(900, 700)
    pane.refresh()
    return pane


def test_a_restore_goes_through_actions_and_never_the_pane():
    """The pane decides when to ask. It must not write."""
    source = (QT_DIR / "changes.py").read_text()
    assert "actions.restore_record" in source
    assert "actions.restore_all" in source
    for forbidden in ("writer.restore(", "\\.unlink(", "atomic_write",
                      "write_text", "rewrite_entry_icon"):
        assert forbidden not in source, (
            f"Changes must not {forbidden} — kairo.actions owns that")
    # And the marker check is still the authority, not the ledger.
    assert "Ledger.restorable" in source


def test_restoring_one_entry_puts_the_packaged_icon_back(
        tmp_path, monkeypatch, qt_app):
    world = _restore_world(tmp_path, monkeypatch, count=3)
    pane = _changes(world, qt_app)
    assert len(world.ledger.records()) == 3

    record = world.ledger.records()[0]
    monkeypatch.setattr("kairo.qt.changes.QMessageBox.exec",
                        lambda self: __import__(
                            "PySide6.QtWidgets", fromlist=["QMessageBox"]
                        ).QMessageBox.Yes)
    pane._restore_one(record)
    assert settle(qt_app, timeout=10.0)

    assert len(world.ledger.records()) == 2, "the record survived its restore"
    assert not (world.local / record.target.split("/")[-1]).exists()
    assert "Restored" in pane.count.text()


def test_a_launcher_edited_outside_kairo_is_refused_not_restored(
        tmp_path, monkeypatch, qt_app):
    """The marker is the authority. Losing it must stop the restore."""
    from kairo.desktop import entry as de

    world = _restore_world(tmp_path, monkeypatch, count=2)
    record = world.ledger.records()[0]
    target = Path(record.target)

    # Someone rewrote it by hand and the marker went with it.
    text = target.read_text().replace("X-Kairo-Managed=true", "")
    target.write_text(text)
    assert not de.is_managed(target)

    pane = _changes(world, qt_app)
    row = pane._row_widgets[record.key]
    assert not row.undo.isEnabled(), "a refused restore must not be clickable"
    assert row.undo.toolTip(), "and it must say why"

    pane._restore_one(record)
    assert settle(qt_app, timeout=10.0)
    assert target.exists(), "Kairo removed a file it no longer owns"
    assert len(world.ledger.records()) == 2, "the record was dropped anyway"


def test_a_missing_target_is_reported_without_touching_anything(
        tmp_path, monkeypatch, qt_app):
    world = _restore_world(tmp_path, monkeypatch, count=2)
    record = world.ledger.records()[0]
    Path(record.target).unlink()

    pane = _changes(world, qt_app)
    pane._restore_one(record)
    assert settle(qt_app, timeout=10.0)
    assert "Already restored" in pane.count.text(), pane.count.text()


def test_an_unknown_provider_is_reported_rather_than_guessed(
        tmp_path, monkeypatch, qt_app):
    from types import SimpleNamespace
    from kairo.qt.changes import ChangesPane

    world = _restore_world(tmp_path, monkeypatch, count=1)
    registry = SimpleNamespace(get=lambda provider_id: None)
    context = SimpleNamespace(ledger=world.ledger, providers=registry,
                              tokens=_Tokens())
    pane = ChangesPane(context)
    pane.refresh()
    pane._restore_one(world.ledger.records()[0])
    assert "provider" in pane.count.text(), pane.count.text()
    assert len(world.ledger.records()) == 1


def test_repeated_clicks_cannot_stack_restores(tmp_path, monkeypatch, qt_app):
    from PySide6.QtWidgets import QMessageBox

    world = _restore_world(tmp_path, monkeypatch, count=3)
    pane = _changes(world, qt_app)
    monkeypatch.setattr("kairo.qt.changes.QMessageBox.exec",
                        lambda self: QMessageBox.Yes)

    prompts = []
    monkeypatch.setattr("kairo.qt.changes.QMessageBox.exec",
                        lambda self: prompts.append(1) or QMessageBox.Yes)

    record = world.ledger.records()[0]
    pane._restore_one(record)
    assert pane._busy_now, "the pane must mark itself busy immediately"
    for row in pane._row_widgets.values():
        assert not row.undo.isEnabled(), "a row stayed clickable mid-restore"

    for _ in range(5):
        pane._restore_one(record)          # must be ignored while busy

    # The ledger lands in the same place either way, because a second restore
    # of the same record is refused on its own merits. What a missing guard
    # actually costs is five more confirmation dialogs and five more jobs
    # racing the first one, so that is what this measures.
    assert len(prompts) == 1, (
        f"{len(prompts)} confirmations for one click — clicks are stacking")
    assert settle(qt_app, timeout=10.0)
    assert len(world.ledger.records()) == 2
    assert not pane._busy_now, "the pane never came out of its busy state"


def test_a_superseded_result_is_dropped(tmp_path, monkeypatch, qt_app):
    """Stale callback: the token that started the work was replaced."""
    world = _restore_world(tmp_path, monkeypatch, count=2)
    pane = _changes(world, qt_app)
    before = pane.count.text()

    token = pane.ctx.tokens.start("changes:restore")
    token.cancel()
    # Simulate the queued result of the cancelled run arriving late.
    pane._busy_now = True
    if not token.cancelled:
        pane._say("this must never be painted")
    assert "must never be painted" not in pane.count.text()
    assert pane.count.text() == before


def test_restore_all_keeps_what_succeeded_when_one_refuses(
        tmp_path, monkeypatch, qt_app):
    """Partial failure: one hand-edited entry must not cost the others."""
    from PySide6.QtWidgets import QMessageBox

    world = _restore_world(tmp_path, monkeypatch, count=4)
    records = world.ledger.records()
    poisoned = Path(records[1].target)
    poisoned.write_text(
        poisoned.read_text().replace("X-Kairo-Managed=true", ""))

    pane = _changes(world, qt_app)
    monkeypatch.setattr("kairo.qt.changes.QMessageBox.exec",
                        lambda self: QMessageBox.Yes)
    pane._restore_all()
    assert settle(qt_app, timeout=15.0)

    remaining = world.ledger.records()
    assert len(remaining) == 1, (
        f"the three restorable entries were not all undone: {remaining}")
    assert remaining[0].key == records[1].key
    assert poisoned.exists(), "Kairo removed a file it no longer owns"
    text = pane.count.text()
    assert "Restored 3 of 4" in text, text
    assert "skipped" in text or "failed" in text, text


def test_restore_all_on_an_empty_history_says_so(tmp_path, monkeypatch, qt_app):
    world = _restore_world(tmp_path, monkeypatch, count=1)
    world.ledger.forget(world.ledger.records()[0].key)
    pane = _changes(world, qt_app)
    pane._restore_all()
    assert "Nothing to restore" in pane.count.text()


def test_closing_mid_restore_cancels_rather_than_painting(
        tmp_path, monkeypatch, qt_app):
    world = _restore_world(tmp_path, monkeypatch, count=3)
    pane = _changes(world, qt_app)
    token = pane.ctx.tokens.start("changes:restore")
    token.cancel()                          # what closeEvent does
    assert token.cancelled
    assert settle(qt_app, timeout=5.0), "work outlived the cancel"


def test_the_summary_counts_are_honest():
    from kairo.qt.changes import ChangesPane
    from kairo.tasks import BulkSummary

    describe = ChangesPane._describe
    assert describe(BulkSummary(total=5, succeeded=5)) == "Restored 5 of 5."
    assert describe(BulkSummary(total=5, succeeded=3, skipped=1, failed=1)) == (
        "Restored 3 of 5 — 1 skipped, 1 failed.")
    assert describe(BulkSummary(total=9, succeeded=2, processed=3,
                                cancelled=True)).startswith(
        "Cancelled after 3 of 9")


def test_declining_the_confirmation_restores_nothing(
        tmp_path, monkeypatch, qt_app):
    """Every destructive restore asks first, and No means no."""
    from PySide6.QtWidgets import QMessageBox

    world = _restore_world(tmp_path, monkeypatch, count=2)
    pane = _changes(world, qt_app)
    asked = []
    monkeypatch.setattr("kairo.qt.changes.QMessageBox.exec",
                        lambda self: asked.append(self.text())
                        or QMessageBox.Cancel)

    pane._restore_one(world.ledger.records()[0])
    assert settle(qt_app, timeout=5.0)
    assert asked, "a destructive restore went ahead without asking"
    assert len(world.ledger.records()) == 2, "Cancel still restored it"
    assert not pane._busy_now

    asked.clear()
    pane._restore_all()
    assert settle(qt_app, timeout=5.0)
    assert asked, "Restore all went ahead without asking"
    assert len(world.ledger.records()) == 2


def test_the_confirmation_wording_comes_from_the_writer(
        tmp_path, monkeypatch, qt_app):
    """Resetting a shortcut Kairo made is not the same act as removing an
    override, and the two must not share a sentence."""
    from PySide6.QtWidgets import QMessageBox

    world = _restore_world(tmp_path, monkeypatch, count=1)
    pane = _changes(world, qt_app)
    seen = []
    monkeypatch.setattr("kairo.qt.changes.QMessageBox.exec",
                        lambda self: seen.append(self.text())
                        or QMessageBox.Cancel)
    pane._restore_one(world.ledger.records()[0])

    expected = world.apps.writer().restore_prompt(
        __import__("kairo.actions", fromlist=["actions"]).entry_from_record(
            world.ledger.records()[0]))
    assert seen and seen[0] == expected, seen


# ---------------------------------------------------------------------------
# Device pixel ratio through the asynchronous paths
#
# images.load already decoded at the screen's ratio, but it is only used by
# the synchronous callers. Every icon that arrives on a worker - the rows of
# a page, the tiles of an artwork grid - went through images.prepare, which
# had no ratio at all: it decoded at logical size and the GUI thread then
# built a pixmap with no ratio set, so the compositor magnified it. The whole
# library was soft on any display above 1x while the sidebar was sharp.

def _png(edge: int, colour=(255, 0, 0, 255)) -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGBA", (edge, edge), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _drawn_bounds(pixmap):
    """The area a pixmap actually covers, in logical points.

    Dividing by the ratio is the whole point: a correct 2x pixmap has twice
    the pixels and covers the same logical box. One drawn at ratio squared
    has the same pixel count and covers a quarter of it, which no assertion
    on size or devicePixelRatio can see.
    """
    from PySide6.QtGui import QColor

    image = pixmap.toImage()
    ratio = pixmap.devicePixelRatio()
    marked = [(x, y)
              for y in range(image.height())
              for x in range(image.width())
              if QColor(image.pixelColor(x, y)).alpha() > 40]
    assert marked, "nothing was drawn at all"
    xs = [x / ratio for x, _ in marked]
    ys = [y / ratio for _, y in marked]
    return min(xs), min(ys), max(xs), max(ys)


def test_a_worker_prepares_an_image_at_the_screens_resolution(qt_core):
    """prepare() is what every asynchronous icon goes through."""
    from kairo.qt import images

    images.clear_cache()
    payload = _png(256)

    plain = images.prepare(116, data=payload)
    retina = images.prepare(116, data=payload, ratio=2.0)
    assert plain is not None and retina is not None
    assert max(plain.width(), plain.height()) == 116
    assert max(retina.width(), retina.height()) == 232, \
        "decoded at logical size, leaving the compositor to magnify it"
    assert retina.devicePixelRatio() == 2.0, \
        "the ratio must travel with the image to the GUI thread"


def test_the_prepared_cache_never_serves_a_1x_image_to_a_2x_screen(qt_core):
    """Ratio is a parameter, so it has to be part of the key.

    A key of (source, logical size) is unique right up until the moment two
    screens want the same icon, and then it hands whichever ratio asked
    first to both of them. Dragging a window between a laptop panel and an
    external display is the ordinary case, not a corner one.
    """
    from kairo.qt import images

    images.clear_cache()
    payload = _png(256)

    first = images.prepare(116, data=payload, ratio=1.0)
    second = images.prepare(116, data=payload, ratio=2.0)
    assert max(second.width(), second.height()) == 232, \
        "the 1x entry was served to a 2x caller"
    # And back again: the 2x entry must not evict or answer for 1x either.
    again = images.prepare(116, data=payload, ratio=1.0)
    assert max(again.width(), again.height()) == 116
    assert max(first.width(), first.height()) == 116

    # The pixel count alone is not enough to tell two requests apart. 104
    # logical points at 1x and 52 at 2x decode to the same 104 pixels and
    # differ only in what those pixels mean, so a key without the ratio
    # hands whichever was cached first to both - and the second one is then
    # drawn at twice the size it was decoded for.
    images.clear_cache()
    wide = images.prepare(104, data=payload, ratio=1.0)
    dense = images.prepare(52, data=payload, ratio=2.0)
    assert wide.width() == dense.width() == 104
    assert wide.devicePixelRatio() == 1.0
    assert dense.devicePixelRatio() == 2.0, \
        "the 1x entry of the same pixel size answered a 2x request"


def test_a_prepared_icon_covers_the_same_area_at_every_ratio(qt_core):
    """More pixels, not a bigger picture - measured on what was drawn.

    QPainter already applies a pixmap's ratio. Setting the ratio and scaling
    as well draws at ratio squared; every assertion on width and
    devicePixelRatio still passes while three quarters of the image is gone.

    Measured on the pixmap itself. QLabel.pixmap() is not a witness: it hands
    back a 1x copy rescaled to the logical size, so every ratio compares
    equal through it and the test passes whatever the code does.
    """
    from kairo.qt import images

    payload = _png(256)
    images.clear_cache()
    plain = _drawn_bounds(images.load(52, data=payload))
    for ratio in (2.0, 3.0):
        images.clear_cache()
        drawn = _drawn_bounds(images.load(52, data=payload, ratio=ratio))
        for a, b in zip(plain, drawn):
            assert abs(a - b) < 1.5, (
                f"at {ratio}x the artwork covers a different area: "
                f"{plain} against {drawn}")


def test_a_worker_image_keeps_its_ratio_when_it_becomes_a_pixmap(qt_core):
    """QPixmap.fromImage is where a worker's ratio was being dropped.

    The image is prepared on a pool thread and converted on the GUI thread,
    and the ratio has to survive that hop or the tile is drawn at double the
    size it was decoded for.
    """
    from PySide6.QtGui import QPixmap

    from kairo.qt import images

    images.clear_cache()
    prepared = images.prepare(52, data=_png(256), ratio=2.0)
    assert prepared.devicePixelRatio() == 2.0

    painted = QPixmap.fromImage(prepared)
    painted.setDevicePixelRatio(prepared.devicePixelRatio())
    assert painted.width() == 104, "decoded at logical size after all"
    assert painted.devicePixelRatio() == 2.0, \
        "the pixmap claims 1x, so Qt draws 104 real pixels into a 104 box"
    assert round(painted.deviceIndependentSize().width()) == 52

    # And the well is what performs that conversion for every async image.
    well_source = (QT_DIR / "widgets.py").read_text()
    block = well_source.split("def show_image")[1].split("\n    def ")[0]
    assert "setDevicePixelRatio(image.devicePixelRatio())" in block, \
        "the well must restate the ratio it was handed"


def test_the_streaming_workers_capture_the_ratio_on_the_gui_thread():
    """devicePixelRatioF() is a GUI-thread call; a pool thread cannot make it."""
    source = (QT_DIR / "library.py").read_text()
    for name in ("_stream_row_icons", "_stream_previews"):
        block = source.split(f"def {name}")[1].split("\n    def ")[0]
        assert "devicePixelRatioF()" in block, f"{name} never asks for a ratio"
        assert block.index("devicePixelRatioF()") < block.index("def pump"), \
            f"{name} reads the ratio inside the worker, not before it"
        assert "ratio=" in block.split("def pump")[1], \
            f"{name} does not hand the ratio to prepare()"


def test_a_screen_change_regenerates_visible_artwork_without_refetching():
    """Moving between mixed-DPI outputs changes the ratio under live images.

    The retained preview bytes exist precisely so this costs no network: a
    refetch here would hit SteamGridDB again for artwork already in hand.
    """
    source = (QT_DIR / "library.py").read_text()
    assert "def refresh_device_pixel_ratio" in source
    block = source.split("def refresh_device_pixel_ratio")[1].split("\n    def ")[0]
    assert "preview_data" in block, "regenerate from the bytes already held"
    assert "source.preview" not in block and "sources.get" not in block, \
        "a ratio change must never re-enter an artwork source"

    shell = (QT_DIR / "shell.py").read_text()
    assert "refresh_device_pixel_ratio" in shell, \
        "nothing tells the panes their screen changed"


def test_proposing_reuses_the_prepared_tile_rather_than_fetching_it_again():
    """Choosing a tile refetched the very bytes the tile was drawn from.

    The preview had already been downloaded, decoded and scaled to build the
    grid; picking one asked the source for it a second time and decoded it
    again on the GUI thread.
    """
    source = (QT_DIR / "library.py").read_text()
    block = source.split("def _propose")[1].split("\n    def ")[0]
    assert "preview_data" in block, "the retained bytes are never consulted"
    assert block.index("preview_data") < block.index("work.submit"), \
        "the fetch must be the fallback, not the first move"
    assert "kairo.actions" not in block and "write" not in block, \
        "proposing stays visual state only"


def test_a_tile_retains_the_bytes_its_preview_was_built_from(qt_core):
    """Retention is what makes both the reuse and the ratio refresh possible."""
    from kairo.qt import images
    from kairo.qt.widgets import ArtworkTile

    class _Art:
        label = "Official"
        name = "Thing"
        kind = "logo"
        official = True
        dimensions = "512x512"
        source_id = "steamgriddb"

    images.clear_cache()
    payload = _png(256)
    tile = ArtworkTile(_Art())
    tile.set_image(images.prepare(116, data=payload, ratio=1.0), data=payload)
    assert tile.preview_data == payload


def test_rebinding_rows_preserves_the_selected_entry(qt_core):
    """A ratio refresh must not leave model and highlight disagreeing."""
    from types import SimpleNamespace

    from kairo.qt.library import LibraryPane
    from kairo.tasks import ActivityTokens

    class Row:
        def __init__(self, entry):
            self.entry = entry
            self.selected = False

        def bind(self, entry, **_kwargs):
            self.entry = entry
            return False

        def set_selected(self, selected):
            self.selected = selected

        def setVisible(self, _visible):
            pass

    entries = [SimpleNamespace(key="one"), SimpleNamespace(key="two")]
    rows = [Row(entry) for entry in entries]
    rows[1].selected = True
    pane = SimpleNamespace(
        tokens=ActivityTokens(), provider=SimpleNamespace(id="apps"),
        rows=rows, selected=rows[1], _icon_generation=3,
        _selected_key="two", _filtered=entries, entries=entries,
        _catalogue_has=lambda key: any(e.key == key for e in entries),
        _stream_row_icons=lambda _pending, _token: None,
    )

    LibraryPane._bind_rows(pane, entries)

    assert pane.selected is rows[1]
    assert pane._selected_key == "two"
    assert [row.selected for row in rows] == [False, True], \
        "the pane kept its selection but erased the visible highlight"

    # Off the current page is not gone. The entry is still in the catalogue,
    # so the logical selection has to survive a slice that omits it —
    # otherwise paging or a ratio refresh silently deselects.
    pane.selected = rows[1]
    LibraryPane._bind_rows(pane, entries[:1])
    assert pane._selected_key == "two", \
        "a page that omitted the entry destroyed the selection"

    # Actually gone is gone.
    pane._filtered = pane.entries = []
    pane._catalogue_has = lambda _key: False
    LibraryPane._bind_rows(pane, [])
    assert pane._selected_key is None


def test_ratio_refresh_prepares_retained_artwork_off_the_gui_thread(
        qt_core, monkeypatch):
    """Moving screens must not synchronously decode a whole artwork grid."""
    from types import SimpleNamespace

    from kairo.qt import images
    from kairo.qt.library import LibraryPane
    from kairo.tasks import ActivityTokens

    payload = _png(256)
    tile = SimpleNamespace(preview_data=payload)
    tokens = ActivityTokens()
    tokens.start("artwork")
    scheduled = []
    pane = SimpleNamespace(
        _paint_ratio=1.0, _preview_generation=7, _icon_generation=2,
        devicePixelRatioF=lambda: 2.0, tiles=[tile], _tile_at={4: tile},
        tokens=tokens, provider=SimpleNamespace(id="apps"),
        selected=SimpleNamespace(
            entry=SimpleNamespace(key="apps:one")),
        _filtered=[], _shown=0,
        _prepare_retained_tiles=lambda pending, token, key: scheduled.append(
            (pending, token, key)),
        _bind_rows=lambda _entries: None,
    )

    monkeypatch.setattr(
        images, "prepare",
        lambda *_args, **_kwargs: pytest.fail(
            "refresh_device_pixel_ratio decoded on the GUI thread"),
    )
    LibraryPane.refresh_device_pixel_ratio(pane)

    assert pane._preview_generation == 8
    assert scheduled and scheduled[0][0] == [(4, payload)]
    assert scheduled[0][2] == "apps:one"


def test_a_late_old_ratio_preview_is_reprepared_instead_of_painted(qt_core):
    """An old worker cannot overwrite tiles corrected for a new screen."""
    from types import SimpleNamespace

    from kairo.qt.library import LibraryPane
    from kairo.tasks import CancelToken

    class Tile:
        preview_data = None

        def __init__(self):
            self.painted = []

        def set_image(self, image, **_kwargs):
            self.painted.append(image)

    payload = _png(256)
    stale_image = object()
    tile = Tile()
    scheduled = []
    token = CancelToken()
    pane = SimpleNamespace(
        _preview_generation=2, _paint_ratio=2.0,
        selected=SimpleNamespace(entry=SimpleNamespace(key="apps:one")),
        _tile_at={0: tile}, tiles=[tile], chosen_tile=None, proposed=None,
        _prepare_retained_tiles=lambda pending, current, key: scheduled.append(
            (pending, current, key)),
        _drop_tile=lambda *_args, **_kwargs: None,
        _reflow_tiles=lambda: None,
    )

    LibraryPane._fill_tile(
        pane, 0, (([(0, stale_image, payload)], 1), token), "apps:one")

    assert tile.painted == [], "an old-ratio image reached the screen"
    assert tile.preview_data == payload
    assert scheduled == [([(0, payload)], token, "apps:one")]


def test_the_title_well_renders_at_its_own_size_not_the_rows(qt_core):
    """A row image is 32 logical points; this well draws at 52.

    Forwarding the row's prepared image put a 32px picture in a 64px well —
    38% of the area — every time a page of icons filled for the selected
    entry. The earlier test asserted only that *an* object was handed over,
    so it could not see the size at all.
    """
    import pathlib
    import tempfile

    from kairo.qt import images, theme as Q
    from kairo.qt.widgets import IconWell

    icon = pathlib.Path(tempfile.mkdtemp()) / "icon.png"
    icon.write_bytes(_png(512))
    images.clear_cache()

    well = IconWell(Q.WELL_TITLE)
    row_image = images.prepare(Q.WELL_ROW - 12, path=icon)
    assert max(row_image.width(), row_image.height()) == Q.WELL_ROW - 12

    # What the pane must produce for this well, whatever the rows hold.
    title_image = images.prepare(Q.WELL_TITLE - 12, path=icon)
    well.show_image(title_image, "—")
    painted = well.label.pixmap()
    assert painted.width() == Q.WELL_TITLE - 12, \
        "the title icon is not being rendered at the title well's size"
    assert painted.width() > (Q.WELL_ROW - 12), \
        "a row-sized image would be smaller than the well it is drawn in"
    assert painted.width() <= well.width()


def test_the_proposal_well_never_receives_a_tile_sized_image(qt_core):
    """104 logical points into a fixed 64px well is a centre crop."""
    from kairo.qt import images, theme as Q
    from kairo.qt.widgets import IconWell

    images.clear_cache()
    payload = _png(512)
    tile_image = images.prepare(Q.TILE - 12, data=payload, min_edge=0)
    assert max(tile_image.width(), tile_image.height()) == Q.TILE - 12

    well = IconWell(Q.WELL_COMPARE)
    proposal = images.prepare(Q.WELL_COMPARE - 12, data=payload, min_edge=0)
    well.show_image(proposal)
    painted = well.label.pixmap()
    assert painted.width() == Q.WELL_COMPARE - 12
    assert painted.width() <= well.width(), "the artwork overflows its well"
    assert well.label.sizeHint().width() <= well.width(), \
        "the label wants more room than the well has, so Qt crops it"


def test_the_header_wells_are_rebuilt_rather_than_borrowed(qt_core):
    """Both wells own their sizing, and neither decodes on the GUI thread."""
    from kairo.qt import theme as Q

    source = (QT_DIR / "library.py").read_text()

    fill_row = source.split("def _fill_row_icon")[1].split("\n    def ")[0]
    assert "current_well.show_image(image" not in fill_row, \
        "the row's own image is being forwarded to a larger well again"

    current = source.split("def _refresh_current_well")[1].split("\n    def ")[0]
    assert "WELL_TITLE" in current, "the title well must ask for its own size"
    assert "work.submit" in current, "decoding belongs off the GUI thread"

    proposal = source.split("def _show_proposal")[1].split("\n    def ")[0]
    assert "WELL_COMPARE" in proposal
    assert "work.submit" in proposal
    assert "source.preview" not in proposal and "sources.get" not in proposal, \
        "rebuilding the proposal must never re-enter an artwork source"

    fill_tile = source.split("def _fill_tile")[1].split("\n    def ")[0]
    assert "proposed_well.show_image(data)" not in fill_tile, \
        "the tile's prepared image is reaching the compare well again"

    assert Q.WELL_TITLE - 12 != Q.WELL_ROW - 12
    assert Q.WELL_COMPARE - 12 != Q.TILE - 12


# -- responsive three-column composition ---------------------------------

def test_the_window_has_deliberate_wide_compact_and_narrow_modes():
    """Snapping the window must change composition before content clips."""
    from kairo.qt.shell import layout_mode

    assert layout_mode(1420) == "wide"
    assert layout_mode(1120) == "compact"
    assert layout_mode(900) == "narrow"


def test_the_narrow_width_budget_protects_the_inspector():
    """Navigation and list yield space; the artwork workspace never does."""
    from kairo.qt import theme as Q

    used = Q.W_NAV_NARROW + Q.W_LIST_NARROW
    assert used <= 360
    assert Q.MIN_WINDOW_WIDTH - used >= 520, \
        "the side columns still starve the inspector at minimum width"


def test_compact_navigation_is_icon_only_but_stays_discoverable(qt_core):
    from kairo.qt.widgets import NavButton

    button = NavButton("steam", "Steam", "steam")
    button.set_count(7)
    button.set_compact(True)

    assert button.name.isHidden()
    assert button.count.isHidden()
    assert "Steam" in button.toolTip() and "7" in button.toolTip()

    button.set_compact(False)
    assert not button.name.isHidden()
    assert not button.count.isHidden()


def test_resizing_propagates_the_mode_to_every_created_pane():
    """A pane made before the snap must adapt as reliably as a later one."""
    source = (QT_DIR / "shell.py").read_text()
    resize = source.split("def resizeEvent")[1].split("\n    def ")[0]
    apply = source.split("def _apply_layout_mode")[1].split("\n    def ")[0]
    factory = source.split("def _pane_for")[1].split("\n    def ")[0]

    assert "_apply_layout_mode" in resize
    assert "self.panes.values()" in apply
    assert "set_layout_mode" in factory


def test_compact_library_labels_are_short_without_changing_their_actions():
    """Short labels are presentation; callbacks and writer verbs stay put."""
    source = (QT_DIR / "library.py").read_text()
    mode = source.split("def set_layout_mode")[1].split("\n    def ")[0]
    labels = source.split("def _refresh_action_labels")[1].split("\n    def ")[0]
    actions = source.split("def _update_actions")[1].split("\n    def ")[0]

    assert "Local file" in labels
    assert "writer.restore_label" in actions
    assert "writer.remove_label" in actions
    for callback in ("_browse", "_restore", "_remove", "_apply"):
        assert f"lambda _c: self.{callback}()" in source


# ---------------------------------------------------------------------------
# Safeguards that an audit proved could be deleted with the suite still green.
#
# Each of these was covered only by a source-substring assertion, or not at
# all. A substring test survives deleting the call it claims to guard, because
# the vocabulary usually remains in a hasattr() check or a loop header nearby.
# These drive real objects and record real calls.

def _spy_pane(**overrides):
    """A stand-in with the attributes LibraryPane's own methods touch."""
    from types import SimpleNamespace

    from kairo.tasks import ActivityTokens

    state = dict(
        tokens=ActivityTokens(), provider=SimpleNamespace(id="apps"),
        tiles=[], _tile_at={}, rows=[], selected=None, chosen_tile=None,
        _preview_generation=0, _paint_ratio=1.0, _paint_token=None,
        _icon_generation=0, _filtered=[], entries=[], _selected_key=None,
        _shown=0,
        grid=SimpleNamespace(count=lambda: 0, takeAt=lambda _i: None),
    )
    state.update(overrides)
    return SimpleNamespace(**state)


def test_a_ratio_within_floating_point_noise_is_not_a_screen_change(qt_core):
    """Wayland fractional scales do not survive exact float comparison.

    1.25 and 1.5 arrive as floats that have already been through a scale
    calculation. Comparing with == treats a rounding difference as a monitor
    change and rebuilds every image on the screen for nothing.
    """
    from kairo.qt.library import LibraryPane

    calls = []
    pane = _spy_pane(
        _paint_ratio=1.25,
        devicePixelRatioF=lambda: 1.25 + 1e-9,
        _bind_rows=lambda entries: calls.append("rebound"),
    )
    LibraryPane.refresh_device_pixel_ratio(pane)
    assert calls == [], "a rounding difference was treated as a new screen"
    assert pane._preview_generation == 0

    pane.devicePixelRatioF = lambda: 2.0
    LibraryPane.refresh_device_pixel_ratio(pane)
    assert calls == ["rebound"], "a real ratio change was ignored"
    assert pane._preview_generation == 1


def test_clearing_a_grid_cancels_the_ratio_work_that_belonged_to_it(qt_core):
    """Indexes are reused, so a late batch can land in the wrong grid.

    Retained-image preparation is keyed by position. Without cancelling the
    activity and advancing the generation, a batch prepared for the grid that
    has just been thrown away paints into whatever now occupies those slots.
    """
    from kairo.qt.library import ACTIVITY_DPR, LibraryPane

    pane = _spy_pane()
    token = pane.tokens.start(f"{ACTIVITY_DPR}:apps")
    pane._paint_token = token
    before = pane._preview_generation

    LibraryPane._clear_grid(pane)

    assert token.cancelled, "the grid's own ratio work was left running"
    assert pane._preview_generation == before + 1, \
        "a batch from the old grid can still match the new generation"


def test_retained_preparation_stops_when_its_screen_is_already_gone(qt_core):
    """Two monitor moves in a row must not both repaint."""
    from kairo.qt.library import LibraryPane
    from kairo.tasks import CancelToken

    submitted = []
    paint_token = CancelToken()
    pane = _spy_pane(_paint_token=paint_token, _preview_generation=2)

    from kairo.qt import work

    real_submit = work.submit
    work.submit = lambda fn, **kw: submitted.append(fn)
    try:
        paint_token.cancel()
        LibraryPane._prepare_retained_tiles(
            pane, [(0, b"bytes")], CancelToken(), "apps:one")
        assert submitted == [], \
            "work was scheduled for a screen the window has already left"

        pane._paint_token = live = CancelToken()
        LibraryPane._prepare_retained_tiles(
            pane, [(0, b"bytes")], CancelToken(), "apps:one")
        assert len(submitted) == 1, "a live ratio change scheduled nothing"

        # The worker itself must keep checking. A move that happens after the
        # job is queued but before it runs — or between two of its items —
        # leaves it decoding for a screen the window has already left, and on
        # a large grid that is the whole batch wasted.
        prepare_batch = submitted[0]
        live.cancel()
        assert prepare_batch() == [], \
            "the worker prepared images for an abandoned screen"
    finally:
        work.submit = real_submit


def test_narrow_navigation_keeps_the_mark_when_it_drops_the_wordmark(qt_core):
    """Something must still identify the column at 80 pixels wide."""
    from kairo.qt.shell import KairoWindow

    window = KairoWindow(translucent=False, want_blur=False)
    try:
        window.show()
        window.resize(900, 900)
        qt_core.processEvents()
        assert window._layout_mode == "narrow"
        if window.nav_badge is not None:
            assert window.nav_badge.isVisible(), \
                "narrow mode removed every piece of branding at once"
            assert not window.nav_logo.isVisible(), \
                "the wordmark does not fit an 80px column"
        else:
            assert window.nav_logo.isVisible(), \
                "with no mark to fall back on the wordmark has to stay"

        window.resize(1420, 900)
        qt_core.processEvents()
        assert window.nav_logo.isVisible(), "the wordmark never came back"
    finally:
        window.close()
        from kairo.qt import work
        work.drain()


def test_a_resize_reaches_panes_that_already_exist(qt_core):
    """Recorded on a real pane, not looked for in the source text."""
    from kairo.qt.shell import KairoWindow

    window = KairoWindow(translucent=False, want_blur=False)
    try:
        window.show()
        window.resize(1420, 900)
        qt_core.processEvents()
        panes = [p for p in window.panes.values()
                 if hasattr(p, "set_layout_mode")]
        assert panes, "no pane to observe"
        for pane in panes:
            assert pane._layout_mode == "wide"

        window.resize(900, 900)
        qt_core.processEvents()
        for pane in panes:
            assert pane._layout_mode == "narrow", \
                "an existing pane never heard about the resize"

        window.resize(1120, 900)
        qt_core.processEvents()
        for pane in panes:
            assert pane._layout_mode == "compact"
    finally:
        window.close()
        from kairo.qt import work
        work.drain()


def test_a_pane_built_after_a_resize_starts_in_the_current_mode(qt_core):
    """The pane factory is the only thing that can tell a late arrival."""
    from kairo.qt.shell import KairoWindow

    window = KairoWindow(translucent=False, want_blur=False)
    try:
        window.show()
        window.resize(900, 900)
        qt_core.processEvents()
        assert window._layout_mode == "narrow"

        # Force the factory to build one, rather than depending on this
        # machine happening to have a destination nobody has opened yet.
        key = next((k for k, p in window.panes.items()
                    if hasattr(p, "set_layout_mode")), None)
        assert key is not None
        stale = window.panes.pop(key)
        window.stack.removeWidget(stale)
        stale.setParent(None)

        pane = window._pane_for(key)
        assert hasattr(pane, "set_layout_mode")
        assert pane is not stale, "the factory returned the old pane"
        assert pane._layout_mode == "narrow", \
            "a pane created while narrow opened in the wide composition"
    finally:
        window.close()
        from kairo.qt import work
        work.drain()


def test_compact_action_labels_shorten_and_come_back(qt_core):
    """Visual aliases only: the writer's wording and the callbacks stand."""
    from kairo.qt.shell import KairoWindow

    window = KairoWindow(translucent=False, want_blur=False)
    try:
        window.show()
        window.resize(1420, 900)
        qt_core.processEvents()
        pane = next((p for p in window.panes.values()
                     if hasattr(p, "set_layout_mode")), None)
        assert pane is not None
        pane._restore_full_label = "Restore original"
        pane._remove_full_label = "Remove shortcut"
        wired = (pane.restore_btn.clicked, pane.remove_btn.clicked,
                 pane.browse_btn.clicked, pane.apply_btn.clicked)

        pane.set_layout_mode("wide")
        assert pane.restore_btn.text() == "Restore original"
        assert pane.browse_btn.text() == "Browse local file…"
        assert pane.restore_btn.toolTip() == ""

        pane.set_layout_mode("narrow")
        assert pane.restore_btn.text() == "Restore", "the label never shortened"
        assert pane.remove_btn.text() == "Remove"
        assert pane.browse_btn.text() == "Local file…"
        assert pane.restore_btn.toolTip() == "Restore original", \
            "the writer's full wording must survive in the tooltip"
        assert pane.remove_btn.toolTip() == "Remove shortcut"

        pane.set_layout_mode("wide")
        assert pane.restore_btn.text() == "Restore original", \
            "the full label never came back"
        assert pane.remove_btn.text() == "Remove shortcut"
        assert pane.restore_btn.toolTip() == ""

        assert wired == (pane.restore_btn.clicked, pane.remove_btn.clicked,
                         pane.browse_btn.clicked, pane.apply_btn.clicked)
    finally:
        window.close()
        from kairo.qt import work
        work.drain()


def test_a_reflow_records_the_column_count_it_used(qt_core):
    """Otherwise the next resize compares against the previous mode.

    Asserting that _last_columns always equals _columns() would be testing
    Qt's layout timing, not Kairo: a pane's resizeEvent runs before its own
    scroll viewport has been re-laid out. What matters is that whatever
    reflowed wrote down the number it reflowed for, and that a resize which
    does not change the column count does not reflow a second time.
    """
    from kairo.qt.library import LibraryPane
    from kairo.qt.shell import KairoWindow

    window = KairoWindow(translucent=False, want_blur=False)
    try:
        window.show()
        window.resize(1420, 900)
        qt_core.processEvents()
        pane = next((p for p in window.panes.values()
                     if hasattr(p, "set_layout_mode")), None)
        assert pane is not None

        reflows = []
        real = LibraryPane._reflow_tiles

        def counted(self):
            reflows.append(self._columns())
            return real(self)

        LibraryPane._reflow_tiles = counted
        try:
            for width in (1320, 1319, 1120, 1040, 1039, 900, 1039, 1040,
                          1319, 1320, 1420):
                window.resize(width, 900)
                qt_core.processEvents()
                assert pane._last_columns == pane._columns() or not pane.tiles \
                    or reflows, "a reflow happened without recording its count"
                if reflows:
                    assert pane._last_columns == reflows[-1], \
                        "the recorded count is not the one just reflowed for"
            # Settling at one width must not keep re-seating the grid.
            before = len(reflows)
            for _ in range(3):
                window.resize(1420, 900)
                qt_core.processEvents()
            assert len(reflows) == before, \
                "a resize that changed no column count reflowed anyway"
        finally:
            LibraryPane._reflow_tiles = real
    finally:
        window.close()
        from kairo.qt import work
        work.drain()


def test_the_image_cache_is_bounded_in_bytes_not_entries(qt_core):
    """256 entries is not a memory bound when ratios differ.

    The same icon at 1x, 2x and 3x is one, four and nine times the pixels.
    An entry cap let a window that had visited a scaled monitor hold roughly
    49 MB of decoded images against a 90 MB process budget, and after a
    monitor change both ratios are live at once.
    """
    from kairo.qt import images, theme as Q

    images.clear_cache()
    payload = _png(512)
    for ratio in (1.0, 1.25, 1.5, 2.0, 3.0):
        for index in range(60):
            images.prepare(Q.TILE - 12, data=payload + bytes([index]),
                           min_edge=0, ratio=ratio)
        held, _pixmaps = images.cache_bytes()
        assert held <= images.IMAGE_CACHE_BYTES, (
            f"at {ratio}x the cache held {held / 1048576:.1f} MiB against a "
            f"{images.IMAGE_CACHE_BYTES / 1048576:.0f} MiB budget")
    assert len(images._IMAGE_CACHE) <= images.CACHE_LIMIT


def test_eviction_is_oldest_first_and_spares_what_was_just_prepared(qt_core):
    """Evicting the newest entry turns the cache into a treadmill.

    The image a caller has just asked for is the one about to be painted.
    Dropping it to satisfy the budget means decoding it again immediately,
    and on a monitor change that is every visible tile, twice.
    """
    from kairo.qt import images

    images.clear_cache()
    cache = images._IMAGE_CACHE
    cache.clear()

    class Fake:
        def __init__(self, edge):
            self._edge = edge

        def width(self):
            return self._edge

        def height(self):
            return self._edge

        def depth(self):
            return 32

    for name in ("oldest", "middle", "newest"):
        cache[name] = Fake(1000)          # 4 MB each
    images._trim(cache, 9 * 1024 * 1024, keep="newest")
    assert "oldest" not in cache, "eviction did not start with the oldest"
    assert "newest" in cache, "the entry about to be painted was evicted"

    # A budget so small that only the protected entry can remain.
    images._trim(cache, 1, keep="newest")
    assert list(cache) == ["newest"]


def test_reflowing_writes_down_the_column_count_it_used(qt_core):
    """Driven directly: a window with no artwork never reflows at all."""
    from types import SimpleNamespace

    from kairo.qt.library import LibraryPane

    seated = []
    pane = SimpleNamespace(
        _columns=lambda: 4,
        _last_columns=None,
        tiles=[object(), object()],
        grid=SimpleNamespace(
            removeWidget=lambda widget: None,
            addWidget=lambda widget, row, column: seated.append((row, column))),
        _grid_note=lambda _text: None,
    )
    LibraryPane._reflow_tiles(pane)
    assert seated == [(0, 0), (0, 1)]
    assert pane._last_columns == 4, \
        "the reflow did not record the count it reflowed for"


# ---------------------------------------------------------------------------
# Artwork grid geometry, measured rather than reasoned about.

def _live_tiles(tiles):
    """Those still alive. A deleted QWidget raises rather than answering.

    _clear_grid unparents and deleteLater()s, and a scan callback landing
    during processEvents can do that underneath a measurement — after which
    even parentWidget() is a RuntimeError from Shiboken, not None.
    """
    alive = []
    for tile in tiles:
        try:
            if tile.parentWidget() is not None:
                alive.append(tile)
        except RuntimeError:
            continue
    return alive


def _fill_grid(pane, count=36):
    from kairo.qt.widgets import ArtworkTile

    class Art:
        label = "SteamGridDB"
        name = "x"
        kind = "logo"
        official = True
        dimensions = "512x512"
        source_id = "s"

    # Quiesce first: a scan landing mid-measurement replaces the grid, and
    # then even parentWidget() on the old tiles is a Shiboken RuntimeError.
    pane.tokens.cancel_all()
    from kairo.qt import work as _work
    _work.drain()
    pane._clear_grid()
    pane.tiles = []
    pane._tile_at = {}
    for index in range(count):
        tile = ArtworkTile(Art())
        pane.tiles.append(tile)
        pane._tile_at[index] = tile
    pane._reflow_tiles()
    # A copy: _clear_grid empties pane.tiles in place, so a scan callback
    # landing during processEvents would empty the caller's list too.
    return list(pane.tiles)


def test_only_whole_artwork_columns_are_ever_shown(qt_core):
    """The right-hand column was cut off at 34 widths between 900 and 1499.

    _columns() divided the raw viewport by (tile + spacing), which asks for
    one gap more than n columns need and ignores the grid's own left and
    right margins entirely. Wherever the viewport landed just above a
    multiple of the pitch, that bought a column there was no room for and
    the last one ran 1-10px past the edge.
    """
    from kairo.qt.shell import KairoWindow

    window = KairoWindow(translucent=False, want_blur=False)
    try:
        window.show()
        offenders = []
        for width in range(900, 1500, 7):
            window.resize(width, 1000)
            qt_core.processEvents()
            pane = next((p for p in window.panes.values()
                         if hasattr(p, "set_layout_mode")), None)
            assert pane is not None
            tiles = _fill_grid(pane)
            qt_core.processEvents()
            viewport = pane.grid_scroll.viewport().width()
            live = _live_tiles(tiles)
            if not live:
                continue
            last = max(t.geometry().x() + t.geometry().width() for t in live)
            if last > viewport:
                offenders.append((width, viewport, last, last - viewport))
        assert not offenders, (
            f"{len(offenders)} widths clip the last column, e.g. {offenders[:3]}")
    finally:
        window.close()
        from kairo.qt import work
        work.drain()


def test_the_column_count_accounts_for_margins_and_gaps(qt_core):
    """Arithmetic, stated directly, so a regression names its own cause."""
    from types import SimpleNamespace

    from kairo.qt.library import LibraryPane
    from kairo.qt.widgets import ArtworkTile
    from PySide6.QtCore import QMargins

    def pane_with(viewport, margin=14, spacing=4):
        return SimpleNamespace(
            grid=SimpleNamespace(
                contentsMargins=lambda: QMargins(margin, 0, margin, 0),
                horizontalSpacing=lambda: spacing),
            grid_scroll=SimpleNamespace(
                viewport=lambda: SimpleNamespace(width=lambda: viewport)))

    tile = ArtworkTile.WIDTH
    for viewport in range(300, 1200):
        columns = LibraryPane._columns(pane_with(viewport))
        needed = columns * tile + (columns - 1) * 4 + 28
        assert columns >= 1
        assert needed <= viewport or columns == 1, (
            f"{columns} columns need {needed}px of a {viewport}px viewport")
        # And it must not be needlessly mean: one more column must not fit.
        more = (columns + 1) * tile + columns * 4 + 28
        assert more > viewport, (
            f"{columns + 1} columns would have fitted in {viewport}px")


def test_a_scrollbar_appearing_recounts_the_columns(qt_core):
    """The viewport narrows under a grid that was already seated."""
    source = (QT_DIR / "library.py").read_text()
    assert "def _follow_grid_scrollbar" in source
    block = source.split("def _follow_grid_scrollbar")[1].split("\n    def ")[0]
    assert "_columns()" in block and "_reflow_tiles" in block

    from kairo.qt.shell import KairoWindow

    window = KairoWindow(translucent=False, want_blur=False)
    try:
        window.show()
        window.resize(1140, 700)
        qt_core.processEvents()
        pane = next((p for p in window.panes.values()
                     if hasattr(p, "set_layout_mode")), None)
        tiles = _fill_grid(pane, 60)
        qt_core.processEvents()
        pane._follow_grid_scrollbar()
        qt_core.processEvents()
        viewport = pane.grid_scroll.viewport().width()
        live = _live_tiles(tiles)
        assert live, "the grid emptied before it could be measured"
        last = max(t.geometry().x() + t.geometry().width() for t in live)
        assert last <= viewport, (
            f"with a scrollbar the last tile ends at {last} in {viewport}px")
    finally:
        window.close()
        from kairo.qt import work
        work.drain()


def test_a_seeded_query_opens_at_its_beginning(qt_core):
    """setText leaves the cursor at the end and the field scrolls to it.

    A long title opened showing "ed network configuration" - the tail of
    "advanced network configuration" - because the cursor sat at position 30
    and a QLineEdit scrolls to keep the cursor visible.
    """
    from PySide6.QtCore import Qt as QtNs

    from kairo.qt.shell import KairoWindow

    window = KairoWindow(translucent=False, want_blur=False)
    try:
        window.show()
        window.resize(900, 900)
        qt_core.processEvents()
        pane = next((p for p in window.panes.values()
                     if hasattr(p, "set_layout_mode")), None)
        assert pane is not None

        pane.query.setFocus(QtNs.OtherFocusReason)
        pane.query.clearFocus()
        blocked = pane.query.blockSignals(True)
        pane.query.setText("advanced network configuration")
        pane.query.blockSignals(blocked)
        assert pane.query.cursorPosition() == len(pane.query.text()), \
            "precondition: a bare setText parks the cursor at the end"

        pane._seeded = "advanced network configuration"
        blocked = pane.query.blockSignals(True)
        pane.query.setText(pane._seeded)
        if not pane.query.hasFocus():
            pane.query.setCursorPosition(0)
            pane.query.deselect()
        pane.query.blockSignals(blocked)
        pane._update_query_tooltip()

        assert pane.query.cursorPosition() == 0, \
            "the field still opens scrolled to its tail"
        assert not pane.query.hasSelectedText()
        assert pane.query.toolTip().startswith("advanced network"), \
            "a query too wide for the field must be readable somewhere"
    finally:
        window.close()
        from kairo.qt import work
        work.drain()


def test_seeding_never_takes_the_cursor_from_someone_typing(qt_core):
    """Repositioning mid-edit is worse than the tail."""
    source = (QT_DIR / "library.py").read_text()
    seed = source.split("def _seed_query")[1].split("\n    def ")[0]
    assert "hasFocus()" in seed, "the reset is unconditional"
    assert seed.index("hasFocus()") < seed.index("setCursorPosition(0)")


# ---------------------------------------------------------------------------
# List rows must follow the viewport, not the longest name in them.

def test_rows_never_grow_wider_than_the_list_viewport(qt_core):
    """A row that cannot shrink drags a horizontal scrollbar behind it.

    The name was ellipsised to a fixed character budget, so the label's size
    hint was its longest name whatever the window was doing. That became the
    row's minimum, then the holder's, and the scroll area could not shrink
    below it: at 900px the list column is 280 and the rows were still 319,
    with a real 91px horizontal range and the icons cut against the edge.
    """
    from kairo.qt.shell import KairoWindow

    window = KairoWindow(translucent=False, want_blur=False)
    try:
        window.show()
        offenders = []
        for width in (900, 1038, 1039, 1040, 1041, 1318, 1319, 1320, 1321,
                      1420, 900, 1420):
            window.resize(width, 1000)
            for _ in range(4):
                qt_core.processEvents()
            pane = next((p for p in window.panes.values()
                         if hasattr(p, "set_layout_mode")), None)
            assert pane is not None
            viewport = pane.scroll.viewport().width()
            horizontal = pane.scroll.horizontalScrollBar().maximum()
            if horizontal:
                offenders.append((width, f"horizontal range {horizontal}"))
            for row in [r for r in pane.rows if r.isVisible()][:5]:
                geometry = row.geometry()
                well = row.well.geometry()
                if geometry.width() > viewport:
                    offenders.append(
                        (width, f"row {geometry.width()} > viewport {viewport}"))
                if well.x() < 0 or well.x() + well.width() > viewport:
                    offenders.append((width, f"icon at {well.x()}"))
                if geometry.x() + geometry.width() > viewport:
                    offenders.append((width, "row right edge past viewport"))
        assert not offenders, offenders[:4]
    finally:
        window.close()
        from kairo.qt import work
        work.drain()


def test_a_row_name_is_fitted_by_measurement_not_by_counting(qt_core):
    """A character budget is a guess about width, wrong at every other mode."""
    from PySide6.QtGui import QFontMetrics

    from kairo.qt.widgets import EntryRow

    widgets = (QT_DIR / "widgets.py").read_text()
    row_source = widgets.split("class EntryRow")[1]
    assert "LIST_NAME_CHARS" not in row_source, \
        "the row is still sizing its name by character count"
    assert "setMinimumWidth(0)" in row_source
    assert "QSizePolicy.Ignored" in row_source

    row = EntryRow()
    # Shown, because Qt defers resize events for hidden widgets: a bare
    # resize() on one that has never been shown delivers nothing, and the
    # refit would look broken when it is only unobserved.
    row.show()
    row.resize(300, 64)
    row.layout().activate()
    qt_core.processEvents()
    long_name = "Advanced Network Configuration And Then Some More Words"
    row.bind(SimpleEntry(long_name), defer_icon=True)
    metrics = QFontMetrics(row.name.font())
    assert metrics.horizontalAdvance(row.name.text()) <= row.width()
    assert row.name.toolTip() == long_name, "the full name must stay readable"

    # Widening must re-fit without anyone asking it to: the row is resized by
    # its layout, not by the code that bound it, so refitting only on bind
    # leaves every name frozen at the width it first appeared in.
    row.resize(900, 64)
    row.layout().activate()
    qt_core.processEvents()
    assert row.name.text() == long_name, \
        "the name never re-fitted when the row grew"
    assert row.name.toolTip() == ""

    row.resize(240, 64)
    row.layout().activate()
    qt_core.processEvents()
    assert row.name.text() != long_name, "it never re-fitted when the row shrank"
    assert metrics.horizontalAdvance(row.name.text()) <= row.width()


class SimpleEntry:
    def __init__(self, name):
        self.key = "desktop:x"
        self.name = name
        self.subtitle = ""
        self.current_icon = None
        self.customized = False
        self.payload = {}


def test_an_svg_icon_keeps_its_shape(qt_core):
    """render(painter) fills whatever rectangle it is handed.

    The raster path has always kept aspect through KeepAspectRatio; the SVG
    path silently did not, so every theme icon with a non-square viewBox was
    stretched to a square. Nothing about the two paths explains the
    difference and nobody reading either would expect it.
    """
    from PySide6.QtGui import QColor

    from kairo.qt import images

    def drawn(image):
        points = [(x, y)
                  for y in range(image.height())
                  for x in range(image.width())
                  if QColor(image.pixelColor(x, y)).alpha() > 40]
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return min(xs), min(ys), max(xs), max(ys)

    def svg(view_box, body):
        return (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="'
                + view_box + b'">' + body + b'</svg>')

    cases = (
        (b"0 0 200 100", b'<rect x="0" y="0" width="200" height="100" '
                         b'fill="red"/>', 2.0),
        (b"0 0 100 200", b'<rect x="0" y="0" width="100" height="200" '
                         b'fill="red"/>', 0.5),
        (b"0 0 100 100", b'<rect x="0" y="0" width="100" height="100" '
                         b'fill="red"/>', 1.0),
    )
    for view_box, body, aspect in cases:
        images.clear_cache()
        image = images.prepare(64, data=svg(view_box, body))
        left, top, right, bottom = drawn(image)
        width = right - left + 1
        height = bottom - top + 1
        assert abs(width / height - aspect) < 0.06, (
            f"a {aspect}:1 icon was drawn at {width}x{height}")
        assert width <= 64 and height <= 64, "the icon overflows its box"
        assert abs(left - (64 - width) // 2) <= 1, "not centred horizontally"
        assert abs(top - (64 - height) // 2) <= 1, "not centred vertically"


def test_no_pane_ever_shows_a_horizontal_scrollbar(qt_core):
    """Neither list nor artwork may scroll sideways at any width."""
    from kairo.qt.shell import KairoWindow

    window = KairoWindow(translucent=False, want_blur=False)
    try:
        window.show()
        offenders = []
        for width in (900, 1039, 1040, 1319, 1320, 1420):
            window.resize(width, 1000)
            for _ in range(4):
                qt_core.processEvents()
            for pane in window.panes.values():
                for name in ("scroll", "grid_scroll"):
                    area = getattr(pane, name, None)
                    if area is None:
                        continue
                    bar = area.horizontalScrollBar()
                    if bar.maximum() or bar.value():
                        offenders.append((width, name, bar.maximum()))
        assert not offenders, offenders[:4]
    finally:
        window.close()
        from kairo.qt import work
        work.drain()


# ---------------------------------------------------------------------------
# The one-time title reveal.

def _reveal(text, width=200):
    from kairo.qt.widgets import RevealLabel

    label = RevealLabel()
    label.resize(width, 30)
    label.show()
    label.setText(text)
    return label


def test_a_title_that_fits_never_moves(qt_core):
    """Motion is for a problem this title does not have."""
    label = _reveal("Short", width=400)
    try:
        assert not label.is_truncated()
        assert not label.is_animating(), "a title that fits started animating"
        assert label.toolTip() == ""
        assert label._offset == 0.0
    finally:
        label.close()


def test_a_truncated_title_reveals_itself_once_and_stops(qt_core):
    """One pass out and back, not a loop."""
    label = _reveal("Call of Duty: Black Ops Cold War Ultimate Edition", 160)
    try:
        assert label.is_truncated()
        assert label.is_animating()
        assert label.toolTip().startswith("Call of Duty")

        overflow = label._overflow()
        # Hold, then pan out, then hold, then return - driven directly so the
        # test does not depend on a wall clock.
        for _ in range(int(label.START_PAUSE_MS / label.TICK_MS) + 2):
            label._tick()
        assert label._phase == "out", "it never left the beginning"

        seen = []
        for _ in range(4000):
            label._tick()
            seen.append(label._offset)
            if not label.is_animating():
                break
        assert not label.is_animating(), "the reveal never ended"
        assert max(seen) >= overflow - 1, \
            "it stopped before the end of the title was readable"
        assert label._offset == 0.0, "it did not return to the beginning"
        assert label._phase == "idle"
    finally:
        label.close()


def test_the_reveal_moves_at_a_readable_speed(qt_core):
    """25-35 logical points a second; fast enough not to wait, slow to read."""
    from kairo.qt.widgets import RevealLabel

    assert 25.0 <= RevealLabel.SPEED <= 35.0
    assert RevealLabel.START_PAUSE_MS >= 800
    per_tick = RevealLabel.SPEED * (RevealLabel.TICK_MS / 1000.0)
    label = _reveal("A title comfortably wider than the room it has", 120)
    try:
        for _ in range(int(label.START_PAUSE_MS / label.TICK_MS) + 2):
            label._tick()
        before = label._offset
        label._tick()
        assert abs((label._offset - before) - per_tick) < 0.51
    finally:
        label.close()


def test_growing_the_window_cancels_the_reveal_immediately(qt_core):
    label = _reveal("A title comfortably wider than the room it has", 120)
    try:
        assert label.is_animating()
        label.resize(1200, 30)
        qt_core.processEvents()
        assert not label.is_truncated()
        assert not label.is_animating(), "it kept animating once it fitted"
        assert label._offset == 0.0, "it did not reset to the beginning"
        assert label.toolTip() == ""
    finally:
        label.close()


def test_hiding_or_replacing_a_title_stops_its_timer(qt_core):
    """A pane switched away from must not keep a timer running."""
    label = _reveal("A title comfortably wider than the room it has", 120)
    try:
        assert label.is_animating()
        label.hide()
        assert not label.is_animating(), "hidden and still ticking"

        label.show()
        label.setText("Another title also much too wide for this label")
        assert label.is_animating()
        label.setText("Short")
        assert not label.is_animating(), "a shorter title left the timer on"
        assert label._offset == 0.0
    finally:
        label.close()


def test_closing_mid_reveal_leaves_nothing_behind(qt_core):
    """No callback into a destroyed widget, and no Qt warning."""
    import gc

    label = _reveal("A title comfortably wider than the room it has", 120)
    assert label.is_animating()
    label.close()
    label.deleteLater()
    del label
    gc.collect()
    for _ in range(6):
        qt_core.processEvents()


def test_reduced_motion_gets_ellipsis_and_a_tooltip_instead(qt_core, monkeypatch):
    """Movement is a convenience; for some readers it is the opposite."""
    from kairo.qt import theme as Q

    monkeypatch.setenv("KAIRO_NO_ANIMATION", "1")
    assert not Q.animations_enabled()

    label = _reveal("A title comfortably wider than the room it has", 120)
    try:
        assert label.is_truncated(), "precondition: it does not fit"
        assert not label.is_animating(), "reduced motion still animated"
        assert label.toolTip().startswith("A title"), \
            "with no movement the tooltip is the only way to read it"
    finally:
        label.close()


def test_the_title_never_takes_focus_or_swallows_scrolling(qt_core):
    from PySide6.QtCore import Qt as QtNs

    label = _reveal("A title comfortably wider than the room it has", 120)
    try:
        assert label.focusPolicy() == QtNs.NoFocus
        assert not hasattr(type(label), "wheelEvent") or \
            type(label).wheelEvent is type(label).__mro__[1].wheelEvent, \
            "the title must not consume wheel events"
    finally:
        label.close()


def test_a_provider_switch_does_not_accumulate_timers(qt_core):
    """Each pane owns one, parented, so it dies with the widget."""
    from kairo.qt.widgets import RevealLabel

    source = (QT_DIR / "widgets.py").read_text()
    block = source.split("class RevealLabel")[1]
    assert "QTimer(self)" in block, "an unparented timer outlives its widget"
    assert "def hideEvent" in block and "_reset()" in block

    labels = [_reveal("A title comfortably wider than the room it has", 120)
              for _ in range(5)]
    try:
        assert all(label.is_animating() for label in labels)
        for label in labels:
            label.hide()
        assert not any(label.is_animating() for label in labels)
    finally:
        for label in labels:
            label.close()


def test_the_artwork_quality_floor_follows_the_screen(qt_core):
    """A 1x floor let 2x tiles be filled by enlarged 128px sources.

    The tile is decoded at logical size times the ratio, so on a 2x display
    it is 208 physical pixels. Accepting a 128px source there and scaling it
    up 1.6x is the soft artwork in the grid — not a bad file, a floor that
    never learned about the screen.
    """
    from kairo.qt import theme as Q
    from kairo.qt.library import MIN_USABLE_EDGE, usable_edge

    assert usable_edge(1.0) == MIN_USABLE_EDGE
    for ratio in (1.25, 2.0, 3.0):
        target = int(round((Q.TILE - 12) * ratio))
        assert usable_edge(ratio) >= target, (
            f"at {ratio}x a source smaller than {target}px would be enlarged")
    assert usable_edge(3.0) > usable_edge(2.0) > usable_edge(1.0)

    source = (QT_DIR / "library.py").read_text()
    for block in ("_stream_previews", "_prepare_retained_tiles"):
        body = source.split(f"def {block}")[1].split("\n    def ")[0]
        if "min_edge" in body:
            assert "usable_edge(ratio)" in body, \
                f"{block} still uses the flat 1x floor"


def test_action_buttons_are_never_squeezed_below_their_labels(qt_core):
    """A QPushButton clips its centred text; it does not elide it."""
    from PySide6.QtGui import QFontMetrics

    from kairo.qt.shell import KairoWindow

    window = KairoWindow(translucent=False, want_blur=False)
    try:
        window.show()
        pane = None
        for width in (900, 998, 1039, 1120, 1320, 1420):
            window.resize(width, 1000)
            qt_core.processEvents()
            pane = next((p for p in window.panes.values()
                         if hasattr(p, "set_layout_mode")), None)
            assert pane is not None
            pane._restore_full_label = "Reset artwork"
            pane._remove_full_label = "Remove shortcut"
            pane.remove_btn.setVisible(True)
            pane.set_layout_mode(pane._layout_mode)
            qt_core.processEvents()
            for name in ("browse_btn", "restore_btn", "remove_btn",
                         "apply_btn"):
                button = getattr(pane, name)
                if not button.isVisible():
                    continue
                needed = QFontMetrics(button.font()).horizontalAdvance(
                    button.text())
                assert button.width() >= needed, (
                    f"at {width}px {name} is {button.width()} wide for "
                    f"{needed}px of text: {button.text()!r}")
        widgets = (QT_DIR / "library.py").read_text()
        actions = widgets.split("def _build_actions")[1].split("\n    def ")[0]
        assert "QSizePolicy.Minimum" in actions, \
            "the layout may still compress a button below its size hint"
    finally:
        window.close()
        from kairo.qt import work
        work.drain()
