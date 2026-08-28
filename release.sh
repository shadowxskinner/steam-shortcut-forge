#!/usr/bin/env bash
# release.sh — cut a release without the version drifting between files.
#
# The version now lives in exactly one place, kairo/__init__.py. pyproject
# reads it via dynamic metadata. Only PKGBUILD's pkgver has to be kept in
# step, because makepkg cannot import Python.
#
# Order matters: the git tag must exist on GitHub before updpkgsums runs,
# because updpkgsums downloads the tarball the tag creates.
#
# Usage:  ./release.sh 2.0.1

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

echo "==> Setting the version"
sed -i -E "s/^__version__ = \".*\"/__version__ = \"$VERSION\"/" kairo/__init__.py
sed -i -E "s/^pkgver=.*/pkgver=$VERSION/" PKGBUILD

# Read it back the way the build will, rather than trusting the sed.
ACTUAL="$(python -c 'import kairo; print(kairo.__version__)')"
[[ "$ACTUAL" == "$VERSION" ]] || { echo "error: kairo.__version__ is $ACTUAL" >&2; exit 1; }
grep -qF "pkgver=$VERSION" PKGBUILD || { echo "error: PKGBUILD did not update" >&2; exit 1; }
echo "    kairo.__version__ and pkgver both $VERSION"

echo "==> Tests"
python -m pytest -q

echo "==> Committing and tagging"
git commit -am "Release $VERSION"
git push
git tag -a "v$VERSION" -m "Release $VERSION"
git push origin "v$VERSION"

echo "==> Waiting for the GitHub tarball"
for _ in $(seq 1 10); do
    updpkgsums 2>/dev/null && break
    echo "    not ready yet, retrying in 3s"
    sleep 3
done

makepkg --printsrcinfo > .SRCINFO
git commit -am "Checksum and .SRCINFO for v$VERSION"
git push

echo
echo "Released v$VERSION"
grep -E '^pkgver|^sha256sums' PKGBUILD
