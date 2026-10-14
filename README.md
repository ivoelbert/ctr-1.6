# CTR 1.6

Crash Team Racing's kart, with the game's own driving code, on Counter-Strike 1.6's maps,
built from the game's own map files: de_dust2, de_aztec and de_inferno so far. And on two whole
cities from their PS2 discs, streamed in as you drive: Bayview, Need for Speed: Underground 2's,
about five kilometres across, and Vice City, Grand Theft Auto: Vice City's, every island of it.
For now every map is a free drive, no laps: pick one and drive it round. Races come next, the
same way for every map.

- `engine/` is [ctr-native](https://github.com/CTR-tools/ctr-native) (the CTR decompilation as a
  native port, GPL-3.0) with a WebAssembly platform layer: the kart physics, the collision and
  the renderer are the decompiled game code.
- `tools/build_map.py` turns a Counter-Strike 1.6 map into CTR level files: `tools/goldsrc.py`
  reads the map file (its geometry, textures and lighting), `tools/maps/` has what to change in
  each map for driving, and `tools/track.py` makes the level (quadblocks, stair ramps, the
  painter's audit, the files the game loads in place of Dingo Canyon's).
- `web/` is the page that runs it; `web/editor/` the track editor (`tools/editor/` its field).

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
- for the THPS4 levels (optional), Tony Hawk's Pro Skater 4 for PC: its `data/levels` folder
  in `~/Documents/THPS4/data` (`THPS4_DATA=...`; see below);
- for Vice City (optional), your Grand Theft Auto: Vice City disc image (PS2, NTSC-U,
  SLUS-20552, an `.iso`), by default at `~/Documents/GTAVC/Grand Theft Auto - Vice City.iso`
  (`GTAVC_ISO=...`);
- Python 3 with numpy and Pillow, a C compiler (`cc`: on a Mac, Xcode's command line tools),
  Node.js, and a browser with WebAssembly JSPI (Chrome or Edge 137+). The first build fetches
  Emscripten 6.0.10 unless `$EMSDK` points at one.

A map takes a minute or two to build: besides turning it into quadblocks, it renders the level
from thousands of camera spots to find where CTR's depth sort (it has no depth buffer) would
paint something behind a wall over it, and cuts those walls shorter (`tools/painter.py`).

Nothing from the discs or from Counter-Strike is in this repository. The levels `play.sh` writes
(`build/lev/`) hold data from them (each map is grafted onto Dingo Canyon's level, keeping its
weapon crates and fruit, and for Counter-Strike's maps its skybox), so keep them to yourself.

## The track editor

The launcher's **Track editor** (or http://localhost:8642/?editor) builds your own tracks, a
piece at a time, Trackmania style: roads, curves, slopes, banked turns, half pipes, jumps, boost
pads, quarter pipes, platforms, blocks, decorations, on the block grid or anywhere at any angle
(grid snap off), every piece's shape and textures to change, and **Tab** drives the track at
once (it's compiled in the page and swapped into the running race: no loading) and brings you
back. Lay a loop from the Start / finish round to it and laps count. `H` in the editor lists the
keys. Tracks are saved in `tracks/` (`Ctrl+S`), and the launcher lists them to drive or edit.
Everything in them is the editor's own (its textures are drawn by code), so a track is yours to
share.

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
rope bridge in `de_aztec.py`). Free drive starts at the map's T spawn, with no pickups (they're
for races and battles). `play.sh` builds every map the install has, and the launcher
lists what's been built.

## Bayview

`tools/nfsu2/` reads Need for Speed: Underground 2's files from the disc image (its PS2 meshes,
textures, the props' placing, the night's light baked into vertex colours) and
`tools/build_bayview.py` makes a loop of streets a level (`--areas` lists them). A CTR level's
positions are 16-bit, about a kilometre across, so `tools/build_world.py` builds the whole city
as 256 m tiles (`python3 -I tools/build_world.py NFSU2.iso CTR_DISC.bin build/lev bayview`,
which `play.sh` runs): the game puts the 3 x 3 round the kart together as the level, fetches
the next ones as it drives, and moves everything back round the origin as it crosses into a
new tile (`engine/platform/native_world.c`). It starts on City Core's loop. NOTES.md has how
the PS2 data is laid out.

## Vice City

`tools/vicecity/` reads Grand Theft Auto: Vice City's map from the disc image: the map files'
placements, the RenderWare models and texture dictionaries in their PS2 form, and the sea, which
the game draws at one level wherever the ground is lower (here it's water you drive on). The
same world builder makes it tiles (`python3 -I tools/build_world.py GTAVC.iso CTR_DISC.bin
build/lev vicecity`, which `play.sh` runs). It starts on Ocean Drive. NOTES.md has how the PS2
data is laid out.

## Tony Hawk's Pro Skater 4

`tools/thps4/` reads the PC version's levels (Aspyr's port: Neversoft's Xbox formats) from the
game's data folder: textures (DXT), the scene (materials, sectors, triangle strips) and each
level's script (its restart points: the start). Every level is a world of its own
(`python3 -I tools/build_world.py THPS4_DATA CTR_DISC.bin build/lev thps4_alc`, which `play.sh`
runs for each): College, San Francisco, Alcatraz, Kona, Shipyard, London, Zoo, Carnival,
Chicago, the motocross track and the skate shop. On the PC install disc the files are in the Mac
(HFS) partition: copy `data/levels` from the mounted disc (or from an installed game) to
`~/Documents/THPS4/data/levels` (`THPS4_DATA=...`).

## Credits

- Crash Team Racing © 1999 Sony Computer Entertainment / Naughty Dog.
- Counter-Strike © Valve. de_dust2 by Dave Johnston; de_aztec (textures by Chris Ashton) and
  de_inferno by Christopher "Narby" Auty.
- Need for Speed: Underground 2 © 2004 Electronic Arts, developed by EA Black Box.
- Grand Theft Auto: Vice City © 2002 Rockstar Games, developed by Rockstar North.
- Tony Hawk's Pro Skater 4 © 2002 Activision, developed by Neversoft; PC version by Aspyr.
- [CTR-ModSDK](https://github.com/CTR-tools/CTR-ModSDK) and
  [ctr-native](https://github.com/CTR-tools/ctr-native): the decompilation and the native port.
