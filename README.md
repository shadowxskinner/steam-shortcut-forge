# Kairo

**Automatic launcher artwork for Linux.**

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-Linux-orange)

Linux already lets you change an application's icon by hand. What it does not
do is find the application, find the artwork, and apply it for you.

Doing it manually means: locate the app, search the web for artwork, download
an image, find the right `.desktop` file, work out which fields are safe to
edit, write the override to the right directory — then repeat for every
application you care about.

Kairo does that part.

```
Scan system  →  63 applications found  →  51 with artwork available  →  Apply
```

You should never need to know what a `.desktop` file is, where your
distribution keeps launcher entries, or what a Flatpak app id looks like.

## What it covers

- **Steam games** — every library on every drive, native and Flatpak installs,
  with artwork from [SteamGridDB](https://www.steamgriddb.com).
- **Everything else with a launcher entry** — native packages, Flatpaks and
  AppImages all install a freedesktop `.desktop` file, so they are all
  discovered by the same scanner. Artwork comes from your installed icon
  themes or from [Iconify](https://iconify.design)'s ~275,000 open source
  icons.
- **Your own images** — any `.png`, `.svg`, `.ico` or `.xpm`.

## Safety

Kairo changes how your launcher looks. That has to be reversible.

- **Original files are never edited.** For an application that already has a
  launcher entry, Kairo copies it to `~/.local/share/applications/` and rewrites
  a single line. Nothing under `/usr` or `/var/lib/flatpak` is ever written.
- **Everything is user-level.** Kairo never needs root.
- **Every change is marked.** Files Kairo creates carry an ownership marker,
  and it refuses to modify or delete any launcher entry that does not have one —
  so a `.desktop` you wrote yourself is safe.
- **The original icon is recorded** inside the override, so Restore works even
  if the application is updated afterwards.
- **Desktop integration survives.** `MimeType`, `StartupWMClass`, `Actions`,
  translated names and vendor keys are copied byte for byte. Only `Icon=` in
  `[Desktop Entry]` changes — never an icon inside a `[Desktop Action]` group.

## Install

### Arch Linux (AUR)

```bash
yay -S kairo
```

Upgrading from `steam-shortcut-forge` replaces it automatically.

### From source

```bash
git clone https://github.com/shadowxskinner/kairo.git
cd kairo
python -m venv .venv && source .venv/bin/activate
pip install -e .
kairo
```

Requires Python 3.10+ and Tk (`pacman -S tk`, `apt install python3-tk`).

A free [SteamGridDB API key](https://www.steamgriddb.com/profile/preferences/api)
is optional — it is only needed for Steam game artwork. Icon themes, Iconify
and local files all work without an account.

## Upgrading from Steam Shortcut Forge

Kairo is the same project, renamed and rebuilt. The old name described a
Steam-only tool; the application had already outgrown it.

On first launch your settings, icons and launcher entries are migrated
automatically:

| Was | Is now |
| --- | --- |
| `~/.config/steam-shortcut-forge/` | `~/.config/kairo/` |
| `~/.local/share/steam-shortcut-forge/icons/` | `~/.local/share/kairo/icons/` |
| `steam-shortcut-forge-<appid>.desktop` | `kairo-<appid>.desktop` |

Your old directories are **left in place**, so nothing is lost and a downgrade
still works. Kairo permanently recognises the old `X-ShortcutForge-*` markers,
so every icon override you made before the rename stays restorable.

## Where things live

- Config: `~/.config/kairo/config.json`
- Cache: `~/.config/kairo/cache/` (safe to delete; it rebuilds)
- Icons: `~/.local/share/kairo/icons/`
- Launcher entries: `~/.local/share/applications/`

## Architecture

Two extension points, so a new kind of application or a new source of artwork
is an added file rather than a rewrite:

- **`AppProvider`** — where applications come from. `SteamProvider` generates
  launcher entries; `DesktopEntryProvider` shadows existing ones. Those are the
  only two ways to own a launcher entry, so there are exactly two writers.
- **`ArtworkSource`** — where icons come from. SteamGridDB, icon themes,
  Iconify and local files.

A dedicated Flatpak or AppImage provider would add richer metadata, not new
coverage — both are already found by `DesktopEntryProvider`.

```bash
python -m pytest      # tests run against a fixture HOME, never your desktop
```

## License

MIT — see [LICENSE](LICENSE).
