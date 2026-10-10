// NOTE(ctr-dust2): see native_precise.h.
#include <platform/native_precise.h>

#include <string.h>

// a direct-mapped table by word address: words within 8 MiB of each other never share a slot
// (a frame's primitive buffer is smaller)
#define NATIVE_PRECISE_SHADOW_BITS 21
#define NATIVE_PRECISE_SUBPIXEL    4096.0f

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
	int16_t dx, dy;
	float z;
} NativePreciseShadow;

static NativePreciseProjection s_preciseSxy[3];  // beside the GTE's SXY0..2
static NativePreciseShadow s_preciseShadow[1u << NATIVE_PRECISE_SHADOW_BITS];
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
	s->dx = (int16_t)(p->dx * NATIVE_PRECISE_SUBPIXEL);
	s->dy = (int16_t)(p->dy * NATIVE_PRECISE_SUBPIXEL);
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
	*dx = s->dx / NATIVE_PRECISE_SUBPIXEL;
	*dy = s->dy / NATIVE_PRECISE_SUBPIXEL;
	*z = s->z;
	return 1;
}
