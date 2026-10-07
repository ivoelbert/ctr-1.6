#include <common.h>

static inline u32 MATH_Matrix_ReadWord(const void *ptr, s32 offset)
{
	return CTR_ReadU32LE((u8 *)ptr + offset);
}

static inline void MATH_Matrix_WriteWord(void *ptr, s32 offset, u32 value)
{
	CTR_WriteU32LE((u8 *)ptr + offset, value);
}

static inline u32 MATH_Matrix_NegLowWord(u32 value)
{
	return (0u - value) & 0xffff;
}

static inline u32 MATH_Matrix_NegHighWord(u32 value)
{
	return MATH_Matrix_NegLowWord(value) << 0x10;
}

static void MATH_Matrix_TrigSinCos(u32 angle, u32 *sinOut, u32 *cosOut)
{
	u32 trig = CTR_ReadU32LE(&data.trigApprox[ANG_MODULO_HALF_PI(angle)]);
	u32 quadrant = angle & ANG_QUADRANT_BITS;

	if (quadrant == 0)
	{
		*sinOut = trig & 0xffff;
		*cosOut = trig >> 0x10;
	}
	else if (quadrant == ANG_QUADRANT_BIT)
	{
		*sinOut = trig >> 0x10;
		*cosOut = MATH_Matrix_NegLowWord(trig);
	}
	else if (quadrant == ANG_SIGN_BIT)
	{
		*sinOut = MATH_Matrix_NegLowWord(trig);
		*cosOut = MATH_Matrix_NegLowWord(trig >> 0x10);
	}
	else
	{
		*sinOut = MATH_Matrix_NegLowWord(trig >> 0x10);
		*cosOut = trig & 0xffff;
	}
}

static void MATH_Matrix_LoadRotWords(u32 r0, u32 r1, u32 r2, u32 r3, u32 r4)
{
	CTC2(r0, 0);
	CTC2(r1, 1);
	CTC2(r2, 2);
	CTC2(r3, 3);
	CTC2(r4, 4);
}

#ifdef CTR_NATIVE
void MATRIX_SET_r11r12r13r14r15(u32 r0, u32 r1, u32 r2, u32 r3, u32 r4)
{
	// NOTE(aalhendi): Retail inputs are t3/t4/t5/t6/t7 and writes GTE regs 0-4.
	MATH_Matrix_LoadRotWords(r0, r1, r2, r3, r4);
}

void Unknown_8006c600(u32 r0, u32 r1, u32 r2, u32 r3, u32 r4)
{
	// NOTE(aalhendi): Retail inputs are t3/t4/t5/t6/t7 and writes GTE regs 8-12.
	CTC2(r0, 8);
	CTC2(r1, 9);
	CTC2(r2, 10);
	CTC2(r3, 11);
	CTC2(r4, 12);
}
#else
// NOTE(aalhendi): These GTE loaders receive t3-t7 from the resident matrix
// routine, not C ABI arguments. Native keeps callable C implementations.
__asm__(".section .MATRIX_SET_r11r12r13r14r15,\"ax\",@progbits\n"
        ".align 2\n"
        ".ent MATRIX_SET_r11r12r13r14r15\n"
        ".set noreorder\n"
        ".globl MATRIX_SET_r11r12r13r14r15\n"
        "MATRIX_SET_r11r12r13r14r15:\n"
        "ctc2 $t3,$0\n"
        "ctc2 $t4,$1\n"
        "ctc2 $t5,$2\n"
        "ctc2 $t6,$3\n"
        "jr $ra\n"
        "ctc2 $t7,$4\n"
        ".end MATRIX_SET_r11r12r13r14r15\n"
        ".set reorder\n"
        ".text\n");

__asm__(".section .Unknown_8006c600,\"ax\",@progbits\n"
        ".align 2\n"
        ".ent Unknown_8006c600\n"
        ".set noreorder\n"
        ".globl Unknown_8006c600\n"
        "Unknown_8006c600:\n"
        "ctc2 $t3,$8\n"
        "ctc2 $t4,$9\n"
        "ctc2 $t5,$10\n"
        "ctc2 $t6,$11\n"
        "jr $ra\n"
        "ctc2 $t7,$12\n"
        ".end Unknown_8006c600\n"
        ".set reorder\n"
        ".text\n");
#endif

