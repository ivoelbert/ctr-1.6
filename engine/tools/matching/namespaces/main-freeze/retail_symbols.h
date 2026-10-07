#ifndef CTR_MATCHING_MAIN_FREEZE_RETAIL_SYMBOLS_H
#define CTR_MATCHING_MAIN_FREEZE_RETAIL_SYMBOLS_H

// NOTE(aalhendi): The linker places this scalar at _gp+832 so GCC can emit
// and schedule the retail gp-relative tracker load before the call frame.
#define GAME_TRACKER              ctr_mainFreezeGameTracker
// NOTE(aalhendi): The menu stores and low-half frame-counter read use absolute
// pages in retail, not gp-relative offsets.
#define GAME_DESIRED_MENU         ctr_mainFreezeDesiredMenu
#define GAME_MAIN_MENU_STATE      ctr_mainFreezeMainMenuState
#define GAME_FRAME_COUNTER_LOW    ctr_mainFreezeFrameCounterLow

// NOTE(aalhendi): The resident EXE links the shared trig table inside data.
#define MAIN_FREEZE_TRIG_ASM_NAME "data+15360"
#define MAIN_FREEZE_LOAD_TRIG_BASE(page, base, offset)                                            \
	do                                                                                            \
	{                                                                                             \
		CTR_PSX_LOAD_SYMBOL_PAGE_AFTER((page), MAIN_FREEZE_TRIG_ASM_NAME, (offset));              \
		CTR_PSX_ADD_SYMBOL_LOW((base), (page), MAIN_FREEZE_TRIG_ASM_NAME, (u8 *)data.trigApprox); \
	} while (0)

#include <common.h>

#undef GHOST_REPLAY_HUMAN
#define GHOST_REPLAY_HUMAN ctr_mainFreezeReplayHuman
#undef GHOST_PLAYING
#define GHOST_PLAYING ctr_mainFreezeGhostPlaying

extern struct GameTracker *ctr_mainFreezeGameTracker;
extern struct RectMenu *ctr_mainFreezeDesiredMenu asm("sdata_static+2488");
extern MainMenuState ctr_mainFreezeMainMenuState asm("sdata_static+2576");
extern u16 ctr_mainFreezeFrameCounterLow asm("sdata_static+2564");
extern b16 ctr_mainFreezeReplayHuman asm("sdata_static+2540");
extern struct GhostHeader *ctr_mainFreezeGhostPlaying asm("sdata_static+2024");

#endif
