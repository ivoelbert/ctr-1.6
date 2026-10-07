#include <common.h>

#ifdef CTR_NATIVE
int MEMCARD_NewTask(int slotIdx, char *name, u8 *ptrMemcard, int memcardFileSize)
{
	sdata->memcardSlot = slotIdx;

	MEMCARD_StringSet(sdata->s_memcardFileCurr, slotIdx, name);

	sdata->memcard_ptrStart = ptrMemcard;
	sdata->memcard_remainingAttempts = 8;
	sdata->memcardFileSize = memcardFileSize;

	return 0;
}

void MEMCARD_CloseFile(void)
{
	int fd = sdata->memcard_fd;

	if (fd != -1)
	{
		close(fd);
		sdata->memcard_fd = -1;
	}

	sdata->memcard_stage = MC_STAGE_IDLE;
}

int MEMCARD_ReadFile(int start_offset, int size)
{
	if (lseek(sdata->memcard_fd, start_offset, 0) != -1 && read(sdata->memcard_fd, sdata->memcard_ptrStart, size) != -1)
	{
		// The read has started, the result will be found
		// the next time we wait for an event result
		return MC_RETURN_PENDING;
	}

	MEMCARD_CloseFile();
	return MC_RETURN_TIMEOUT;
}

u8 MEMCARD_WriteFile(int start_offset, const u8 *data, int size)
{
	if (lseek(sdata->memcard_fd, start_offset, 0) != -1 && write(sdata->memcard_fd, data, size) != -1)
	{
		// The write has started, the result will be found
		// the next time we wait for an event result
		return MC_RETURN_PENDING;
	}

	MEMCARD_CloseFile();
	return MC_RETURN_TIMEOUT;
}
#else
// NOTE(aalhendi): Retail constructs the filename's absolute address and
// interleaves card-state stores with register restores. GCC 2.8.1 instead
// forms a gp-relative pointer and groups the stores before its epilogue.
// maspsx recognizes tabbed .ent directives and preserves each delay slot.
__asm__(".section .MEMCARD_NewTask,\"ax\",@progbits\n"
        ".align 2\n"
        ".ent\tMEMCARD_NewTask\n"
        ".set\tnoreorder\n"
        ".globl MEMCARD_NewTask\n"
        "MEMCARD_NewTask:\n"
        "addiu $sp,$sp,-32\n"
        "move $v0,$a0\n"
        "move $v1,$a1\n"
        "sw $s0,16($sp)\n"
        "move $s0,$a2\n"
        "sw $s1,20($sp)\n"
        "move $s1,$a3\n"
        "lui $a0,0x800a\n"
        "addiu $a0,$a0,-28508\n"
        "move $a1,$v0\n"
        "sw $ra,24($sp)\n"
        "sw $v0,2380($gp)\n"
        "jal MEMCARD_StringSet\n"
        "move $a2,$v1\n"
        "lw $ra,24($sp)\n"
        "sw $s1,2364($gp)\n"
        "lw $s1,20($sp)\n"
        "sw $s0,1180($gp)\n"
        "lw $s0,16($sp)\n"
        "addiu $v0,$zero,8\n"
        "sw $v0,1188($gp)\n"
        "move $v0,$zero\n"
        "jr $ra\n"
        "addiu $sp,$sp,32\n"
        ".end MEMCARD_NewTask\n"
        ".set\treorder\n"
        ".text\n");

// NOTE(aalhendi): Retail loads the descriptor before allocating its frame
// and fills the conditional branch delay slot with the saved return address.
__asm__(".section .MEMCARD_CloseFile,\"ax\",@progbits\n"
        ".align 2\n"
        ".ent\tMEMCARD_CloseFile\n"
        ".set\tnoreorder\n"
        ".globl MEMCARD_CloseFile\n"
        "MEMCARD_CloseFile:\n"
        "lw $a0,1184($gp)\n"
        "addiu $sp,$sp,-24\n"
        "sw $s0,16($sp)\n"
        "addiu $s0,$zero,-1\n"
        "beq $a0,$s0,.LMemcardCloseDone\n"
        "sw $ra,20($sp)\n"
        "jal close\n"
        "nop\n"
        "sw $s0,1184($gp)\n"
        ".LMemcardCloseDone:\n"
        "lw $ra,20($sp)\n"
        "lw $s0,16($sp)\n"
        "sw $zero,1176($gp)\n"
        "jr $ra\n"
        "addiu $sp,$sp,24\n"
        ".end MEMCARD_CloseFile\n"
        ".set\treorder\n"
        ".text\n");

