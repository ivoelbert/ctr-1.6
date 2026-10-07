/*
 * Web (Emscripten) glue: what the page asks of the game.
 *
 * Module.ctrBoot = { level, mode, character, laps, players } boots straight into a race:
 * mode 0 = Time Trial, 1 = Arcade (single race), 2 = VS (no AI); players 1-4 split the
 * screen (Arcade takes 1 or 2, VS 2 to 4).
 */
#if defined(__EMSCRIPTEN__)
#include <emscripten.h>

EM_JS(int, NativeWeb_BootValue, (int index, int fallback), {
	const boot = Module.ctrBoot;
	if (!boot) return fallback;
	const v = [boot.level, boot.mode, boot.character, boot.laps, boot.players][index];
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
	int players = NativeWeb_BootValue(4, mode == 2 ? 2 : 1);
	if (players < 1)
	{
		players = 1;
	}
	if (players > ((mode == 0) ? 1 : (mode == 1) ? 2 : 4))
	{
		players = (mode == 0) ? 1 : (mode == 1) ? 2 : 4;
	}

	gGT->levelID = level;
	gGT->numPlyrNextGame = (u8)players;
	gGT->numPlyrCurrGame = (u8)players;
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
	for (int i = 1; i < players; i++)
	{
		// the other players: the next racers along, skipping player 1's
		GAME_CHARACTER_IDS[i] = (s16)((character + i) % 8);
	}

	printf("[CTR Web] Boot override: level %d, mode %d, character %d, laps %d, players %d\n", level, mode, character, laps, players);
}
#endif

#if defined(__EMSCRIPTEN__)
extern int g_nativeWebHeldButtons;

// Test hooks for the page (window.ctr in web/index.html).

EMSCRIPTEN_KEEPALIVE void NativeWeb_SetButtons(int mask)
{
	g_nativeWebHeldButtons = mask & 0xffff;
}

internal int NativeWeb_QuadIndex(const struct QuadBlock *quad)
{
	struct GameTracker *gGT = sdata->gGT;
	if ((quad == NULL) || (gGT->level1 == NULL) || (gGT->level1->ptr_mesh_info == NULL))
	{
		return -1;
	}
	return (int)(quad - gGT->level1->ptr_mesh_info->ptrQuadBlockArray);
}

// Fills out[0..39]; returns the number of values written.
EMSCRIPTEN_KEEPALIVE int NativeWeb_GetState(int *out)
{
	struct GameTracker *gGT = sdata->gGT;
	struct Driver *d = gGT->drivers[0];

	memset(out, 0, 40 * sizeof(int));
	out[0] = gGT->levelID;
	out[1] = (int)gGT->gameMode1;
	out[2] = gGT->numPlyrCurrGame;
	out[3] = sdata->Loading.stage;
	out[21] = Platform_GetVBlankCount();
	out[20] = gGT->elapsedEventTime;
	{
		// primitive memory: the most the two frame buffers used this frame
		struct PrimMem *a = &gGT->db[0].primMem;
		struct PrimMem *b = &gGT->db[1].primMem;
		int usedA = (int)((u32)a->cursor - (u32)a->start);
		int usedB = (int)((u32)b->cursor - (u32)b->start);
		out[27] = usedA > usedB ? usedA : usedB;
		out[28] = (int)a->capacityBytes;
	}
	if ((d == NULL) || ((gGT->gameMode1 & LOADING) != 0) || (gGT->level1 == NULL))
	{
		return 40;
	}

	out[4] = 1;
	out[5] = d->posCurr.x;
	out[6] = d->posCurr.y;
	out[7] = d->posCurr.z;
	out[8] = d->rotCurr.x;
	out[9] = d->rotCurr.y;
	out[10] = d->rotCurr.z;
	out[11] = d->speed;
	out[12] = d->speedApprox;
	out[13] = d->kartState;
	out[14] = d->lapIndex;
	out[15] = NativeWeb_QuadIndex(d->underDriver);
	out[16] = NativeWeb_QuadIndex(d->currBlockTouching);
	out[17] = NativeWeb_QuadIndex(d->lastValid);
	out[18] = (int)d->actionsFlagSet;
	out[19] = (int)d->distanceToFinish_curr;
	out[22] = (d->underDriver != NULL) ? d->underDriver->terrain_type : -1;
	out[23] = d->angle;
	out[24] = d->jumpHeightCurr;
	out[25] = d->reserves;
	out[26] = (d->underDriver != NULL) ? d->underDriver->checkpointIndex : -1;
	out[29] = (int)d->heldItemID;
	out[30] = d->numWumpas;
	out[31] = d->driverRank;
	// player 1's camera
	out[32] = gGT->pushBuffer[0].pos.x;
	out[33] = gGT->pushBuffer[0].pos.y;
	out[34] = gGT->pushBuffer[0].pos.z;
	out[35] = NativeWeb_QuadIndex(gGT->cameraDC[0].ptrQuadBlock);
	return 40;
}

// Prints the level's instances: what each InstDef became and how it's flagged.
EMSCRIPTEN_KEEPALIVE void NativeWeb_DumpInstances(void)
{
	struct GameTracker *gGT = sdata->gGT;
	struct Level *lev = gGT->level1;
	if (lev == NULL)
	{
		return;
	}
	printf("[CTR Web] %d instances, %d players, LOD mask %d\n", lev->numInstances, gGT->numPlyrCurrGame,
	       sdata->LOD[gGT->numPlyrCurrGame - 1]);
	for (int i = 0; i < lev->numInstances; i++)
	{
		struct InstDef *def = &lev->ptrInstDefs[i];
		struct Instance *inst = def->ptrInstance;
		if (inst == NULL)
		{
			printf("[CTR Web]  %2d %-16.16s no instance\n", i, def->name);
			continue;
		}
		struct Model *m = inst->model;
		printf("[CTR Web]  %2d %-16.16s flags %08x thread %p headers %d lod0 %d pos %d %d %d\n", i, def->name, inst->flags,
		       (void *)inst->thread, m ? m->numHeaders : -1, (m && m->numHeaders > 0) ? m->headers[0].maxDistanceLOD : -1,
		       inst->matrix.t[0], inst->matrix.t[1], inst->matrix.t[2]);
	}
}

// Puts player 1's kart at (x, y, z) in level units, heading `angle` (4096 = full turn).
EMSCRIPTEN_KEEPALIVE void NativeWeb_Teleport(int x, int y, int z, int angle)
{
	struct GameTracker *gGT = sdata->gGT;
	struct Driver *d = gGT->drivers[0];
	if (d == NULL)
	{
		return;
	}

	d->posCurr.x = x << 8;
	d->posCurr.y = y << 8;
	d->posCurr.z = z << 8;
	d->posPrev = d->posCurr;
	d->rotCurr.y = (s16)angle;
	d->angle = (s16)angle;
	d->speed = 0;
	d->speedApprox = 0;
}
#endif

#if defined(__EMSCRIPTEN__)
// Module.ctrRename = { levelID: "NAME" }: the names shown for levels (HUD, menus), set once
// the language file is loaded. The game's font has capitals, digits and some punctuation.
EM_JS(int, NativeWeb_RenameCount, (void), {
	return Module.ctrRename ? Object.keys(Module.ctrRename).length : 0;
});
EM_JS(int, NativeWeb_RenameLevel, (int i), {
	return Number(Object.keys(Module.ctrRename)[i]) | 0;
});
EM_JS(int, NativeWeb_RenameText, (int i, char *buf, int cap), {
	const text = String(Object.values(Module.ctrRename)[i]).toUpperCase();
	stringToUTF8(text, buf, cap);
	return text.length;
});

void NativeWeb_ApplyRenames(void)
{
	static char names[8][32];
	int count = NativeWeb_RenameCount();

	for (int i = 0; (i < count) && (i < 8); i++)
	{
		int level = NativeWeb_RenameLevel(i);
		if ((level < 0) || (level >= SCRAPBOOK))
		{
			continue;
		}
		NativeWeb_RenameText(i, names[i], sizeof(names[i]));
		sdata->lngStrings[data.metaDataLEV[level].name_LNG] = names[i];
		printf("[CTR Web] Level %d is called %s\n", level, names[i]);
	}
}
#endif