static void MATH_Matrix_MulRotWords(u32 *r0, u32 *r1, u32 *r2, u32 *r3, u32 *r4)
{
	u32 t3 = *r0;
	u32 t4 = *r1;
	u32 t5 = *r2;
	u32 t6 = *r3;
	u32 t7 = *r4;
	u32 nextT6;
	u32 nextT5;

	u32 v0 = (t3 & 0xffff) | (t4 & 0xffff0000);
	MTC2(v0, 0);
	MTC2(t6, 1);

	v0 = (t3 >> 0x10) | (t5 << 0x10);
	gte_rtv0_b();
	MTC2(v0, 2);
	MTC2(t6 >> 0x10, 3);

	v0 = (t4 & 0xffff) | (t5 & 0xffff0000);
	t3 = MFC2(9);
	t4 = MFC2(10);
	t6 = MFC2(11);
	gte_rtv1_b();
	MTC2(v0, 4);
	MTC2(t7, 5);

	t3 &= 0xffff;
	t4 <<= 0x10;
	t6 &= 0xffff;

	v0 = MFC2(9);
	t5 = MFC2(10);
	nextT6 = MFC2(11);
	gte_rtv2_b();

	t3 |= v0 << 0x10;
	t5 &= 0xffff;
	t6 |= nextT6 << 0x10;

	v0 = MFC2(9) & 0xffff;
	nextT5 = MFC2(10);
	t7 = MFC2(11);

	t4 |= v0;
	t5 |= nextT5 << 0x10;

	*r0 = t3;
	*r1 = t4;
	*r2 = t5;
	*r3 = t6;
	*r4 = t7;

	MATH_Matrix_LoadRotWords(t3, t4, t5, t6, t7);
}

void Unknown_8006c49c(u32 *r0, u32 *r1, u32 *r2, u32 *r3, u32 *r4)
{
	// NOTE(aalhendi): Retail transforms and reloads caller-owned t3/t4/t5/t6/t7.
	MATH_Matrix_MulRotWords(r0, r1, r2, r3, r4);
}

void Unknown_8006c558(u32 *r0, u32 *r1, u32 *r2, u32 *r3, u32 *r4)
{
	u32 t3 = *r0;
	u32 t4 = *r1;
	u32 t5 = *r2;
	u32 t6 = *r3;
	u32 t7 = *r4;
	u32 nextT6;
	u32 nextT5;

	u32 v0 = (t3 & 0xffff) | (t4 & 0xffff0000);
	MTC2(v0, 0);
	MTC2(t6, 1);

	v0 = (t3 >> 0x10) | (t5 << 0x10);
	gte_llv0_b();
	MTC2(v0, 2);
	MTC2(t6 >> 0x10, 3);

	v0 = (t4 & 0xffff) | (t5 & 0xffff0000);
	t3 = MFC2(9);
	t4 = MFC2(10);
	t6 = MFC2(11);
	gte_llv1_b();
	MTC2(v0, 4);
	MTC2(t7, 5);

	t3 &= 0xffff;
	t4 <<= 0x10;
	t6 &= 0xffff;

	v0 = MFC2(9);
	t5 = MFC2(10);
	nextT6 = MFC2(11);
	gte_llv2_b();

	t3 |= v0 << 0x10;
	t5 &= 0xffff;
	t6 |= nextT6 << 0x10;

	v0 = MFC2(9) & 0xffff;
	nextT5 = MFC2(10);
	t7 = MFC2(11);

	t4 |= v0;
	t5 |= nextT5 << 0x10;

	*r0 = t3;
	*r1 = t4;
	*r2 = t5;
	*r3 = t6;
	*r4 = t7;
}

static void MATH_Matrix_StoreWords(void *m, u32 r0, u32 r1, u32 r2, u32 r3, u32 r4)
{
	MATH_Matrix_WriteWord(m, 0x0, r0);
	MATH_Matrix_WriteWord(m, 0x4, r1);
	MATH_Matrix_WriteWord(m, 0x8, r2);
	MATH_Matrix_WriteWord(m, 0xc, r3);
	MATH_Matrix_WriteWord(m, 0x10, r4);
}

