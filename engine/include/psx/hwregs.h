#ifndef CTR_PSX_HWREGS_H
#define CTR_PSX_HWREGS_H

#include <macros.h>

// NOTE(aalhendi): Keep the register view usable by the pinned GCC 2.8.1,
// which has no stdint.h for the PSX target.
#define CTR_PSX_IO_BASE        0x1f800000u
#define CTR_PSX_MMIO8(offset)  (*(volatile u8 *)(CTR_PSX_IO_BASE + (offset)))
#define CTR_PSX_MMIO16(offset) (*(volatile u16 *)(CTR_PSX_IO_BASE + (offset)))

#define CD_REG(index)          CTR_PSX_MMIO8(0x1800u + (index))

#define SPU_MASTER_VOL_L       CTR_PSX_MMIO16(0x1d80u)
#define SPU_MASTER_VOL_R       CTR_PSX_MMIO16(0x1d82u)
#define SPU_CTRL               CTR_PSX_MMIO16(0x1daau)
#define SPU_CD_VOL_L           CTR_PSX_MMIO16(0x1db0u)
#define SPU_CD_VOL_R           CTR_PSX_MMIO16(0x1db2u)
#define SPU_CURRENT_VOL_L      CTR_PSX_MMIO16(0x1db8u)
#define SPU_CURRENT_VOL_R      CTR_PSX_MMIO16(0x1dbau)

#endif
