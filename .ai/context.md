# Kairo Shared Context

## Purpose

Kairo is a Linux desktop application that discovers Steam games, registered desktop applications, and configured emulator libraries, then lets the user preview and apply launcher artwork.

## Durable Safety Invariants

- Launcher changes are user-level: Kairo either creates a launcher it owns or writes a user-level override for an existing launcher. It does not require root.
- System and vendor `.desktop` files are never edited. Overrides live in the user's XDG applications directory and preserve launcher content except for `Icon=` in `[Desktop Entry]` and ownership metadata.
- Authority to overwrite, restore, or delete comes from the ownership marker in the live launcher file—not from its filename or a historical record.
- Both current `X-Kairo-*` and legacy `X-ShortcutForge-*` marker keys remain recognized so pre-rename changes stay restorable.
- Resetting artwork on a Kairo-generated launcher preserves the launcher. Removing the launcher is a separate, explicitly destructive operation.
- Launcher updates use same-directory atomic replacement to avoid truncated entries.

## Compatibility and Migration

- Migration from Steam Shortcut Forge copies legacy configuration and icons, moves only generated launchers whose ownership can be proven, and leaves foreign, colliding, malformed, or unreadable entries untouched.
- Legacy configuration and data directories remain available for downgrade safety. Cleanup of legacy leftovers is never automatic.

## Verification Safety

- Tests use an isolated HOME and must never read or write the developer's real configuration, icon store, or applications directory.
