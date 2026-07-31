# Maintainer: Shadow Skinner <shadowxskinner@gmail.com>
pkgname=steam-shortcut-forge
pkgver=1.1.1
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
sha256sums=('4e50da4151b21c81eb78a56c56ef6919487147e746e4aa1ca737b7effb757ecd')

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
