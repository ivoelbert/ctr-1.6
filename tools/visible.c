// Which triangles can be seen at all: renders them (with a depth buffer) from many camera
// views and counts, per triangle, the pixels where it is the nearest thing drawn.
//
// stdin:  int ntris, int nviews, int width, int height, float focal
//         ntris x (9 floats: corners, 3 floats: normal, int flags: 1 occludes, 2 double-sided)
//         nviews x (3 floats eye, 9 floats: right, down, forward rows)
// stdout: ntris x uint32 pixel counts (summed over the views)
// Occluders are drawn first; the others (see-through cutouts) are then tested against them
// and counted, but hide nothing.
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
	float p[3][3], n[3];
	int flags;
} Tri;

static int W, H;
static float F;
static float *zbuf;  // 1/z of the nearest occluder
static int32_t *ibuf;
static uint32_t *count;

static void read_all(void *dst, size_t size, size_t n)
{
	if (fread(dst, size, n, stdin) != n) {
		fprintf(stderr, "visible: short input\n");
		exit(1);
	}
}

typedef struct {
	float x, y, w;  // screen position, 1/z
} SV;

static float edge(const SV *a, const SV *b, float px, float py)
{
	return (b->x - a->x) * (py - a->y) - (b->y - a->y) * (px - a->x);
}

// pass 0: occluders write depth and id; pass 1: cutouts count where they pass the depth test
static void raster(SV a, SV b, SV c, int id, int pass)
{
	float area = edge(&a, &b, c.x, c.y);
	if (fabsf(area) < 1e-6f)
		return;
	if (area < 0) {
		SV t = b;
		b = c;
		c = t;
		area = -area;
	}
	int x0 = (int)floorf(fminf(a.x, fminf(b.x, c.x))), x1 = (int)ceilf(fmaxf(a.x, fmaxf(b.x, c.x)));
	int y0 = (int)floorf(fminf(a.y, fminf(b.y, c.y))), y1 = (int)ceilf(fmaxf(a.y, fmaxf(b.y, c.y)));
	if (x0 < 0) x0 = 0;
	if (y0 < 0) y0 = 0;
	if (x1 > W - 1) x1 = W - 1;
	if (y1 > H - 1) y1 = H - 1;
	for (int y = y0; y <= y1; y++) {
		for (int x = x0; x <= x1; x++) {
			float px = x + 0.5f, py = y + 0.5f;
			float w0 = edge(&b, &c, px, py), w1 = edge(&c, &a, px, py), w2 = edge(&a, &b, px, py);
			if (w0 < 0 || w1 < 0 || w2 < 0)
				continue;
			float iz = (w0 * a.w + w1 * b.w + w2 * c.w) / area;
			int k = y * W + x;
			if (iz <= zbuf[k])
				continue;
			if (pass == 0) {
				zbuf[k] = iz;
				ibuf[k] = id;
			} else {
				count[id]++;
			}
		}
	}
}

static void draw(const Tri *t, int id, const float *eye, const float *m, int pass)
{
	float d[3] = {eye[0] - t->p[0][0], eye[1] - t->p[0][1], eye[2] - t->p[0][2]};
	if (!(t->flags & 2) && d[0] * t->n[0] + d[1] * t->n[1] + d[2] * t->n[2] <= 0)
		return;  // seen from behind
	float c[3][3];
	for (int i = 0; i < 3; i++) {
		float r[3] = {t->p[i][0] - eye[0], t->p[i][1] - eye[1], t->p[i][2] - eye[2]};
		for (int j = 0; j < 3; j++)
			c[i][j] = m[3 * j] * r[0] + m[3 * j + 1] * r[1] + m[3 * j + 2] * r[2];
	}
	// clip at the near plane (z > 8): up to 4 points
	const float NEAR = 8.0f;
	float poly[4][3];
	int n = 0;
	for (int i = 0; i < 3; i++) {
		const float *a = c[i], *b = c[(i + 1) % 3];
		int ia = a[2] > NEAR, ib = b[2] > NEAR;
		if (ia)
			memcpy(poly[n++], a, sizeof(float) * 3);
		if (ia != ib) {
			float f = (NEAR - a[2]) / (b[2] - a[2]);
			for (int j = 0; j < 3; j++)
				poly[n][j] = a[j] + (b[j] - a[j]) * f;
			n++;
		}
	}
	if (n < 3)
		return;
	SV s[4];
	for (int i = 0; i < n; i++) {
		s[i].x = W * 0.5f + F * poly[i][0] / poly[i][2];
		s[i].y = H * 0.5f + F * poly[i][1] / poly[i][2];
		s[i].w = 1.0f / poly[i][2];
	}
	for (int i = 1; i < n - 1; i++)
		raster(s[0], s[i], s[i + 1], id, pass);
}

int main(void)
{
	int ntris, nviews;
	read_all(&ntris, 4, 1);
	read_all(&nviews, 4, 1);
	read_all(&W, 4, 1);
	read_all(&H, 4, 1);
	read_all(&F, 4, 1);
	Tri *tris = malloc(sizeof(Tri) * (size_t)ntris);
	for (int i = 0; i < ntris; i++) {
		read_all(tris[i].p, 4, 9);
		read_all(tris[i].n, 4, 3);
		read_all(&tris[i].flags, 4, 1);
	}
	zbuf = malloc(sizeof(float) * W * H);
	ibuf = malloc(sizeof(int32_t) * W * H);
	count = calloc((size_t)ntris, sizeof(uint32_t));
	for (int v = 0; v < nviews; v++) {
		float eye[3], m[9];
		read_all(eye, 4, 3);
		read_all(m, 4, 9);
		for (int k = 0; k < W * H; k++) {
			zbuf[k] = 0;
			ibuf[k] = -1;
		}
		for (int i = 0; i < ntris; i++)
			if (tris[i].flags & 1)
				draw(&tris[i], i, eye, m, 0);
		for (int k = 0; k < W * H; k++)
			if (ibuf[k] >= 0)
				count[ibuf[k]]++;
		for (int i = 0; i < ntris; i++)
			if (!(tris[i].flags & 1))
				draw(&tris[i], i, eye, m, 1);
	}
	fwrite(count, sizeof(uint32_t), (size_t)ntris, stdout);
	return 0;
}
