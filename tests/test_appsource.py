"""Installation-source classification, described rather than discovered.

Not one of these reads the machine the suite runs on: no real pacman
database, no installed Flatpaks, no desktop entries outside tmp_path. Every
command result is supplied. A test that consults the host passes on the
developer's Arch box and fails everywhere else, which is exactly how the two
PCSX2 tests went wrong.
"""

from pathlib import Path

import pytest

from kairo import appsource


def fake_pacman(owned=None, foreign=(), fail=False):
    """A pacman that answers from a dict instead of a package database."""
    owned = owned or {}

    def run(argv):
        assert argv[0] == "pacman"
        assert "shell" not in argv
        if fail:
            return None
        if argv[1] == "-Qo":
            lines = []
            for path in argv[3:]:
                package = owned.get(path)
                if package is not None:
                    lines.append(f"{path} is owned by {package} 1.0-1")
            return "\n".join(lines)
        if argv[1] == "-Qm":
            return "\n".join(f"{name} 1.0-1" for name in foreign)
        return ""

    return run


def entry(path: Path, body: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[Desktop Entry]\nType=Application\nName=Thing\n" + body)
    return path


# -- the four buckets --------------------------------------------------------

def test_a_repository_package_and_a_foreign_one_are_told_apart(tmp_path):
    """`pacman -Qm` is the only thing that knows, so it has to be asked."""
    shipped = entry(tmp_path / "usr/share/applications/kate.desktop")
    built = entry(tmp_path / "usr/share/applications/yay.desktop")

    result = appsource.classify(
        [shipped, built], roots=[],
        run=fake_pacman(owned={str(shipped): "kate", str(built): "yay-bin"},
                        foreign=["yay-bin"]))

    assert result[str(shipped)] == appsource.ARCH
    assert result[str(built)] == appsource.FOREIGN


def test_a_foreign_package_is_not_called_aur(tmp_path):
    """`-Qm` means foreign to the configured repos, not "from the AUR".

    A package built by hand and installed with `pacman -U` reports exactly
    the same way. Labelling the bucket AUR would state something the package
    database does not say.
    """
    assert dict(appsource.LABELS)[appsource.FOREIGN] == "Foreign / AUR"


def test_an_exported_flatpak_is_recognised_by_its_path(tmp_path):
    exports = tmp_path / "flatpak/exports/share/applications"
    app = entry(exports / "org.gimp.GIMP.desktop")
    result = appsource.classify([app], roots=[exports],
                                run=fake_pacman())
    assert result[str(app)] == appsource.FLATPAK


def test_a_flatpak_is_recognised_by_metadata_and_by_its_command(tmp_path):
    keyed = entry(tmp_path / "a.desktop", "X-Flatpak=org.gimp.GIMP\n")
    launched = entry(tmp_path / "b.desktop",
                     "Exec=/usr/bin/flatpak run --branch=stable org.gimp.GIMP\n")
    result = appsource.classify([keyed, launched], roots=[], run=fake_pacman())
    assert result[str(keyed)] == appsource.FLATPAK
    assert result[str(launched)] == appsource.FLATPAK


def test_merely_mentioning_flatpak_does_not_make_an_application_one(tmp_path):
    """The Exec is parsed, not searched for a word."""
    named = entry(tmp_path / "c.desktop",
                  "Exec=/usr/bin/flatpak-builder-helper --gui\n"
                  "Comment=Manage your flatpak run configuration\n")
    result = appsource.classify(
        [named], roots=[],
        run=fake_pacman(owned={str(named): "flatpak-builder"}))
    assert result[str(named)] == appsource.ARCH


def test_an_unowned_launcher_is_local_rather_than_missing(tmp_path):
    """Hand-written entries and AppImages have no owner, and must still show."""
    hand = entry(tmp_path / ".local/share/applications/mine.desktop")
    result = appsource.classify([hand], roots=[], run=fake_pacman())
    assert result[str(hand)] == appsource.LOCAL


# -- hostile machines --------------------------------------------------------

def test_a_missing_package_manager_leaves_everything_local(tmp_path):
    """No pacman is a normal state for a container or another distribution."""
    app = entry(tmp_path / "app.desktop")

    def absent(_argv):
        return None

    result = appsource.classify([app], roots=[], run=absent)
    assert result[str(app)] == appsource.LOCAL


def test_a_failing_package_manager_does_not_lose_entries(tmp_path):
    apps = [entry(tmp_path / f"app{index}.desktop") for index in range(5)]
    result = appsource.classify(apps, roots=[], run=fake_pacman(fail=True))
    assert len(result) == 5
    assert set(result.values()) == {appsource.LOCAL}


def test_localised_output_does_not_reclassify_the_whole_machine(tmp_path):
    """`is owned by` is translated; the path and package positions are not."""
    app = entry(tmp_path / "app.desktop")

    def german(argv):
        if argv[1] == "-Qo":
            return f"{app} gehört zu paketname 1.0-1"
        return ""

    result = appsource.classify([app], roots=[], run=german)
    assert result[str(app)] == appsource.ARCH


def test_unexpected_output_is_ignored_rather_than_guessed(tmp_path):
    app = entry(tmp_path / "app.desktop")

    def noise(argv):
        return ":: Synchronising package databases...\nerror: nothing\n"

    result = appsource.classify([app], roots=[], run=noise)
    assert result[str(app)] == appsource.LOCAL


def test_a_file_that_vanishes_mid_scan_is_not_a_crash(tmp_path):
    gone = tmp_path / "ghost.desktop"
    result = appsource.classify([gone], roots=[], run=fake_pacman())
    assert result[str(gone)] == appsource.LOCAL


def test_a_malformed_entry_and_an_unmatched_quote_are_survivable(tmp_path):
    broken = entry(tmp_path / "broken.desktop", 'Exec="/opt/a b/app --x\n')
    junk = tmp_path / "junk.desktop"
    junk.write_bytes(b"\x00\xff not a desktop file")
    result = appsource.classify([broken, junk], roots=[], run=fake_pacman())
    assert result[str(broken)] == appsource.LOCAL
    assert result[str(junk)] == appsource.LOCAL


def test_a_name_with_shell_metacharacters_is_never_interpreted(tmp_path):
    """The filename is an argument, not a fragment of a command line."""
    nasty = entry(tmp_path / "Photo Editor (2024); touch pwned.desktop")
    seen = {}

    def recording(argv):
        seen["argv"] = argv
        return ""

    appsource.classify([nasty], roots=[], run=recording)
    assert str(nasty) in seen["argv"], "the path was mangled before the call"
    assert not (tmp_path / "pwned").exists()


def test_a_flatpak_export_shadowing_a_system_entry_stays_one_bucket(tmp_path):
    """Same basename in two places; each path gets exactly one answer."""
    exports = tmp_path / "flatpak/exports/share/applications"
    shadowed = entry(exports / "org.gimp.GIMP.desktop")
    system = entry(tmp_path / "usr/share/applications/org.gimp.GIMP.desktop")
    result = appsource.classify(
        [shadowed, system], roots=[exports],
        run=fake_pacman(owned={str(system): "gimp"}))
    assert result[str(shadowed)] == appsource.FLATPAK
    assert result[str(system)] == appsource.ARCH
    assert len(result) == 2


def test_every_path_lands_in_exactly_one_bucket(tmp_path):
    exports = tmp_path / "flatpak/exports/share/applications"
    paths = [entry(exports / "flat.desktop"),
             entry(tmp_path / "owned.desktop"),
             entry(tmp_path / "foreign.desktop"),
             entry(tmp_path / "loose.desktop"),
             tmp_path / "absent.desktop"]
    result = appsource.classify(
        paths, roots=[exports],
        run=fake_pacman(owned={str(paths[1]): "kate", str(paths[2]): "yay"},
                        foreign=["yay"]))
    assert len(result) == len(paths)
    assert set(result) == {str(p) for p in paths}
    assert set(result.values()) <= set(appsource.BUCKETS)


# -- batching, which is the whole performance story --------------------------

def test_classification_is_batched_not_one_call_per_application(tmp_path):
    """One subprocess per visible row is a fork bomb in slow motion."""
    apps = [entry(tmp_path / f"app{index}.desktop") for index in range(500)]
    calls = []

    def counting(argv):
        calls.append(argv)
        return ""

    appsource.classify(apps, roots=[], run=counting)
    queries = [call for call in calls if call[1] == "-Qo"]
    assert len(queries) <= (500 // appsource.CHUNK) + 1
    assert len(calls) < 10, f"{len(calls)} package queries for 500 entries"


def test_counts_add_up_and_unknown_buckets_fall_to_local():
    tally = appsource.counts([appsource.ARCH, appsource.ARCH,
                              appsource.FLATPAK, "something-new"])
    assert tally[appsource.ALL] == 4
    assert tally[appsource.ARCH] == 2
    assert tally[appsource.FLATPAK] == 1
    assert tally[appsource.LOCAL] == 1


def test_a_pill_caption_carries_its_count():
    tally = appsource.counts([appsource.ARCH])
    assert appsource.label_for(appsource.ARCH, tally).startswith("Arch packages")
    assert appsource.label_for(appsource.ARCH, tally).endswith("1")
    assert appsource.label_for(appsource.ARCH) == "Arch packages"


# -- how the pane uses it ----------------------------------------------------

def test_a_pane_filters_by_bucket_without_touching_identity(qt_app, tmp_path):
    """Provenance is metadata. It must not reach a key, a path or a writer."""
    from types import SimpleNamespace

    from kairo.qt.library import LibraryPane

    entries = [SimpleNamespace(key="desktop:a", name="A", customized=False,
                               payload={"source": "/usr/share/a.desktop"}),
               SimpleNamespace(key="desktop:b", name="B", customized=False,
                               payload={"source": "/home/u/b.desktop"})]
    before = [(e.key, dict(e.payload)) for e in entries]

    pane = SimpleNamespace(
        entries=entries,
        search=SimpleNamespace(text=lambda: ""),
        filters=SimpleNamespace(value=lambda: "All"),
        provider=SimpleNamespace(classifies_sources=True),
        _source_filter=appsource.ARCH,
        _source_of={"desktop:a": appsource.ARCH, "desktop:b": appsource.LOCAL},
        source_of=lambda entry: {"desktop:a": appsource.ARCH,
                                 "desktop:b": appsource.LOCAL}[entry.key],
        _classifies_sources=lambda: True,
    )
    visible = LibraryPane.visible_entries(pane)
    assert [e.key for e in visible] == ["desktop:a"]

    pane._source_filter = appsource.ALL
    assert len(LibraryPane.visible_entries(pane)) == 2

    assert [(e.key, dict(e.payload)) for e in entries] == before, \
        "classification rewrote an entry's identity"


def test_an_entry_with_no_classification_yet_is_local_not_hidden(qt_app):
    """Rows must never vanish while the package query is still running."""
    from types import SimpleNamespace

    from kairo.qt.library import LibraryPane

    pane = SimpleNamespace(_source_of={})
    unknown = SimpleNamespace(key="desktop:never-classified")
    assert LibraryPane.source_of(pane, unknown) == appsource.LOCAL


def test_a_stale_classification_never_lands(qt_app):
    """A rescan or provider switch mid-classification invalidates the answer."""
    from types import SimpleNamespace

    from kairo.qt.library import LibraryPane
    from kairo.qt import work
    from kairo.tasks import ActivityTokens

    tokens = ActivityTokens()
    token = tokens.start("sources:desktop")
    applied = []
    pane = SimpleNamespace(
        tokens=tokens, provider=SimpleNamespace(id="desktop"),
        _source_of={}, _source_counts={}, _source_filter=appsource.ALL,
        _refresh_origin_pills=lambda: applied.append("refreshed"),
        refilter=lambda: None,
    )
    captured = []
    real = work.submit
    work.submit = lambda fn, **kw: captured.append((fn, kw))
    try:
        LibraryPane._classify_sources(
            pane,
            [SimpleNamespace(key="desktop:a",
                             payload={"source": "/usr/share/a.desktop"})],
            token)
        assert captured, "classification never left the GUI thread"
        arrived = captured[0][1]["on_done"]

        tokens.start("sources:desktop")     # a newer scan supersedes this one
        arrived({"desktop:a": appsource.ARCH})
        assert pane._source_of == {}, "a superseded classification was applied"

        token2 = tokens.start("sources:desktop")
        LibraryPane._classify_sources(
            pane,
            [SimpleNamespace(key="desktop:a",
                             payload={"source": "/usr/share/a.desktop"})],
            token2)
        captured[-1][1]["on_done"]({"desktop:a": appsource.ARCH})
        assert pane._source_of == {"desktop:a": appsource.ARCH}
    finally:
        work.submit = real


def test_the_pills_are_built_before_any_scan_result_arrives(qt_app):
    """Controls that appear as a scan finishes move the list under the cursor."""
    source = (Path(__file__).resolve().parents[1]
              / "kairo" / "qt" / "library.py").read_text()
    build = source.split("def _build_list")[1].split("\n    def ")[0]
    assert "_refresh_origin_pills()" in build, \
        "the selector is only created once results land"
    assert "classifies_sources" in build


def test_commands_are_argument_lists_and_never_a_shell(tmp_path, monkeypatch):
    """These arguments are filenames chosen by whatever installed an app.

    `Photo Editor (2024); rm -rf ~.desktop` is a legal name. Handed to a
    shell it is two commands.
    """
    import subprocess as sp

    seen = {}

    class Result:
        returncode = 0
        stdout = ""

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return Result()

    monkeypatch.setattr(sp, "run", fake_run)
    appsource._run(["pacman", "-Qm"])

    assert isinstance(seen["argv"], list), "a string would be shell-parsed"
    assert seen["kwargs"].get("shell") is False, \
        "a shell would interpret filenames as syntax"
    assert seen["kwargs"]["env"]["LC_ALL"] == "C", \
        "parsed output must not be localised"


def test_an_unowned_entry_is_labelled_by_the_fallback_not_by_luck(tmp_path):
    """The single place that decides what "we could not tell" means."""
    known = entry(tmp_path / "known.desktop")
    unowned = entry(tmp_path / "unowned.desktop")
    result = appsource.classify(
        [known, unowned], roots=[],
        run=fake_pacman(owned={str(known): "kate"}))
    assert result[str(known)] == appsource.ARCH
    assert result[str(unowned)] == appsource.LOCAL
    assert len(result) == 2, "an entry disappeared instead of degrading"
