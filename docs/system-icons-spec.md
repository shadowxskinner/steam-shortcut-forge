# Spec — System icons (v1.2.0)

Extend Shortcut Forge from "icons for Steam games" to "icons for anything on
this machine", via two tabs: **Steam** (existing behaviour, unchanged) and
**System** (every installed application).

Both icon sources are free and require no account or API key.

---

## 1. Goals

- Browse every installed application, not just Steam games.
- Assign a custom icon to any of them, one by one.
- Keep the Steam tab working exactly as it does today.
- Stay free and keyless. No attribution obligations passed to the user.

## 2. Non-goals

- Changing the system-wide icon *theme*. That is System Settings' job.
- Editing anything outside `~/.local/share/applications` and
  `~/.local/share/steam-shortcut-forge/`.
- Icon editing, cropping, or recolouring.

---

## 3. Why the write path is different, and why it matters most

This is the part that will break things if it is done casually.

For a Steam game, `create_shortcut()` **generates** a `.desktop` file from
scratch. That is correct: the file does not exist yet, and every field is
derived (`Exec=` from `steam_cmd(appid)`, `Categories=Game;`, and so on).

For a system application, the `.desktop` file **already exists** and contains
fields we neither understand nor own — `MimeType`, `StartupWMClass`, `Actions`,
`X-*` vendor keys, `TryExec`, translated `Name[de]` entries, and often multiple
`[Desktop Action ...]` groups. Regenerating that file destroys the application's
integration with the desktop: default-handler associations break, window
matching breaks, jump-list actions vanish.

**Rule: for system apps, copy the original file verbatim and rewrite only the
`Icon=` line in the `[Desktop Entry]` group.**

Specifically:

- Preserve byte-for-byte everything except the one line.
- Only touch `Icon=` inside `[Desktop Entry]`, never inside a
  `[Desktop Action ...]` group.
- If no `Icon=` key exists, insert one at the end of `[Desktop Entry]`.
- Write to `~/.local/share/applications/<same-basename>.desktop`. That location
  shadows the system copy per the XDG base directory spec, and survives package
  and Flatpak updates.
- Never modify anything under `/usr` or `/var/lib/flatpak`.

Reverting is then simply deleting the local override.

---

## 4. Data model

`SteamGame` becomes the Steam-specific case of a shared shape:

```python
@dataclass
class AppEntry:
    key: str              # "steam:10190" or "system:org.kde.dolphin"
    name: str
    kind: str             # "steam" | "system"
    icon_path: Path | None
    has_shortcut: bool    # steam: managed .desktop exists
                          # system: local override exists

    appid: str | None = None          # steam only
    desktop_source: Path | None = None  # system only, the file we copy
    desktop_local: Path | None = None   # system only, our override
```

`GameItem` renders `AppEntry` unchanged — it only reads `name`, `icon_path`,
`has_shortcut`, and a subtitle string. Give `AppEntry` a `subtitle` property
returning the appid for Steam entries and the desktop basename for system ones.

---

## 5. Scanner — system applications

Read `*.desktop` from, in ascending precedence:

```
/usr/share/applications
/usr/local/share/applications
/var/lib/flatpak/exports/share/applications
~/.local/share/flatpak/exports/share/applications
~/.local/share/applications          # user overrides, wins
```

Parse with `configparser` (the format is INI-like), not regex.

Exclude entries where any of these hold:

- `NoDisplay=true`
- `Hidden=true`
- `Type` is not `Application`
- `OnlyShowIn` names a desktop that is not the current one
- basename starts with `DESKTOP_PREFIX` — those are our own Steam shortcuts and
  belong to the other tab

Deduplicate by basename, keeping the highest-precedence copy. Mark
`has_shortcut = True` when a file with the same basename already exists in
`~/.local/share/applications` **and** carries our marker key (see §9).

Resolve the current `Icon=` value for the thumbnail. It is usually a *name*,
not a path, so implement the freedesktop icon lookup: search
`$XDG_DATA_DIRS/icons/<theme>/<size>/apps/<name>.{svg,png}` across the active
theme, then `hicolor`, then `/usr/share/pixmaps/<name>.{svg,png,xpm}`. Absolute
paths in `Icon=` are used directly.

---

## 6. Icon sources

Three, presented as a segmented control above the grid. Availability depends on
the active tab.

### 6.1 Installed icon themes — local, offline, default for System

Scan `/usr/share/icons/*/`, `~/.icons/*/`, and `~/.local/share/icons/*/`.

This is the strongest source for system applications and costs nothing: the
themes already contain artwork named for real Linux applications
(`firefox.svg`, `dolphin.svg`, `steam.svg`), drawn to match the desktop. If the
user installs `papirus-icon-theme` and `tela-icon-theme`, they get thousands of
appropriate, consistent icons with no network access.

Index lazily on first use — walk each theme's `apps/` directories at the largest
available size, build `{name: [paths]}`, cache to
`~/.config/steam-shortcut-forge/cache/themes.json` keyed on the mtime of each
theme root.

Search is a substring match on icon name. Group results by theme in the grid.

### 6.2 Iconify — online, free, keyless

