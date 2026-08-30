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

## Tuning the glass

**Settings → Appearance.** A slider per layer, a button per preset, and the
resulting values printed in a form you can paste back to me:

```
Glass(nav=0.94, list=0.93, panel=0.92, card=0.88, tile=0.84, line=0.55)
```

"Copy values" puts that on the clipboard. Send me the line you settle on and it
becomes the default.

Shortcuts also work — **Ctrl+1…4** for the presets, **Ctrl+]** / **Ctrl+[** to
nudge everything together, with **Ctrl+=** and **Ctrl+-** bound to the same
thing in case the bracket keys are taken. They are convenience, not the only
route: the earlier build had shortcuts and nothing else, and when they silently
failed there was no way to tune at all.

Restyling is a stylesheet swap, so this costs nothing and needs no restart.

## Glass

Alpha is applied per surface, never to the window. A window-wide opacity is
what Tk offered and it is the wrong model: it fades text along with the
background, and makes every surface equally see-through whether it is holding
content or not.

| layer | frosted | dense |
| --- | --- | --- |
| navigation | 0.94 | 0.985 |
| entry column | 0.93 | 0.98 |
| workspace cards | 0.92 | 0.975 |
| rows, wells, fields | 0.88 | 0.95 |
| artwork tiles | 0.84 | 0.92 |
| borders | 0.55 | 0.70 |

`dense` exists because 0.92 still let terminal text read through on a real
display. It is a preset to compare against rather than a new default guessed at
in code — try both and tell me which is closer.

The root stays fully transparent, so the compositor's blur of the wallpaper is
what fills the gaps between panels — that is where the colour is meant to come
from. Text, icons and the accent never take any alpha at all.

## Blur

Optional, and never required. Without it the window is translucent and
unblurred, which is the normal appearance anywhere except a KDE Wayland session
offering `ext-background-effect-v1`.

```bash
./kairo/qt/native/build.sh
.venv/bin/python -m kairo.qt
```

`build.sh` runs `wayland-scanner` over the XML from `wayland-protocols`,
compiles one shared library **inside the package directory**, and installs
nothing. Build-time it needs `gcc`, `pkg-config`, `wayland` and
`wayland-protocols`; at runtime only the resulting `.so`, and not even that if
you do not want blur.

The status is shown in the status bar and under Settings → Appearance, and
printed once at startup. Every failure path names itself: no shim, no protocol,
not Wayland, wrong handle.

The whole interaction is one registry roundtrip and one `set_blur_region` at
startup. No thread, no timer, no capture, nothing on resize or repaint.

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

## What could not be verified here

I have no display, no Wayland and no `libEGL`, so no Qt widget has ever been
constructed. What is checked: every PySide6 name and method call against the
shipped type stubs (64 imports, 66 methods, none missing), pyflakes across the
package, that no Qt module imports Tk, and that blur degrades to a message
rather than an exception. The first genuine test is yours.

## Worth judging

- Do the three columns read the same as the Tk build, or has something drifted?
- Does the artwork grid reflow sensibly as the window resizes?
- Is `--alpha 0.82` right, or does text want more backing over your wallpaper?
- Does scrolling the entry list stay smooth with a few hundred applications?
- Idle CPU with the window open and doing nothing.
