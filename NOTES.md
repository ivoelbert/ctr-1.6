# Notes

What was learned building Dust 2 for CTR, and what's left. The code has the details; this is
the map.

## The engine (engine/, ctr-native fc3fa26 + changes)

- 32-bit only (the decompiled game keeps 32-bit pointers in data): WebAssembly is 32-bit, so
  the web build works where a 64-bit native build wouldn't. JSPI suspends the game's blocking
  loop at each VBlank wait; `web/ctr-pre.js` counts VBlanks off requestAnimationFrame.
- Our changes are marked `NOTE(web)` / `NOTE(ctr-dust2)`:
  - `platform/native_web.c`: boot override (`?level=&mode=`), test hooks (`window.ctr`).
  - `platform/native_cd.c`: `assets/override/NNN.bin` replaces BIGFILE entry NNN.
  - `platform/native_memory.c`: 16 MiB heap (`CTR_DUST2_EXPANDED_MEMPACK`).
  - `platform/native_renderer.c` + `native_gpu.c`: `TF_VIRTUAL_ATLAS`, tpage colour mode 3
    samples `/assets/dust2/atlas.rgba`; CLUT = layer << 10 | (y / 32) << 5 | (x / 32).
  - `LOAD_IsCustomLevel`: overridden levels get 2.5 MB of primitive memory and a 64000-word
    clip buffer (everything is visible from everywhere, unlike retail's PVS).

## LEV files (tools/ctrlev.py reads, tools/levwriter.py writes)

- u32 data size, data (pointers as data offsets), u32 map byte count, pointer slot offsets.
  Null pointers must stay out of the map.
- Quadblock: 3x3 vertices (0 4 1 / 5 6 7 / 2 8 3); a triangle repeats slots 2, 6, 2 in 3, 7, 8.
  Collision front face is (p2 - p0) x (p1 - p0); collision is one-sided.
- Normal dividends: (4096 << shift) / |edgeA x edgeB| (low LOD: cross >> 2), largest shift
  keeping s16 -- matches retail exactly.
- Floors 0x1800 (GROUND | CAMERA_SEARCH), walls 0x2000; flags 0 = drawn but never collided;
  no textures = collided but never drawn (stair ramps, kill plane 0x2200).
- blockID is the quadblock's bit in the visibility list.
- Texture layouts: (u0v0, u1v1, u2v2, u3v3) = face corners (0,4,5,6), (4,1,6,7), (5,6,2,8),
  (6,7,8,3) with face flags 0. The "mosaic" word (layout + 0x24) is tested as a heap pointer:
  keep CLUTs >= 1024 (atlas cells start at 1).
- Must-haves: an AnimTex list that points to itself; SpawnType1 with 7 null slots after it
  (GhostReplay reads slots 4 and 5 regardless of count).
- Time Trial and Relic load entry 8 * level + 7; 1P races + 1, 2P + 3, 4P + 5. Each mode
  also loads its own texture file (the VRM, the entry before), with its own VRAM layout and
  some of the mode's HUD textures: a LEV's model texture layouts only match its own mode's
  VRM. So Dust 2 is grafted onto each of Dingo Canyon's four LEVs (`MODES`), and the page
  loads all four. (One 1P LEV in every mode gave pink, then vanishing, crates in split screen;
  loading the 1P VRM everywhere fixed those but broke the 2P HUD's fruit.)
- Instances draw only if their flags have the bit for the player count (`sdata->LOD`: 1P 1,
  2P 2, 3-4P 4, relic 8).
- The minimap: SpawnType1 slot 0 is a struct UIMap (world range, icon size and start, rotation)
  and the image is two global icons ('map-proto8-01'/'-02') that share one 80x40 4-bit image
  in the mode's VRM, each half through its own palette (high/low two bits of a texel). A VRM
  is two raw 16-bit VRAM blocks, so build_dust2 redraws the texels and palettes (slate
  floors, the loop in white) in a copy of each mode's VRM; the page loads those too.
- Laps: distToFinish (x8) must exceed 32000 at the line; a lap counts when it jumps from
  < 1200 to > 32000. Checkpoint indices are u8 (255 = none). Mask grab fires on GROUND
  quadblocks that jump more than a quarter lap ahead of the last valid one.
- AI: LevNavTable -> 3 NavHeaders (magic -0x1303) + 20-byte frames; frame 0x12 is the
  checkpoint index; pathChangeOpcode = path << 10 | frame (3072 = none) for overtaking.
- Instances: behaviour comes from the model id's LInB. Level instances are drawn through the
  camera's visInstSrc list (PVS), which LevInstDef_UnPack toggles InstDef<->Instance once per
  referencing quadblock: share it an odd number of times. Pickups need hitboxes in BSP leaves
  (flag 0x4C0, radius, radius^2, centre above the instance, InstDef pointer).

## Dust 2 (tools/build_dust2.py)

- Model: "De_Dust 2 with real light" (Neo_minigan, CC-BY-4.0): 9061 triangles in Hammer
  units, 11 baked 1024^2 atlases. Hammer (x, y, z) -> CTR 4 * (x + 320, z, -(y - 1120)).
- Stairs get invisible ramps (tools/stairs.py); mid doors and long doors swing open.
- The model's light baking left ~270 faces (mostly) black: they take a texel from around them
  (`fill_black_faces`), as dim as their surroundings.
- Free drive's checkpoint nodes each point at a twin straight above: the wrong-way test
  compares the heading with the way between a node's next two nodes, which is then vertical.
- Karts are shaded by the vertex colours of the floor under them, so floors carry the model's
  baked light as vertex colours (sunlit sand = 0x60, full light); the atlas shader leaves
  vertex colours out, so they only light the karts. Stair ramps take the nearest floor's.
- Two race loops (`LOOPS`), both starting on long A heading north: round the block between T
  ramp and mid (outside long, long doors, long A, CT ramp, CT spawn, mid doors, mid; 36034
  units), and the long way round (long A, CT spawn, B doors, B site, upper tunnels, T spawn,
  outside long; 52036 units). Each is its own LEV (dust2.lev, dust2_b.lev); the page loads
  the chosen one into Dingo Canyon's slot and renames it. A slot's eight BIGFILE entries can
  take any of them: the CTR menus mode puts the tunnels loop in Dragon Mines' slot too.
- Floors near a loop that the nav grid doesn't reach take the nearest route point's checkpoint
  (`ROUTE_REACH`); pickups without floor at their spot take the nearest drivable one.
- Grafted onto Dingo Canyon (entry 1): its models, skybox, textures; 16 crates, 16 fruit.

## Tools

- `tools/navgrid.py` drivable grid + A*, `tools/route.py`, `tools/floor_map.py` (maps),
  `tools/inspect_region.py` (a zoomed floor map with a trace).
- `tools/e2e`: `pursuit.mjs` (autopilot round a route, laps, items), `trace.mjs`,
  `tour.mjs`/`view.mjs` (screenshots at places), `probe.mjs`.

## Left to do

- Track select previews and menu maps still show Dingo Canyon's and Dragon Mines'.
- A two-level edge at A site (CTR ~6300, -6700): its stair ramp covers the first 64 units of
  128, so a kart can't climb it there (free drive only; the slope just east of it works).
- Driving off-centre round both loops (`OFFSET`) and a tour of every landmark (`CONTINUE`)
  found no snags beyond real obstacles (crates, the 90-degree corner at the top of long A).
- 2P/4P: work (tested with fake gamepads, `tools/e2e/lib.mjs`). With one gamepad, the gamepad
  is player 1 and the keyboard player 2.
