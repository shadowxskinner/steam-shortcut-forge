#!/usr/bin/env bash
# Builds the optional KWin blur bridge in this directory; installs nothing.
set -euo pipefail
cd "$(dirname "$0")"

XML="/usr/share/wayland-protocols/staging/ext-background-effect/ext-background-effect-v1.xml"
if [ ! -f "$XML" ]; then
  echo "missing: $XML"
  exit 1
fi
for tool in wayland-scanner gcc pkg-config; do
  command -v "$tool" >/dev/null || { echo "missing: $tool"; exit 1; }
done

wayland-scanner client-header "$XML" ext-background-effect-v1-client-protocol.h
wayland-scanner private-code "$XML" ext-background-effect-v1-protocol.c
gcc -shared -fPIC -O2 -Wall -Wextra -Werror -o libkairoblur.so \
    blur.c ext-background-effect-v1-protocol.c \
    $(pkg-config --cflags --libs wayland-client)
echo "built: $(pwd)/libkairoblur.so"
