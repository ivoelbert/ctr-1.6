// NOTE(ctr-dust2): a floating origin for custom levels (native_world.h).

#include "platform/native_world.h"

#ifdef __EMSCRIPTEN__
#include <emscripten.h>
#endif

static int s_worldShiftPending;
static Vec3 s_worldShift;
static Vec3 s_worldOrigin;
static int s_worldActive;
static struct Level *s_worldLevel;
// a world's pickup hitboxes, one of each (ended by a zero flag): every window leaf's list
static struct BSP *s_worldHitboxes;
static int s_worldHitboxCount;
// the level's instances (its PVS's list, of InstDefs: the start level's mesh is never unpacked),
// and theirs once made: every camera's to draw
static struct InstDef **s_worldInstDefs;
static struct Instance **s_worldInstances;

static void NativeWorld_ShiftSVec3(SVec3 *p, int dx, int dy, int dz)
{
	p->x = (s16)(p->x + dx);
	p->y = (s16)(p->y + dy);
	p->z = (s16)(p->z + dz);
}

static void NativeWorld_ShiftVec3(Vec3 *p, int dx, int dy, int dz)
{
	p->x += dx;
	p->y += dy;
	p->z += dz;
}

static void NativeWorld_ShiftBox(struct BoundingBox *b, int dx, int dy, int dz)
{
	NativeWorld_ShiftSVec3(&b->min, dx, dy, dz);
	NativeWorld_ShiftSVec3(&b->max, dx, dy, dz);
}

// A mesh's positions: vertices, quadblock and BSP boxes, split planes, pickup hitboxes.
static void NativeWorld_ShiftMesh(struct mesh_info *mesh, int dx, int dy, int dz)
{
	for (int i = 0; i < mesh->numVertex; i++)
	{
		NativeWorld_ShiftSVec3(&mesh->ptrVertexArray[i].pos, dx, dy, dz);
	}
	for (int i = 0; i < mesh->numQuadBlock; i++)
	{
		NativeWorld_ShiftBox(&mesh->ptrQuadBlockArray[i].bbox, dx, dy, dz);
	}
	for (int i = 0; i < mesh->numBspNodes; i++)
	{
		struct BSP *node = &mesh->bspRoot[i];
		NativeWorld_ShiftBox(&node->box, dx, dy, dz);
		if (node->flag & BSP_NODE_FLAG_LEAF)
		{
			// the leaf's pickup hitboxes (a list ended by a zero flag)
			for (struct BSP *hb = node->data.leaf.bspHitboxArray; hb != 0 && hb->flag != 0; hb++)
			{
				NativeWorld_ShiftBox(&hb->box, dx, dy, dz);
				NativeWorld_ShiftSVec3(&hb->data.hitbox.center, dx, dy, dz);
			}
		}
		else
		{
			// split plane: axis[0..2] a unit normal (4096 = 1), axis[3] the offset along it
			s16 *axis = node->data.branch.axis;
			axis[3] = (s16)(axis[3] + ((axis[0] * dx + axis[1] * dy + axis[2] * dz) >> 12));
		}
	}
}

// The level's other positions: checkpoints, nav paths, spawns, InstDefs. (The minimap stays in
// the level's own coordinates: UI_Map_GetIconPos.)
static void NativeWorld_ShiftLevelData(struct Level *lev, int dx, int dy, int dz)
{
	for (int i = 0; i < lev->cnt_restart_points; i++)
	{
		NativeWorld_ShiftSVec3(&lev->ptr_restart_points[i].pos, dx, dy, dz);
	}
	if (lev->LevNavTable != 0)
	{
		for (int k = 0; k < 3; k++)
		{
			struct NavHeader *nh = lev->LevNavTable[k];
			if (nh == 0)
			{
				continue;
			}
			struct NavFrame *frame = NAVHEADER_GETFRAME(nh);
			for (int i = 0; i < nh->numPoints; i++)
			{
				NativeWorld_ShiftSVec3(&frame[i].pos, dx, dy, dz);
			}
		}
	}
	for (int i = 0; i < 8; i++)
	{
		NativeWorld_ShiftSVec3(&lev->DriverSpawn[i].pos, dx, dy, dz);
	}
	for (u32 i = 0; i < lev->numInstances; i++)
	{
		NativeWorld_ShiftSVec3(&lev->ptrInstDefs[i].pos, dx, dy, dz);
	}
	if (lev == s_worldLevel)
	{
		for (int i = 0; i < s_worldHitboxCount; i++)
		{
			NativeWorld_ShiftBox(&s_worldHitboxes[i].box, dx, dy, dz);
			NativeWorld_ShiftSVec3(&s_worldHitboxes[i].data.hitbox.center, dx, dy, dz);
		}
	}
}

