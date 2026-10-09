#!/usr/bin/env bash
# Builds whatever is missing and opens the game in the browser.
#
#   ./play.sh
#
#   CTR_DISC=...  your NTSC-U CTR disc image, MODE2/2352 .bin
#                 (default: ~/Documents/CTRDUST2/CTR - Crash Team Racing/CTR - Crash Team Racing.bin)
#   CSTRIKE=...   a Counter-Strike 1.6 install's cstrike folder, where the maps come from
#                 (default: Steam's, ~/Library/Application Support/Steam/steamapps/common/Half-Life/cstrike)
#   NFSU2_ISO=... your Need for Speed: Underground 2 disc image (PS2, NTSC-U), for Bayview
#                 (default: ~/Documents/NFSU2/Need for Speed - Underground 2 (USA).iso; none, no Bayview)
#   PORT=8642
#   NO_OPEN=1     serve without opening a browser
#
# The levels it writes (build/lev) hold data from your discs and from Counter-Strike's map
# files: keep them to yourself.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

DISC="${CTR_DISC:-$HOME/Documents/CTRDUST2/CTR - Crash Team Racing/CTR - Crash Team Racing.bin}"
CSTRIKE="${CSTRIKE:-$HOME/Library/Application Support/Steam/steamapps/common/Half-Life/cstrike}"
NFSU2_ISO="${NFSU2_ISO:-$HOME/Documents/NFSU2/Need for Speed - Underground 2 (USA).iso}"
PORT="${PORT:-8642}"
URL="http://localhost:$PORT/"

die() { echo "play.sh: $*" >&2; exit 1; }

[ -f "$DISC" ] || die "no CTR disc image at '$DISC' (set CTR_DISC)"
[ -d "$CSTRIKE/maps" ] || die "no Counter-Strike 1.6 at '$CSTRIKE' (set CSTRIKE)"
command -v node >/dev/null || die "needs Node.js (https://nodejs.org)"
command -v python3 >/dev/null || die "needs Python 3"
python3 -I -c 'import numpy, PIL' 2>/dev/null || die "needs numpy and Pillow: python3 -m pip install numpy pillow"

# Each map in tools/maps/ that the install has, when its level is missing or older than the
# tools that write it.
for cfg in tools/maps/de_*.py tools/maps/cs_*.py; do
  [ -f "$cfg" ] || continue
  map="$(basename "$cfg" .py)"
  if [ ! -f "$CSTRIKE/maps/$map.bsp" ]; then
    echo "Skipping $map: it isn't in $CSTRIKE/maps"
    continue
  fi
  lev="$ROOT/build/lev/${map#*_}_free.lev"
  if [ ! -f "$lev" ] || [ "$cfg" -nt "$lev" ] || [ -n "$(find tools -maxdepth 1 -name '*.py' -newer "$lev" | head -1)" ]; then
    echo "Building $map from Counter-Strike's map file (a minute or two)..."
    python3 -I tools/build_map.py "$map" "$CSTRIKE" "$DISC" "$ROOT/build/lev"
  fi
done

# Bayview's stretches, from Need for Speed: Underground 2's disc, the same way.
if [ -f "$NFSU2_ISO" ]; then
  for area in $(python3 -I tools/build_bayview.py --areas); do
    lev="$ROOT/build/lev/${area}_free.lev"
    if [ ! -f "$lev" ] || [ -n "$(find tools -maxdepth 2 -name '*.py' -newer "$lev" | head -1)" ]; then
      echo "Building $area from Need for Speed: Underground 2 (a minute or two)..."
      python3 -I tools/build_bayview.py "$NFSU2_ISO" "$DISC" "$ROOT/build/lev" "$area"
    fi
  done
fi

# The game, when it's missing or older than its sources.
WASM="$ROOT/build/web/ctr.wasm"
if [ ! -f "$WASM" ] || [ -n "$(find engine web/ctr-pre.js build-web.sh -type f -newer "$WASM" | head -1)" ]; then
  echo "Building the game (a few minutes the first time)..."
  ./build-web.sh
elif [ web/index.html -nt build/web/index.html ]; then
  cp web/index.html build/web/index.html
fi

open_browser() {
  # JSPI: Chrome or Edge 137+.
  if [ -n "${NO_OPEN:-}" ]; then
    return
  elif [ "$(uname)" = Darwin ]; then
    for app in "Google Chrome" "Microsoft Edge" "Chromium"; do
      if [ -d "/Applications/$app.app" ] || [ -d "$HOME/Applications/$app.app" ]; then open -a "$app" "$URL"; return; fi
    done
    open "$URL"
  elif command -v xdg-open >/dev/null; then
    xdg-open "$URL" >/dev/null 2>&1 &
  else
    echo "Open $URL in Chrome or Edge."
  fi
}

# Already serving? Then just open it.
if curl -s -I "$URL" 2>/dev/null | grep -qi '^x-ctr-dust2:'; then
  echo "Already running at $URL"
  open_browser
  exit 0
fi
if curl -s -o /dev/null "$URL" 2>/dev/null; then
  die "something else is using port $PORT: set PORT to another one"
fi

echo "Serving $URL (Ctrl-C to stop)"
CTR_DISC="$DISC" node tools/serve.mjs "$PORT" &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT INT TERM
for _ in $(seq 50); do
  curl -s -I "$URL" >/dev/null 2>&1 && break
  sleep 0.1
done
open_browser
wait $SERVER
