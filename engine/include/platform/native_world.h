#ifndef NATIVE_WORLD_H
#define NATIVE_WORLD_H

// NOTE(ctr-dust2): a floating origin for custom levels, and worlds bigger than a level. The
// engine's positions are 16-bit (the camera's, the collision's, the level's vertices), so
// whatever is in play has to sit within about 32,767 units of the origin. A world bigger than
// that keeps the origin near the player: at the start of a frame, the level and everything in
// play (drivers, instances, particles, cameras) move by the same amount, and nothing on screen
// changes. NativeWorld_RequestShift(d) moves them by d at the next frame's start; the origin, in
// the coordinates the level was built in, moves by -d (NativeWorld_GetOrigin).
//
// A tiled world (assets/world/: index.bin and a mesh per tile, tools/build_world.py) replaces
// the level's mesh with the 3 x 3 tiles round the kart, and moves the origin a tile at a time
// as the kart drives on (native_world.c).
struct GameTracker;
void NativeWorld_RequestShift(int dx, int dy, int dz);
void NativeWorld_FrameStart(struct GameTracker *gGT);
void NativeWorld_GetOrigin(int *out);
void NativeWorld_LevelStart(struct GameTracker *gGT);
void NativeWorld_LevelReady(struct GameTracker *gGT);
int NativeWorld_OwnsSpan(unsigned int ptr, unsigned int size);
int NativeWorld_Info(int *out);

#endif