// What moves: drivers, instances, particles, cameras.
static void NativeWorld_ShiftDynamic(struct GameTracker *gGT, int dx, int dy, int dz)
{
	for (int i = 0; i < 8; i++)
	{
		struct Driver *d = gGT->drivers[i];
		if (d == 0)
		{
			continue;
		}
		NativeWorld_ShiftVec3(&d->posCurr, dx << 8, dy << 8, dz << 8);
		NativeWorld_ShiftVec3(&d->posPrev, dx << 8, dy << 8, dz << 8);
		NativeWorld_ShiftVec3(&d->botData.positionBackup, dx << 8, dy << 8, dz << 8);
		NativeWorld_ShiftSVec3(&d->spsHitPos, dx, dy, dz);
		NativeWorld_ShiftSVec3(&d->posWallColl, dx, dy, dz);
		NativeWorld_ShiftSVec3(&d->botData.estimateNavFrame.pos, dx, dy, dz);
		for (int f = 0; f < DRIVER_SKIDMARK_FRAME_COUNT; f++)
		{
			for (int t = 0; t < DRIVER_SKIDMARK_TIRE_COUNT; t++)
			{
				NativeWorld_ShiftSVec3(&d->skidmarks[f][t].fields.edge0, dx, dy, dz);
				NativeWorld_ShiftSVec3(&d->skidmarks[f][t].fields.edge1, dx, dy, dz);
			}
		}
	}
	for (struct Instance *inst = (struct Instance *)LIST_GetFirstItem(&gGT->JitPools.instance.taken); inst != 0;
	     inst = (struct Instance *)LIST_GetNextItem((struct Item *)inst))
	{
		// the HUD's (its fruit, the big 1st) are on the screen
		if ((inst->flags & PUSHBUFFER_EXISTS) || INST_GETIDPP(inst)[0].pushBuffer == &gGT->pushBuffer_UI)
		{
			continue;
		}
		inst->matrix.t[0] += dx;
		inst->matrix.t[1] += dy;
		inst->matrix.t[2] += dz;
	}
	// a world's level instances (its pickups) are the level's own, outside that pool
	for (int i = 0; s_worldInstances != NULL && s_worldInstances[i] != NULL; i++)
	{
		struct Instance *inst = s_worldInstances[i];
		int pooled = 0;
		for (struct Item *it = LIST_GetFirstItem(&gGT->JitPools.instance.taken); it != 0 && !pooled; it = LIST_GetNextItem(it))
		{
			pooled = (it == (struct Item *)inst);
		}
		if (!pooled)
		{
			inst->matrix.t[0] += dx;
			inst->matrix.t[1] += dy;
			inst->matrix.t[2] += dz;
		}
	}
	for (struct Particle *p = (struct Particle *)LIST_GetFirstItem(&gGT->JitPools.particle.taken); p != 0;
	     p = (struct Particle *)LIST_GetNextItem((struct Item *)p))
	{
		p->axis[0].startVal += dx << 8;
		p->axis[1].startVal += dy << 8;
		p->axis[2].startVal += dz << 8;
	}
	for (int i = 0; i < 4; i++)
	{
		struct CameraDC *cdc = &gGT->cameraDC[i];
		NativeWorld_ShiftVec3(&cdc->cameraPos, dx, dy, dz);
		NativeWorld_ShiftVec3(&cdc->lookAtPos, dx, dy, dz);
		NativeWorld_ShiftSVec3(&cdc->transitionTo.pos, dx, dy, dz);
		struct PushBuffer *pb = &gGT->pushBuffer[i];
		NativeWorld_ShiftSVec3(&pb->pos, dx, dy, dz);
		pb->matrix_Camera.t[0] += dx;
		pb->matrix_Camera.t[1] += dy;
		pb->matrix_Camera.t[2] += dz;
	}
}

void NativeWorld_RequestShift(int dx, int dy, int dz)
{
	s_worldShift.x += dx;
	s_worldShift.y += dy;
	s_worldShift.z += dz;
	s_worldShiftPending = 1;
}

static void NativeWorld_Follow(struct GameTracker *gGT);
static void NativeWorld_Stream(void);
static void NativeWorld_UpdateMap(struct GameTracker *gGT);
static void NativeWorld_LoadMap(void);
static void NativeWorld_FindMapIcon(struct Level *lev);

void NativeWorld_FrameStart(struct GameTracker *gGT)
{
	if (gGT->level1 == 0 || !LOAD_IsCustomLevel(gGT->levelID))
	{
		return;
	}
	if (s_worldActive && gGT->level1 == s_worldLevel)
	{
		// a world keeps its origin on its tiles: no shifts by hand
		s_worldShiftPending = 0;
		NativeWorld_Follow(gGT);
		// every instance is drawn: the tiles' quadblocks have no list for the cameras to take
		for (int p = 0; p < 4 && s_worldInstances != NULL; p++)
		{
			gGT->cameraDC[p].visInstSrc = s_worldInstances;
		}
		NativeWorld_Stream();
		NativeWorld_UpdateMap(gGT);
		return;
	}
	if (!s_worldShiftPending)
	{
		return;
	}
	int dx = s_worldShift.x, dy = s_worldShift.y, dz = s_worldShift.z;
	s_worldShiftPending = 0;
	s_worldShift.x = s_worldShift.y = s_worldShift.z = 0;
	if (gGT->level1->ptr_mesh_info != 0)
	{
		NativeWorld_ShiftMesh(gGT->level1->ptr_mesh_info, dx, dy, dz);
	}
	NativeWorld_ShiftLevelData(gGT->level1, dx, dy, dz);
	NativeWorld_ShiftDynamic(gGT, dx, dy, dz);
	s_worldOrigin.x -= dx;
	s_worldOrigin.y -= dy;
	s_worldOrigin.z -= dz;
}

void NativeWorld_GetOrigin(int *out)
{
	out[0] = s_worldOrigin.x;
	out[1] = s_worldOrigin.y;
	out[2] = s_worldOrigin.z;
}

// ---------------------------------------------------------------------------------------------
// Tiled worlds. A world is square tiles (index.bin: their size and (i, j)), each a mesh-only
// level file in coordinates from its centre (tools/build_world.py). The level's mesh is the
// 3 x 3 tiles round the centre tile, put together (vertices, quadblocks, BSP) in coordinates
// from that tile's centre; when the player's kart gets far enough into the next tile, the
// window round that one is put together in the other buffer, swapped in, the quadblock
// pointers the game holds are moved over, and everything moves by a tile (as a shift does).
// Everything is visible: one PVS of all ones for every quadblock.

#define NATIVE_WORLD_MAX_TILES 4096
#define NATIVE_WORLD_WINDOW 9
#define NATIVE_WORLD_MAX_NODES 0x3fff
#define NATIVE_WORLD_VIS_WORDS (1 << 15) // a million quadblocks' bits

typedef struct NativeWorldTile
{
	s16 i;
	s16 j;
	u32 bytes;  // its file's size
	int slot;   // -1: not loaded
	int asked;  // the page was asked for it (web)
	u8 *data;
	struct mesh_info *mesh;
	int banks;
} NativeWorldTile;

typedef struct NativeWorldWindow
{
	struct mesh_info mesh;
	struct QuadBlock *quads;
	int quadCap;
	struct LevVertex *verts;
	int vertCap;
	struct BSP *bsp;
	int count;
	int tile[NATIVE_WORLD_WINDOW];
	int quadBase[NATIVE_WORLD_WINDOW];
	int quadCount[NATIVE_WORLD_WINDOW];
	int ci;
	int cj;
} NativeWorldWindow;

