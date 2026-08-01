# Maintainer: Shadow Skinner <shadowxskinner@gmail.com>
pkgname=steam-shortcut-forge
pkgver=1.3.0
pkgrel=1
pkgdesc="Assign custom icons to Steam games in your Linux app launcher"
arch=('any')
url="https://github.com/shadowxskinner/steam-shortcut-forge"
license=('MIT')
depends=(
    'python>=3.10'
    'tk'
    'python-customtkinter'
    'python-pillow'
    'python-cairosvg'
)
makedepends=(
    'python-build'
    'python-installer'
    'python-setuptools'
    'python-wheel'
)
# Icon themes are read from disk, never bundled — they carry their own
# licenses (WhiteSur is GPL-3.0) and installing them is one command.
optdepends=(
    'papirus-icon-theme: large library of application icons to choose from'
    'whitesur-icon-theme: macOS Big Sur style application icons'
    'tela-icon-theme: flat colourful application icons'
)
source=("$pkgname-$pkgver.tar.gz::https://github.com/shadowxskinner/steam-shortcut-forge/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('eab72f35eb9084c7e795e2c25da1dad428d8746dd356baa0f0ba2c8f4a90da64')

build() {
    cd "$pkgname-$pkgver"
    python -m build --wheel --no-isolation
}

package() {
    cd "$pkgname-$pkgver"
    python -m installer --destdir="$pkgdir" dist/*.whl

    # Desktop file
    install -Dm644 steam-shortcut-forge.desktop \
        "$pkgdir/usr/share/applications/steam-shortcut-forge.desktop"

    # License
    install -Dm644 LICENSE \
        "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
