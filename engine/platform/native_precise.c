// NOTE(ctr-dust2): see native_precise.h.
#include <platform/native_precise.h>

#include <string.h>

#include <ctr_scratchpad.h>

// a direct-mapped table by word address: words within 8 MiB of each other never share a slot
// (a frame's primitive buffer is smaller). The scratchpad, where the level renderer keeps the
// vertices it's working on, has a table of its own: a primitive written 8 MiB past it took a
// vertex's slot halfway through a face (its subdivisions then had no exact depth, and were
// painted unsorted, over the road in front of them)
#define NATIVE_PRECISE_SHADOW_BITS 21

typedef struct
{
	uint32_t sxy;
	int valid;
	float dx, dy, z;
} NativePreciseProjection;

typedef struct
{
	const void *addr;
	uint32_t sxy;  // the word it describes
	float dx, dy;  // pixels: past the GTE's ±1024 limit the exact place is far from the clamped one
	float z;
} NativePreciseShadow;

static NativePreciseProjection s_preciseSxy[3];  // beside the GTE's SXY0..2
static NativePreciseShadow s_preciseShadow[1u << NATIVE_PRECISE_SHADOW_BITS];
static NativePreciseShadow s_preciseScratch[CTR_SCRATCHPAD_SIZE / 4];
static int s_preciseEnabled;
static int s_preciseRecording;

void NativePrecise_BeginLevel(int enabled)
{
	s_preciseEnabled = enabled;
	s_preciseRecording = s_preciseEnabled;
}

void NativePrecise_EndLevel(void)
{
	s_preciseRecording = 0;
}

static NativePreciseShadow *NativePrecise_Slot(const void *addr)
{
	uintptr_t scratch = (uintptr_t)addr - (uintptr_t)CTR_SCRATCHPAD_BASE;

	if (scratch < CTR_SCRATCHPAD_SIZE)
	{
		return &s_preciseScratch[scratch >> 2];
	}
	return &s_preciseShadow[((uintptr_t)addr >> 2) & ((1u << NATIVE_PRECISE_SHADOW_BITS) - 1)];
}

static uint32_t NativePrecise_Load(const void *addr)
{
	uint32_t w;

	memcpy(&w, addr, 4);
	return w;
}

void NativePrecise_PushProjection(uint32_t sxy, int valid, float dx, float dy, float z)
{
	s_preciseSxy[0] = s_preciseSxy[1];
	s_preciseSxy[1] = s_preciseSxy[2];
	s_preciseSxy[2] = (NativePreciseProjection){sxy, valid && s_preciseRecording, dx, dy, z};
}

void NativePrecise_StoreSXY(const void *addr, int reg)
{
	if (!s_preciseRecording)
	{
		return;
	}

	const NativePreciseProjection *p = &s_preciseSxy[reg];
	NativePreciseShadow *s = NativePrecise_Slot(addr);
	uint32_t sxy = NativePrecise_Load(addr);

	if (!p->valid || p->sxy != sxy)
	{
		s->addr = NULL;
		return;
	}
	s->addr = addr;
	s->sxy = sxy;
	s->dx = p->dx;
	s->dy = p->dy;
	s->z = p->z;
}

void NativePrecise_Copy(const void *dst, const void *src)
{
	if (!s_preciseRecording)
	{
		return;
	}

	const NativePreciseShadow *s = NativePrecise_Slot(src);
	NativePreciseShadow *d = NativePrecise_Slot(dst);
	uint32_t sxy = NativePrecise_Load(src);

	if (s->addr != src || s->sxy != sxy || NativePrecise_Load(dst) != sxy)
	{
		d->addr = NULL;
		return;
	}
	*d = *s;
	d->addr = dst;
}

int NativePrecise_Get(const void *addr, float *dx, float *dy, float *z)
{
	if (!s_preciseEnabled)
	{
		return 0;
	}

	const NativePreciseShadow *s = NativePrecise_Slot(addr);

	if (s->addr != addr || s->sxy != NativePrecise_Load(addr))
	{
		return 0;
	}
	*dx = s->dx;
	*dy = s->dy;
	*z = s->z;
	return 1;
}