// Tiles live in slots of one arena (the renderer's checks see one range): the 5 x 5 round the
// centre tile, loaded as they come (the page fetches them on the web), and the slots of tiles
// outside that reused.
#define NATIVE_WORLD_RING 2
#define NATIVE_WORLD_SLOTS ((2 * NATIVE_WORLD_RING + 1) * (2 * NATIVE_WORLD_RING + 1))

static NativeWorldTile s_tiles[NATIVE_WORLD_MAX_TILES];
static int s_tileCount;
static int s_tileSize;
static u8 *s_tileArena;
static u32 s_tileArenaSize;
static u32 s_slotSize;
static int s_slotOwner[NATIVE_WORLD_SLOTS];
static NativeWorldWindow s_windows[2];
static int s_windowCur = -1;
static int s_centreI, s_centreJ;
static int *s_visAll;
static struct PVS s_worldPVS;
static struct VisMem s_worldVisMem;
static double s_lastAssemblyMs;
static double s_lastLoadMs;
static int s_tilesLoaded;

#ifdef __EMSCRIPTEN__
// the page fetches a tile into assets/world/ (index.html: Module.ctrFetchTile)
EM_JS(void, NativeWorld_AskPage, (int i, int j), {
	if (Module.ctrFetchTile) Module.ctrFetchTile(i, j);
});
#else
static void NativeWorld_AskPage(int i, int j)
{
	(void)i;
	(void)j;
}
#endif

static int NativeWorld_FindTile(int i, int j)
{
	for (int k = 0; k < s_tileCount; k++)
	{
		if (s_tiles[k].i == i && s_tiles[k].j == j)
		{
			return k;
		}
	}
	return -1;
}

static void NativeWorld_TilePath(char *path, size_t size, int i, int j)
{
	snprintf(path, size, "%s/world/T_%d_%d.lev", NativeAssets_GetAssetDir(), i, j);
}

static u8 *NativeWorld_ReadFile(const char *path, u32 *size)
{
	FILE *f = fopen(path, "rb");
	if (f == NULL)
	{
		return NULL;
	}
	fseek(f, 0, SEEK_END);
	long n = ftell(f);
	fseek(f, 0, SEEK_SET);
	u8 *buf = (u8 *)malloc((size_t)n);
	if (buf != NULL && fread(buf, 1, (size_t)n, f) != (size_t)n)
	{
		free(buf);
		buf = NULL;
	}
	fclose(f);
	*size = (u32)n;
	return buf;
}

static void NativeWorld_FreeTiles(void)
{
	free(s_tileArena);
	s_tileArena = NULL;
	s_tileArenaSize = 0;
	s_tileCount = 0;
}

// index.bin: 'WRLD', tile size (units), count, then per tile (i, j) s16 and its file's bytes.
static int NativeWorld_LoadIndex(void)
{
	char path[768];
	u32 size;
	snprintf(path, sizeof(path), "%s/world/index.bin", NativeAssets_GetAssetDir());
	u8 *index = NativeWorld_ReadFile(path, &size);
	if (index == NULL)
	{
		return 0;
	}
	int count = 0;
	if (size >= 12 && memcmp(index, "WRLD", 4) == 0)
	{
		memcpy(&s_tileSize, index + 4, 4);
		memcpy(&count, index + 8, 4);
	}
	if (count <= 0 || count > NATIVE_WORLD_MAX_TILES || size < 12 + 8 * (u32)count)
	{
		free(index);
		return 0;
	}
	s_slotSize = 0;
	for (int k = 0; k < count; k++)
	{
		NativeWorldTile *t = &s_tiles[k];
		memset(t, 0, sizeof(*t));
		memcpy(&t->i, index + 12 + 8 * k, 2);
		memcpy(&t->j, index + 14 + 8 * k, 2);
		memcpy(&t->bytes, index + 16 + 8 * k, 4);
		t->slot = -1;
		s_slotSize = t->bytes > s_slotSize ? t->bytes : s_slotSize;
	}
	free(index);
	s_tileCount = count;
	s_slotSize = (s_slotSize + 0xffff) & ~0xffffu;
	s_tileArenaSize = s_slotSize * NATIVE_WORLD_SLOTS;
	s_tileArena = (u8 *)malloc(s_tileArenaSize);
	for (int k = 0; k < NATIVE_WORLD_SLOTS; k++)
	{
		s_slotOwner[k] = -1;
	}
	s_tilesLoaded = 0;
	printf("[CTR Native] world: %d tiles of %d units, %d slots of %u KB\n", s_tileCount, s_tileSize, NATIVE_WORLD_SLOTS,
	       s_slotSize >> 10);
	return s_tileArena != NULL;
}

static int NativeWorld_InRing(const NativeWorldTile *t, int ci, int cj, int r)
{
	return t->i >= ci - r && t->i <= ci + r && t->j >= cj - r && t->j <= cj + r;
}