static void MATH_Matrix_MulIfNonZero(s32 angle, u32 *r0, u32 *r1, u32 *r2, u32 *r3, u32 *r4, s32 axis)
{
	u32 sine;
	u32 cosine;

	if (angle == 0)
	{
		return;
	}

	MATH_Matrix_TrigSinCos(angle, &sine, &cosine);

	if (axis == 0)
	{
		*r0 = FP_ONE;
		*r1 = 0;
		*r2 = MATH_Matrix_NegHighWord(sine) | cosine;
		*r3 = sine << 0x10;
		*r4 = cosine;
	}
	else if (axis == 1)
	{
		*r0 = cosine;
		*r1 = sine;
		*r2 = FP_ONE;
		*r3 = MATH_Matrix_NegLowWord(sine);
		*r4 = cosine;
	}
	else
	{
		*r0 = MATH_Matrix_NegHighWord(sine) | cosine;
		*r1 = sine << 0x10;
		*r2 = cosine;
		*r3 = 0;
		*r4 = FP_ONE;
	}

	MATH_Matrix_MulRotWords(r0, r1, r2, r3, r4);
}

void ConvertRotToMatrix_InverseTranspose_NoRotY(MATRIX *m, const SVec3 *rot)
{
	u32 sine;
	u32 cosine;
	u32 r0;
	u32 r1;
	u32 r2;
	u32 r3 = 0;
	u32 r4 = FP_ONE;

	MATH_Matrix_TrigSinCos((s32)rot->z, &sine, &cosine);
	r0 = MATH_Matrix_NegHighWord(sine) | cosine;
	r1 = sine << 0x10;
	r2 = cosine;
	MATH_Matrix_LoadRotWords(r0, r1, r2, r3, r4);

	MATH_Matrix_MulIfNonZero((s32)rot->x, &r0, &r1, &r2, &r3, &r4, 0);
	MATH_Matrix_StoreWords(m, r0, r1, r2, r3, r4);
}

static void MATH_Matrix_InverseTransposeBody(MATRIX *m, s32 rotX, s32 rotZ, s32 rotY)
{
	u32 sine;
	u32 cosine;
	u32 r0;
	u32 r1;
	u32 r2;
	u32 r3 = 0;
	u32 r4 = FP_ONE;

	MATH_Matrix_TrigSinCos(rotZ, &sine, &cosine);
	r0 = MATH_Matrix_NegHighWord(sine) | cosine;
	r1 = sine << 0x10;
	r2 = cosine;
	MATH_Matrix_LoadRotWords(r0, r1, r2, r3, r4);

	MATH_Matrix_MulIfNonZero(rotX, &r0, &r1, &r2, &r3, &r4, 0);
	MATH_Matrix_MulIfNonZero(rotY, &r0, &r1, &r2, &r3, &r4, 1);
	MATH_Matrix_StoreWords(m, r0, r1, r2, r3, r4);
}

void ConvertRotToMatrix_InverseTranspose(MATRIX *m, const SVec3 *rot)
{
	MATH_Matrix_InverseTransposeBody(m, (s32)rot->x, (s32)rot->z, (s32)rot->y);
}

void ConvertRotToMatrix(MATRIX *m, const SVec3 *rot)
{
	u32 sine;
	u32 cosine;
	u32 r0;
	u32 r1;
	u32 r2 = FP_ONE;
	u32 r3;
	u32 r4;

	MATH_Matrix_TrigSinCos((s32)rot->y, &sine, &cosine);
	r0 = cosine;
	r1 = sine;
	r3 = MATH_Matrix_NegLowWord(sine);
	r4 = cosine;
	MATH_Matrix_LoadRotWords(r0, r1, r2, r3, r4);

	MATH_Matrix_MulIfNonZero((s32)rot->x, &r0, &r1, &r2, &r3, &r4, 0);
	MATH_Matrix_MulIfNonZero((s32)rot->z, &r0, &r1, &r2, &r3, &r4, 2);
	MATH_Matrix_StoreWords(m, r0, r1, r2, r3, r4);
}

void ConvertRotToMatrix_Transpose(MATRIX *m, const SVec3 *rot)
{
	MATH_Matrix_InverseTransposeBody(m, -(s32)rot->x, -(s32)rot->z, -(s32)rot->y);
}

