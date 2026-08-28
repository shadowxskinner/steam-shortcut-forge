"""Import every GUI module against a stubbed toolkit.

The test machine has no Tk, and CI for a desktop app usually has no display
either, so the UI would otherwise get zero execution of any kind. Importing
each module runs its class bodies, which catches import cycles, misspelled
imports and references to theme tokens that do not exist - the errors that
would otherwise surface as a traceback on the user's first launch.

It is not a substitute for running the application. It is the floor.
"""

import sys
import types

import pytest

UI_MODULES = [
    "kairo.imaging",
    "kairo.ui.theme",
    "kairo.ui.widgets",
    "kairo.ui.settings",
    "kairo.ui.changes",
    "kairo.ui.review",
    "kairo.ui.app",
    "kairo.__main__",
]


class _Stub:
    """Stands in for any widget: constructible, callable, attribute-tolerant."""

    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return _Stub()

    def __call__(self, *args, **kwargs):
        return _Stub()


class _StubModule(types.ModuleType):
    """Every attribute is a fresh subclassable class.

    Widgets are subclassed (``class AppRow(ctk.CTkFrame)``), so attributes have
    to be real classes rather than mocks. Anything named like an exception
    becomes one, because the code catches ``tkinter.TclError``.
    """

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        base = Exception if name.endswith("Error") else _Stub
        created = type(name, (base,), {})
        setattr(self, name, created)
        return created


@pytest.fixture
def stub_toolkit(monkeypatch):
    if "tkinter" in sys.modules and not isinstance(sys.modules["tkinter"], _StubModule):
        pytest.skip("real Tk is available; import check is redundant")

    for name in ("tkinter", "tkinter.filedialog", "tkinter.messagebox",
                 "tkinter.ttk", "customtkinter",
                 "customtkinter.windows", "customtkinter.windows.widgets",
                 "customtkinter.windows.widgets.core_rendering"):
        monkeypatch.setitem(sys.modules, name, _StubModule(name))

    for name in list(sys.modules):
        if name.startswith("kairo.ui") or name in {"kairo.imaging", "kairo.__main__"}:
            monkeypatch.delitem(sys.modules, name, raising=False)
    yield


@pytest.mark.parametrize("module", UI_MODULES)
def test_gui_module_imports(module, stub_toolkit):
    __import__(module)


def test_main_refuses_a_non_linux_platform(stub_toolkit, monkeypatch, capsys):
    import importlib
    main_module = importlib.import_module("kairo.__main__")
    monkeypatch.setattr(sys, "platform", "darwin")
    assert main_module.main() == 1
    assert "Linux" in capsys.readouterr().err


def test_theme_helpers_need_no_toolkit():
    """Pure presentation logic must stay testable without a display."""
    from kairo.ui import theme

    assert theme.ellipsize("a very long application name indeed", 12).endswith("…")
    assert theme.ellipsize("short", 12) == "short"
    assert theme.confidence_label(1.0) == "Exact match"
    assert theme.confidence_label(0.7) == "Good match"
    assert theme.format_date("2026-08-27T14:02:11Z") == "27 Aug 2026"
    assert theme.format_date("") == ""