// Loads tile k from assets/world/ when its file is there (the page fetched it), into a free
// slot or one whose tile is out of the ring round the centre (never the window's).
static int NativeWorld_LoadTile(int k)
{
	NativeWorldTile *t = &s_tiles[k];
	if (t->slot >= 0)
	{
		return 1;
	}
	char path[768];
	NativeWorld_TilePath(path, sizeof(path), t->i, t->j);
	FILE *f = fopen(path, "rb");
	if (f == NULL)
	{
		return 0;
	}
	int slot = -1;
	for (int s = 0; s < NATIVE_WORLD_SLOTS && slot < 0; s++)
	{
		if (s_slotOwner[s] < 0)
		{
			slot = s;
		}
	}
	for (int s = 0; s < NATIVE_WORLD_SLOTS && slot < 0; s++)
	{
		if (!NativeWorld_InRing(&s_tiles[s_slotOwner[s]], s_centreI, s_centreJ, NATIVE_WORLD_RING))
		{
			slot = s;
		}
	}
	if (slot < 0)
	{
		fclose(f);
		return 0;
	}
	double t0 = ((double)SDL_GetTicksNS() / 1e6);
	if (s_slotOwner[slot] >= 0)
	{
		NativeWorldTile *old = &s_tiles[s_slotOwner[slot]];
		old->slot = -1;
		old->asked = 0;
		old->data = NULL;
		old->mesh = NULL;
		s_tilesLoaded--;
	}
	u8 *file = s_tileArena + (size_t)slot * s_slotSize;
	size_t n = fread(file, 1, s_slotSize, f);
	fclose(f);
	s_slotOwner[slot] = -1;
	if (n < 8 || n != t->bytes)
	{
		printf("[CTR Native] world: %s: %zu bytes, expected %u\n", path, n, t->bytes);
		return 0;
	}
#ifdef __EMSCRIPTEN__
	remove(path); // the page's copy, read: the slot holds it now
#endif
	// a level file: u32 data size, the data, then its pointer map (u32 bytes, the slots)
	u32 dataSize;
	memcpy(&dataSize, file, 4);
	u8 *data = file + 4;
	u32 mapBytes;
	memcpy(&mapBytes, data + dataSize, 4);
	const u8 *slots = data + dataSize + 4;
	for (u32 s = 0; s < mapBytes / 4; s++)
	{
		u32 at;
		memcpy(&at, slots + 4 * s, 4);
		u32 value;
		memcpy(&value, data + at, 4);
		value += (u32)(uintptr_t)data;
		memcpy(data + at, &value, 4);
	}
	t->slot = slot;
	t->data = data;
	t->mesh = ((struct Level *)data)->ptr_mesh_info;
	t->banks = (t->mesh->numVertex + 0xffff) >> 16;
	s_slotOwner[slot] = k;
	s_tilesLoaded++;
	s_lastLoadMs = ((double)SDL_GetTicksNS() / 1e6) - t0;
	return 1;
}

// The ring round the centre tile: asks the page for what's missing and loads what's come (one
// tile a frame: a few milliseconds each), nearest first.
static void NativeWorld_Stream(void)
{
	int best = -1, bestD = 1 << 30;
	for (int k = 0; k < s_tileCount; k++)
	{
		NativeWorldTile *t = &s_tiles[k];
		if (t->slot >= 0 || !NativeWorld_InRing(t, s_centreI, s_centreJ, NATIVE_WORLD_RING))
		{
			continue;
		}
		if (!t->asked)
		{
			t->asked = 1;
			NativeWorld_AskPage(t->i, t->j);
		}
		int d = abs(t->i - s_centreI) + abs(t->j - s_centreJ);
		if (d < bestD)
		{
			bestD = d;
			best = k;
		}
	}
	if (best >= 0)
	{
		NativeWorld_LoadTile(best);
	}
}

// Whether every tile of the window round (ci, cj) is loaded (asking for and loading the rest).
static int NativeWorld_WindowReady(int ci, int cj)
{
	int ready = 1;
	for (int k = 0; k < s_tileCount; k++)
	{
		NativeWorldTile *t = &s_tiles[k];
		if (NativeWorld_InRing(t, ci, cj, 1) && t->slot < 0)
		{
			if (!t->asked)
			{
				t->asked = 1;
				NativeWorld_AskPage(t->i, t->j);
			}
			ready &= NativeWorld_LoadTile(k);
		}
	}
	return ready;
}

static int NativeWorld_Grow(void **buf, int *cap, int need, size_t item)
{
	if (need <= *cap)
	{
		return 1;
	}
	void *p = realloc(*buf, (size_t)need * item);
	if (p == NULL)
	{
		return 0;
	}
	*buf = p;
	*cap = need;
	return 1;
}

static int s_topNext;

// The BSP over a window's tiles: halves split between tiles, alternating by their spread.
static u16 NativeWorld_TopTree(NativeWorldWindow *w, int *order, int n, const u16 *rootIds, int ox, int oz)
{
	if (n == 1)
	{
		return rootIds[order[0]];
	}
	int me = s_topNext++;
	int imin = 1 << 30, imax = -(1 << 30), jmin = 1 << 30, jmax = -(1 << 30);
	for (int k = 0; k < n; k++)
	{
		NativeWorldTile *t = &s_tiles[w->tile[order[k]]];
		imin = t->i < imin ? t->i : imin;
		imax = t->i > imax ? t->i : imax;
		jmin = t->j < jmin ? t->j : jmin;
		jmax = t->j > jmax ? t->j : jmax;
	}
	int alongI = (imax - imin) >= (jmax - jmin);
	// sort by i or j (insertion: nine at most)
	for (int a = 1; a < n; a++)
	{
		int v = order[a], b = a - 1;
		int key = alongI ? s_tiles[w->tile[v]].i : s_tiles[w->tile[v]].j;
		while (b >= 0 && (alongI ? s_tiles[w->tile[order[b]]].i : s_tiles[w->tile[order[b]]].j) > key)
		{
			order[b + 1] = order[b];
			b--;
		}
		order[b + 1] = v;
	}
	int mid = n / 2;
	NativeWorldTile *t = &s_tiles[w->tile[order[mid]]];
	int split = alongI ? (t->i * s_tileSize - s_tileSize / 2 - ox) : (t->j * s_tileSize - s_tileSize / 2 - oz);
	u16 left = NativeWorld_TopTree(w, order, mid, rootIds, ox, oz);
	u16 right = NativeWorld_TopTree(w, order + mid, n - mid, rootIds, ox, oz);
	struct BSP *node = &w->bsp[me];
	memset(node, 0, sizeof(*node));
	node->flag = 0;
	node->id = (s16)me;
	struct BoundingBox *a = &w->bsp[left & BSP_CHILD_ID_INDEX_MASK].box;
	struct BoundingBox *b = &w->bsp[right & BSP_CHILD_ID_INDEX_MASK].box;
	node->box.min.x = a->min.x < b->min.x ? a->min.x : b->min.x;
	node->box.min.y = a->min.y < b->min.y ? a->min.y : b->min.y;
	node->box.min.z = a->min.z < b->min.z ? a->min.z : b->min.z;
	node->box.max.x = a->max.x > b->max.x ? a->max.x : b->max.x;
	node->box.max.y = a->max.y > b->max.y ? a->max.y : b->max.y;
	node->box.max.z = a->max.z > b->max.z ? a->max.z : b->max.z;
	node->data.branch.axis[0] = alongI ? 0x1000 : 0;
	node->data.branch.axis[1] = 0;
	node->data.branch.axis[2] = alongI ? 0 : 0x1000;
	node->data.branch.axis[3] = (s16)split;
	node->data.branch.childID[0] = (BspChildId)left;
	node->data.branch.childID[1] = (BspChildId)right;
	node->data.branch.childID[2] = (BspChildId)0x0D02; // near side first (levwriter BSP_NEAR_FIRST)
	node->data.branch.childID[3] = 0;
	return (u16)me;
}

