#!/usr/bin/env bash
# release.sh — cut a release without the version drifting between files.
#
# The version lives in three places (pyproject.toml, PKGBUILD, and
# APP_VERSION in the source). Bumping them by hand has silently gone wrong
# on every release so far, producing tags whose tarballs contain the
# previous version's code. This does all three, in the right order.
#
# Order matters: the git tag must exist on GitHub before updpkgsums runs,
# because updpkgsums downloads the tarball that the tag creates.
#
# Usage:  ./release.sh 1.1.2

set -euo pipefail

VERSION="${1:-}"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "usage: ./release.sh X.Y.Z" >&2
    exit 1
fi

cd "$(dirname "$0")"

if [[ -n "$(git status --porcelain)" ]]; then
    echo "error: working tree is dirty — commit or stash first" >&2
    exit 1
fi

if [[ "$(git rev-parse --abbrev-ref HEAD)" != "main" ]]; then
    echo "error: releases are cut from main" >&2
    exit 1
fi

if git rev-parse "v$VERSION" >/dev/null 2>&1; then
    echo "error: tag v$VERSION already exists" >&2
    exit 1
fi

echo "==> Bumping all three version strings to $VERSION"
sed -i -E "s/^pkgver=.*/pkgver=$VERSION/"            PKGBUILD
sed -i -E "s/^version = \".*\"/version = \"$VERSION\"/" pyproject.toml
sed -i -E "s/^APP_VERSION = \".*\"/APP_VERSION = \"$VERSION\"/" steam_shortcut_forge.py

# Fail loudly rather than shipping a mismatch.
for check in "PKGBUILD:pkgver=$VERSION" \
             "pyproject.toml:version = \"$VERSION\"" \
             "steam_shortcut_forge.py:APP_VERSION = \"$VERSION\""; do
    file="${check%%:*}"; expect="${check#*:}"
    grep -qF "$expect" "$file" || { echo "error: $file did not update" >&2; exit 1; }
done
echo "    all three agree"

python -m py_compile steam_shortcut_forge.py
echo "    py_compile ok"

echo "==> Committing and tagging"
git commit -am "Bump version to $VERSION"
git push
git tag -a "v$VERSION" -m "Release $VERSION"
git push origin "v$VERSION"

echo "==> Waiting for the GitHub tarball to become available"
for _ in $(seq 1 10); do
    if updpkgsums 2>/dev/null; then
        break
    fi
    echo "    not ready yet, retrying in 3s"
    sleep 3
done

makepkg --printsrcinfo > .SRCINFO
git commit -am "Checksum and .SRCINFO for v$VERSION"
git push

echo
echo "Released v$VERSION"
grep -E '^pkgver|^sha256sums' PKGBUILD
