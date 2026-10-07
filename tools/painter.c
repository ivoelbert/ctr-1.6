// Painter's-order audit for a CTR level; tools/painter.py builds it, feeds it and reads it.
//
// CTR draws the level without a depth buffer: each quadblock face goes into an ordering-table
// slot by its farthest corner's depth (>> 6, plus the face's draw-order byte), and the GPU
// paints the slots far to near. A face that reaches far (a long wall seen along its length)
// sorts as far as its far end, so a face just behind its near part can be painted after it,
// over it. For each camera view this finds every pixel's true front face with a depth buffer,
// then looks at the faces behind it there: one in a nearer slot is painted over it (an
// error), and so is one in the same slot whose quadblock had its turn first (a lost tie).
//
// Inside a slot the quadblocks' faces are painted in reverse order of the quadblocks' turn
// (each is linked in at the head of the slot's list), so of two faces in one slot the one
// whose quadblock came first ends up on top. The turn follows the BSP: the leaves are walked
// in a fixed order (child 0's side first) or, with mode 1, near side first (back to front).
//
// stdin:  i32 nfaces, nviews, width, height, nnodes, mode; f32 focal
//         nfaces x { f32 p[4][3]; i32 bias; i32 flags; i32 quad }  corners in the PS1 order
//                                                        0 1 / 2 3, triangles 0 1 2 and 1 3 2,
//                                                        front (p2 - p0) x (p1 - p0); flags
//                                                        1: double-sided; quad: its index in
//                                                        the level's quadblock array
//         nnodes x { i32 leaf, axis, split, child0, child1, first, count }  the BSP (node 0
//                                                        the root, children -1 when none)
//         nviews x { f32 eye[3]; f32 m[9]; f32 anchor[3] }  m rows: right, down (with the
//                                                        aspect), forward, as CTR's view
//                                                        matrix; a view whose eye can't see
//                                                        its anchor (the kart) is skipped
// stdout: nfaces x { u32 front_err, front_tie, behind_err, views_err }  front_tie: pixels
//                                                        where a face behind in the same slot
//                                                        ends up on top
//         nviews x { i32 err, tie }  (-1: skipped)
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ZNEAR 64.0f
#define EPS 0.01f      // a face counts as behind another 1% of the depth farther away
#define MAX_SLOT 1020

typedef struct
{
	float p[4][3];
	int32_t bias, flags, quad;
} Face;

typedef struct
{
	int32_t leaf, axis, split, child[2], first, count;
} Node;

typedef struct
{
	float eye[3], m[9], anchor[3];
} View;

typedef struct
{
	float x, y, iz;
} SV;

static int W, H;
static float F;
static float *zbuf;
static int32_t *ibuf;
static uint8_t *mark;
static int32_t *key, *qrank, *rank;
static Face *faces;
static uint32_t *front_err, *front_tie, *behind_err, *views_err, *stamp;

static void read_all(void *dst, size_t size, size_t count)
{
	if (fread(dst, size, count, stdin) != count)
	{
		fprintf(stderr, "painter: short input\n");
		exit(1);
	}
}

static float edge(const SV *a, const SV *b, float px, float py)
{
	return (b->x - a->x) * (py - a->y) - (b->y - a->y) * (px - a->x);
}

static void raster(SV a, SV b, SV c, int face, int pass)
{
	float area = edge(&a, &b, c.x, c.y);
	if (fabsf(area) < 1e-4f)
		return;
	if (area < 0)
	{
		SV t = b;
		b = c;
		c = t;
		area = -area;
	}
	float minx = fminf(a.x, fminf(b.x, c.x)), maxx = fmaxf(a.x, fmaxf(b.x, c.x));
	float miny = fminf(a.y, fminf(b.y, c.y)), maxy = fmaxf(a.y, fmaxf(b.y, c.y));
	int x0 = (int)floorf(minx), x1 = (int)ceilf(maxx), y0 = (int)floorf(miny), y1 = (int)ceilf(maxy);
	if (x0 < 0)
		x0 = 0;
	if (y0 < 0)
		y0 = 0;
	if (x1 > W - 1)
		x1 = W - 1;
	if (y1 > H - 1)
		y1 = H - 1;
	float inv = 1.0f / area;
	for (int y = y0; y <= y1; y++)
	{
		float py = y + 0.5f;
		for (int x = x0; x <= x1; x++)
		{
			float px = x + 0.5f;
			float w0 = edge(&b, &c, px, py), w1 = edge(&c, &a, px, py), w2 = edge(&a, &b, px, py);
			if (w0 < 0 || w1 < 0 || w2 < 0)
				continue;
			float iz = (w0 * a.iz + w1 * b.iz + w2 * c.iz) * inv;
			int i = y * W + x;
			if (pass == 0)
			{
				if (iz > zbuf[i])
				{
					zbuf[i] = iz;
					ibuf[i] = face;
				}
				continue;
			}
			int t = ibuf[i];
			if (t < 0 || t == face || iz >= zbuf[i] * (1.0f - EPS))
				continue;
			if (key[face] < key[t])
			{
				mark[i] = 2;
				behind_err[face]++;
			}
			else if (key[face] == key[t] && rank[face] < rank[t] && mark[i] == 0)
			{
				mark[i] = 1;
				behind_err[face]++;
			}
		}
	}
}