// Puts the window round tile (ci, cj) together in w, in coordinates from origin (ox, oz).
static int NativeWorld_Assemble(NativeWorldWindow *w, int ci, int cj, int ox, int oz)
{
	double t0 = ((double)SDL_GetTicksNS() / 1e6);
	w->count = 0;
	int nq = 0, banks = 0, nodes = 0;
	for (int dj = -1; dj <= 1; dj++)
	{
		for (int di = -1; di <= 1; di++)
		{
			int k = NativeWorld_FindTile(ci + di, cj + dj);
			if (k < 0 || s_tiles[k].slot < 0)
			{
				continue;
			}
			w->tile[w->count++] = k;
			nq += s_tiles[k].mesh->numQuadBlock;
			banks += s_tiles[k].banks;
			nodes += s_tiles[k].mesh->numBspNodes;
		}
	}
	if (w->count == 0)
	{
		return 0;
	}
	int top = w->count - 1;
	if (top + nodes > NATIVE_WORLD_MAX_NODES || banks > 256)
	{
		printf("[CTR Native] world: window %d,%d too big (%d BSP nodes, %d vertex banks)\n", ci, cj, top + nodes, banks);
		return 0;
	}
	if (!NativeWorld_Grow((void **)&w->quads, &w->quadCap, nq, sizeof(struct QuadBlock)) ||
	    !NativeWorld_Grow((void **)&w->verts, &w->vertCap, banks << 16, sizeof(struct LevVertex)))
	{
		return 0;
	}
	if (w->bsp == NULL)
	{
		w->bsp = (struct BSP *)calloc(NATIVE_WORLD_MAX_NODES + 1, sizeof(struct BSP));
	}
	u16 rootIds[NATIVE_WORLD_WINDOW];
	int qbase = 0, bank = 0, nbase = top;
	for (int k = 0; k < w->count; k++)
	{
		NativeWorldTile *t = &s_tiles[w->tile[k]];
		struct mesh_info *m = t->mesh;
		int dx = t->i * s_tileSize - ox, dz = t->j * s_tileSize - oz;
		int tileBanked = ((u32)m->unk2 == LEV_VERTEX_BANKS);
		struct LevVertex *vdst = &w->verts[bank << 16];
		memcpy(vdst, m->ptrVertexArray, (size_t)m->numVertex * sizeof(struct LevVertex));
		for (int v = 0; v < m->numVertex; v++)
		{
			vdst[v].pos.x = (s16)(vdst[v].pos.x + dx);
			vdst[v].pos.z = (s16)(vdst[v].pos.z + dz);
		}
		struct QuadBlock *qdst = &w->quads[qbase];
		memcpy(qdst, m->ptrQuadBlockArray, (size_t)m->numQuadBlock * sizeof(struct QuadBlock));
		for (int q = 0; q < m->numQuadBlock; q++)
		{
			struct QuadBlock *qb = &qdst[q];
			qb->weather_vanishRate = (u8)(bank + (tileBanked ? qb->weather_vanishRate : 0));
			NativeWorld_ShiftBox(&qb->bbox, dx, 0, dz);
			qb->pvs = &s_worldPVS;
			int gi = qbase + q;
			qb->blockID = (s16)(((gi & ~31) | (31 - (gi & 31))) & 0x7fff);
		}
		struct BSP *ndst = &w->bsp[nbase];
		memcpy(ndst, m->bspRoot, (size_t)m->numBspNodes * sizeof(struct BSP));
		for (int n = 0; n < m->numBspNodes; n++)
		{
			struct BSP *node = &ndst[n];
			node->id = (s16)(nbase + n);
			NativeWorld_ShiftBox(&node->box, dx, 0, dz);
			if (node->flag & BSP_NODE_FLAG_LEAF)
			{
				node->data.leaf.ptrQuadBlockArray = qdst + (node->data.leaf.ptrQuadBlockArray - m->ptrQuadBlockArray);
				node->data.leaf.bspHitboxArray = s_worldHitboxCount > 0 ? s_worldHitboxes : NULL;
			}
			else
			{
				for (int c = 0; c < 2; c++)
				{
					u16 id = (u16)node->data.branch.childID[c];
					if (id != BSP_CHILD_ID_NONE)
					{
						node->data.branch.childID[c] = (BspChildId)(((id & BSP_CHILD_ID_INDEX_MASK) + nbase) | (id & BSP_CHILD_ID_LEAF_FLAG));
					}
				}
				s16 *axis = node->data.branch.axis;
				axis[3] = (s16)(axis[3] + ((axis[0] * dx + axis[2] * dz) >> 12));
			}
		}
		rootIds[k] = (u16)(nbase | ((ndst[0].flag & BSP_NODE_FLAG_LEAF) ? BSP_CHILD_ID_LEAF_FLAG : 0));
		w->quadBase[k] = qbase;
		w->quadCount[k] = m->numQuadBlock;
		qbase += m->numQuadBlock;
		bank += t->banks;
		nbase += m->numBspNodes;
	}
	int order[NATIVE_WORLD_WINDOW];
	for (int k = 0; k < w->count; k++)
	{
		order[k] = k;
	}
	s_topNext = 0;
	NativeWorld_TopTree(w, order, w->count, rootIds, ox, oz);
	w->mesh.numQuadBlock = nq;
	w->mesh.numVertex = bank << 16;
	w->mesh.unk1 = 0;
	w->mesh.ptrQuadBlockArray = w->quads;
	w->mesh.ptrVertexArray = w->verts;
	w->mesh.unk2 = (int)LEV_VERTEX_BANKS;
	w->mesh.bspRoot = w->bsp;
	w->mesh.numBspNodes = nbase;
	w->ci = ci;
	w->cj = cj;
	s_lastAssemblyMs = ((double)SDL_GetTicksNS() / 1e6) - t0;
	return 1;
}

