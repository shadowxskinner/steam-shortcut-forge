# Kairo — Qt shell milestone

A second frontend over the unchanged backend. The CustomTkinter shell still
runs and is still the default; this one exists to be looked at side by side.

**Read-only.** Scanning, searching, filtering, selecting, browsing artwork and
previewing a proposal all work against the real backend. Apply, Reset, Remove,
Restore, Restore All, Auto Match and Settings→Save are present so the layout
can be judged, and are disabled. Nothing in this milestone writes to a launcher
entry, the ledger or your config.

## Run it

```bash
cd ~/Downloads/kairo-qt-shell
python -m venv .venv
.venv/bin/pip -q install -e ".[qt]"     # PySide6 only; no CustomTkinter needed
.venv/bin/python -m pytest -q           # 456 tests

.venv/bin/python -m kairo.qt            # the Qt shell
```

Side by side with the current build:

```bash
.venv/bin/pip -q install -e ".[tk]"     # add the other frontend
.venv/bin/python -m kairo               # CustomTkinter, unchanged
```

Flags:

```
--glass frosted   default: reading surfaces nearly solid, gaps open
--glass dense     heavier, for when frosted still reads through
--glass clear     thinner surfaces, for comparison
--glass solid     no transparency at all
--alpha 0.85      nudge every layer together, keeping their relationship
--no-blur         translucent, never ask the compositor for blur
--opaque          same as --glass solid
```

## The glass is settled

The per-layer sliders, the preset buttons and the tuning shortcuts are gone.
The values below are the design now, not something to adjust at runtime:

```
Glass(workspace=0.78, nav=0.97, list=0.96, panel=0.95, card=0.92,
      tile=0.88, line=0.62)
```

`--glass` and `--opaque` still exist on the command line for a one-off look,
but nothing in the window edits them, and the window no longer reports blur
state or a read-only banner along the bottom. Blur is printed once at startup
for a terminal launch and never mentioned again.


## Glass

Alpha is applied per surface, never to the window. A window-wide opacity is
what Tk offered and it is the wrong model: it fades text along with the
background, and makes every surface equally see-through whether it is holding
content or not.

| layer | frosted | dense |
| --- | --- | --- |
| **workspace backdrop** | **0.62** | **0.86** |
| navigation | 0.94 | 0.985 |
| entry column | 0.93 | 0.98 |
| workspace cards | 0.92 | 0.975 |
| rows, wells, fields | 0.88 | 0.95 |
| artwork tiles | 0.84 | 0.92 |
| borders | 0.55 | 0.70 |

`dense` exists because 0.92 still let terminal text read through on a real
display. It is a preset to compare against rather than a new default guessed at
in code — try both and tell me which is closer.

## Opacity and blur are different levers

**Kairo controls opacity. KWin controls blur.**

Kairo only advertises a *region* for KWin to blur; that request carries no
radius or strength, so there is deliberately no blur control in Kairo — a
slider here would be claiming a setting the compositor owns.

Blur smears what is behind a surface. It does not dim it. A region with little
opacity keeps its contrast however hard the compositor works, which is why the
**workspace backdrop** matters most: until this build it was fully transparent,
and it is the largest area of the window — the title row, the gaps between
cards, the action bar and every margin. Raising it is the single change most
likely to fix legible background text; lowering it shows more wallpaper.

For blur strength, read what you currently have:

```bash
./kwin-blur-report.sh          # read-only: reads config, queries KWin, writes nothing
```

Then change it yourself in **System Settings → Desktop Effects → Blur → ⚙**, so
KWin reloads the effect properly. I have not touched your `kwinrc` and will
not.

The root stays fully transparent, so the compositor's blur of the wallpaper is
what fills the gaps between panels — that is where the colour is meant to come
from. Text, icons and the accent never take any alpha at all.

## Blur

Optional, and never required. On KDE Wayland, Kairo asks KWin to blur the exact
logical area of its native Wayland surface through
`ext-background-effect-v1`. The protocol carries a region only — KWin still
owns blur radius, noise and strength.

Build the small optional bridge once:

```bash
./kairo/qt/native/build.sh
.venv/bin/python -m kairo.qt
```

If the bridge, protocol or compositor support is absent, the shell remains
translucent and reports blur as unavailable. `--no-blur` skips the request
without changing the design.

