"""Build the whole window against a stubbed toolkit.

There is no Tk here and no display, so the GUI would otherwise get no
execution at all. Importing a module only runs its class bodies; *constructing*
the widgets runs every _build method, which is where the mistakes actually
live - a misspelled attribute, a theme token that does not exist, a method
called with the wrong arguments, a pane that assumes state set up elsewhere.

It cannot check that anything looks right. It can check that the window can be
assembled at all, which is the difference between a layout problem and a
traceback on first launch.
"""

import sys
import types

import pytest


class _Var:
    """A Tk variable that actually holds a value, because the code reads it."""

    def __init__(self, value="", **kwargs):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value

    def trace_add(self, *args, **kwargs):
        return "trace0"


class _Widget:
    """Accepts anything, returns something plausible for what the code asks."""

    _LISTS = {"winfo_children"}
    _FALSE = {"winfo_ismapped"}
    _TRUE = {"winfo_exists"}
    _NUMBERS = {"winfo_width", "winfo_reqwidth", "winfo_rootx", "winfo_rooty",
                "winfo_height"}

    def __init__(self, *args, **kwargs):
        self._scrollbar = _Widget.__new__(_Widget)
        self._parent_canvas = _Widget.__new__(_Widget)

    def __getattr__(self, name):
        if name in self._LISTS:
            return lambda *a, **k: []
        if name in self._FALSE:
            return lambda *a, **k: False
        if name in self._TRUE:
            return lambda *a, **k: True
        if name in self._NUMBERS:
            return lambda *a, **k: 200
        if name == "after":
            return lambda *a, **k: "after0"
        return lambda *a, **k: None

    def __call__(self, *args, **kwargs):
        return None


class _StubModule(types.ModuleType):
    """Attributes are subclassable classes; exception-ish names are exceptions."""

    _SPECIAL = {"StringVar": _Var, "BooleanVar": _Var, "IntVar": _Var,
                "DoubleVar": _Var}

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name in self._SPECIAL:
            created = self._SPECIAL[name]
        elif name.endswith("Error"):
            created = type(name, (Exception,), {})
        else:
            created = type(name, (_Widget,), {})
        setattr(self, name, created)
        return created


class _DialogModule(types.ModuleType):
    """Dialogs decline by default.

    A construction test must not have confirmations answering "yes" and
    quietly running the very code paths it is not trying to exercise.
    """

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name.startswith("ask"):
            if "filename" in name or "directory" in name:
                return lambda *a, **k: ""
            return lambda *a, **k: False
        return lambda *a, **k: None


@pytest.fixture
def toolkit(monkeypatch):
    if "tkinter" in sys.modules and not isinstance(sys.modules["tkinter"], _StubModule):
        pytest.skip("real Tk is available; this stub would shadow it")

    modules = {}
    for name in ("tkinter", "tkinter.ttk", "customtkinter",
                 "customtkinter.windows", "customtkinter.windows.widgets",
                 "customtkinter.windows.widgets.core_rendering"):
        modules[name] = _StubModule(name)
    for name in ("tkinter.filedialog", "tkinter.messagebox"):
        modules[name] = _DialogModule(name)

    # `from tkinter import messagebox` resolves the attribute on the parent
    # package before falling back to sys.modules, so the parent has to carry
    # its submodules explicitly.
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
        if "." in name:
            parent, _, leaf = name.rpartition(".")
            setattr(modules[parent], leaf, module)

    for name in list(sys.modules):
        if name.startswith("kairo.ui") or name in {"kairo.imaging"}:
            monkeypatch.delitem(sys.modules, name, raising=False)
    yield


@pytest.fixture
def furnished(fake_home, steam_library, system_apps):
    """A home with a couple of Steam games and a couple of applications."""
    return fake_home


# -- navigation is built from providers, not hard-coded ---------------------

def test_nav_groups_providers_and_management(toolkit, furnished):
    from kairo.providers.registry import default_registry
    from kairo.ui import nav

    items = nav.build_items(default_registry())
    groups = [i.group for i in items]
    assert "Library" in groups
    assert nav.GROUP_MANAGEMENT in groups
    assert {i.key for i in items} >= {"provider:steam", "provider:desktop",
                                      nav.VIEW_CHANGES, nav.VIEW_SETTINGS}


def test_a_new_provider_group_appears_without_touching_the_ui(toolkit, furnished):
    """The whole point of putting `group` on the provider: a future
    PCSX2Provider must reach the navigation without a UI change."""
    from kairo.providers.base import AppProvider
    from kairo.providers.registry import default_registry
    from kairo.ui import nav

    class PretendEmulator(AppProvider):
        id = "pretend"
        label = "PCSX2"
        noun = "games"
        group = "Emulators"
        order = 0

        def scan(self):
            return []

        def artwork_query(self, entry):
            raise NotImplementedError

        def writer(self):
            raise NotImplementedError

    registry = default_registry()
    registry.register(PretendEmulator())

    items = nav.build_items(registry)
    emulators = [i for i in items if i.group == "Emulators"]
    assert [i.label for i in emulators] == ["PCSX2"]
    # and it lands before the management section
    assert items.index(emulators[0]) < items.index(
        next(i for i in items if i.key == nav.VIEW_CHANGES))


