#!/usr/bin/env bash
# Builds the CTR engine (engine/, a ctr-native fork) to WebAssembly in build/web.
#
#   ./build-web.sh            optimized build
#   DEBUG=1 ./build-web.sh    assertions and debug info
#
# Uses $EMSDK if set, otherwise vab's pinned emsdk, otherwise .cache/emsdk.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ -z "${EMSDK:-}" ]; then
  for candidate in "$ROOT/.cache/emsdk" "$HOME/Documents/personales/vab/emulator/.cache/emsdk"; do
    if [ -x "$candidate/upstream/emscripten/emcc" ]; then EMSDK="$candidate"; break; fi
  done
fi
if [ -z "${EMSDK:-}" ]; then
  git clone https://github.com/emscripten-core/emsdk.git "$ROOT/.cache/emsdk"
  "$ROOT/.cache/emsdk/emsdk" install 6.0.10
  "$ROOT/.cache/emsdk/emsdk" activate 6.0.10
  EMSDK="$ROOT/.cache/emsdk"
fi
# shellcheck disable=SC1091
source "$EMSDK/emsdk_env.sh" >/dev/null 2>&1

OUT="$ROOT/build/web"
mkdir -p "$OUT"

VERSION="0.1.0-web"
BUILD_ID="$(git -C "$ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo dev)"

CFLAGS=(
  -std=c17
  -Iengine/include -Iengine
  -DCTR_NATIVE
  "-DCTR_NATIVE_VERSION=\"$VERSION\""
  "-DCTR_NATIVE_BUILD_ID=\"$BUILD_ID\""
  -Wno-constant-conversion
  -sUSE_SDL=3
)
LDFLAGS=(
  -sUSE_SDL=3
  -sMIN_WEBGL_VERSION=2 -sMAX_WEBGL_VERSION=2
  -sGL_ENABLE_GET_PROC_ADDRESS=1
  -sJSPI=1
  -sALLOW_MEMORY_GROWTH=1 -sINITIAL_MEMORY=128MB
  -sSTACK_SIZE=8MB
  -sFORCE_FILESYSTEM=1
  "-sEXPORTED_RUNTIME_METHODS=['FS','callMain']"
  -sINVOKE_RUN=0
  -sEXIT_RUNTIME=0
  --pre-js web/ctr-pre.js
)
if [ "${DEBUG:-0}" = "1" ]; then
  CFLAGS+=(-O1 -g)
  LDFLAGS+=(-O1 -g -sASSERTIONS=2)
else
  CFLAGS+=(-O2)
  LDFLAGS+=(-O2)
fi

emcc "${CFLAGS[@]}" -c engine/main.c -o "$OUT/main.o"
emcc "$OUT/main.o" "${LDFLAGS[@]}" -o "$OUT/ctr.js"
cp web/index.html "$OUT/index.html"
echo "built $OUT/ctr.js"
