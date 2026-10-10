"""A module per Counter-Strike 1.6 map, named after its map file (de_dust2.py for
maps/de_dust2.bsp): what tools/build_map.py needs to know about it. Every name is optional.

TITLE            the map's name in the launcher and on CTR's HUD
SKY              CTR's clear colours, its background gradient: 3 (r, g, b, 1)
DENSITY          atlas texels per map unit (1.0: about Counter-Strike's own texels; the
                 renderer has 63 atlas layers of 1024^2)
FLOOR_CELL       the floor grid near drivable ground, CTR units (512): the renderer gave up on
                 big floor quads right under the camera (holes to the void)
WALL_EDGE        the longest wall quadblock edge, CTR units (1200): the vertex budget
ENTITY_KINDS     brush entity classes over build_map.ENTITY_KINDS: 'solid', 'decor' (drawn,
                 never collided with) or 'water'; classes not there aren't drawn
REMOVE_MODELS    brush models left out ('*N' in the map's entities is model N)
TEXTURE_SWAP     {texture: the texture drawn in its place}
TEXTURE_DENSITY  {texture: atlas density}, for textures barely seen
WATER_Z          the water's surface (map z): CTR draws a kart on water only above y 0, so the
                 map is shifted to put the surface there, and what's under it is left out
LANDMARKS        {name: (x, y, z, compass heading)}, places on the map (z: about the floor's;
                 heading 0 is north, 90 east); 't_spawn' and 'ct_spawn' default to where the
                 map's spawn points are, facing the way most of them face
FREE_ROUTE       landmarks free drive's route goes through: its start, pickups and AI lines
                 (t_spawn, ct_spawn, t_spawn)

extra_quads(bsp, sel, charts, out)
                 adds collision-only quadblocks to `out` (track.emit_ramp): where Counter-Strike
                 keeps players up with clip brushes, of which the map file has no faces
split_face(pts, n)
                 (pieces, solid flags) for a face of which some parts mustn't collide, or None
"""
