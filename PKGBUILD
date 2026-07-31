# Maintainer: Shadow Skinner <shadowxskinner@gmail.com>
pkgname=steam-shortcut-forge
pkgver=1.1.0
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
)
makedepends=(
    'python-build'
    'python-installer'
    'python-setuptools'
    'python-wheel'
)
source=("$pkgname-$pkgver.tar.gz::https://github.com/shadowxskinner/steam-shortcut-forge/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('2c84b8981445de3798508b55bce07212bae1821f1df42de2f496e82ac4223bb1')

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