// view-space triangle (x, y, z) clipped at z = ZNEAR, projected and rasterized as a fan
static void draw_tri(const float v[3][3], int face, int pass)
{
	float poly[4][3];
	int n = 0;
	for (int k = 0; k < 3; k++)
	{
		const float *a = v[k], *b = v[(k + 1) % 3];
		int ina = a[2] >= ZNEAR, inb = b[2] >= ZNEAR;
		if (ina)
			memcpy(poly[n++], a, sizeof(float) * 3);
		if (ina != inb)
		{
			float t = (ZNEAR - a[2]) / (b[2] - a[2]);
			for (int d = 0; d < 3; d++)
				poly[n][d] = a[d] + (b[d] - a[d]) * t;
			poly[n][2] = ZNEAR;
			n++;
		}
	}
	if (n < 3)
		return;
	SV s[4];
	for (int k = 0; k < n; k++)
	{
		s[k].iz = 1.0f / poly[k][2];
		s[k].x = F * poly[k][0] * s[k].iz + W * 0.5f;
		s[k].y = F * poly[k][1] * s[k].iz + H * 0.5f;
	}
	for (int k = 1; k + 1 < n; k++)
		raster(s[0], s[k], s[k + 1], face, pass);
}

static void sub3(float *o, const float *a, const float *b)
{
	o[0] = a[0] - b[0];
	o[1] = a[1] - b[1];
	o[2] = a[2] - b[2];
}

static void cross3(float *o, const float *a, const float *b)
{
	o[0] = a[1] * b[2] - a[2] * b[1];
	o[1] = a[2] * b[0] - a[0] * b[2];
	o[2] = a[0] * b[1] - a[1] * b[0];
}