def test_management_comes_last(toolkit, furnished):
    from kairo.providers.registry import default_registry
    from kairo.ui import nav

    items = nav.build_items(default_registry())
    assert items[-2].key == nav.VIEW_CHANGES
    assert items[-1].key == nav.VIEW_SETTINGS


# -- every pane can actually be built ---------------------------------------

def test_library_pane_builds_for_each_provider(toolkit, furnished):
    from kairo.ledger import Ledger
    from kairo.providers.registry import default_registry
    from kairo.artwork.registry import default_registry as artwork_registry
    from kairo.tasks import ActivityTokens
    from kairo.ui.context import UIContext
    from kairo.ui.library import LibraryPane

    registry = default_registry()
    ctx = UIContext(providers=registry, sources=artwork_registry({}), config={},
                    ledger=Ledger().load(), tokens=ActivityTokens())

    for provider in registry.all():
        pane = LibraryPane(None, provider, ctx)
        assert pane.provider is provider
        assert isinstance(pane.entries, list)


def test_library_pane_lists_and_filters_entries(toolkit, furnished):
    from kairo.ledger import Ledger
    from kairo.providers.registry import default_registry
    from kairo.artwork.registry import default_registry as artwork_registry
    from kairo.tasks import ActivityTokens
    from kairo.ui.context import UIContext
    from kairo.ui.library import LibraryPane

    registry = default_registry()
    ctx = UIContext(providers=registry, sources=artwork_registry({}), config={},
                    ledger=Ledger().load(), tokens=ActivityTokens())
    pane = LibraryPane(None, registry.get("steam"), ctx)

    assert len(pane.entries) == 2                     # from the fixture
    pane.search_var.set("portal")
    assert [e.name for e in pane.visible_entries()] == ["Portal 2"]
    pane.search_var.set("")
    pane._set_filter("with")
    assert pane.visible_entries() == []


def test_changes_pane_builds_empty_and_populated(toolkit, furnished):
    from kairo.ledger import ChangeRecord, Ledger
    from kairo.providers.registry import default_registry
    from kairo.artwork.registry import default_registry as artwork_registry
    from kairo.tasks import ActivityTokens
    from kairo.ui.changes_pane import ChangesPane
    from kairo.ui.context import UIContext

    ledger = Ledger().load()
    ctx = UIContext(providers=default_registry(),
                    sources=artwork_registry({}), config={}, ledger=ledger,
                    tokens=ActivityTokens())
    ChangesPane(None, ctx)                            # empty state

    from kairo import paths
    target = paths.applications_dir() / "kairo-440.desktop"
    target.write_text("[Desktop Entry]\nType=Application\nName=TF2\n"
                      "Icon=/x.png\nX-Kairo-Managed=true\n")
    ledger.record(ChangeRecord(key="steam:440", provider_id="steam", name="TF2",
                               action="created", target=str(target)))
    ChangesPane(None, ctx)                            # populated state


def test_settings_pane_builds(toolkit, furnished):
    from kairo.ledger import Ledger
    from kairo.providers.registry import default_registry
    from kairo.artwork.registry import default_registry as artwork_registry
    from kairo.tasks import ActivityTokens
    from kairo.ui.context import UIContext
    from kairo.ui.settings_pane import SettingsPane

    ctx = UIContext(providers=default_registry(), sources=artwork_registry({}),
                    config={"steamgriddb_api_key": "abc"},
                    ledger=Ledger().load(), tokens=ActivityTokens())
    SettingsPane(None, ctx)


# -- and the whole window -----------------------------------------------------

def test_the_shell_assembles(toolkit, furnished):
    from kairo.ui.shell import KairoShell

    shell = KairoShell()
    assert shell.items
    assert shell.current_key is not None
    assert shell.current_key in shell.panes


def test_switching_panes_builds_each_destination(toolkit, furnished):
    from kairo.ui import nav
    from kairo.ui.shell import KairoShell

    shell = KairoShell()
    for item in shell.items:
        shell._select(item)
        assert shell.current_key == item.key
        assert item.key in shell.panes
    assert nav.VIEW_CHANGES in shell.panes
    assert nav.VIEW_SETTINGS in shell.panes


def test_shell_survives_rescan(toolkit, furnished):
    from kairo.ui.shell import KairoShell

    shell = KairoShell()
    shell.rescan()
    shell._on_changed()


def test_shell_collects_entries_across_providers(toolkit, furnished):
    from kairo.ui.shell import KairoShell

    shell = KairoShell()
    entries = shell._all_entries()
    keys = {e.key for e in entries}
    assert any(k.startswith("steam:") for k in keys)
    assert any(k.startswith("desktop:") for k in keys)


def test_classic_window_still_assembles(toolkit, furnished):
    """Kept reachable via `kairo --classic` while the new shell is proven."""
    from kairo.ui.app import KairoApp

    app = KairoApp()
    assert app.entries is not None