static struct QuadBlock *NativeWorld_MoveQuad(struct QuadBlock *q, NativeWorldWindow *from, NativeWorldWindow *to)
{
	if (q == NULL || from == NULL || q < from->quads || q >= from->quads + from->mesh.numQuadBlock)
	{
		return NULL;
	}
	int gi = (int)(q - from->quads);
	for (int k = 0; k < from->count; k++)
	{
		if (gi >= from->quadBase[k] && gi < from->quadBase[k] + from->quadCount[k])
		{
			for (int k2 = 0; k2 < to->count; k2++)
			{
				if (to->tile[k2] == from->tile[k])
				{
					return to->quads + to->quadBase[k2] + (gi - from->quadBase[k]);
				}
			}
			return NULL;
		}
	}
	return NULL;
}

static void NativeWorld_ResetVisMem(struct GameTracker *gGT)
{
	struct mesh_info *mesh = gGT->level1->ptr_mesh_info;
	for (int p = 0; p < 4; p++)
	{
		s_worldVisMem.visLeafSrc[p] = NULL;
		s_worldVisMem.visFaceSrc[p] = NULL;
		s_worldVisMem.visOVertSrc[p] = NULL;
		s_worldVisMem.visSCVertSrc[p] = NULL;
		memset(s_worldVisMem.visLeafList[p], 0xff, NATIVE_WORLD_VIS_WORDS * 4);
		memset(s_worldVisMem.visFaceList[p], 0xff, NATIVE_WORLD_VIS_WORDS * 4);
		for (int n = 0; n < mesh->numBspNodes; n++)
		{
			s_worldVisMem.bspList[p][n].next = NULL;
			s_worldVisMem.bspList[p][n].bsp = &mesh->bspRoot[n];
		}
	}
}

// The level's own pickup hitboxes (listed in each leaf they overlap), one of each, for the
// windows' leaves: the tiles have none.
static void NativeWorld_CollectHitboxes(struct mesh_info *mesh)
{
	s_worldHitboxCount = 0;
	for (int pass = 0; pass < 2; pass++)
	{
		int n = 0;
		for (int i = 0; i < mesh->numBspNodes; i++)
		{
			struct BSP *node = &mesh->bspRoot[i];
			if ((node->flag & BSP_NODE_FLAG_LEAF) == 0)
			{
				continue;
			}
			for (struct BSP *hb = node->data.leaf.bspHitboxArray; hb != 0 && hb->flag != 0; hb++)
			{
				int seen = 0;
				for (int k = 0; pass == 1 && k < n; k++)
				{
					seen |= (s_worldHitboxes[k].data.hitbox.instDef == hb->data.hitbox.instDef);
				}
				if (pass == 0)
				{
					n++;
				}
				else if (!seen)
				{
					s_worldHitboxes[n++] = *hb;
				}
			}
		}
		if (pass == 0)
		{
			free(s_worldHitboxes);
			s_worldHitboxes = (struct BSP *)calloc((size_t)n + 1, sizeof(struct BSP));
			if (s_worldHitboxes == NULL)
			{
				return;
			}
		}
		else
		{
			s_worldHitboxes[n].flag = 0;
			s_worldHitboxCount = n;
		}
	}
}

// Before the drivers are made (they land on what's under the spawn): the world's mesh in
// place of the level's, round tile (0, 0) (the level is built in the world's coordinates).
void NativeWorld_LevelStart(struct GameTracker *gGT)
{
	struct Level *lev = gGT->level1;
	s_worldShiftPending = 0;
	s_worldShift.x = s_worldShift.y = s_worldShift.z = 0;
	free(s_worldInstances);
	s_worldInstances = NULL;
	s_worldInstDefs = NULL;
	s_worldHitboxCount = 0;
	if (lev == NULL || !LOAD_IsCustomLevel(gGT->levelID))
	{
		s_worldActive = 0;
		s_worldLevel = NULL;
		s_worldOrigin.x = s_worldOrigin.y = s_worldOrigin.z = 0;
		return;
	}
	if (lev == s_worldLevel)
	{
		// a restart: the level's data back where it was built
		NativeWorld_ShiftLevelData(lev, s_worldOrigin.x, s_worldOrigin.y, s_worldOrigin.z);
	}
	else
	{
		NativeWorld_FreeTiles();
		s_worldActive = NativeWorld_LoadIndex();
		s_worldLevel = lev;
	}
	s_worldOrigin.x = s_worldOrigin.y = s_worldOrigin.z = 0;
	if (!s_worldActive)
	{
		return;
	}
	if (s_visAll == NULL)
	{
		s_visAll = (int *)malloc(NATIVE_WORLD_VIS_WORDS * 4);
		memset(s_visAll, 0xff, NATIVE_WORLD_VIS_WORDS * 4);
		s_worldPVS.visLeafSrc = s_visAll;
		s_worldPVS.visFaceSrc = s_visAll;
		s_worldPVS.visInstSrc = NULL;
		s_worldPVS.visExtraSrc = NULL;
		for (int p = 0; p < 4; p++)
		{
			s_worldVisMem.visLeafList[p] = (int *)malloc(NATIVE_WORLD_VIS_WORDS * 4);
			s_worldVisMem.visFaceList[p] = (int *)malloc(NATIVE_WORLD_VIS_WORDS * 4);
			s_worldVisMem.visOVertList[p] = (int *)calloc(16, 4);
			s_worldVisMem.visSCVertList[p] = (int *)calloc(16, 4);
			s_worldVisMem.bspList[p] = (struct VisMemBspListNode *)calloc(NATIVE_WORLD_MAX_NODES + 1, sizeof(struct VisMemBspListNode));
		}
	}
	NativeWorld_CollectHitboxes(lev->ptr_mesh_info);
	s_worldInstDefs = NULL;
	for (int q = 0; q < lev->ptr_mesh_info->numQuadBlock && s_worldInstDefs == NULL; q++)
	{
		struct PVS *pvs = lev->ptr_mesh_info->ptrQuadBlockArray[q].pvs;
		if (pvs != NULL && pvs->visInstSrc != NULL)
		{
			s_worldInstDefs = (struct InstDef **)pvs->visInstSrc;
		}
	}
	s_centreI = s_centreJ = 0;
	if (!NativeWorld_WindowReady(0, 0) || !NativeWorld_Assemble(&s_windows[0], 0, 0, 0, 0))
	{
		printf("[CTR Native] world: the tiles round 0,0 aren't there\n");
		s_worldActive = 0;
		return;
	}
	s_windowCur = 0;
	lev->ptr_mesh_info = &s_windows[0].mesh;
	NativeWorld_LoadMap();
	NativeWorld_FindMapIcon(lev);
	// MainInit_VisMem fills the VisMem's BSP lists for the mesh: the world's, sized for any window
	lev->visMem = &s_worldVisMem;
	printf("[CTR Native] world: window 0,0: %d tiles, %d quadblocks, %d BSP nodes (%.1f ms)\n", s_windows[0].count,
	       s_windows[0].mesh.numQuadBlock, s_windows[0].mesh.numBspNodes, s_lastAssemblyMs);
}

