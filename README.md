# CTR on Dust 2

Crash Team Racing's kart, with the game's own driving code, on Counter-Strike 1.6's de_dust2.

- `engine/` is [ctr-native](https://github.com/CTR-tools/ctr-native) (the CTR decompilation as a
  native port, GPL-3.0) with a WebAssembly platform layer: the race, the kart physics, the
  collision and the renderer are the decompiled game code, unchanged.
- `tools/` builds the Dust 2 track (a CTR level file) from a model of the map.
- `web/` is the page that runs it.

## Building

```sh
./build-web.sh                 # engine -> build/web (Emscripten 6.0.10)
node tools/serve.mjs           # http://localhost:8642/
```

The game needs your own NTSC-U CTR disc image (SCUS-94426, a raw MODE2/2352 `.bin`). The server
hands it to the page from `$CTR_DISC` (default:
`~/Documents/CTRDUST2/CTR - Crash Team Racing/CTR - Crash Team Racing.bin`). Nothing from the
disc is in this repository.

`?level=N&mode=0` boots straight into a Time Trial on track `N` (`enum LevelID` in
`engine/include/namespace_Level.h`); `mode=1` is an Arcade race.

## Controls (keyboard)

| PS1 | key |
|---|---|
| Cross (gas) | C |
| Square (brake) | X |
| Circle (item) | V |
| Triangle | Z |
| L1 / R1 (hop, power slide) | Shift |
| L2 | Ctrl |
| D-pad | arrows |
| Start | Enter |
| Select | Space |

A gamepad works too.

## Credits

- Crash Team Racing © 1999 Sony Computer Entertainment / Naughty Dog.
- [CTR-ModSDK](https://github.com/CTR-tools/CTR-ModSDK) and
  [ctr-native](https://github.com/CTR-tools/ctr-native): the decompilation and the native port.
- "De_Dust 2 with real light" by [Neo_minigan](https://sketchfab.com/neominigan),
  [CC-BY-4.0](http://creativecommons.org/licenses/by/4.0/),
  https://sketchfab.com/3d-models/de-dust-2-with-real-light-4ce74cd95c584ce9b12b5ed9dc418db5
- de_dust2 by Dave Johnston, for Valve's Counter-Strike.
