"""The installed application must agree with its package and documentation."""

import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10, which pyproject still supports
    # A bare `import tomllib` here aborted collection of the whole suite -
    # not one test - on every Python below 3.11, and PKGBUILD's check()
    # runs pytest, so packaging failed on the floor the project declares.
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def _project():
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]


def _pkg_array(name: str) -> str:
    text = (ROOT / "PKGBUILD").read_text()
    match = re.search(rf"(?ms)^{re.escape(name)}=\((.*?)^\)", text)
    assert match is not None, f"PKGBUILD has no {name}=() array"
    return match.group(1)


def test_console_commands_have_one_unambiguous_owner():
    project = _project()
    assert "gui-scripts" not in project, (
        "two entry-point groups previously created different `kairo` scripts")
    assert project["scripts"] == {
        "kairo": "kairo.qt.__main__:main",
        "kairo-qt": "kairo.qt.__main__:main",
        "kairo-tk": "kairo.__main__:main",
    }


def test_the_shipping_wheel_requires_qt_but_not_the_legacy_frontend():
    project = _project()
    required = "\n".join(project["dependencies"]).casefold()
    assert "pyside6" in required
    assert "customtkinter" not in required and "cairosvg" not in required
    optional = project.get("optional-dependencies", {})
    assert "qt" not in optional, "Qt is the application, not an install extra"
    legacy = "\n".join(optional["tk"]).casefold()
    assert "customtkinter" in legacy and "cairosvg" in legacy


def test_the_arch_package_matches_the_wheel_frontends():
    required = _pkg_array("depends")
    assert "'pyside6'" in required
    assert "'python-pillow'" in required
    assert "customtkinter" not in required
    assert re.search(r"(?m)^\s*'tk'\s*$", required) is None

    optional = _pkg_array("optdepends")
    assert "python-customtkinter" in optional
    assert "python-cairosvg" in optional
    assert re.search(r"(?m)^\s*'tk:", optional)


def test_release_recipe_cannot_ship_a_skip_checksum():
    text = (ROOT / "PKGBUILD").read_text()
    state = re.search(r"(?m)^_unreleased=(\d+)$", text)
    assert state is not None, "the untagged recipe needs an explicit guard"
    assert "if (( _unreleased )); then" in text
    assert "RELEASING.md" in text
    if state.group(1) == "0":
        sums = re.search(r"(?m)^sha256sums=(.*)$", text)
        assert sums is not None and "SKIP" not in sums.group(1), (
            "a release must hash the archive produced by its real Git tag")


def test_user_facing_launch_instructions_match_the_desktop_file():
    desktop = (ROOT / "io.github.shadowxskinner.Kairo.desktop").read_text()
    readme = (ROOT / "README.md").read_text()
    qt_readme = (ROOT / "README-QT.md").read_text()
    assert re.search(r"(?m)^Exec=kairo$", desktop)
    assert "pip install -e ." in readme and "kairo-tk" in readme
    assert "Qt is Kairo's shipping frontend" in qt_readme
    for stale in ("Qt shell milestone", "**Read-only.**", "456 tests",
                  "Ctrl+1/2/3"):
        assert stale not in qt_readme