static float dot3(const float *a, const float *b)
{
	return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

static const int TRI[2][3] = {{0, 1, 2}, {1, 3, 2}};

// does the segment o -> o + d (0 < t < 1) cross the triangle?
static int seg_hits(const float *o, const float *d, const float *p0, const float *p1, const float *p2)
{
	float e1[3], e2[3], pv[3], tv[3], qv[3];
	sub3(e1, p1, p0);
	sub3(e2, p2, p0);
	cross3(pv, d, e2);
	float det = dot3(e1, pv);
	if (fabsf(det) < 1e-6f)
		return 0;
	float inv = 1.0f / det;
	sub3(tv, o, p0);
	float u = dot3(tv, pv) * inv;
	if (u < 0 || u > 1)
		return 0;
	cross3(qv, tv, e1);
	float w = dot3(d, qv) * inv;
	if (w < 0 || u + w > 1)
		return 0;
	float t = dot3(e2, qv) * inv;
	return t > 0.0f && t < 1.0f;
}

static Node *nodes;
static int next_rank;

// the quadblocks' turn: leaves in walk order (near side first in mode 1), quadblocks in a leaf
// in array order
static void walk(int n, const float *eye, int mode)
{
	if (n < 0)
		return;
	const Node *b = &nodes[n];
	if (b->leaf)
	{
		for (int k = 0; k < b->count; k++)
			qrank[b->first + k] = next_rank++;
		return;
	}
	int near = 0;
	if (mode == 1 && eye[b->axis] >= (float)b->split)
		near = 1;
	walk(b->child[near], eye, mode);
	walk(b->child[1 - near], eye, mode);
}

int main(void)
{
	int32_t hdr[6];
	read_all(hdr, 4, 6);
	read_all(&F, 4, 1);
	int nf = hdr[0], nv = hdr[1], nn = hdr[4], mode = hdr[5];
	W = hdr[2];
	H = hdr[3];
	faces = malloc(sizeof(Face) * nf);
	View *views = malloc(sizeof(View) * nv);
	nodes = malloc(sizeof(Node) * nn);
	read_all(faces, sizeof(Face), nf);
	read_all(nodes, sizeof(Node), nn);
	read_all(views, sizeof(View), nv);
	int nq = 0;
	for (int f = 0; f < nf; f++)
		if (faces[f].quad + 1 > nq)
			nq = faces[f].quad + 1;
	for (int n = 0; n < nn; n++)
		if (nodes[n].leaf && nodes[n].first + nodes[n].count > nq)
			nq = nodes[n].first + nodes[n].count;
	qrank = malloc(sizeof(int32_t) * nq);
	rank = malloc(sizeof(int32_t) * nf);

	zbuf = malloc(sizeof(float) * W * H);
	ibuf = malloc(sizeof(int32_t) * W * H);
	mark = malloc(W * H);
	key = malloc(sizeof(int32_t) * nf);
	front_err = calloc(nf, 4);
	front_tie = calloc(nf, 4);
	behind_err = calloc(nf, 4);
	views_err = calloc(nf, 4);
	stamp = calloc(nf, 4);
	int32_t *view_out = calloc(nv * 2, 4);
	float (*vs)[4][3] = malloc(sizeof(float) * 12 * nf);
	uint8_t *live = malloc(nf);
	float *centre = malloc(sizeof(float) * 3 * nf), *radius = malloc(sizeof(float) * nf);
	for (int f = 0; f < nf; f++)
	{
		float *c = &centre[3 * f];
		for (int d = 0; d < 3; d++)
			c[d] = 0.25f * (faces[f].p[0][d] + faces[f].p[1][d] + faces[f].p[2][d] + faces[f].p[3][d]);
		float r = 0;
		for (int k = 0; k < 4; k++)
		{
			float dv[3];
			sub3(dv, faces[f].p[k], c);
			r = fmaxf(r, sqrtf(dot3(dv, dv)));
		}
		radius[f] = r;
	}

	for (int vi = 0; vi < nv; vi++)
	{
		const View *v = &views[vi];
		// a camera inside a wall sees nothing a player does
		float seg[3], mid[3];
		sub3(seg, v->eye, v->anchor);
		float half = 0.5f * sqrtf(dot3(seg, seg));
		for (int d = 0; d < 3; d++)
			mid[d] = v->anchor[d] + 0.5f * seg[d];
		int blocked = 0;
		for (int f = 0; f < nf && !blocked; f++)
		{
			float dv[3];
			sub3(dv, &centre[3 * f], mid);
			float r = half + radius[f];
			if (dot3(dv, dv) > r * r)
				continue;
			for (int t = 0; t < 2 && !blocked; t++)
				blocked = seg_hits(v->anchor, seg, faces[f].p[TRI[t][0]], faces[f].p[TRI[t][1]], faces[f].p[TRI[t][2]]);
		}
		if (blocked)
		{
			view_out[2 * vi] = view_out[2 * vi + 1] = -1;
			continue;
		}

		for (int i = 0; i < W * H; i++)
		{
			zbuf[i] = 0;
			ibuf[i] = -1;
			mark[i] = 0;
		}
		next_rank = 0;
		walk(0, v->eye, mode);
		for (int f = 0; f < nf; f++)
			rank[f] = qrank[faces[f].quad];
		const float *right = &v->m[0], *down = &v->m[3], *fwd = &v->m[6];
		float ys = sqrtf(dot3(down, down));
		for (int f = 0; f < nf; f++)
		{
			live[f] = 0;
			float dv[3];
			sub3(dv, &centre[3 * f], v->eye);
			float cz = dot3(fwd, dv), cx = dot3(right, dv), cy = dot3(down, dv) / ys, r = radius[f];
			// outside the view: behind, or past the side (45 degrees) or top/bottom planes
			if (cz < ZNEAR - r || (fabsf(cx) - cz) * 0.7072f > r || (fabsf(cy) - 0.75f * cz) * 0.8f > r * 1.0001f + 1.0f)
				continue;
			float maxz = -1e30f;
			for (int k = 0; k < 4; k++)
			{
				float pv[3];
				sub3(pv, faces[f].p[k], v->eye);
				vs[f][k][0] = dot3(right, pv);
				vs[f][k][1] = dot3(down, pv);
				vs[f][k][2] = dot3(fwd, pv);
				maxz = fmaxf(maxz, vs[f][k][2]);
			}
			if (maxz < ZNEAR)
				continue;
			int slot = ((int)maxz >> 6) + faces[f].bias;
			key[f] = slot < 0 ? 0 : (slot > MAX_SLOT ? MAX_SLOT : slot);
			live[f] = 1;
		}
		for (int pass = 0; pass < 2; pass++)
		{
			for (int f = 0; f < nf; f++)
			{
				if (!live[f])
					continue;
				for (int t = 0; t < 2; t++)
				{
					const float *p0 = faces[f].p[TRI[t][0]], *p1 = faces[f].p[TRI[t][1]], *p2 = faces[f].p[TRI[t][2]];
					if (!(faces[f].flags & 1))
					{
						float e1[3], e2[3], n[3], to[3];
						sub3(e1, p2, p0);
						sub3(e2, p1, p0);
						cross3(n, e1, e2);
						sub3(to, v->eye, p0);
						if (dot3(n, to) <= 0)
							continue;
					}
					float tv[3][3];
					for (int k = 0; k < 3; k++)
						memcpy(tv[k], vs[f][TRI[t][k]], sizeof(float) * 3);
					draw_tri(tv, f, pass);
				}
			}
		}
		int err = 0, tie = 0;
		for (int i = 0; i < W * H; i++)
		{
			if (!mark[i])
				continue;
			int t = ibuf[i];
			if (mark[i] == 2)
			{
				err++;
				front_err[t]++;
				if (stamp[t] != (uint32_t)vi + 1)
				{
					stamp[t] = vi + 1;
					views_err[t]++;
				}
			}
			else
			{
				tie++;
				front_tie[t]++;
			}
		}
		view_out[2 * vi] = err;
		view_out[2 * vi + 1] = tie;
	}

	for (int f = 0; f < nf; f++)
	{
		uint32_t row[4] = {front_err[f], front_tie[f], behind_err[f], views_err[f]};
		fwrite(row, 4, 4, stdout);
	}
	fwrite(view_out, 4, nv * 2, stdout);
	return 0;
}