// NOTE(aalhendi): The destination is five packed GTE rotation words, not a
// complete MATRIX. Cutscene tables store this compact form without translation.
void MatrixRotate(void *dst, MATRIX *src, MATRIX *rot)
{
	u32 r0 = MATH_Matrix_ReadWord(src, 0x0);
	u32 r1 = MATH_Matrix_ReadWord(src, 0x4);
	u32 r2 = MATH_Matrix_ReadWord(src, 0x8);
	u32 r3 = MATH_Matrix_ReadWord(src, 0xc);
	u32 r4 = MATH_Matrix_ReadWord(src, 0x10);

	MATH_Matrix_LoadRotWords(r0, r1, r2, r3, r4);

	r0 = MATH_Matrix_ReadWord(rot, 0x0);
	r1 = MATH_Matrix_ReadWord(rot, 0x4);
	r2 = MATH_Matrix_ReadWord(rot, 0x8);
	r3 = MATH_Matrix_ReadWord(rot, 0xc);
	r4 = MATH_Matrix_ReadWord(rot, 0x10);

	MATH_Matrix_MulRotWords(&r0, &r1, &r2, &r3, &r4);
	MATH_Matrix_StoreWords(dst, r0, r1, r2, r3, r4);
}

#ifdef CTR_NATIVE
s32 SquareRoot0_stub(s32 value)
{
	u32 shifted;
	s32 leading;
	s32 bit;
	u32 remainder;
	u32 root;

	MTC2((u32)value, 30);
	if (value == 0)
	{
		return 0;
	}

	shifted = (u32)value;
	leading = MFC2(31) & 0x1e;
	shifted <<= leading;

	bit = leading ^ 0x1e;
	remainder = 0;
	root = 0;

	do
	{
		u32 trial;
		u32 nextRemainder;

		remainder |= shifted >> 0x1e;
		trial = (root << 2) + 1;
		root <<= 1;

		nextRemainder = remainder - trial;
		shifted <<= 2;
		if ((s32)nextRemainder >= 0)
		{
			root++;
			remainder = nextRemainder << 2;
		}
		else
		{
			remainder <<= 2;
		}

		bit -= 2;
	} while (bit >= 0);

	return (s32)root;
}
#else
// NOTE(aalhendi): Retail carries the result in v0 and uses the GTE leading-zero
// count in t1. GCC's C loop adds a second live result register and a branch,
// so keep this small PSX routine in its original register/branch shape.
__asm__(".section .SquareRoot0_stub,\"ax\",@progbits\n"
        ".align 2\n"
        ".ent SquareRoot0_stub\n"
        ".set\tnoreorder\n"
        ".globl SquareRoot0_stub\n"
        "SquareRoot0_stub:\n"
        "mtc2 $a0,$30\n"
        "beq $a0,$zero,.Lsqrt_zero\n"
        "addiu $v0,$zero,0\n"
        "mfc2 $t1,$31\n"
        "addiu $v1,$zero,0\n"
        "andi $t1,$t1,0x1e\n"
        "sllv $a0,$a0,$t1\n"
        "bgez $zero,.Lsqrt_test\n"
        "xori $t1,$t1,0x1e\n"
        ".Lsqrt_loop:\n"
        "srl $t0,$a0,0x1e\n"
        "or $v1,$v1,$t0\n"
        "sll $t0,$v0,2\n"
        "addiu $t0,$t0,1\n"
        "sll $v0,$v0,1\n"
        "subu $t0,$v1,$t0\n"
        "bltz $t0,.Lsqrt_subtract_failed\n"
        "sll $a0,$a0,2\n"
        "addiu $v0,$v0,1\n"
        "sll $v1,$t0,2\n"
        ".Lsqrt_test:\n"
        "bgez $t1,.Lsqrt_loop\n"
        "addiu $t1,$t1,-2\n"
        "jr $ra\n"
        ".Lsqrt_subtract_failed:\n"
        "sll $v1,$v1,2\n"
        "bgez $t1,.Lsqrt_loop\n"
        "addiu $t1,$t1,-2\n"
        ".Lsqrt_zero:\n"
        "jr $ra\n"
        "nop\n"
        ".end SquareRoot0_stub\n"
        ".set\treorder\n"
        ".text\n");
#endif