// NOTE(aalhendi): GCC 2.8.1 schedules the first lseek arguments after the
// saved registers. Retail puts the s0 save in the call's delay slot. The
// gp offsets below address memcard_fd and memcard_ptrStart respectively;
// native C above retains the same syscall result semantics.
__asm__(".section .MEMCARD_ReadFile,\"ax\",@progbits\n"
        ".align 2\n"
        ".ent\tMEMCARD_ReadFile\n"
        ".set\tnoreorder\n"
        ".globl MEMCARD_ReadFile\n"
        "MEMCARD_ReadFile:\n"
        "addiu $sp,$sp,-32\n"
        "move $v0,$a0\n"
        "sw $s1,20($sp)\n"
        "move $s1,$a1\n"
        "move $a1,$v0\n"
        "lw $a0,1184($gp)\n"
        "move $a2,$zero\n"
        "sw $ra,24($sp)\n"
        "jal lseek\n"
        "sw $s0,16($sp)\n"
        "addiu $s0,$zero,-1\n"
        "beq $v0,$s0,.LMemcardReadFailed\n"
        "nop\n"
        "lw $a0,1184($gp)\n"
        "lw $a1,1180($gp)\n"
        "jal read\n"
        "move $a2,$s1\n"
        "bne $v0,$s0,.LMemcardReadDone\n"
        "addiu $v0,$zero,7\n"
        ".LMemcardReadFailed:\n"
        "jal MEMCARD_CloseFile\n"
        "nop\n"
        "addiu $v0,$zero,1\n"
        ".LMemcardReadDone:\n"
        "lw $ra,24($sp)\n"
        "lw $s1,20($sp)\n"
        "lw $s0,16($sp)\n"
        "jr $ra\n"
        "addiu $sp,$sp,32\n"
        ".end MEMCARD_ReadFile\n"
        ".set\treorder\n"
        ".text\n");

__asm__(".section .MEMCARD_WriteFile,\"ax\",@progbits\n"
        ".align 2\n"
        ".ent\tMEMCARD_WriteFile\n"
        ".set\tnoreorder\n"
        ".globl MEMCARD_WriteFile\n"
        "MEMCARD_WriteFile:\n"
        "addiu $sp,$sp,-32\n"
        "move $v0,$a0\n"
        "sw $s1,20($sp)\n"
        "move $s1,$a1\n"
        "sw $s2,24($sp)\n"
        "move $s2,$a2\n"
        "move $a1,$v0\n"
        "lw $a0,1184($gp)\n"
        "move $a2,$zero\n"
        "sw $ra,28($sp)\n"
        "jal lseek\n"
        "sw $s0,16($sp)\n"
        "addiu $s0,$zero,-1\n"
        "beq $v0,$s0,.LMemcardWriteFailed\n"
        "move $a1,$s1\n"
        "lw $a0,1184($gp)\n"
        "jal write\n"
        "move $a2,$s2\n"
        "bne $v0,$s0,.LMemcardWriteDone\n"
        "addiu $v0,$zero,7\n"
        ".LMemcardWriteFailed:\n"
        "jal MEMCARD_CloseFile\n"
        "nop\n"
        "addiu $v0,$zero,1\n"
        ".LMemcardWriteDone:\n"
        "lw $ra,28($sp)\n"
        "lw $s2,24($sp)\n"
        "lw $s1,20($sp)\n"
        "lw $s0,16($sp)\n"
        "jr $ra\n"
        "addiu $sp,$sp,32\n"
        ".end MEMCARD_WriteFile\n"
        ".set\treorder\n"
        ".text\n");
#endif