// After MainInit_VisMem: the world's VisMem (sized for any window) in place of the level's.
void NativeWorld_LevelReady(struct GameTracker *gGT)
{
	if (!s_worldActive)
	{
		return;
	}
	gGT->visMem1 = &s_worldVisMem;
	gGT->level1->visMem = &s_worldVisMem;
	NativeWorld_ResetVisMem(gGT);
	// the instances are made by now
	free(s_worldInstances);
	s_worldInstances = NULL;
	int n = 0;
	while (s_worldInstDefs != NULL && s_worldInstDefs[n] != NULL)
	{
		n++;
	}
	s_worldInstances = (struct Instance **)calloc((size_t)n + 1, sizeof(struct Instance *));
	for (int i = 0, k = 0; s_worldInstances != NULL && i < n; i++)
	{
		if (s_worldInstDefs[i]->ptrInstance != NULL)
		{
			s_worldInstances[k++] = s_worldInstDefs[i]->ptrInstance;
		}
	}
	printf("[CTR Native] world: %d instances, %d pickup hitboxes\n", n, s_worldHitboxCount);
}

// A frame's start: past the edge of the centre tile (and an eighth of a tile more), the
// window round the tile the kart is in takes over.
static void NativeWorld_Follow(struct GameTracker *gGT)
{
	struct Driver *d = gGT->drivers[0];
	if (d == NULL || s_windowCur < 0)
	{
		return;
	}
	int x = d->posCurr.x >> 8, z = d->posCurr.z >> 8;
	int reach = s_tileSize / 2 + s_tileSize / 8;
	if (x > -reach && x < reach && z > -reach && z < reach)
	{
		return;
	}
	NativeWorldWindow *from = &s_windows[s_windowCur];
	int di = (x + (x >= 0 ? s_tileSize / 2 : -s_tileSize / 2)) / s_tileSize;
	int dj = (z + (z >= 0 ? s_tileSize / 2 : -s_tileSize / 2)) / s_tileSize;
	int ci = from->ci + di, cj = from->cj + dj;
	int ox = ci * s_tileSize, oz = cj * s_tileSize;
	NativeWorldWindow *to = &s_windows[1 - s_windowCur];
	// not before its tiles are in (the kart drives on in this window meanwhile)
	if (!NativeWorld_WindowReady(ci, cj) || !NativeWorld_Assemble(to, ci, cj, ox, oz))
	{
		return;
	}
	// the quadblocks the game holds, moved over (NULL when their tile is left behind)
	for (int i = 0; i < 8; i++)
	{
		struct Driver *dr = gGT->drivers[i];
		if (dr == NULL)
		{
			continue;
		}
		struct QuadBlock *touching = NativeWorld_MoveQuad(dr->currBlockTouching, from, to);
		struct QuadBlock *under = NativeWorld_MoveQuad(dr->underDriver, from, to);
		struct QuadBlock *last = NativeWorld_MoveQuad(dr->lastValid, from, to);
		dr->currBlockTouching = touching;
		dr->underDriver = under;
		dr->lastValid = last != NULL ? last : (under != NULL ? under : touching);
	}
	for (int i = 0; i < 4; i++)
	{
		gGT->cameraDC[i].ptrQuadBlock = NativeWorld_MoveQuad(gGT->cameraDC[i].ptrQuadBlock, from, to);
	}
	gGT->level1->ptr_mesh_info = &to->mesh;
	s_windowCur = 1 - s_windowCur;
	int dx = (s_worldOrigin.x - ox), dz = (s_worldOrigin.z - oz);
	NativeWorld_ShiftLevelData(gGT->level1, dx, 0, dz);
	NativeWorld_ShiftDynamic(gGT, dx, 0, dz);
	s_worldOrigin.x = ox;
	s_worldOrigin.z = oz;
	s_centreI = ci;
	s_centreJ = cj;
	NativeWorld_ResetVisMem(gGT);
	printf("[CTR Native] world: window %d,%d: %d tiles, %d quadblocks (%.1f ms)\n", ci, cj, to->count, to->mesh.numQuadBlock,
	       s_lastAssemblyMs);
}

// NOTE(ctr-dust2): the renderer checks texture pointers lie in level memory: a world's are in
// its tiles and windows.
int NativeWorld_OwnsSpan(u32 ptr, u32 size)
{
	if (!s_worldActive)
	{
		return 0;
	}
	if (ptr >= (u32)(uintptr_t)s_tileArena && ptr + size <= (u32)(uintptr_t)s_tileArena + s_tileArenaSize)
	{
		return 1;
	}
	for (int k = 0; k < 2; k++)
	{
		NativeWorldWindow *w = &s_windows[k];
		if (w->quads != NULL && ptr >= (u32)(uintptr_t)w->quads && ptr + size <= (u32)(uintptr_t)(w->quads + w->quadCap))
		{
			return 1;
		}
	}
	return 0;
}

int NativeWorld_Info(int *out)
{
	out[0] = s_worldActive;
	out[1] = s_windowCur >= 0 ? s_windows[s_windowCur].ci : 0;
	out[2] = s_windowCur >= 0 ? s_windows[s_windowCur].cj : 0;
	out[3] = s_windowCur >= 0 ? s_windows[s_windowCur].mesh.numQuadBlock : 0;
	out[4] = (int)(s_lastAssemblyMs * 1000.0);
	out[5] = s_tileCount;
	out[6] = s_tilesLoaded;
	out[7] = (int)(s_lastLoadMs * 1000.0);
	return s_worldActive;
}

