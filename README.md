# CTR on Dust 2

Crash Team Racing's kart, with the game's own driving code, on Counter-Strike 1.6's de_dust2.

- `engine/` is [ctr-native](https://github.com/CTR-tools/ctr-native) (the CTR decompilation as a
  native port, GPL-3.0) with a WebAssembly platform layer: the race, the kart physics, the
  collision, the AI and the renderer are the decompiled game code.
- `tools/` turns a model of Dust 2 into a CTR track (a level file the game loads in place of
  Dingo Canyon's).
- `web/` is the page that runs it.

## Playing

```sh
./play.sh
```

builds whatever is missing (the track from your disc and the model, then the game), serves it
on http://localhost:8642/ and opens it in Chrome. It needs:

- your own NTSC-U CTR disc image (SCUS-94426, a raw MODE2/2352 `.bin`), by default at
  `~/Documents/CTRDUST2/CTR - Crash Team Racing/CTR - Crash Team Racing.bin` (`CTR_DISC=...`);
- the "De_Dust 2 with real light" download from Sketchfab, by default at
  `~/Documents/CTRDUST2/dust-2-cs-16.zip` (`DUST2_ZIP=...`, or `DUST2_MODEL=...` for its `.glb`);
- for Aztec (free drive), Counter-Strike 1.6 installed through Steam: its map file is read
  directly (`CSTRIKE=...` for another install's `cstrike` folder); without it, the launcher's
  Aztec choice has nothing to load;
- Python 3 with numpy and Pillow, a C compiler (`cc`: on a Mac, Xcode's command line tools),
  Node.js, and a browser with WebAssembly JSPI (Chrome or Edge 137+). The first build fetches
  Emscripten 6.0.10 unless `$EMSDK` points at one.

The track takes a few minutes to build: besides turning the model into quadblocks, it renders
the level from ~12,000 camera spots to find where CTR's depth sort (it has no depth buffer)
would paint something behind a wall over it, and cuts those walls shorter (`tools/painter.py`).

Nothing from the disc is in this repository. The track `play.sh` writes (`build/lev/`) holds
data from your disc (Dust 2 is grafted onto Dingo Canyon's level, keeping its weapon crates,
fruit, start banner and skybox), so keep it to yourself.

The launcher has four modes:

- **Race**: an Arcade race against seven CTR racers, with weapon crates and wumpa fruit, on
  one of two loops, both starting on long A:
  - *Long A and mid* (Dust 2, ~33 s laps): long A, CT ramp, CT spawn, mid doors, mid, outside
    long, long doors;
  - *The long way* (Dust 2 Tunnels, ~47 s laps): long A, CT spawn, B doors, B site, the upper
    tunnels, T spawn, outside long, long doors.
- **Time Trial**: either loop alone against the clock.
- **Free drive**: a whole map without laps: Dust 2 (A site, B, the tunnels, T spawn) or Aztec
  (the river, the bridge, both sites), made from Counter-Strike 1.6's own map file.
- **CTR menus**: the whole game from its title screen, with Dust 2 in Dingo Canyon's place and
  Dust 2 Tunnels in Dragon Mines'.

The memory card (Time Trial records and ghosts, Adventure saves) is kept in the browser's
storage for the page.

## Controls (keyboard)

| | key | PS1 |
|---|---|---|
| Steer | arrows | D-pad |
| Gas | C | Cross |
| Brake / reverse | X | Square |
| Hop, power slide | Right Shift (hold through a turn) | R1 |
| Slide boost | Left Shift (the other shoulder) | L1 |
| Use item | V | Circle |
| Look back | A or Right Ctrl (hold) | R2 |
| Camera distance | Left Ctrl | L2 |
| Skip the intro | Z | Triangle |
| Pause | Enter | Start |
| Full screen | F11 | |
| Copy where you are (for bug reports) | P | |

A gamepad works too, with CTR's own buttons.

## Building by hand

```sh
python3 -I tools/build_dust2.py MODEL.glb DISC.bin build/lev   # the track
./build-web.sh                                                  # the game -> build/web
node tools/serve.mjs                                            # http://localhost:8642/
```

`?dust2&level=0&mode=1` boots straight into a race on Dust 2 (`mode=0` Time Trial,
`dust2=b` the tunnels loop, `dust2=free` free drive, `dust2=free&map=aztec` Aztec's free drive,
`character=N`, `laps=N`; `python3 -I tools/build_aztec.py CSTRIKE_DIR DISC.bin build/lev` builds
Aztec); without
`dust2`, `level=N` is any CTR track
(`enum LevelID` in `engine/include/namespace_Level.h`). `tools/e2e/` drives the game headless
(see its scripts' headers) and `NOTES.md` has what was learned on the way.

## Credits

- Crash Team Racing © 1999 Sony Computer Entertainment / Naughty Dog.
- [CTR-ModSDK](https://github.com/CTR-tools/CTR-ModSDK) and
  [ctr-native](https://github.com/CTR-tools/ctr-native): the decompilation and the native port.
- "De_Dust 2 with real light" by [Neo_minigan](https://sketchfab.com/neominigan),
  [CC-BY-4.0](http://creativecommons.org/licenses/by/4.0/),
  https://sketchfab.com/3d-models/de-dust-2-with-real-light-4ce74cd95c584ce9b12b5ed9dc418db5
- de_dust2 by Dave Johnston, for Valve's Counter-Strike.
