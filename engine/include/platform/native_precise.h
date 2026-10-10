#ifndef NATIVE_PRECISE_H
#define NATIVE_PRECISE_H

#include <stdint.h>

// NOTE(ctr-dust2): sub-pixel vertices and perspective-correct texturing for a custom level's
// atlas polygons. The GTE projects to whole pixels and the PS1 maps textures affinely: at a
// raised render scale, with sharp textures, vertices jump from pixel to pixel and textures swim.
// As emulators' PGXP does, each projection's exact screen position and depth follow its whole-
// pixel word through memory while the level renderer runs: the GTE keeps them beside its SXY
// registers, a store of an SXY register (CTR_GteStoreSXY*) records them for the address it
// wrote, and the renderer copies them along with the word into its polygons
// (NativePrecise_Copy), where the GPU finds them (NativePrecise_Get). A word that changed some
// other way has none: that vertex stays on its whole pixel, and its polygon is mapped affinely.
void NativePrecise_BeginLevel(int enabled);
void NativePrecise_EndLevel(void);
void NativePrecise_PushProjection(uint32_t sxy, int valid, float dx, float dy, float z);
void NativePrecise_StoreSXY(const void *addr, int reg);
void NativePrecise_Copy(const void *dst, const void *src);
// dx, dy: exact position minus the whole pixel; z: depth. 0 when the word at addr has none.
int NativePrecise_Get(const void *addr, float *dx, float *dy, float *z);

#endif
