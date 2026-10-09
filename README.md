# CTR 1.6

Crash Team Racing's kart, with the game's own driving code, on Counter-Strike 1.6's maps,
built from the game's own map files: de_dust2, de_aztec and de_inferno so far. And on Bayview,
Need for Speed: Underground 2's city, from its PS2 disc: three loops of its streets (City Core,
Coal Harbor, Jackson Heights). For now every map is a free drive, no laps: pick one and drive
it round. Races come next, the same way for every map.

- `engine/` is [ctr-native](https://github.com/CTR-tools/ctr-native) (the CTR decompilation as a
  native port, GPL-3.0) with a WebAssembly platform layer: the kart physics, the collision and
  the renderer are the decompiled game code.
- `tools/build_map.py` turns a Counter-Strike 1.6 map into CTR level files: `tools/goldsrc.py`
  reads the map file (its geometry, textures and lighting), `tools/maps/` has what to change in
  each map for driving, and `tools/track.py` makes the level (quadblocks, stair ramps, the
  painter's audit, the files the game loads in place of Dingo Canyon's).
- `web/` is the page that runs it.

## Playing

```sh
./play.sh
```

builds whatever is missing (each map, then the game), serves it on http://localhost:8642/ and
opens it in Chrome. It needs:

- your own NTSC-U CTR disc image (SCUS-94426, a raw MODE2/2352 `.bin`), by default at
  `~/Documents/CTRDUST2/CTR - Crash Team Racing/CTR - Crash Team Racing.bin` (`CTR_DISC=...`);
- Counter-Strike 1.6, installed through Steam: the maps come from its map files (`CSTRIKE=...`
  for another install's `cstrike` folder);
- for Bayview (optional), your Need for Speed: Underground 2 disc image (PS2, NTSC-U,
  SLUS-21065, an `.iso`), by default at `~/Documents/NFSU2/Need for Speed - Underground 2
  (USA).iso` (`NFSU2_ISO=...`);
- Python 3 with numpy and Pillow, a C compiler (`cc`: on a Mac, Xcode's command line tools),
  Node.js, and a browser with WebAssembly JSPI (Chrome or Edge 137+). The first build fetches
  Emscripten 6.0.10 unless `$EMSDK` points at one.

A map takes a minute or two to build: besides turning it into quadblocks, it renders the level
from thousands of camera spots to find where CTR's depth sort (it has no depth buffer) would
paint something behind a wall over it, and cuts those walls shorter (`tools/painter.py`).

Nothing from the discs or from Counter-Strike is in this repository. The levels `play.sh` writes
(`build/lev/`) hold data from them (each map is grafted onto Dingo Canyon's level, keeping its
weapon crates and fruit, and for Counter-Strike's maps its skybox), so keep them to yourself.

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

A gamepad works too, with CTR's own buttons. Split screen takes up to four players, one gamepad
each past the first (with one gamepad, it drives player 1 and the keyboard player 2).

## Building by hand

```sh
python3 -I tools/build_map.py de_dust2 CSTRIKE_DIR DISC.bin build/lev   # a map
./build-web.sh                                                          # the game -> build/web
node tools/serve.mjs                                                    # http://localhost:8642/
```

Most of a map's build is the painter's-order audit (the game sorts faces instead of keeping a
depth buffer). `FAST=1` before the build command takes its cuts from the last full build
(`build/checks/`) for every polygon that hasn't changed instead of running it: for trying edits
quickly. Build in full before playing for real.

`?map=dust2` drives a map straight away (`&players=2` to 4, `&character=N`); `?level=N&mode=0`
boots a CTR track (`enum LevelID` in `engine/include/namespace_Level.h`). `tools/e2e/` drives
the game headless (the launcher, smoke tests, screenshots at places, an autopilot: see the
scripts' headers) and `NOTES.md` has what was learned on the way.

## Adding a map

A Counter-Strike 1.6 map is a module in `tools/maps/` named after its file (`de_dust2.py` for
`maps/de_dust2.bsp`) that says what to change for driving: its title, sky, texture density,
entities to leave out, textures to swap, its water, and anything Counter-Strike keeps players up
on with clip brushes, which the map file has no faces of (see `tools/maps/__init__.py`, and the
rope bridge in `de_aztec.py`). Free drive starts at the map's T spawn and places its pickups on
the way to the CT spawn and back. `play.sh` builds every map the install has, and the launcher
lists what's been built.

## Bayview

`tools/nfsu2/` reads Need for Speed: Underground 2's files from the disc image (its PS2 meshes,
textures, the props' placing, the night's light baked into vertex colours) and
`tools/build_bayview.py` makes a loop of streets a level: `python3 -I tools/build_bayview.py
NFSU2.iso CTR_DISC.bin build/lev AREA` (`--areas` lists them). A level holds 65,536
vertices, so each map is a stretch of the city along a loop, and what's by it. NOTES.md has
how the PS2 data is laid out.

## Credits

- Crash Team Racing © 1999 Sony Computer Entertainment / Naughty Dog.
- Counter-Strike © Valve. de_dust2 by Dave Johnston; de_aztec (textures by Chris Ashton) and
  de_inferno by Christopher "Narby" Auty.
- Need for Speed: Underground 2 © 2004 Electronic Arts, developed by EA Black Box.
- [CTR-ModSDK](https://github.com/CTR-tools/CTR-ModSDK) and
  [ctr-native](https://github.com/CTR-tools/ctr-native): the decompilation and the native port.
