#!/usr/bin/env bash
# Builds the blur shim. Compiles into this directory only; installs nothing.
set -euo pipefail
cd "$(dirname "$0")"

XML=""
for candidate in \
  /usr/share/wayland-protocols/staging/ext-background-effect/ext-background-effect-v1.xml \
  /usr/share/wayland-protocols/staging/background-effect/ext-background-effect-v1.xml
do
  [ -f "$candidate" ] && XML="$candidate" && break
done

if [ -z "$XML" ]; then
  echo "ext-background-effect-v1.xml not found."
  echo
  echo "It ships with wayland-protocols. Check what you have:"
  echo "    pacman -Q wayland-protocols"
  echo "    find /usr/share/wayland-protocols -name '*background-effect*'"
  echo
  echo "If it is genuinely absent your wayland-protocols is older than the"
  echo "protocol. Nothing has been installed; tell me and we will decide."
  exit 1
fi
echo "protocol XML : $XML"

for tool in wayland-scanner gcc pkg-config; do
  command -v "$tool" >/dev/null || { echo "missing: $tool"; exit 1; }
done

wayland-scanner client-header "$XML" ext-background-effect-v1-client-protocol.h
wayland-scanner private-code  "$XML" ext-background-effect-v1-protocol.c

gcc -shared -fPIC -O2 -Wall -Wextra -Werror -o libkairoblur.so \
    blur.c ext-background-effect-v1-protocol.c \
    $(pkg-config --cflags --libs wayland-client)

echo "built: $(pwd)/libkairoblur.so"