#ifdef CTR_NATIVE
VECTOR *ApplyMatrixLV_stub(VECTOR *input, VECTOR *output)
{
	u32 x = (u32)input->vx;
	u32 y = (u32)input->vy;
	u32 z = (u32)input->vz;
	u32 highX;
	u32 highY;
	u32 highZ;

	MTC2((u32)((s32)x >> 0xf), 9);
	MTC2((u32)((s32)y >> 0xf), 10);
	MTC2((u32)((s32)z >> 0xf), 11);

	x &= 0x7fff;
	gte_rtir_sf0_b();
	y &= 0x7fff;
	z &= 0x7fff;

	highX = MFC2(25);
	highY = MFC2(26);
	highZ = MFC2(27);

	MTC2(x, 9);
	MTC2(y, 10);
	MTC2(z, 11);

	highX <<= 3;
	gte_rtir_b();
	highY <<= 3;
	highZ <<= 3;

	output->vx = (s32)(MFC2(25) + highX);
	output->vy = (s32)(MFC2(26) + highY);
	output->vz = (s32)(MFC2(27) + highZ);

	return output;
}

VECTOR *Unknown_8006c6c8(VECTOR *input, VECTOR *output, MATRIX *matrix)
{
	MATH_Matrix_LoadRotWords(MATH_Matrix_ReadWord(matrix, 0x0), MATH_Matrix_ReadWord(matrix, 0x4), MATH_Matrix_ReadWord(matrix, 0x8),
	                         MATH_Matrix_ReadWord(matrix, 0xc), MATH_Matrix_ReadWord(matrix, 0x10));

	return ApplyMatrixLV_stub(input, output);
}
#else
// NOTE(aalhendi): Retail's matrix-loading entry has no branch or return; it
// falls through into ApplyMatrixLV_stub. The final EXE link must keep these
// two sections adjacent in this order.
__asm__(".section .Unknown_8006c6c8,\"ax\",@progbits\n"
        ".align 2\n"
        ".ent Unknown_8006c6c8\n"
        ".set\tnoreorder\n"
        ".globl Unknown_8006c6c8\n"
        "Unknown_8006c6c8:\n"
        "lw $t0,0($a2)\n"
        "lw $t1,4($a2)\n"
        "lw $t2,8($a2)\n"
        "lw $t3,12($a2)\n"
        "lw $t4,16($a2)\n"
        "ctc2 $t0,$0\n"
        "ctc2 $t1,$1\n"
        "ctc2 $t2,$2\n"
        "ctc2 $t3,$3\n"
        "ctc2 $t4,$4\n"
        ".end Unknown_8006c6c8\n"
        ".set\treorder\n"
        ".text\n");

__asm__(".section .ApplyMatrixLV_stub,\"ax\",@progbits\n"
        ".align 2\n"
        ".ent ApplyMatrixLV_stub\n"
        ".set\tnoreorder\n"
        ".globl ApplyMatrixLV_stub\n"
        "ApplyMatrixLV_stub:\n"
        "lw $t0,0($a0)\n"
        "lw $t1,4($a0)\n"
        "lw $t2,8($a0)\n"
        "sra $t3,$t0,15\n"
        "sra $t4,$t1,15\n"
        "sra $t5,$t2,15\n"
        "mtc2 $t3,$9\n"
        "mtc2 $t4,$10\n"
        "mtc2 $t5,$11\n"
        "andi $t0,$t0,0x7fff\n"
        "cop2 0x041e012\n"
        "andi $t1,$t1,0x7fff\n"
        "andi $t2,$t2,0x7fff\n"
        "mfc2 $t3,$25\n"
        "mfc2 $t4,$26\n"
        "mfc2 $t5,$27\n"
        "mtc2 $t0,$9\n"
        "mtc2 $t1,$10\n"
        "mtc2 $t2,$11\n"
        "sll $t3,$t3,3\n"
        "cop2 0x049e012\n"
        "sll $t4,$t4,3\n"
        "sll $t5,$t5,3\n"
        "mfc2 $t0,$25\n"
        "mfc2 $t1,$26\n"
        "mfc2 $t2,$27\n"
        "addu $t0,$t0,$t3\n"
        "addu $t1,$t1,$t4\n"
        "addu $t2,$t2,$t5\n"
        "sw $t0,0($a1)\n"
        "sw $t1,4($a1)\n"
        "sw $t2,8($a1)\n"
        "jr $ra\n"
        "addu $v0,$a1,$zero\n"
        ".end ApplyMatrixLV_stub\n"
        ".set\treorder\n"
        ".text\n");
#endif
