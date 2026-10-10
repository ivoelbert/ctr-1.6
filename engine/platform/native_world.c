// NOTE(ctr-dust2): a floating origin for custom levels (native_world.h).

#include "platform/native_world.h"

static int s_worldShiftPending;
static Vec3 s_worldShift;
static Vec3 s_worldOrigin;

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

// The level's own positions: vertices, quadblock and BSP boxes, split planes, pickup hitboxes,
// checkpoints, nav paths, spawns. (The minimap stays in the level's own coordinates: UI_Map_GetIconPos.)
static void NativeWorld_ShiftLevel(struct Level *lev, int dx, int dy, int dz)
{
	struct mesh_info *mesh = lev->ptr_mesh_info;
	if (mesh != 0)
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
		inst->matrix.t[0] += dx;
		inst->matrix.t[1] += dy;
		inst->matrix.t[2] += dz;
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

void NativeWorld_FrameStart(struct GameTracker *gGT)
{
	if (!s_worldShiftPending || gGT->level1 == 0 || !LOAD_IsCustomLevel(gGT->levelID))
	{
		return;
	}
	int dx = s_worldShift.x, dy = s_worldShift.y, dz = s_worldShift.z;
	s_worldShiftPending = 0;
	s_worldShift.x = s_worldShift.y = s_worldShift.z = 0;
	NativeWorld_ShiftLevel(gGT->level1, dx, dy, dz);
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
