# Releasing Kairo

Kairo's source package must never claim a release that does not exist. The
repository PKGBUILD therefore stays at `_unreleased=1` until the version has a
real Git tag and the archive produced from that tag has been hashed.

## Release checklist

1. Confirm `kairo.__version__` and `pkgver` contain the intended version.
2. Run the full test suite with Qt's offscreen platform.
3. Build the wheel once and inspect its metadata and entry points.
4. Install that wheel into one clean environment and verify `kairo --help`,
   `kairo --version`, `kairo-qt`, the Qt import, and the optional `kairo-tk`
   dependency error.
5. Validate the desktop entry and run the application on a real KDE Wayland
   desktop, including blur, rapid navigation and close-during-work checks.
6. Commit the release candidate, create the signed `v<version>` tag, and push
   the commit and tag.
7. Download the tag archive named by `source=()` in PKGBUILD and verify it
   exists before changing the package state.
8. Run `updpkgsums` so `sha256sums` contains the archive's real checksum.
9. Set `_unreleased=0`, then run `makepkg --cleanbuild --syncdeps --install`
   and inspect the result with `namcap` where available.
10. Commit the release PKGBUILD and publish the release notes and package.

Never replace the checksum with a value calculated from a working tree or a
different archive. Never change `_unreleased` to zero while `sha256sums`
contains `SKIP`.