// ---------------------------------------------------------------------------------------------
// The minimap of a world. CTR draws a track's map from one 80 x 80 4-bit image in VRAM (two
// 80 x 40 halves sharing texels: the top half's value in the high two bits, the bottom's in
// the low two, each half through its palette; tools/track.py). A world's map is the whole
// city (assets/world/map.bin: a byte a texel, the two-bit values), and the minimap shows the
// 80 x 80 texels round the kart, rewritten in VRAM when the kart moves a texel; the racers'
// icons go by that window (NativeWorld_MapIconPos).

#define NATIVE_WORLD_MAP 80

static u8 *s_map;
static int s_mapUnits, s_mapX, s_mapZ, s_mapW, s_mapH;
static int s_mapLeft = 1 << 30, s_mapTop = 1 << 30; // the window's corner texel
static int s_mapVramX, s_mapVramY, s_mapFound;

static void NativeWorld_LoadMap(void)
{
	char path[768];
	u32 size;
	free(s_map);
	s_map = NULL;
	s_mapFound = 0;
	s_mapLeft = s_mapTop = 1 << 30;
	snprintf(path, sizeof(path), "%s/world/map.bin", NativeAssets_GetAssetDir());
	u8 *file = NativeWorld_ReadFile(path, &size);
	if (file == NULL)
	{
		return;
	}
	int head[5];
	if (size >= 24 && memcmp(file, "WMAP", 4) == 0)
	{
		memcpy(head, file + 4, sizeof(head));
		if (head[3] > 0 && head[4] > 0 && size >= 24 + (u32)head[3] * (u32)head[4])
		{
			s_mapUnits = head[0];
			s_mapX = head[1];
			s_mapZ = head[2];
			s_mapW = head[3];
			s_mapH = head[4];
			s_map = (u8 *)malloc((size_t)s_mapW * s_mapH);
			memcpy(s_map, file + 24, (size_t)s_mapW * s_mapH);
		}
	}
	free(file);
}

// Where the level's minimap image is in VRAM: its icon "map-proto8-01" (the top half).
static void NativeWorld_FindMapIcon(struct Level *lev)
{
	struct LevTexLookup *lookup = lev->levTexLookup;
	if (lookup == NULL || lookup->firstIcon == NULL)
	{
		return;
	}
	for (int k = 0; k < lookup->numIcon; k++)
	{
		struct Icon *icon = &lookup->firstIcon[k];
		if (strncmp(icon->name, "map-proto8-01", sizeof(icon->name)) == 0)
		{
			struct TextureLayout *t = &icon->texLayout;
			s_mapVramX = (t->tpage & 0xf) * 64 + t->u0 / 4;
			s_mapVramY = ((t->tpage >> 4) & 1) * 256 + t->v0;
			s_mapFound = (t->u0 % 4) == 0;
			return;
		}
	}
}

static int NativeWorld_MapAt(int x, int z)
{
	return (x >= 0 && z >= 0 && x < s_mapW && z < s_mapH) ? (s_map[(size_t)z * s_mapW + x] & 3) : 0;
}

static void NativeWorld_UpdateMap(struct GameTracker *gGT)
{
	struct Driver *d = gGT->drivers[0];
	if (s_map == NULL || !s_mapFound || d == NULL)
	{
		return;
	}
	int wx = (d->posCurr.x >> 8) + s_worldOrigin.x, wz = (d->posCurr.z >> 8) + s_worldOrigin.z;
	int left = (int)floor((double)(wx - s_mapX) / s_mapUnits) - NATIVE_WORLD_MAP / 2;
	int top = (int)floor((double)(wz - s_mapZ) / s_mapUnits) - NATIVE_WORLD_MAP / 2;
	if (left == s_mapLeft && top == s_mapTop)
	{
		return;
	}
	s_mapLeft = left;
	s_mapTop = top;
	u16 words[NATIVE_WORLD_MAP / 4 * NATIVE_WORLD_MAP / 2];
	for (int row = 0; row < NATIVE_WORLD_MAP / 2; row++)
	{
		for (int col = 0; col < NATIVE_WORLD_MAP; col += 4)
		{
			u16 word = 0;
			for (int j = 0; j < 4; j++)
			{
				int hi = NativeWorld_MapAt(left + col + j, top + row);
				int lo = NativeWorld_MapAt(left + col + j, top + row + NATIVE_WORLD_MAP / 2);
				word |= (u16)(((hi << 2) | lo) << (4 * j));
			}
			words[row * (NATIVE_WORLD_MAP / 4) + col / 4] = word;
		}
	}
	RECT16 r = {(s16)s_mapVramX, (s16)s_mapVramY, NATIVE_WORLD_MAP / 4, NATIVE_WORLD_MAP / 2};
	LoadImage(&r, words);
}

// The racers' icons on a world's minimap: by the window of texels it shows. pos: x and z in
// the level's coordinates (the window's); returns 0 when the world draws no map of its own.
int NativeWorld_MapIconPos(const struct UIMap *map, s32 *posX, s32 *posY)
{
	if (!s_worldActive || s_map == NULL || !s_mapFound || s_mapLeft == (1 << 30))
	{
		return 0;
	}
	// the map image's corner on screen, from the level's own placement (its world rectangle)
	s32 rangeX = map->worldEndX - map->worldStartX;
	s32 rangeY = map->worldEndY - map->worldStartY;
	s32 screenLeft = map->iconStartX + map->worldStartX * map->iconSizeX / rangeX;
	s32 screenTop = map->iconStartY - UI_MAP_ICON_Y_OFFSET + map->worldStartY * map->iconSizeY * 2 / rangeY;
	s32 side = NATIVE_WORLD_MAP * s_mapUnits;
	s32 x = *posX + s_worldOrigin.x - (s_mapX + s_mapLeft * s_mapUnits);
	s32 z = *posY + s_worldOrigin.z - (s_mapZ + s_mapTop * s_mapUnits);
	*posX = screenLeft + x * map->iconSizeX / side;
	*posY = screenTop + z * map->iconSizeY * 2 / side;
	return 1;
}
