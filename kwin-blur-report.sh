#!/usr/bin/env bash
# What your compositor's blur is currently set to. Read-only: reads config and
# queries KWin over D-Bus, writes nothing, changes nothing.
set -u

echo "=============================================================="
echo " Session"
echo "=============================================================="
echo "  type    : ${XDG_SESSION_TYPE:-?}    desktop: ${XDG_CURRENT_DESKTOP:-?}"
command -v plasmashell >/dev/null && echo "  plasma  : $(plasmashell --version 2>/dev/null | tail -1)"

echo
echo "=============================================================="
echo " Is the stock Blur effect loaded?"
echo "=============================================================="
for tool in qdbus6 qdbus-qt6 qdbus; do
  if command -v "$tool" >/dev/null 2>&1; then
    "$tool" org.kde.KWin /Effects org.kde.kwin.Effects.loadedEffects 2>/dev/null \
      | tr ' ' '\n' | grep -i blur | sed 's/^/  loaded: /' && break
  fi
done || true
echo "  (no output above means the query failed or no blur effect is loaded)"

echo
echo "=============================================================="
echo " Current blur settings in ~/.config/kwinrc"
echo "=============================================================="
if [ -f "$HOME/.config/kwinrc" ]; then
  awk '/^\[Effect-blur\]/{f=1;print;next} /^\[/{f=0} f' "$HOME/.config/kwinrc" \
    | sed 's/^/  /'
  grep -q '^\[Effect-blur\]' "$HOME/.config/kwinrc" \
    || echo "  no [Effect-blur] section — every value is at its default"
else
  echo "  no kwinrc yet — every value is at its default"
fi

echo
echo "=============================================================="
echo " Which keys that section accepts"
echo "=============================================================="
echo "  Read from the effect's own schema rather than from memory:"
found=0
for path in /usr/share/kwin/effects /usr/lib/qt6/plugins/kwin/effects \
            /usr/share/kconfig /usr/share/config.kcfg; do
  [ -d "$path" ] || continue
  while IFS= read -r file; do
    found=1
    echo "  $file"
    grep -oE 'name="[A-Za-z]+"' "$file" 2>/dev/null | sed 's/name=//;s/"//g;s/^/      /' | sort -u
  done < <(grep -rl -i "blur" "$path" --include="*.kcfg" 2>/dev/null)
done
if [ "$found" -eq 0 ]; then
  echo "  No blur .kcfg found on this system. The settings dialog is the"
  echo "  authoritative list:  System Settings -> Desktop Effects -> Blur -> gear icon"
fi

echo
echo "Nothing was written. To change anything, use System Settings so KWin"
echo "reloads the effect itself."
