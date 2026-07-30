# Steam Shortcut Forge

A Linux desktop app that gives your Steam games proper icons in the
system app launcher (KDE, GNOME, or any freedesktop-compliant desktop).

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-Linux-orange)

## The problem

Steam auto-generates launcher entries for installed games, but you
can't control their icons, and the entries go stale when games get
uninstalled. On KDE/GNOME, this means broken or ugly shortcuts in
your app launcher.

## The solution

Steam Shortcut Forge scans every Steam library on your machine, shows
you exactly what's installed, and lets you assign icons — either
fetched automatically from [SteamGridDB](https://www.steamgriddb.com)
or picked manually from your own files.

## Features

- **SteamGridDB integration** — browse and apply community-uploaded
  icons for any game. Results are cached locally.
- **Bulk auto-assign** — one click to fetch the best icon for every
  game at once.
- **Multi-library support** — finds games across native installs,
  Flatpak, and extra library folders on other drives.
- **Filter & search** — filter by shortcut status, search by name.
- **Icon preview** — see assigned icons right in the game list.
- **Clean dark UI** — built with CustomTkinter.
- Creates standard `.desktop` launcher entries — shows up in your
  launcher immediately, no logout required.
- Detects native vs Flatpak Steam automatically.

## Screenshots

<!-- Add screenshots here after first run -->

## Installation

### Requirements

- Python 3.10+
- Tk (`sudo pacman -S tk` on Arch, `sudo apt install python3-tk` on
  Debian/Ubuntu)
- A free [SteamGridDB API key](https://www.steamgriddb.com/profile/preferences/api)

### Setup

```bash
git clone https://github.com/YOUR_USERNAME/steam-shortcut-forge.git
cd steam-shortcut-forge
python -m venv .venv
source .venv/bin/activate
pip install customtkinter
python steam_shortcut_forge.py
```

On first launch, enter your SteamGridDB API key in Settings.

## How it works

- Steam libraries are found by checking standard install locations
  and parsing `libraryfolders.vdf` for additional drives.
- Installed games are read from `appmanifest_*.acf` files.
- SteamGridDB lookups go through their REST API with disk caching
  (game IDs cached permanently, icon lists cached 24h, thumbnails
  cached after first download).
- Icons are stored in `~/.local/share/steam-shortcut-forge/icons/`.
- Launcher entries are written as
  `~/.local/share/applications/steam-shortcut-forge-<appid>.desktop`,
  separate from Steam's own entries.
- Config and cache live in `~/.config/steam-shortcut-forge/`.

## License

MIT — see [LICENSE](LICENSE).
