/*
 * Web (Emscripten) glue: what the page asks of the game.
 *
 * Module.ctrBoot = { level, mode, character } boots straight into a race:
 * mode 0 = Time Trial, 1 = Arcade (single race), 2 = VS (no AI).
 */
#if defined(__EMSCRIPTEN__)
#include <emscripten.h>

EM_JS(int, NativeWeb_BootValue, (int index, int fallback), {
	const boot = Module.ctrBoot;
	if (!boot) return fallback;
	const v = [boot.level, boot.mode, boot.character, boot.laps][index];
	return (v === undefined || v === null || Number.isNaN(Number(v))) ? fallback : (Number(v) | 0);
});

void NativeWeb_ApplyBootOverride(struct GameTracker *gGT)
{
	const int level = NativeWeb_BootValue(0, -1);
	if (level < 0)
	{
		return;
	}

	const int mode = NativeWeb_BootValue(1, 0);
	const int character = NativeWeb_BootValue(2, 0);
	const int laps = NativeWeb_BootValue(3, 3);

	gGT->levelID = level;
	gGT->numPlyrNextGame = 1;
	gGT->numPlyrCurrGame = 1;
	gGT->numLaps = (u8)laps;
	gGT->gameMode1 &= ~(BATTLE_MODE | ADVENTURE_MODE | TIME_TRIAL | ADVENTURE_ARENA | ARCADE_MODE | ADVENTURE_CUP);
	gGT->gameMode2 &= ~(CUP_ANY_KIND);
	if (mode == 0)
	{
		gGT->gameMode1 |= TIME_TRIAL;
	}
	else if (mode == 1)
	{
		gGT->gameMode1 |= ARCADE_MODE;
	}
	GAME_CHARACTER_IDS[0] = (s16)character;

	printf("[CTR Web] Boot override: level %d, mode %d, character %d, laps %d\n", level, mode, character, laps);
}
#endif