The bridge keeps its Wayland objects on a private event queue, supplies the
window's real width and height instead of an unbounded rectangle, and updates
that region after resize through a short debounce. It retains Python's GIL for
every native call and releases the effect with the cached surface pointer
before Qt tears that surface down. It never changes KWin configuration or
forces Qt onto XWayland.

## Emulators

Settings → Emulators → Add emulator… opens a catalogue of seventeen systems.
Pick one and the file types, the emulator command and its arguments are
already filled in; the only thing to point at is the folder your games are
in, and even that is pre-filled when the collection sits somewhere
conventional. Systems whose emulator is installed are listed first.

This follows what every comparable tool does — ES-DE ships `es_systems.xml`,
Steam ROM Manager ships community presets — because the alternative is asking
someone to know that GameCube means `.rvz`.

One emulator can cover several systems. Dolphin takes two folder rows,
GameCube and Wii, each with its own extensions and its own label, and the
label rides along to the entry so the library reads as both rather than as
one pile. Cemu and PCSX2 take one row and leave the label blank.

Each row reports how many files it matches as you type, so a folder in the
wrong box or an extension typed `.rvs` shows `0 files` before you save. An
emulator that cannot work refuses to save and names the problem, and a
library that comes up empty says why rather than showing a blank list.

Anything not in the catalogue is still reachable: **Something else — describe
it myself** takes the executable, arguments and extensions directly.

ROM artwork comes from SteamGridDB by title. It indexes plenty of games that
were never on Steam, which is most of an emulator library; the Steam-only
restriction was Kairo's rather than the API's. A title match is scored as a
search hit rather than as an identifier, so an appid always outranks it.

## The portal warning

Set `QGuiApplication.setDesktopFileName()` to the application id and install a
matching `.desktop`; the warning is the portal saying it cannot find one.

```bash
install -Dm644 io.github.shadowxskinner.Kairo.desktop \
  ~/.local/share/applications/io.github.shadowxskinner.Kairo.desktop
update-desktop-database ~/.local/share/applications
```

The shell already reports itself as `io.github.shadowxskinner.Kairo`, which is
the same id the Tk build has used since 2.0.0.

## What changed in the shared code

Two things only, both additive:

- `kairo/navmodel.py` is new. Which providers appear, how they group and which
  icon each gets are questions about the application rather than about a
  toolkit, so both shells now build navigation from one model. `kairo/ui/nav.py`
  re-exports it, so the Tk shell is unchanged in behaviour. This is also what
  stops the Qt shell needing CustomTkinter installed.
- `pyproject.toml` makes each frontend an extra. The backend depends on
  neither, which the test suite demonstrates by passing with no GUI library
  present.

Everything else under `kairo/` is byte-identical: providers, artwork sources,
the ledger, migration, adoption, matching, the launcher writers, paths and
their tests.

## Two bugs, and which one actually crashed

Shell 6 asked for blur with `set_blur_region(effect, NULL)`. The protocol says
a NULL region *removes* the effect, so that request was wrong — but it was not
what crashed the shell.

The crash was the worker pool. A `QRunnable` with auto-delete let Qt destroy a
Python-owned `QObject` on a pool thread, racing Shiboken's reference handling
on the GUI thread. It could crash with `--no-blur`, which is what ruled
transparency out. Jobs are now retained, released on the GUI thread, and
closing drains any active lookup before Qt tears anything down.

A KWin scripted effect was tried during diagnosis and abandoned:
`WindowForceBlurRole` does not create a blur region for an ordinary window, and
back-to-back screenshots differed by zero pixels. It is gone from the tree.

## What was verified, and how

The worker lifecycle is covered by tests that run a real `QCoreApplication`
and pool headlessly: a job drains, a failing job still drains, a batch drains,
and `is_idle()` reads false while work is outstanding. The native bridge
compiles clean under `-Wall -Wextra -Werror`, and its failure codes are
cross-checked against the Python status table so the two files cannot drift.

Repeated open/lookup/close cycles were run live before the corrected bridge
landed, with blur disabled. **Cycles against this build with real blur enabled,
and the blur-on/blur-off pixel comparison, are still yours to run** — see the
commands at the end of the delivery notes.

## Worth judging

- Do the three columns read the same as the Tk build, or has something drifted?
- Does the artwork grid reflow sensibly as the window resizes?
- Is `--alpha 0.82` right, or does text want more backing over your wallpaper?
- Does scrolling the entry list stay smooth with a few hundred applications?
- Idle CPU with the window open and doing nothing.
