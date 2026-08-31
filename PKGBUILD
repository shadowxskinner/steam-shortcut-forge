# Maintainer: Shadow Skinner <shadowxskinner@gmail.com>
pkgname=kairo
_appid=io.github.shadowxskinner.Kairo
pkgver=2.3.2
pkgrel=1
pkgdesc="Automatic launcher artwork for Linux"
arch=('any')
url="https://github.com/shadowxskinner/kairo"
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
# Renamed from steam-shortcut-forge in 2.0.0. Without these three, pacman
# leaves both packages installed and they fight over the same .desktop file.
provides=('steam-shortcut-forge')
conflicts=('steam-shortcut-forge')
replaces=('steam-shortcut-forge')
# Icon themes are read from disk, never bundled - they carry their own
# licenses (WhiteSur is GPL-3.0) and installing them is one command.
optdepends=(
    'papirus-icon-theme: large library of application icons to choose from'
    'whitesur-icon-theme: macOS Big Sur style application icons'
    'tela-icon-theme: flat colourful application icons'
)
source=("$pkgname-$pkgver.tar.gz::https://github.com/shadowxskinner/kairo/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('SKIP')

build() {
    cd "$pkgname-$pkgver"
    python -m build --wheel --no-isolation
}

check() {
    cd "$pkgname-$pkgver"
    python -m pytest -q
}

package() {
    cd "$pkgname-$pkgver"
    python -m installer --destdir="$pkgdir" dist/*.whl

    install -Dm644 io.github.shadowxskinner.Kairo.desktop \
        "$pkgdir/usr/share/applications/io.github.shadowxskinner.Kairo.desktop"

    for _size in 512 256 128 64 48 32 24 16; do
        install -Dm644 "icons/hicolor/${_size}x${_size}/apps/$_appid.png" \
            "$pkgdir/usr/share/icons/hicolor/${_size}x${_size}/apps/$_appid.png"
    done

    install -Dm644 LICENSE \
        "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
