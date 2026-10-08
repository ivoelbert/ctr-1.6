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
  - `platform/native_memory.c`: 32 MiB heap (`CTR_DUST2_EXPANDED_MEMPACK`).
  - `platform/native_renderer.c` + `native_gpu.c`: `TF_VIRTUAL_ATLAS`, tpage colour mode 3
    samples `/assets/dust2/atlas.rgba`; CLUT = layer << 10 | (y / 32) << 5 | (x / 32).
  - `LOAD_IsCustomLevel`: overridden levels get 2.5 MB of primitive memory and a 64000-word
    clip buffer (everything is visible from everywhere, unlike retail's PVS).

- The level has no depth buffer (painter's algorithm). Each face goes into an ordering-table
  slot by its farthest corner's depth >> 6 (plus its draw-order byte); a face subdivided near
  the camera passes its slot to its sub-faces (`inheritedOtIndex`), so subdivision doesn't
  sharpen the sort. The slots are painted far to near, and inside a slot the faces of the
  quadblock drawn first end up on top (each is linked in at the head). Quadblocks are drawn
  leaf by leaf in render-list order, and `RenderLists.c` lists the leaves in reverse walk
  order: retail's fixed walk lets child 0's side win every tie. Branches our levwriter marks
  (`BSP_NEAR_FIRST` in childID[2]; retail has 0 there) are walked near side first, so ties go
  to the nearer side. Long faces seen along their length still sort by their far end: see
  `tools/painter.py` for how the track builder cuts the walls where that shows.
- `native_gpu.c` batches a frame's vertices in a 65536-vertex array and the primitive handlers
  write without checking its end: a heavy Dust 2 frame (the long doors, after the painter cuts)
  went past it into the globals behind it (garbled HUD, kart, minimap, then a black screen).
  `ParsePrimitive` now draws the batch when it's nearly full (as before a VRAM move).
- The quadblocks the renderer defers to its near pass are listed 64 per player in
  `sdata_static.quadBlocksRendered`, unchecked too; a Dust 2 view lists up to ~60. Each player
  now gets a host list as long as the level's quadblocks (`CTR_RenderLists.c`).
- 1-pixel cracks between neighbouring faces (T-junctions, neighbours subdivided differently,
  whole-pixel vertices): `native_gpu.c` pushes every atlas polygon's edges out by 0.6 pixels
  (a per-vertex offset the atlas vertex shader applies), so neighbours overlap.
- The canvas has no alpha channel (`SDL_GL_ALPHA_SIZE` 0): the frame reaches the screen with
  VRAM's mask bit as alpha, and in a real Chrome window on macOS every pixel without the bit
  (the level, the HUD) showed the black page instead. Headless screenshots go through Chrome's
  own compositor and looked fine, so they can't catch this: check the context attributes.

## LEV files (tools/ctrlev.py reads, tools/levwriter.py writes)

- u32 data size, data (pointers as data offsets), u32 map byte count, pointer slot offsets.
  Null pointers must stay out of the map.
- Quadblock: 3x3 vertices (0 4 1 / 5 6 7 / 2 8 3); a triangle repeats slots 2, 6, 2 in 3, 7, 8.
  Collision front face is (p2 - p0) x (p1 - p0); collision is one-sided.
- Normal dividends: (4096 << shift) / |edgeA x edgeB| (low LOD: cross >> 2), largest shift
  keeping s16 -- matches retail exactly.
- Floors 0x1800 (GROUND | CAMERA_SEARCH), walls 0x2000; flags 0 = drawn but never collided;
  no textures = collided but never drawn (stair ramps, kill plane 0x2200).
- blockID gives the quadblock's bit in the visibility list, retail-style: each run of 32
  quadblocks is numbered backwards (index 0 is 31), and the face list holds index i at bit
  (i & 31). The renderer reads the word at (blockID >> 3) & 0x1fc bytes: only 4096 quadblocks
  have bits of their own, and quadblock i shares the bit of i mod 4096. Dust 2 has 16,000, so
  every bit is set (clearing one to hide a stair ramp hid three other quadblocks: holes in
  walls and floors), and collision-only quadblocks hide by their texture instead (layer 15).
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
- The painter's audit (`tools/painter.py`, `tools/painter.c`, compiled with `cc` during the
  build): the level is rendered at half resolution from the chase camera at every 4th drivable
  grid cell in 8 directions (~12,000 views), once with a depth buffer and once checking the
  game's slots, and the polygons whose quadblocks have things behind them painted over them
  (40 pixels or more in all) are cut to 256 units, then the ones still at it to 128. Out of
  order pixels: 326,000 before (the fixed walk, uncut walls), 48,000 after; ~800 more
  quadblocks, 61,600 of the 65,536 vertices. The A-site crates no longer show through the
  wall of long A.

## Counter-Strike 1.6 maps (tools/goldsrc.py, tools/build_aztec.py)

- The game's own map files (GoldSrc BSP 30) carry everything the Sketchfab model of Dust 2 was
  made from: convex faces with a texture mapping, the textures (8-bit + palette, in the map or
  in WADs) and baked light (RGB samples every 16 texels per face, per light style). goldsrc.bake
  gives each face a chart in 1024^2 atlas layers, texture times light, so the rest of the Dust 2
  pipeline takes it as it took the model.
- Light grids: the size of a face's grid follows the engine's float arithmetic (each texture
  coordinate summed in double, stored as a float); in double precision a few hundred faces per
  map read the wrong samples. With it, every face's grid tiles the lighting lump exactly.
- Brightness: about light / 116 (GoldSrc's lightmaps are overbright), fitted to the Dust 2 model
  at 10,000 matched points; shadows lifted 15% of the way to the plain texture (SHADOW_LIFT).
- Edits per map (build_aztec.py): brush entities kept or left out by class or model number,
  textures swapped (Aztec's wall tops are a 16-pixel barrel texture), tool textures ('sky',
  'clip', triggers) and alpha-tested ones ('{': vines, rungs; the atlas has no alpha yet) out.
- Water: the engine draws a kart on water/mud terrain only above y 0 (half sunk), so Aztec is
  shifted so the river's surface is at y 0, and the surface is a floor with the water terrain
  (70% speed, the water sound). A liquid brush is drawn from both sides: only each one's top
  is the water floor (its inside-out bottom painted over the real one everywhere). Everything
  under the surface is clipped off: never seen, and painted after it (out of order) it showed.
- Clip: CS keeps players on things that are only drawn with 'clip' brushes, which the map file
  keeps only in its collision hulls (planes, no faces; a point probe of hull 1 shows where).
  Aztec's rope bridge is such decor (func_illusionary planks): the build lays an invisible
  deck along the planks' tops, in the three planes of the beams under them, shaded with the
  planks' light for the kart, and invisible walls under the rails, where CS clips them too.
  The walls under the landings that face the bridge are only drawn across its width: their
  top edge is the deck's end, and a kart (which rides a hair below a floor) leaving the bridge
  ran into it, every time at one end and in some lanes at the other.
- Budget: Aztec is as big as Dust 2 in CTR units but has nearly twice the drawn surface. Floors
  are cut into cells polygon by polygon (cutting the triangles split every cell their diagonal
  crossed), only near ground the kart can reach (roofs stay whole), at 512 units (Dust 2: 256);
  walls up to 1200 (800). 13,500 quadblocks, 57,300 vertices before the painter's cuts, which
  then take the worst offenders that fit under 64,000.

## Tools

- `tools/navgrid.py` drivable grid + A*, `tools/route.py`, `tools/floor_map.py` (maps),
  `tools/inspect_region.py` (a zoomed floor map with a trace).
- `tools/e2e`: `pursuit.mjs` (autopilot round a route, laps, items), `trace.mjs`,
  `tour.mjs`/`view.mjs` (screenshots at places), `probe.mjs`.
- Build time: the painter's audit runs a painter.c process per CPU over a share of the views,
  and the backface rays a thread per CPU (every count is a sum over views: the same result);
  the level's polygons are paired once for all of the audit's trial cuts. `FAST=1` reuses the
  last full build's results of both checks per polygon (identified by corners, facing and
  texture layer; `build/checks/`) instead of running them.

## Left to do

- Track select previews and menu maps still show Dingo Canyon's and Dragon Mines'.
- Collision-only quadblocks (stair ramps, the kill plane) use atlas layer 15, which the atlas
  shader discards, and stay out of the visibility lists (a quadblock without textures is drawn
  black, with texture page 0).
- Floors are cut along a world grid of 256 units, and floor T-junctions closed: the renderer
  gave up on big floor quads right under the camera (holes to the void), and floor pieces split
  their own way left dotted cracks. The 1-pixel cracks where neighbouring quadblocks are
  subdivided differently by distance (the PS1 snaps split points to whole pixels) are covered
  by the atlas polygons' 0.6-pixel dilation. Leaf render flags 4X1/4X2/4X4 didn't help (4X1
  adds sparkles). Walls aren't T-junction-fixed: past 65536 vertices (u16 indices).
- Painter's sort: what the audit still finds is mostly same-slot ties inside one BSP leaf or
  between leaves the split planes don't separate (splitting at wall planes might help), and
  faces under 64 units apart (one slot). More cuts cost vertices: 4000 left.
- Door leaves are taken out (swung open, they z-fought with the frames). The frames had faces
  only the leaves hid from behind: every triangle around a doorway gets a reversed twin, as
  does any triangle a ray from a reachable spot hits from behind (tools/visibility.py). The
  arches and jambs had a slot where each leaf's edge sat (the leaf filled it): the two outlines
  the leaf's faces left (open mesh edges) are zipped closed with the arch's texture.
- The memory pool is 32 MiB on the web (the levels are ~7.7 MB, 16,000 quadblocks).
- An edge at A site (CTR ~6300, -6700) is two steps (ramped, drivable) for most of its width
  and a 32-unit ledge (a wall, in Counter-Strike too) for the rest; the nav grid's 64-unit
  cells blur the two, so a tour route can cut across the ledge.
- Driving off-centre round both loops (`OFFSET`) and a tour of every landmark (`CONTINUE`)
  found no snags beyond real obstacles (crates, the 90-degree corner at the top of long A).
- 2P/4P: work (tested with fake gamepads, `tools/e2e/lib.mjs`). With one gamepad, the gamepad
  is player 1 and the keyboard player 2.