Public API at `https://api.iconify.design`. Over 275,000 icons across 200+ open
source icon sets. No account, no API key, no rate-limit documented for
reasonable use. Backup hosts `api.simplesvg.com` and `api.unisvg.com` exist for
redundancy; fall back to them on timeout.

**Search** — `GET /search?query=<q>&limit=<n>`

`limit` minimum 32, default 64, maximum 999. Response:

```json
{
  "icons": ["mdi:steam", "simple-icons:steam", "logos:steam"],
  "total": 3,
  "limit": 64,
  "start": 0,
  "collections": { "mdi": { "name": "Material Design Icons", ... } }
}
```

Each entry is `prefix:name`. Use `collections` to label each tile with its set,
the same way the Steam tab shows a style pill.

**Fetch** — `GET /<prefix>/<name>.svg?height=256`

Verify this exact URL form with a smoke test during implementation; it is the
standard Iconify form but is worth confirming before building on it.

Cache responses under `cache/iconify_<md5>.svg` with the same 24h expiry the
SteamGridDB lists use.

Note this source is *searchable by name*, which is what makes it usable for
arbitrary applications — unlike SteamGridDB, which is keyed on Steam appid and
therefore cannot serve a System tab at all.

### 6.3 Browse local file — unchanged

Already implemented. Available in both tabs.

---

## 7. SVG rendering — the one new dependency

Theme icons and Iconify results are predominantly SVG. Pillow cannot rasterize
SVG, so those tiles would fail to preview even though the written `.desktop`
would display them correctly, since GTK and Qt render SVG natively.

Add `cairosvg` (pip) / `python-cairosvg` (Arch). Extend `_scaled_photo()` and
`_ctk_icon()`:

```python
if data[:200].lstrip().startswith((b"<svg", b"<?xml")):
    data = cairosvg.svg2png(bytestring=data,
                            output_width=size, output_height=size)
```

Rasterize at the target size rather than scaling after — SVG is resolution
independent, so this yields a sharp result at any `TILE_SIZE`.

Degrade gracefully when `cairosvg` is absent: show the existing `?` placeholder
and a one-line hint in the status bar. Do not make it a hard requirement — the
Steam tab does not need it.

---

## 8. UI changes

- Segmented control at the top of the sidebar: **Steam** | **System**, styled
  like the existing All / Active / None chips.
- Switching tabs swaps the sidebar list and clears the icon grid.
- Icon-source selector above the grid, options depending on tab:
  - Steam → SteamGridDB, Icon themes, Local file
  - System → Icon themes, Iconify, Local file
- The System tab needs a **Revert to default** action where the Steam tab has
  **Remove shortcut**. Same slot, different verb: it deletes the local override
  rather than a shortcut we created.
- Search box filters the active list; the count pill reflects the active tab.

---

## 9. Ownership marker

We must be able to tell "an override this app created" from "an override the
user hand-wrote", so that Revert never deletes someone else's work.

Write `X-ShortcutForge-Managed=true` into the `[Desktop Entry]` group of every
override we create. Revert refuses, with an explanation, on any local file
lacking that key.

Also record the original `Icon=` value as
`X-ShortcutForge-OriginalIcon=<value>` so Revert can be offered even when the
system file has since changed.

---

## 10. Phasing

Land these separately. Each is independently useful and independently
revertable.

1. **Refactor to `AppEntry`.** No user-visible change. Steam tab keeps working.
   This is the risky commit; get it merged and exercised before building on it.
2. **System scanner + tab**, with Browse-local-file only as the icon source.
   Useful on its own — it is exactly the "change the Steam client's icon"
   case that motivated this.
3. **Icon theme source.** Offline, no new dependency beyond SVG rendering.
4. **cairosvg rendering.** Can land with or before step 3.
5. **Iconify source.** The largest surface, and the only one needing network
   error handling, so last.

---

## 11. Risks and open questions

**File size.** `steam_shortcut_forge.py` is ~1100 lines before any of this. The
audit already flagged that it should be split into modules. Doing steps 1–5
inside one file will make it unmaintainable. Split first, at minimum into
`sources/` (steamgriddb, themes, iconify), `scanners/`, `desktop.py`, `ui/`.

**Flatpak `Exec` rewriting.** A Flatpak app's exported `.desktop` has an `Exec`
line referencing `/usr/bin/flatpak run ...`. Copying verbatim is correct — but
confirm that a copy in `~/.local/share/applications` actually takes precedence
over the Flatpak export on both KDE and GNOME. Test before shipping.

**Icon cache invalidation.** Changing the system icon theme changes what
`Icon=firefox` resolves to. The theme index cache must key on the active theme
as well as mtimes.

**Scope.** This roughly doubles the application's surface area. An alternative
worth considering is shipping step 2 alone as v1.2.0 — "assign a local icon file
to any installed app" — and deciding whether the online sources are wanted only
after that has been used for a while.

---

## 12. References

- Iconify API — https://iconify.design/docs/api/
- Iconify search query — https://iconify.design/docs/api/search.html
- freedesktop Desktop Entry Specification —
  https://specifications.freedesktop.org/desktop-entry-spec/latest/
- freedesktop Icon Theme Specification —
  https://specifications.freedesktop.org/icon-theme-spec/latest/
