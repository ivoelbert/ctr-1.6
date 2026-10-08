# Notes

What was learned putting Counter-Strike 1.6's maps into CTR, and what's left. The code has the
details; this is the map. (The project began with Dust 2 from a Sketchfab model of it, then
moved every map to Counter-Strike's own map files.)

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
  VRM. So each map is grafted onto each of Dingo Canyon's four LEVs (`MODES`), and the page
  loads all four. (One 1P LEV in every mode gave pink, then vanishing, crates in split screen;
  loading the 1P VRM everywhere fixed those but broke the 2P HUD's fruit.)
- Instances draw only if their flags have the bit for the player count (`sdata->LOD`: 1P 1,
  2P 2, 3-4P 4, relic 8).
- The minimap: SpawnType1 slot 0 is a struct UIMap (world range, icon size and start, rotation)
  and the image is two global icons ('map-proto8-01'/'-02') that share one 80x40 4-bit image
  in the mode's VRM, each half through its own palette (high/low two bits of a texel). A VRM
  is two raw 16-bit VRAM blocks, so track.py redraws the texels and palettes (slate floors, a
  route in white) in a copy of each mode's VRM; the page loads those too.
- Laps: distToFinish (x8) must exceed 32000 at the line; a lap counts when it jumps from
  < 1200 to > 32000. Checkpoint indices are u8 (255 = none). Mask grab fires on GROUND
  quadblocks that jump more than a quarter lap ahead of the last valid one.
- AI: LevNavTable -> 3 NavHeaders (magic -0x1303) + 20-byte frames; frame 0x12 is the
  checkpoint index; pathChangeOpcode = path << 10 | frame (3072 = none) for overtaking.
- Instances: behaviour comes from the model id's LInB. Level instances are drawn through the
  camera's visInstSrc list (PVS), which LevInstDef_UnPack toggles InstDef<->Instance once per
  referencing quadblock: share it an odd number of times. Pickups need hitboxes in BSP leaves
  (flag 0x4C0, radius, radius^2, centre above the instance, InstDef pointer).

## Every map (tools/build_map.py, tools/track.py)

A map comes in from its file (tools/goldsrc.py) as textured, lit polygons in map units
(Hammer's; CTR's are 4 times smaller) and goes out as Dingo Canyon's four LEVs with its geometry
in place of the canyon's.

- The minimap shows the drivable grid's cells reachable from the start (roofs are floors too:
  Inferno's covered the whole map).
- Grafted onto Dingo Canyon (entry 1): its models, skybox, textures. Free drive's route runs
  from the T spawn to the CT spawn and back; along it (`place_pickups`), weapon crates in rows of
  four across the track, wumpa fruit in lines along it and two fruit crates.
- Floors the kart can get near are cut along a world grid (a map's FLOOR_CELL): the renderer
  gave up on big floor quads right under the camera (holes to the void). Polygon by polygon, so
  whole cells stay single quads (cutting triangles split every cell their diagonal crossed);
  roofs and ledges no one reaches stay whole. Floor T-junctions are closed.
- Stairs get invisible ramps (tools/stairs.py).
- Karts are shaded by the vertex colours of the floor under them, so floors carry the map's
  light as vertex colours (sunlit sand = 0x60, full light); the atlas shader leaves vertex
  colours out, so they only light the karts. Stair ramps take the nearest floor's.
- Free drive's checkpoint nodes each point at a twin straight above: the wrong-way test
  compares the heading with the way between a node's next two nodes, which is then vertical.
- The painter's audit (`tools/painter.py`, `tools/painter.c`, compiled with `cc` during the
  build): the level is rendered at half resolution from the chase camera at every 4th drivable
  grid cell in 8 directions (~12,000 views on Dust 2, ~16,000 on Aztec), once with a depth
  buffer and once checking the game's slots, and the polygons whose quadblocks have things
  behind them painted over them (40 pixels or more in all) are cut to 256 units, then the ones
  still at it to 128, as many as the vertex budget takes. Dust 2: 144,500 + 72,200 pixels out of
  order (nearer slot + same slot) down to 2,900 + 30,600.
- Build time: the audit runs a painter.c process per CPU over a share of the views (its counts
  are sums over views: the same result), and the level's polygons are paired once for all its
  trial cuts. `FAST=1` takes the cuts of the last full build per polygon (identified by
  corners, facing and texture layer; `build/checks/`) instead of running it.

## Counter-Strike 1.6 map files (tools/goldsrc.py)

- A map file (GoldSrc BSP 30) has the world and the brush entities as convex faces with a
  texture mapping, the textures (8-bit + palette, in the map or in the WADs worldspawn names)
  and baked light (RGB samples every 16 texels per face, per light style). goldsrc.bake gives
  each face a chart in 1024^2 atlas layers, texture times light.
- Light grids: the size of a face's grid follows the engine's float arithmetic (each texture
  coordinate summed in double, stored as a float); in double precision a few hundred faces per
  map read the wrong samples. With it, every face's grid tiles the lighting lump exactly.
- Brightness: about light / 116 (GoldSrc's lightmaps are overbright), fitted to the Dust 2 model
  at 10,000 matched points; shadows lifted 15% of the way to the plain texture (SHADOW_LIFT).
- The entities are read from their lump: a '{' byte can come earlier in the file (Dust 2's
  planes have one), and parsing from there found no WADs (grey Dust 2).
- Merging: the map compiler splits surfaces along its BSP's planes, and into pieces of at most
  240 texels for their light maps. Faces in one plane with one texture mapping that share an edge
  are merged back while the result stays convex (goldsrc.merge_coplanar): 24 to 33% fewer faces
  (Inferno 8,130 -> 5,491), 5 to 12% fewer vertices (Inferno didn't fit before: 71,000 of
  65,536), and room for more of the painter's cuts.
  A merged face's atlas chart takes each texel's light from the piece it falls in.
- Edits per map (tools/maps/MAP.py): brush entities kept or left out by class or model number,
  textures swapped; tool textures ('sky', 'clip', triggers) and alpha-tested ones ('{': vines,
  rungs; the atlas has no alpha yet) are left out everywhere. Counter-Strike culls back faces
  too, so nothing on a map is seen from behind.
- Clip: Counter-Strike keeps players on things that are only drawn with 'clip' brushes, which
  the map file keeps only in its collision hulls (planes, no faces; a point probe of hull 1
  shows where). A map's module lays its own invisible floors and walls there (extra_quads).
- Water: the engine draws a kart on water/mud terrain only above y 0 (half sunk), so a map with
  water is shifted so its surface is at y 0, and the surface is a floor with the water terrain
  (70% speed, the water sound). A liquid brush is drawn from both sides: only each one's top
  is the water floor (its inside-out bottom painted over the real one everywhere). Everything
  under the surface is clipped off: never seen, and painted after it (out of order) it showed.
- Spawns: free drive starts in the middle of the T spawn points, facing the way most of them
  face (Counter-Strike's yaw: 0 east, 90 north).

## Dust 2 (tools/maps/de_dust2.py)

- As Counter-Strike has it, doors and all. It draws about two thirds of Aztec's surface: sharper
  textures (0.55 texels per unit, 13 atlas layers), a 256-unit floor grid and 800-unit walls,
  46,200 vertices.
- The mid doors stand half open with a 39-unit gap (a Counter-Strike player is 32 wide): a kart
  doesn't fit, so it goes round (long A, short A or B). The model the project began with had the
  leaves taken out; from the map file that means patching the floor, jambs and arch the map
  compiler cut away where the leaves stood.

## Inferno (tools/maps/de_inferno.py)

- As Counter-Strike has it. The most faces of the three: 62,400 vertices before the painter's
  cuts, room for its 66 worst offenders; textures at 0.42 texels per unit to leave an atlas layer
  spare (all 14 at 0.45).

## Aztec (tools/maps/de_aztec.py)

- Edits: the wall tops are a 16-pixel barrel texture that reads as flat yellow from a kart on
  higher ground, swapped for the walls' stone; the river and the pool are the water floor.
- The rope bridge is decor (func_illusionary planks), with clip under it: an invisible deck
  along the planks' tops, in the three planes of the beams under them, shaded with the planks'
  light for the kart, and invisible walls under the rails, where Counter-Strike clips them too.
  The walls under the landings that face the bridge are only drawn across its width: their top
  edge is the deck's end, and a kart (which rides a hair below a floor) leaving the bridge ran
  into it, every time at one end and in some lanes at the other.
- Budget: as big as Dust 2 in CTR units but nearly twice the drawn surface: a 512-unit floor
  grid, walls up to 1200; 12,600 quadblocks, 54,500 vertices before the painter's cuts, which
  then take the worst offenders that fit under 64,000.

## Tools

- `tools/navgrid.py`: the drivable grid (from the level's own collision data), A*, what's
  reachable from where.
- `tools/e2e`: `launcher.mjs` (the launcher, then a map from it), `smoke.mjs` (boots and
  screenshots; fake gamepads for split screen), `shots.mjs` (screenshots at places on a map),
  `pursuit.mjs` (an autopilot along a map's free-drive route: snags and stuck spots).
- `tools/roundtrip.py` rebuilds a retail level with levwriter (a test of the writer).

## Left to do

- Races, the same way for every map: a loop through landmarks, Time Trial, CTR's own menus with
  the maps in retail tracks' places. (Dust 2 had two loops from its model: long A, CT spawn,
  mid doors, mid, outside long; and the long way through B site and the tunnels.)
- More maps, each a module in tools/maps.
- Map edits that cut into the world, like taking Dust 2's door leaves out (see Dust 2).
- Aztec: its vines and ladder rungs (alpha-tested) aren't drawn; its sky is Dingo Canyon's.
- Vertices: Aztec and Inferno still use all 64,000 the painter's cuts may (out-of-order pixels
  left: Aztec 66,000 + 217,000, Inferno about 140,000 + 254,000).
- Track select previews and menu maps still show Dingo Canyon's.
- Collision-only quadblocks (stair ramps, the kill plane) use atlas layer 15, which the atlas
  shader discards, and stay out of the visibility lists (a quadblock without textures is drawn
  black, with texture page 0).
- The 1-pixel cracks where neighbouring quadblocks are subdivided differently by distance (the
  PS1 snaps split points to whole pixels) are covered by the atlas polygons' 0.6-pixel dilation.
  Leaf render flags 4X1/4X2/4X4 didn't help (4X1 adds sparkles). Walls aren't
  T-junction-fixed: past 65536 vertices (u16 indices).
- Painter's sort: what the audit still finds is mostly same-slot ties inside one BSP leaf or
  between leaves the split planes don't separate (splitting at wall planes might help), and
  faces under 64 units apart (one slot).
- The autopilot (`pursuit.mjs`) gets stuck where its line hugs a corner or an edge: on Aztec, the
  crate on the bridge's east landing and the end of the wall west of the bridge's tunnel (map x
  -1664); on Inferno, the corner of a block where a ramp starts (map -416, 752) and the edge of a
  raised platform it rolls off (around 200, 700); on Dust 2, the mid doors (a kart doesn't fit).
- The memory pool is 32 MiB on the web (a level is up to ~7.5 MB, 15,000 quadblocks).
- 2P/4P: work (tested with fake gamepads, `tools/e2e/lib.mjs`). With one gamepad, the gamepad
  is player 1 and the keyboard player 2.
