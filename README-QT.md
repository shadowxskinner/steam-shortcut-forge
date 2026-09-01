# Kairo Qt frontend

Qt is Kairo's shipping frontend. It presents Steam games, registered desktop
applications and configured emulator libraries in one three-column window over
the shared provider, artwork, ledger and action layers.

## Run from source

```bash
python -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m pytest
.venv/bin/kairo
```

`kairo-qt` launches the same application explicitly. The legacy Tk frontend is
optional and never imported by Qt:

```bash
.venv/bin/pip install -e ".[tk]"
.venv/bin/kairo-tk
```

## Command-line appearance options

```text
--glass frosted   default neutral dark material
--glass dense     more backing over a busy wallpaper
--glass clear     thinner surfaces for comparison
--glass solid     fully opaque surfaces
--alpha 0.85      shift every surface together
--no-blur         do not request compositor blur
--opaque          alias for the solid preset
--version         print Kairo's version
```

The window contains no live glass-tuning shortcuts. These flags are launch-time
diagnostics and preferences, not an editor for KWin.

## What is wired

- Scan, search and filter Steam, application and emulator libraries.
- Search artwork from the sources available for the selected entry, including
  SteamGridDB, installed themes, Iconify and local files.
- Preview a proposal, Apply it through `kairo.actions`, and reset artwork where
  the provider supports that operation.
- Save the SteamGridDB key and add, edit or remove emulator configurations.
- Review Kairo-owned changes and restore one or all of them through the
  provider writer's ownership checks.
- Jump from an emulator or Steam sidebar entry to the launcher whose icon owns
  that navigation logo.

Qt Auto Match is not exposed in this release. The backend implementation and
legacy Tk control remain available, but a disabled production button would
promise work the Qt workflow cannot yet complete. Removing generated shortcuts
and cleaning unused artwork are also intentionally unavailable until their own
ownership and reference-accounting passes are complete.

## Safety boundary

The frontend never edits or deletes launcher files directly. Apply and Restore
go through `kairo.actions`, then through the provider writer that owns the
entry. The marker inside the live launcher file is authoritative, so a file
edited outside Kairo is refused even if an older ledger record says Kairo once
owned it. Restore All skips refusals and continues with safe records.

Long filesystem and network operations run on the Qt worker pool. Activity
tokens reject superseded results, and shutdown cancels tokens and drains the
pool before Qt tears down its native objects.

## Glass and compositor blur

Alpha is applied per surface, not to the whole window, so text and icons remain
opaque. Kairo asks KWin for blur only on KDE Wayland when the optional native
bridge and protocol are available; KWin owns blur strength, radius and noise.
Kairo never edits compositor configuration.

Build the bridge in a source checkout with the required Wayland development
headers installed:

```bash
./kairo/qt/native/build.sh
kairo
```

If the bridge or compositor support is absent, Kairo still runs with its dark
translucent surfaces. `--no-blur` bypasses the native request, and `--opaque`
provides a compositor-independent fallback.

## Verification boundary

The test suite exercises the backend, widget construction, worker lifecycle,
ownership guards and offscreen Qt behavior without reading the developer's
configuration. The remaining release checks require a real desktop:

- KWin blur and repeated open/close cycles on Plasma Wayland.
- Artwork queries that require network access and a real SteamGridDB key.
- Arch package installation with `makepkg` after a real release tag and source
  checksum exist.

See [RELEASING.md](RELEASING.md) for the packaging order.
