#!/usr/bin/env bash
# Builds whatever is missing and opens the game in the browser.
#
#   ./play.sh
#
#   CTR_DISC=...     your NTSC-U CTR disc image, MODE2/2352 .bin
#                    (default: ~/Documents/CTRDUST2/CTR - Crash Team Racing/CTR - Crash Team Racing.bin)
#   DUST2_ZIP=...    the "De_Dust 2 with real light" download from Sketchfab
#                    (default: ~/Documents/CTRDUST2/dust-2-cs-16.zip)
#   DUST2_MODEL=...  or its de_dust_2_with_real_light.glb directly
#   PORT=8642
#   NO_OPEN=1        serve without opening a browser
#
# The level it writes (build/lev) holds data from your disc: keep it to yourself.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

DISC="${CTR_DISC:-$HOME/Documents/CTRDUST2/CTR - Crash Team Racing/CTR - Crash Team Racing.bin}"
ZIP="${DUST2_ZIP:-$HOME/Documents/CTRDUST2/dust-2-cs-16.zip}"
PORT="${PORT:-8642}"
URL="http://localhost:$PORT/"

die() { echo "play.sh: $*" >&2; exit 1; }

[ -f "$DISC" ] || die "no CTR disc image at '$DISC' (set CTR_DISC)"
command -v node >/dev/null || die "needs Node.js (https://nodejs.org)"
command -v python3 >/dev/null || die "needs Python 3"
python3 -I -c 'import numpy, PIL' 2>/dev/null || die "needs numpy and Pillow: python3 -m pip install numpy pillow"

# The model: the Sketchfab zip has it inside a second zip.
MODEL="${DUST2_MODEL:-$ROOT/work/model/de_dust_2_with_real_light.glb}"
if [ ! -f "$MODEL" ]; then
  [ -z "${DUST2_MODEL:-}" ] || die "no model at '$MODEL'"
  [ -f "$ZIP" ] || die "no Dust 2 model at '$ZIP' (set DUST2_ZIP or DUST2_MODEL)"
  echo "Unpacking the Dust 2 model..."
  mkdir -p "$ROOT/work/model"
  unzip -p "$ZIP" source/zone9_real_light.zip > "$ROOT/work/model/zone9_real_light.zip"
  unzip -o -q "$ROOT/work/model/zone9_real_light.zip" de_dust_2_with_real_light.glb -d "$ROOT/work/model"
  rm "$ROOT/work/model/zone9_real_light.zip"
fi

# The track, when it's missing or older than the tools that write it.
LEV="$ROOT/build/lev/dust2.lev"
if [ ! -f "$LEV" ] || [ -n "$(find tools -maxdepth 1 -name '*.py' -newer "$LEV" | head -1)" ]; then
  echo "Building the Dust 2 track (a few minutes)..."
  python3 -I tools/build_dust2.py "$MODEL" "$DISC" "$ROOT/build/lev"
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
