# Notes

What was learned putting Counter-Strike 1.6's maps, and Need for Speed: Underground 2's city,
into CTR, and what's left. The code has the details; this is the map. (The project began with
Dust 2 from a Sketchfab model of it, then moved every map to Counter-Strike's own map files.)

## The engine (engine/, ctr-native fc3fa26 + changes)

- 32-bit only (the decompiled game keeps 32-bit pointers in data): WebAssembly is 32-bit, so
  the web build works where a 64-bit native build wouldn't. JSPI suspends the game's blocking
  loop at each VBlank wait; `web/ctr-pre.js` counts VBlanks off requestAnimationFrame.
- Our changes are marked `NOTE(web)` / `NOTE(ctr-dust2)`:
  - `platform/native_web.c`: boot override (`?level=&mode=`), test hooks (`window.ctr`).
  - `platform/native_cd.c`: `assets/override/NNN.bin` replaces BIGFILE entry NNN.
  - `platform/native_memory.c`: 64 MiB heap (`CTR_DUST2_EXPANDED_MEMPACK`).
  - `platform/native_precise.c` (PGXP-style): while a custom level draws, each GTE projection's
    exact position and depth follow its whole-pixel word into the polygons, which are drawn at
    sub-pixel positions with perspective-correct textures and culled by their exact winding
    (whole pixels fold thin faces to nothing: holes once drawn exactly).
  - `platform/native_renderer.c` + `native_gpu.c`: `TF_VIRTUAL_ATLAS`, tpage colour mode 3
    samples `/assets/dust2/atlas.rgba`; CLUT = layer << 10 | (y / 32) << 5 | (x / 32). A
    "CTRA" atlas has the light baked in (Counter-Strike's maps); a "CTRV" atlas (Bayview) is
    textures lit by the vertex colours (0x80 = 1), alpha-tested, that repeat inside their
    rectangle like the PS1's texture window: tpage bits 0-4 = 16 | log2(w / 32) |
    log2(h / 32) << 2 (the bits are the page base, which atlas primitives don't use), and
    CLUT bits 14-15 scale the UVs by 1-8 before they wrap (the CLUT arrives as a signed short);
    its textures are 64-aligned, CLUT = layer << 8 | (y / 64) << 4 | (x / 64): 59 layers.
    The repeats are sampled with the unwrapped UVs' gradients (`textureGrad`), so the mipmap
    doesn't jump at the seams. A "CTRW" atlas (Vice City) is a "CTRV" one without the 8-texel
    wrapped border round each texture (with 64-aligned origins a border costs a 128-texel
    texture a 192-texel slot): the shader filters its repeating textures itself, four
    `texelFetch` taps wrapped in the texture on each of the two mip levels round the footprint
    (a power-of-two texture at a 64-aligned origin has mip levels of its own down to one texel).
  - `LOAD_IsCustomLevel`: overridden levels get 2.5 MB of primitive memory and a 256,000-word
    clip buffer (64,000 ran out on Vice City's big floors near the camera: the faces past the
    end were left out, chunks of road gone for a frame) (everything is visible from everywhere, unlike retail's PVS).

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
  (6,7,8,3) with face flags 0. Retail tests the "mosaic" word (layout + 0x24, our fourth copy's
  u, v, CLUT) as a heap pointer; for a custom level the engine never does (a CLUT that looked
  like an address in the heap gave floors garbage UVs, more of them the bigger the heap).
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
  from the T spawn to the CT spawn and back; along it `place_pickups` lays weapon crates in rows
  of four across the track, wumpa fruit in lines along it and two fruit crates, for races
  (`write_modes(pickups=True)`): free drive keeps only the start banner.
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
  water is shifted so its surface is at y 0, and the surface is a floor with the fast-water
  terrain (the water sound at full speed; plain water is 70%). A liquid brush is drawn from both sides: only each one's top
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

## Bayview: Need for Speed: Underground 2's city (tools/nfsu2/, tools/build_bayview.py)

From the PS2 disc (NTSC-U, SLUS-21065), read straight from the image:

- Files: `NFSUNDER/ZDIR.BIN` indexes `ZZDATA0-3.BIN`, 24 bytes an entry (EA's bStringHash of
  the path, archive, sector in it, a disc sector, size, checksum). The city is
  `TRACKS\L4RA.BUN` (the section table, chunk 0x34110: name, offset and size in the stream,
  middle and radius) and `TRACKS\STREAML4RA.BUN` (130 MB of sections). Sections A-R are the
  city; X hold the props every section places (and the sky), Y texture packs. Chunks are EA's
  bChunks (id, size; nested when bit 31 is set), padded with 0x11 bytes.
- Meshes (0x80134010 solids): world coordinates in metres, z up. A batch is one VIF packet for
  the vector unit: vertex count and group count at VU address 0, strip flags at 1, bounding
  box at 2, positions at 5 (groups of four vertices, x0-3 y0-3 z0-3, 16-bit in 1/256 m from an
  origin in whole metres the packet doesn't hold: at or one below the box's corner; floats in
  batches over 256 m), uvs at 29 (two quadwords per group, s0 t0 t1 s1 / s2 t2 t3 s3, 4096 =
  1), colours at 45 (0x80 = 1: the night's light, baked per vertex). The vertices are triangle
  strips; the flag bit per vertex that starts a strip comes from words 0, 2 and 3 of address 1
  by a layout that depends on the group count (mesh.strip_skip): worked out by testing every
  layout against each batch's triangle count in the batch table, then checked on all 102,005
  batches of the city.
- Winding: roads and terrain face up; buildings and props face either way (the PS2 doesn't
  cull). Walls are turned to face the route and drawn from both sides; ground that faces down
  is turned up.
- Textures (0xB3300000 packs): 4- and 8-bit palettized, stored as the GS holds them: 8-bit ones
  uploaded as 32-bit pixels, 4-bit ones as 16-bit (gs.write_read writes them back and reads
  indices); 256-colour palettes in CSM1 order; alpha 0x80 = opaque. Roads and pavements have
  alpha too, but it's how much they reflect: textures are cutouts only when their alpha is
  all but on or off, and ground textures never are.
- Scenery (0x80034100): kinds (name, solid hashes of its levels of detail A, B, Z) and
  instances (bounding box, kind, position, rotation as 16-bit 3x3, 8192 = 1, applied as
  point @ rotation). Props take their most detailed level. Left out: race barriers, the
  panoramas (PAN_: skylines and hills for far away, a shell over the streets), light glows and
  shafts (additive).

The budget: 400,000 vertices a level (vertex banks of 65,536; it was 65,536 before them, with
props' simplest levels, small props left out and a third of the corridor below). The city is about 1.2 million triangles; downtown has
5,000-10,000 per 200 m square. So a level is a loop of streets (waypoints, joined by A* on the
drivable grid, kept on roads, each leg avoiding the last), and what's along it: buildings and
the city's own terrain within 150 m, props within 60 m, floors within 60 m (an invisible wall
where a floor is cut off). Cutting faces where their textures repeat used to double the
triangles: with the atlas's repeating textures and uv scale, a face is cut only past 2,040
texels. Coplanar merging saves almost nothing on NFSU2's meshes (2%). The 2 m drivable grid
(navgrid.CELL 128 here) keeps the route planning to seconds.

- City Core: 1.7 km round the west of City Core (the pink castle, the KONOPA store).
- Coal Harbor: 1.8 km between the warehouses (chimneys, the truss bridge).
- Jackson Heights: 2.9 km of the hill roads (villas, palms, guard rails).
- 64 CTR units a metre: streets about as wide, to a kart, as Dust 2's.
- All three run at 60 fps and the autopilot drives each loop round.

## Vice City: Grand Theft Auto: Vice City's city (tools/vicecity/, tools/build_world.py)

From the PS2 disc (NTSC-U, SLUS-20552): plain ISO 9660, the map's text files in `DATA/` and the
models, textures and collision in `MODELS/GTA3.IMG` (indexed by `GTA3.DIR`: 32-byte entries,
sector, sector count, name). The shared PS2 parts (the ISO reader, the GS swizzles) are in
`tools/ps2/`.

- The map: `DATA/GTA_VC.DAT` lists the IDE files (objs: id, model, texture dictionary, ...;
  tobj: the same shown between two hours) and the IPL files (inst: id, model, interior,
  position, scale, a quaternion x y z w, applied inverted). Outdoors is interior 0, and 13
  (everywhere). Left out: the far stand-ins (`LOD...` and the islands' `islandlod...`), the
  night versions of tobj, the ground shadows (`...shad...` models, see-through `shad` textures:
  the PS2 multiplies them over the ground, CTR would draw them black). 7,122 placements,
  2,162 models, 2.3 million triangles; the islands reach x -2458 to 1709, y -2027 to 1896.
- Models (RenderWare 3.x clumps): frames (3 x 4 matrices, names in extension 0x253F2FE; a
  model's `_l1` frames are its simpler level of detail, left out), geometries (the native ones,
  flag 0x01000000, keep their vertices in the Native Data extension 0x510) and atomics. Per
  mesh (BinMesh 0x50E: a strip or a list, its material) a DMA chain of VIF UNPACKs to the
  default PS2 pipeline's layout: positions V3_32 at address 0, uvs V2_32 at 1, colours V4_8 at
  2, normals V3_8 at 3. A strip comes in batches of up to 68 vertices, each starting with the
  last two of the one before; a list in batches of 60, not overlapping (970 of the 11,597
  meshes are lists: read as strips they were shards over the buildings). A strip's runs are
  joined by degenerate triangles, and each run alternates its triangles' turn from its own
  first. The winding is either way all the same (the PS2 doesn't cull): what's flat is turned
  to face up, and walls are drawn from both sides (`back_to_back = False`). A few vertices'
  uvs are junk (NaN, 1e21): they take a neighbour's (one made a tile's build cut a triangle
  into millions of pieces).
- Light: the colours are RenderWare's prelight (255 = 1.0); the game adds the hour's ambient
  for the map (`TIMECYC.DAT`, midday's 125 120 85), up to 1.0. Read as the PS2's 0x80 = 1 they
  were twice as bright.
- Textures (dictionaries, 0x16, of native textures, 0x15, platform PS2): the GIF packets
  that upload each (BITBLTBUF is the game's to choose, so it isn't in them: TRXREG gives the
  size) and its TEX0. A transfer half the texture's width and height is a swizzled one: 8-bit
  indices sent as 32-bit pixels, 4-bit as 16-bit (`ps2.gs.write_read`); palettes are 32-bit,
  256-colour ones in CSM1 order; alpha 0x80 = opaque. The districts' dictionaries share images:
  a texture is keyed by name and a hash of its pixels, 3,176 in all (7,089 by dictionary).
- The sea isn't a model: one level, 6 m (`WATER.DAT`), wherever the ground is lower. The world
  makes it 16 m floors of fast water (`waterclear256` from `PARTICLE.TXD`, tinted with
  midday's WaterRGBA 90 170 170) in every cell nothing reaches above 6 m, and drops the seabed
  under them. CTR's height 0 is the sea's (`floor_z`): the engine draws a kart on water only
  above 0.
- Overlays the game blends over walls and roads (grime and shade: `black`, `black64` under
  every balcony on Ocean Drive, tyre tracks, light glows): mostly see-through and all but black
  or all but invisible (`blended_overlay`), they're left out. CTR doesn't blend a level's faces,
  so they were solid black wedges under the balconies (the depth buffer put them in front;
  painted in CTR's order the walls mostly hid them).
- Flicker: the exact depth (native_gpu.c) was z / 2^30 with z already in units, so the depth
  buffer's step was 64 units, a metre of the city: windows in their frames, trim and balconies
  fought as the camera moved. It's z / 2^17 now (1/128 unit a step, 2 km deep).
- Layers: the models lay trim, signs and window frames on their walls in the same plane (or a
  centimetre off, which CTR's 1.6 cm units round away), and the PS2 draws them after: with the
  depth buffer they fought, and flickered as the camera moved. `lift_layers` lifts each face
  that lies on another (the later mesh of a model, or the smaller model's) 5 cm per layer, away
  from the lower one's model, or up.
- The backdrop under the horizon (`clear_colors`' second: `CAM_ClearScreen` paints the first
  above the camera's horizon and the second under it, the third isn't used) is a grey between
  the roads' and the sea's: the hairline cracks between the models' pieces showed it, bright
  sky blue, all along the roads.
- Kerbs and steps: a kerb isn't solid (under `LOW_WALL`), but a floor a kerb higher still
  stops a kart. The tiles get `tools/stairs.py`'s ramps (`stair_unit`: its sizes are inches),
  with Vice City's own looseness: a step's floors within 6 inches of its riser's ends and up to
  14 degrees off flat (kerbs reach under the road, pavements slope to drain), each riser looked
  at both ways round (`SIDES`: the floor at the foot must be nearer the riser's bottom), and its
  line taken from its faces (`EXACT`: rebuilt from the rounded normal times its offset, 460 m
  from the origin, it landed metres off the stairs). A step's ramp starts a tread out; a kart
  with a run-up takes Ocean Drive's 27-step staircase and the hotels' front steps.
- The generic dictionary is `MODELS/GENERIC.TXD` (40 textures, loaded at start), not
  GTA3.IMG's generic.txd (10 of them): pavements, verges and medians all over the city used the
  other 30, and were left out (holes the size of a median strip).
- Cut-outs: a texture with a clearly see-through part and a clearly solid one (a tenth or more
  each), whatever's between (the palms' soft edges failed `build_bayview.is_cutout` and were drawn
  solid, black round the fronds); glass, see-through all over, is drawn solid.
- Buried walls: foundations and kerb skirts hanging under the street, their top edge level with
  a floor on either side (`buried_walls`), are drawn but not solid (LOOSE): the top edge caught
  a kart driving over it, an invisible wall.
- Draw distance: a frame's primitive memory is 7 MB (two of them nearly fill the 24-bit GPU
  links' 16 MB), and Ocean Drive's views filled it: the faces past the end were dropped (the road
  in front of the kart, half a hotel). A world's `draw_distance` (Vice City's 300 m, `drawDistance`
  in its json) leaves farther BSP leaves out (`RenderLists.c`): the densest view now takes 5.6 MB.
  `NativeWeb_PrimMem` reports a frame's peak, for tests.
- Layers lift as whole meshes (a marking, trim) or, where only part of a mesh lies on another
  (a road's border on the next), just those triangles by 2.5 cm: lifting them 5 cm tore cracks.
- Kerbs: a kerb is a lip and a step half a metre apart; their chain's ramp was three times as
  steep as it should be. Ramps rising under 12 inches run at least 8 times their rise
  (`stair_run_per_rise`, `stairs.MIN_RUN`); the settings now hold while the ramps are shaped too.
- What `OBJECT.DAT` makes a physics object (under 9,999 kg: lamp posts, bins, benches, signs,
  hydrants; 1,894 placements) is drawn but not solid (`build_bayview.LOOSE`), as a car knocks
  them over: they walled off the pavements on the drivable grid.
- The atlas: the 3,176 textures fit 40 layers borderless at full size (with borders, not even
  all halved to 64 texels did). `pack_textures` halves the least used first when they don't fit.
- Tiles: 1.36 million quadblocks, 391 MB, built in under 5 minutes; a dense tile is up to 25
  MB (Bayview's up to 8), so each of the engine's 25 tile slots grows to the biggest tile it
  has held instead of all being the biggest's size. The start level keeps 20 m round its loop
  (the game's memory holds a level of about 30 MB; the tiles take its mesh's place).
- Ocean Drive's start loop: down Ocean Drive and back up the streets behind it.

## Tony Hawk's Pro Skater 4 (tools/thps4/, tools/build_world.py)

The PC version (Aspyr): the install disc is a hybrid, its ISO 9660 side all stubs (extents at
0); the files are in its Mac (HFS) partition, `Win/program files/Aspyr/Tony Hawks Pro Skater 4/
Game/data`. The play disc's `.TGR` files are Bink videos. A level is `data/levels/Lvl/` (any
case): `lvlscn.dat`, `lvltex.dat`, `lvl.qb`, `lvlcol.dat` (collision; not read).

- tex.dat: version, count; per texture checksum, width, height, mip levels, depths,
  compression, palette size, palette, then each level's size and data. DXT1 (size w*h/2:
  compression 1 or 2, the one-bit alpha read either way), DXT5 (w*h), or 32-bit.
- scn.dat: three version words and the material count; a material: checksum, passes, alpha
  cutoff, sorted (byte), draw order (float), single-sided (byte), grassify (byte: then height
  and layers, 8 bytes); a pass: texture checksum, flags, has-colour (byte), colour, blend (8),
  addressing, envmap multiples, filtering (77 bytes so far), UV wibble (flags & 1: 32 bytes),
  VC wibble (flags & 2: sequences of key count, phase and (time, colour) keys), mipmap settings
  (16). Then the sectors: checksum, bone, flags, mesh count, box, sphere, vertex count and
  stride, positions, normals (flags & 4), texture coordinate sets (flags & 1), BGRA colours
  (flags & 2, 0x80 = 1), VC wibble bytes (flags & 0x800); a mesh: flags, material, index count,
  16-bit strip indices joined by repeats. All eleven levels parse to their files' last word.
- qb: tokens and a table of names (0x2B checksum, name). A node's struct starts with
  Position (0x16 name, 0x07 =, 0x1E vector); its Name, Class and the names it lists follow up
  to the next node's Position. The start: a Restart node that lists Player1.
- Inches, y up: metres, z up, is (x, -z, y) * 0.0254 (a turn: (x, z, y) mirrored the levels,
  the signs read backwards). Faces that look down are turned up, walls
  drawn from both sides (as Vice City's). Alcatraz's bay is a ring of flat sectors 1.3 km
  across: big flat sectors are fast water, and the world's height 0.
- What the level holds at its start: a sector whose LevelGeometry node (the node named as the
  sector's checksum) isn't CreatedAtStart comes with a goal or a cheat (Alcatraz's loop, the
  broken windows' other halves, race planes): left out.
- Light: the PC's vertex colours have 255 = 1 (read as 0x80 = 1 every level was blinding);
  CTR's 0x80 = 1, times 1.2 (the materials' darkening passes aren't drawn).
- Scale 128 units a metre (the cities' 64): the kart half as big. A tile is then 128 m (16384
  units at most, for 16-bit positions). Draw distance 120 m: Alcatraz's view filled the frame's
  primitive memory (the yard's floor dropped: the "holes"); now 2-2.5 MB at most. No start
  banner (the skate shop's filled the view).
- The start loop: a skate park's drivable grid is islands between ledges and ramps, so the
  restarts nearest the start can't be routed between; `auto_waypoints` takes, of the restarts
  (the start's first), the one whose floor reaches farthest and back, and the two places
  farthest apart that it reaches and is reached from.

## Tools

- `tools/navgrid.py`: the drivable grid (from the level's own collision data), A*, what's
  reachable from where.
- `tools/visibility.py` + `visible.c`: which triangles a chase camera sees from the drivable
  floor (a depth-buffered render of the views): Bayview leaves the rest out.
- `tools/e2e`: `launcher.mjs` (the launcher, then a map from it), `smoke.mjs` (boots and
  screenshots; fake gamepads for split screen), `shots.mjs` (screenshots at places on a map),
  `pursuit.mjs` (an autopilot along a map's free-drive route: snags and stuck spots).
- `tools/roundtrip.py` rebuilds a retail level with levwriter (a test of the writer).

Iterating on a report (a P line: `bayview_free 15303,958,8413,2505 level 0 mode 20000`):

- `node tools/e2e/spot.mjs MAP OUTDIR 'P line'...` goes there (`ctr.goto`: the world's
  coordinates, hopping a window at a time in a world), screenshots, and prints fps and the
  world's tile; `DRIVE=2500` then holds the gas and prints top speed, item and fruit.
  `BASE_URL` picks the server: a test one (`WEB_DIR=... LEV_DIR=... node tools/serve.mjs PORT`)
  leaves 8642 alone.
- `AROUND='P line' python3 -I tools/build_world.py ...` rebuilds only the city's tiles round
  there (the 3 x 3; `AROUND_TILES=0`, the one) and patches the index and minimap: 45 s, not
  8 minutes, byte for byte the full build's (it refuses when the textures changed: the atlas
  id in WORLD.json).
- One map: `tools/build_map.py` alone (a minute and a half); the engine alone:
  `OUT=build/web-x ./build-web.sh` (a minute or two).
- `python3 -I tools/levinfo.py LEV [x,y,z [radius]]`: a built level's terrain, flags, extent and
  instances, or its quadblocks near a spot, without the game.
- `tools/deps.py`: what each builder runs; play.sh rebuilds a level only when one of those is
  newer (a fix to the city's builder leaves the Counter-Strike maps alone, and the other way;
  `--skip` leaves the other city's reader out: a Vice City fix leaves Bayview alone).
- `START_ONLY=1 python3 -I tools/build_world.py ...` rebuilds a world's start level alone.
- `ctr.boost(reserves)` gives player 1 a boost (960 a second), for the reserves bar under the
  slide meter (`UI_DrawReservesMeter`, not in the retail game: a full bar is two seconds, more
  stack on in yellow, then white).

## Left to do

- Bayview: more of the city (the downtown towers, the airport, Beacon Hill) as more loops; the
  panoramas as a skyline that doesn't collide; the glows and light shafts (additive); the decal
  textures (soft alpha) are drawn alpha-tested.
- Vice City: the hours (the night versions, the lit windows), the cars, the interiors; the
  blended overlays (grime, road markings, glass) as something CTR can draw.

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
