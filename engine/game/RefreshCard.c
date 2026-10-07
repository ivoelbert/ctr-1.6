#include <common.h>


s16 RefreshCard_CountGhostProfilesForLEV(s16 trackID)
{
	s16 i;
	s16 count = 0;
	s16 numGhosts;
	s16 levelID = trackID;
	struct MemcardState *card;
	struct MemcardState *loopCard;

	CTR_PSX_BIND_ABSOLUTE_PAGE_PTR(card, sdata->memcard, OFFSETOF_SDATA(memcard));
	numGhosts = card->numGhostProfilesSaved;
	i = 0;
	if (numGhosts > 0)
	{
		CTR_PSX_COPY_VALUE(loopCard, card);
		do
		{
			// NOTE(aalhendi): Offset-first addition preserves retail's MIPS
			// operand order while still addressing the shared ghost array.
			if (((struct GhostProfile *)((i * sizeof(struct GhostProfile)) + (u8 *)loopCard + offsetof(struct MemcardState, ghostProfile_memcard)))->trackID ==
			    levelID)
			{
				count++;
			}
			i++;
		} while (i < numGhosts);
	}

	return (s16)count;
}


void RefreshCard_Unknown1(void)
{
	s32 *status;
	CTR_PSX_BIND_ABSOLUTE_PAGE_PTR(status, sdata->memcard.memcardUnk1, OFFSETOF_SDATA(memcard.memcardUnk1));
	*status = (*status | 6) & ~8;
}


b32 RefreshCard_GetResult(int result)
{
	int originalResult;
	s16 result16 = result;
	struct MemcardState *card;
	b32 matches;

	// NOTE(aalhendi): Retail retains the untruncated result for its final
	// comparison, then sign-extends it only on that path.
	CTR_PSX_COPY_VALUE(originalResult, result);
	CTR_PSX_BIND_ABSOLUTE_PAGE_PTR(card, sdata->memcard, OFFSETOF_SDATA(memcard));

	if (result16 == 8)
	{
		if ((card->memcardUnk1 & 6) != 0)
		{
			return true;
		}
	}

	matches = false;
	if ((card->memcardUnk1 & 6) != 0)
	{
		goto done;
	}

	if (card->frame3_memcardAction != card->frame4_memcardAction)
	{
		goto done;
	}

	if (card->frame3_memcardSlot != card->frame4_memcardSlot)
	{
		goto done;
	}

	matches = card->desired_memcardResult == (s16)originalResult;

done:
	return matches;
}


u32 RefreshCard_GhostEncodeByte(int currByte)
{
	int originalByte;
	s16 byte = currByte;
	// NOTE(aalhendi): Retail tests the signed halfword but encodes the
	// original integer argument.
	CTR_PSX_COPY_VALUE(originalByte, currByte);

	if (byte < 10)
	{
		return (originalByte + '0') & 0xff;
	}

	if (byte < 0x24)
	{
		return (originalByte + 0x37) & 0xff;
	}

	if (byte < 0x3e)
	{
		return (originalByte + 0x3d) & 0xff;
	}

	if (byte == 0x3e)
	{
		return '-';
	}

	return '_';
}


void RefreshCard_NextMemcardAction(int slot, int action, char *fileName, char *fileIconHeader, struct GhostHeader *ptrGhostHeader, int fileSize)
{
	struct MemcardState *card;
	struct GhostHeader *ghostHeader;
	int size;
	u32 page;

	// NOTE(aalhendi): Both stack arguments are fetched between the rounded
	// page load and its low-half addition in the retail leaf function.
	CTR_PSX_LOAD_SYMBOL_PAGE(page, "0x8009aa30");
	CTR_PSX_LOAD_STACK_WORD_AFTER(ghostHeader, 16, ptrGhostHeader, page);
	CTR_PSX_LOAD_STACK_WORD_AFTER(size, 20, fileSize, ghostHeader);
	CTR_PSX_DEPEND_VALUE(page, ghostHeader);
	CTR_PSX_DEPEND_VALUE(page, size);
	CTR_PSX_ADD_SYMBOL_LOW(card, page, "0x8009aa30", &sdata->memcard);
	card->frame4_memcardAction = action;
	card->frame2_memcardAction = action;
	card->frame4_memcardSlot = slot;
	card->frame2_memcardSlot = slot;
	card->ghostProfile_fileName = fileName;
	card->ghostProfile_fileIconHeader = fileIconHeader;
	CTR_PSX_PAGE_LVALUE(s32, page, (s16)OFFSETOF_SDATA(memcard.memcardUnk1), card->memcardUnk1) &= ~8;
	card->ghostProfile_ptrGhostHeader = ghostHeader;
	card->ghostProfile_size3E00 = size;
}


static int RefreshCard_GhostProfileNameExists(char *profileName)
{
	int i;

	for (i = 0; i < sdata->memcard.numGhostProfilesSaved; i++)
	{
		if (strcmp(sdata->memcard.ghostProfile_memcard[i].profile_name, profileName) == 0)
		{
			return 1;
		}
	}

	return 0;
}

void RefreshCard_GhostEncodeProfile(u32 slotIndex, u16 characterID, u16 levelID, int time, char *name)
{
	char description[0x80];
	char scrambled[0x80] = {0};
	s32 characterID32 = (s16)characterID;
	u32 packed;
	int isUnique;
	struct GhostProfile *profile;

	do
	{
		isUnique = 1;

		if (time > 0x8c9ff)
		{
			time = 0x8c9ff;
		}

		packed = (u32)characterID32 | ((u32)((s32)(s16)levelID << 4)) | ((u32)time << 9) | (slotIndex << 0x1d);
		data.s_BASCUS_94426G_Question[13] = RefreshCard_GhostEncodeByte(packed & 0x3f);
		data.s_BASCUS_94426G_Question[14] = RefreshCard_GhostEncodeByte((packed >> 6) & 0x3f);
		data.s_BASCUS_94426G_Question[15] = RefreshCard_GhostEncodeByte((packed >> 0xc) & 0x3f);
		data.s_BASCUS_94426G_Question[16] = RefreshCard_GhostEncodeByte((packed >> 0x12) & 0x3f);
		data.s_BASCUS_94426G_Question[17] = RefreshCard_GhostEncodeByte((packed >> 0x18) & 0x3f);
		data.s_BASCUS_94426G_Question[18] = RefreshCard_GhostEncodeByte(packed >> 0x1e);
		data.s_BASCUS_94426G_Question[19] = '\0';

		if (RefreshCard_GhostProfileNameExists(data.s_BASCUS_94426G_Question) != 0)
		{
			isUnique = 0;
		}

		slotIndex = (slotIndex + 1) & 7;
	} while (isUnique == 0);

	description[0] = '\0';

	strcat(&description[strlen(description)], sdata->lngStrings[data.metaDataLEV[(s16)levelID].name_LNG]);
	strcat(description, sdata->strcatData1_colon);
	strcat(&description[strlen(description)], sdata->lngStrings[data.MetaDataCharacters[(s16)characterID].name_LNG_short]);
	strcat(description, sdata->strcatData1_colon);
	strcat(description, (char *)RECTMENU_DrawTime(time));

	CTR_ScrambleGhostString(scrambled, description);
	memcpy(sdata->memcardIcon_HeaderGHOST, scrambled, 0x3e);

	profile = &sdata->memcard.ghostProfile_current;
	memcpy(profile->profile_name, data.s_BASCUS_94426G_Question, sizeof(data.s_BASCUS_94426G_Question));
	profile->profile_name[sizeof(data.s_BASCUS_94426G_Question)] = data.s_BASCUS_94426G_Star[0];

	memcpy(profile->SubmitName_name, name, sizeof(profile->SubmitName_name));

	*(u8 *)&profile->alwaysOne = 1;
	profile->trackID = levelID;
	profile->characterID = characterID;
	CTR_WriteU16LE(&profile->memcardProfileIndex, (u16)slotIndex);
	profile->trackTime = time;
}


int RefreshCard_GhostDecodeByte(int value)
{
	// NOTE(aalhendi): Retail keeps the unmasked argument in a0 while testing
	// the byte-sized value in v1, then remasks a0 on each arithmetic path.
	// The complemented constants preserve its add-and-sign-extend sequence.
	register int rawValue CTR_PSX_REGISTER("$4") = value;
	u8 byte = value;

	if (byte == '-')
	{
		return 0x3e;
	}

	if (byte == '_')
	{
		return 0x3f;
	}

	if (byte < ':')
	{
		return ((u8)rawValue) - '0';
	}

	if (byte < '[')
	{
		return (s16)((u8)rawValue + 0xffc9);
	}

	return (s16)((u8)rawValue + 0xffc3);
}


void RefreshCard_GhostDecodeProfile(struct GhostProfile *profile, char *fileName)
{
	u32 packed;
	u32 timeMask;
	int decoded0;
	int decoded1;
	int decoded2;
	int decoded3;
	int decoded4;
	int decoded5;

	decoded0 = RefreshCard_GhostDecodeByte(fileName[13]);
	decoded1 = RefreshCard_GhostDecodeByte(fileName[14]);
	decoded2 = RefreshCard_GhostDecodeByte(fileName[15]);
	decoded3 = RefreshCard_GhostDecodeByte(fileName[16]);
	decoded4 = RefreshCard_GhostDecodeByte(fileName[17]);
	decoded5 = RefreshCard_GhostDecodeByte(fileName[18]);
	timeMask = 0xfffff;

	packed = (s16)decoded0;
	packed |= (s16)decoded1 << 6;
	packed |= (s16)decoded2 << 12;
	packed |= decoded3 << 18;
	packed |= decoded4 << 24;
	packed |= decoded5 << 30;

	profile->characterID = packed & 0xf;
	profile->trackID = (packed >> 4) & 0x1f;
	profile->trackTime = (packed >> 9) & timeMask;
	profile->memcardProfileIndex = (u32)packed >> 29;

	*(u8 *)&profile->alwaysOne = 0;
	memcpy(profile->profile_name, fileName, sizeof(profile->profile_name));
	*((u8 *)&profile->trackID + 1) = 0;
}


// NOTE(aalhendi): Keep the final stores before jr; GCC otherwise moves them
// into its delay slot and changes both retail function lengths.
void RefreshCard_StartMemcardAction(int action)
{
	sdata->mcStart = action;
	sdata->boolError = 0;
	sdata->unk8008d964 = 0;
	CTR_PSX_MEMORY_BARRIER();
}


void RefreshCard_StopMemcardAction(void)
{
	sdata->unk8008d964 = 1;
	sdata->mcStart = 2;
	CTR_PSX_MEMORY_BARRIER();
}


void RefreshCard_SetScreenText(int screenText)
{
	// NOTE(aalhendi): The explicit store keeps the retail nop after jal.
	CTR_PSX_STORE_HALF(sdata->mcScreenText, screenText);
	RefreshCard_Unknown1();
}


#ifdef CTR_NATIVE
void RefreshCard_Unknown2(void)
{
	if (sdata->boolAdvProfilesChecked == 0)
	{
		GAMEPROG_InitFullMemcard((struct MemcardProfile *)sdata->ptrToMemcardBuffer2);
		sdata->boolAdvProfilesChecked = 1;
	}

	sdata->unk8008d95c = 1;
	sdata->unk_memcardRelated_8008d928 = 0;
}
#else
// NOTE(aalhendi): Retail checks the halfword before the stack prologue and
// saves ra in the branch delay slot. GCC 2.8.1 does not emit that order here;
// ASPSX supplies the nop after jal, so there is no source nop at that point.
__asm__(".section .RefreshCard_Unknown2,\"ax\",@progbits\n"
        ".align 2\n"
        ".ent RefreshCard_Unknown2\n"
        ".set noreorder\n"
        ".globl RefreshCard_Unknown2\n"
        "RefreshCard_Unknown2:\n"
        "lh $2,2556($28)\n"
        "addiu $29,$29,-24\n"
        "bnez $2,.LRefreshCard_Unknown2_resetFlags\n"
        "sw $31,16($29)\n"
        "lw $4,1288($28)\n"
        "jal GAMEPROG_InitFullMemcard\n"
        "li $2,1\n"
        "sh $2,2556($28)\n"
        ".LRefreshCard_Unknown2_resetFlags:\n"
        "lw $31,16($29)\n"
        "li $2,1\n"
        "sh $2,2544($28)\n"
        "sh $0,2492($28)\n"
        "jr $31\n"
        "addiu $29,$29,24\n"
        ".end RefreshCard_Unknown2\n"
        ".set reorder\n"
        ".text\n");
#endif


void RefreshCard_GetNumGhostsTotal(void)
{
	CTR_PSX_STORE_ABSOLUTE_HALF(sdata->memcard.numGhostProfilesSaved, OFFSETOF_SDATA(memcard.numGhostProfilesSaved), 0);
}


#ifdef CTR_NATIVE
void RefreshCard_GameProgressAndOptions(void)
{
	struct MemcardProfile *memcard;

	sdata->unk8008d95c = 1;
	sdata->unk_memcardRelated_8008d928 = 1;
	sdata->advProfileIndex = -1;

	GAMEPROG_SyncGameAndCard(&((struct MemcardProfile *)sdata->ptrToMemcardBuffer2)->gameSave.progress, &GAME_SAVE.progress);
	memcard = (struct MemcardProfile *)sdata->ptrToMemcardBuffer2;
	memcpy(&GAME_SAVE, &memcard->gameSave, sizeof(struct GameSave));
	RaceConfig_LoadGameOptions();
}
#else
// NOTE(aalhendi): GCC 2.8.1 saves s0/ra before the first two card-state
// stores; retail interleaves those saves with argument setup. The native
// implementation above retains the same buffer and 16-bit index semantics.
__asm__(".section .RefreshCard_GameProgressAndOptions,\"ax\",@progbits\n"
        ".align 2\n"
        ".ent RefreshCard_GameProgressAndOptions\n"
        ".set\tnoreorder\n"
        ".globl RefreshCard_GameProgressAndOptions\n"
        "RefreshCard_GameProgressAndOptions:\n"
        "addiu $sp,$sp,-24\n"
        "li $v0,1\n"
        "sh $v0,2544($gp)\n"
        "sh $v0,2492($gp)\n"
        "li $v0,-1\n"
        "sw $s0,16($sp)\n"
        "lui $s0,%hi(sdata_static+6012)\n"
        "addiu $s0,$s0,%lo(sdata_static+6012)\n"
        "lw $a0,1288($gp)\n"
        "move $a1,$s0\n"
        "sw $ra,20($sp)\n"
        "sh $v0,2560($gp)\n"
        "jal GAMEPROG_SyncGameAndCard\n"
        "addiu $a0,$a0,324\n"
        "lw $v0,1288($gp)\n"
        "nop\n"
        "addiu $v1,$v0,324\n"
        "addiu $v0,$v0,5620\n"
        ".LRefreshCard_GameProgress_copy:\n"
        "lw $a2,0($v1)\n"
        "lw $a3,4($v1)\n"
        "lw $t0,8($v1)\n"
        "lw $t1,12($v1)\n"
        "sw $a2,0($s0)\n"
        "sw $a3,4($s0)\n"
        "sw $t0,8($s0)\n"
        "sw $t1,12($s0)\n"
        "addiu $v1,$v1,16\n"
        "bne $v1,$v0,.LRefreshCard_GameProgress_copy\n"
        "addiu $s0,$s0,16\n"
        "lw $a2,0($v1)\n"
        "lw $a3,4($v1)\n"
        "lw $t0,8($v1)\n"
        "sw $a2,0($s0)\n"
        "sw $a3,4($s0)\n"
        "jal RaceConfig_LoadGameOptions\n"
        "sw $t0,8($s0)\n"
        "lw $ra,20($sp)\n"
        "lw $s0,16($sp)\n"
        "jr $ra\n"
        "addiu $sp,$sp,24\n"
        ".end RefreshCard_GameProgressAndOptions\n"
        ".set\treorder\n"
        ".text\n");
#endif


static void RefreshCard_QueueGetInfo(void)
{
	RefreshCard_NextMemcardAction(0, MC_ACTION_GetInfo, data.s_BASCUS_94426_SLOTS, NULL, NULL, 0);
}

static void RefreshCard_QueueMainLoad(void)
{
	RefreshCard_NextMemcardAction(0, MC_ACTION_Load, data.s_BASCUS_94426_SLOTS, NULL, (struct GhostHeader *)sdata->ptrToMemcardBuffer1, 0x1680);
}

static void RefreshCard_QueueMainSave(void)
{
	RefreshCard_NextMemcardAction(0, MC_ACTION_Save, data.s_BASCUS_94426_SLOTS, (char *)data.memcardIcon_HeaderSLOTS,
	                              (struct GhostHeader *)sdata->ptrToMemcardBuffer1, 0x1680);
}

static void RefreshCard_QueueGhostSave(void)
{
	RefreshCard_NextMemcardAction(0, MC_ACTION_Save, data.s_BASCUS_94426G_Question, sdata->memcardIcon_HeaderGHOST, sdata->GhostRecording.ptrGhost, 0x3e00);
}

static void RefreshCard_QueueGhostLoad(void)
{
	RefreshCard_NextMemcardAction(0, MC_ACTION_Load, sdata->memcard.ghostProfile_memcard[sdata->memcard.ghostProfile_indexLoad].profile_name, NULL,
	                              sdata->ptrGhostTapePlaying, 0x3e00);
}

static void RefreshCard_SetScreenAndPoll(int screenText)
{
	RefreshCard_SetScreenText(screenText);
	RefreshCard_QueueGetInfo();
	sdata->boolError = 1;
}

void RefreshCard_Unknown3(void)
{
	b32 keepPolling = false;

	switch (sdata->mcScreenText)
	{
	case MC_SCREEN_WARNING_NOCARD:
		keepPolling = true;
		sdata->mcStart = 2;
		sdata->boolError = 1;
		break;

	case MC_SCREEN_WARNING_UNFORMATTED:
		if (sdata->mcStart != 7)
		{
			sdata->mcStart = 2;
			keepPolling = true;
			sdata->boolError = 1;
			break;
		}

		sdata->mcStart = 2;
		RefreshCard_SetScreenText(MC_SCREEN_FORMATTING);
		RefreshCard_NextMemcardAction(0, MC_ACTION_Format, data.s_BASCUS_94426_SLOTS, NULL, NULL, 0);
		sdata->boolError = 0;
		break;

	case MC_SCREEN_CHECKING:
	case MC_SCREEN_ERROR_FULL:
		keepPolling = true;
		break;

	case MC_SCREEN_ERROR_TIMEOUT:
	case MC_SCREEN_NULL:
	case MC_SCREEN_ERROR_NODATA:
		if (sdata->mcStart == 5)
		{
			RefreshCard_SetScreenText(MC_SCREEN_LOADING);
			RefreshCard_QueueGhostLoad();
		}
		else if (sdata->mcStart == 3)
		{
			sdata->mcStart = 2;
			RefreshCard_SetScreenText(MC_SCREEN_SAVING);
			RefreshCard_QueueMainSave();
			sdata->boolError = 0;
			break;
		}
		else if (sdata->mcStart == 6)
		{
			if (sdata->memcard.ghostProfile_rowSelect >= 0)
			{
				int remaining;

				memcpy(sdata->ghostFileNameFinal, sdata->memcard.ghostProfile_memcard[sdata->memcard.ghostProfile_rowSelect].profile_name,
				       sizeof(sdata->memcard.ghostProfile_memcard[0].profile_name));
				RefreshCard_SetScreenText(MC_SCREEN_SAVING);
				RefreshCard_NextMemcardAction(0, MC_ACTION_Erase, sdata->ghostFileNameFinal, NULL, NULL, 0);
				sdata->boolError = 0;

				remaining = (sdata->memcard.numGhostProfilesSaved - 1) - sdata->memcard.ghostProfile_rowSelect;
				if (remaining != 0)
				{
					memmove(&sdata->memcard.ghostProfile_memcard[sdata->memcard.ghostProfile_rowSelect],
					        &sdata->memcard.ghostProfile_memcard[sdata->memcard.ghostProfile_rowSelect + 1], remaining * sizeof(struct GhostProfile));
				}
				sdata->memcard.numGhostProfilesSaved--;
				break;
			}

			RefreshCard_SetScreenText(MC_SCREEN_SAVING);
			RefreshCard_QueueGhostSave();
			sdata->boolError = 0;
			break;
		}

		keepPolling = true;
		sdata->boolError = 1;
		break;
	}

	if (RefreshCard_GetResult(MC_RESULT_NEWCARD))
	{
		RefreshCard_Unknown2();
		RefreshCard_GetNumGhostsTotal();
		goto done;
	}

	if (RefreshCard_GetResult(MC_RESULT_ERROR_NOCARD))
	{
		RefreshCard_Unknown2();
		RefreshCard_GetNumGhostsTotal();
		RefreshCard_SetScreenAndPoll(MC_SCREEN_WARNING_NOCARD);
		keepPolling = false;
		goto done;
	}

	if (RefreshCard_GetResult(MC_RESULT_FULL))
	{
		RefreshCard_SetScreenAndPoll(MC_SCREEN_ERROR_FULL);
		keepPolling = false;
		goto done;
	}

	if (RefreshCard_GetResult(MC_RESULT_ERROR_TIMEOUT))
	{
		RefreshCard_Unknown2();
		RefreshCard_SetScreenAndPoll(MC_SCREEN_ERROR_TIMEOUT);
		keepPolling = false;
		goto done;
	}

	if (RefreshCard_GetResult(MC_RESULT_ERROR_NODATA))
	{
		sdata->boolMemcardDataValid = 0;
		RefreshCard_Unknown2();
		sdata->boolError = 1;

		if ((sdata->memcardAction >= 0) && (sdata->memcardAction < 3))
		{
			RefreshCard_SetScreenText((sdata->memcardAction == 0) ? MC_SCREEN_ERROR_NODATA : MC_SCREEN_NULL);
			RefreshCard_QueueGetInfo();
			keepPolling = false;
		}
		goto done;
	}

	if (RefreshCard_GetResult(MC_RESULT_READY_LOAD))
	{
		RefreshCard_Unknown2();
		sdata->unk8008d95c = 0;
		sdata->boolAdvProfilesChecked = 0;
		RefreshCard_SetScreenText(MC_SCREEN_LOADING);
		RefreshCard_QueueMainLoad();
		sdata->boolError = 0;
		keepPolling = false;
		goto done;
	}

	if (RefreshCard_GetResult(MC_RESULT_ERROR_UNFORMATTED))
	{
		RefreshCard_GetNumGhostsTotal();
		RefreshCard_Unknown2();
		RefreshCard_SetScreenAndPoll(MC_SCREEN_WARNING_UNFORMATTED);
		keepPolling = false;
		goto done;
	}

	if (!RefreshCard_GetResult(MC_RESULT_READY_SAVE))
	{
		goto done;
	}

	sdata->boolError = 1;

	if (sdata->mcScreenText == MC_SCREEN_SAVING)
	{
		if (sdata->mcStart == 6)
		{
			if (sdata->memcard.ghostProfile_rowSelect >= 0)
			{
				sdata->memcard.ghostProfile_rowSelect = -1;
				RefreshCard_SetScreenText(MC_SCREEN_SAVING);
				RefreshCard_QueueGhostSave();
				sdata->boolError = 0;
				keepPolling = false;
				goto done;
			}

			{
				int remaining = (sdata->memcard.numGhostProfilesSaved - 1) - sdata->memcard.ghostProfile_indexSave;

				if (remaining != 0)
				{
					memmove(&sdata->memcard.ghostProfile_memcard[sdata->memcard.ghostProfile_indexSave + 1],
					        &sdata->memcard.ghostProfile_memcard[sdata->memcard.ghostProfile_indexSave], remaining * sizeof(struct GhostProfile));
				}

				sdata->memcard.numGhostProfilesSaved++;
				sdata->memcard.ghostProfile_memcard[sdata->memcard.ghostProfile_indexSave] = sdata->memcard.ghostProfile_current;
			}
		}

		sdata->unk8008d964 = 1;
		sdata->mcStart = 2;
		RefreshCard_SetScreenText(MC_SCREEN_NULL);
		RefreshCard_QueueGetInfo();
		keepPolling = false;
		goto done;
	}

	if (sdata->mcScreenText < MC_SCREEN_LOADING)
	{
		if (sdata->mcScreenText == MC_SCREEN_FORMATTING)
		{
			RefreshCard_GetNumGhostsTotal();
			RefreshCard_Unknown2();
			sdata->unk_memcardRelated_8008d928 = 1;

			if (sdata->memcardAction >= 0)
			{
				if (sdata->memcardAction < 2)
				{
					GAMEPROG_InitFullMemcard(sdata->ptrToMemcardBuffer2);
					RefreshCard_SetScreenText(MC_SCREEN_NULL);
					RefreshCard_QueueGetInfo();
					keepPolling = false;
				}
				else if (sdata->memcardAction == 2)
				{
					sdata->boolError = 1;
				}
			}
		}
		goto done;
	}

	if (sdata->mcScreenText != MC_SCREEN_LOADING)
	{
		if (sdata->mcScreenText == MC_SCREEN_CHECKING)
		{
			RefreshCard_GetNumGhostsTotal();
			RefreshCard_Unknown2();
			sdata->unk8008d95c = 0;
			sdata->boolAdvProfilesChecked = 0;
			RefreshCard_SetScreenText(MC_SCREEN_LOADING);
			RefreshCard_QueueMainLoad();
			sdata->boolError = 0;
			keepPolling = false;
		}
		goto done;
	}

	if (sdata->mcStart == 5)
	{
		sdata->boolReplayHumanGhost = 1;
		sdata->unk8008d964 = 1;
		RefreshCard_SetScreenText(MC_SCREEN_NULL);
	}
	else if (CTR_ReadU32LE(sdata->ptrToMemcardBuffer2) == 0x1600ffee)
	{
		sdata->boolMemcardDataValid = 0;
		RefreshCard_GameProgressAndOptions();
		RefreshCard_SetScreenText(MC_SCREEN_NULL);
	}
	else
	{
		sdata->boolMemcardDataValid = 1;
		RefreshCard_Unknown2();
		RefreshCard_SetScreenText(MC_SCREEN_ERROR_NODATA);
	}

	sdata->mcStart = 2;
	RefreshCard_QueueGetInfo();
	keepPolling = false;

done:
	if (keepPolling && !RefreshCard_GetResult(MC_RESULT_PENDING))
	{
		RefreshCard_QueueGetInfo();
	}
}


void RefreshCard_Unknown4(void)
{
	int result = -1;
	register int desiredResult CTR_PSX_REGISTER("$2");
	register struct MemcardState *card CTR_PSX_REGISTER("$16") = &GAME_MEMCARD_STATE;
	register s32 memcardFlags CTR_PSX_REGISTER("$4");
	register s32 nextFlags CTR_PSX_REGISTER("$6");
	register u32 action CTR_PSX_REGISTER("$8");
	register u16 slot CTR_PSX_REGISTER("$3");

	memcardFlags = card->memcardUnk1;
	if ((memcardFlags & 1) != 0)
	{
		register s32 scratch CTR_PSX_REGISTER("$2");
		register s32 actionIndex CTR_PSX_REGISTER("$2");
		scratch = ~1;
		nextFlags = memcardFlags & scratch;
		action = (u16)card->frame1_memcardAction;
		CTR_PSX_LOAD_UNSIGNED_HALF_AFTER(slot, card, 8, card->frame1_memcardSlot, action);
		scratch = memcardFlags & 2;
		card->memcardUnk1 = nextFlags;
		CTR_PSX_STORE_HALF(card->frame3_memcardAction, action);
		card->frame3_memcardSlot = slot;

		if (scratch == 0)
		{
			scratch = nextFlags & ~4;
			card->memcardUnk1 = scratch;
		}

		actionIndex = action - MC_ACTION_GetInfo;
		switch ((s16)actionIndex)
		{
		case MC_ACTION_GetInfo - MC_ACTION_GetInfo:
			result = MEMCARD_GetInfo(card->frame1_memcardSlot);
			break;
		case MC_ACTION_Save - MC_ACTION_GetInfo:
		{
			char *saveName = card->ghostProfile_fileName;
			char *saveIcon = card->ghostProfile_fileIconHeader;
			u8 *saveData = (u8 *)card->ghostProfile_ptrGhostHeader;
#if defined(CTR_NATIVE)
			result = MEMCARD_Save(card->frame1_memcardSlot, saveName, saveIcon, saveData, card->ghostProfile_size3E00, 0);
#else
			__asm__ volatile("sw $0,20($sp)" : : : "memory");
			result = RefreshCard_SaveWithPreloadedFlags(card->frame1_memcardSlot, saveName, saveIcon, saveData, card->ghostProfile_size3E00);
#endif
		}
		break;
		case MC_ACTION_Load - MC_ACTION_GetInfo:
#if defined(CTR_NATIVE)
			result =
			    MEMCARD_Load(card->frame1_memcardSlot, card->ghostProfile_fileName, (u8 *)card->ghostProfile_ptrGhostHeader, card->ghostProfile_size3E00, 0);
#else
		{
			char *loadName = card->ghostProfile_fileName;
			u8 *loadData = (u8 *)card->ghostProfile_ptrGhostHeader;
			__asm__ volatile("sw $0,16($sp)" : : : "memory");
			result = RefreshCard_LoadWithPreloadedFlags(card->frame1_memcardSlot, loadName, loadData, card->ghostProfile_size3E00);
		}
#endif
			break;
		case MC_ACTION_Format - MC_ACTION_GetInfo:
			result = MEMCARD_Format(card->frame1_memcardSlot);
			break;
		case MC_ACTION_Erase - MC_ACTION_GetInfo:
			result = MEMCARD_EraseFile(card->frame1_memcardSlot, card->ghostProfile_fileName);
			break;
		}
	}
	else if (card->frame1_memcardAction != 0)
	{
		result = MEMCARD_HandleEvent();
		card->frame3_memcardAction = card->frame1_memcardAction;
		card->frame3_memcardSlot = card->frame1_memcardSlot;
	}

	if ((card->frame1_memcardAction == MC_ACTION_GetInfo) && ((s16)result == MC_RETURN_NEWCARD))
	{
		char *fileName;
		s16 totalGhosts = 0;

		card->numGhostProfilesSaved = 0;
		fileName = MEMCARD_FindFirstGhost(card->frame1_memcardSlot, data.s_BASCUS_94426G_Star);

		while (fileName != NULL)
		{
			if (totalGhosts < 7)
			{
				RefreshCard_GhostDecodeProfile(&card->ghostProfile_memcard[totalGhosts], fileName);
				card->numGhostProfilesSaved++;
			}

			totalGhosts++;
			fileName = MEMCARD_FindNextGhost();
		}

		MEMCARD_IsFile(card->frame1_memcardSlot, card->ghostProfile_fileName);
		card->memcardUnk1 |= 8;
		result = MEMCARD_IsFile(card->frame1_memcardSlot, card->ghostProfile_fileName);
	}

	switch ((s16)result)
	{
	case MC_RETURN_IOE:
		if (card->frame1_memcardAction == MC_ACTION_GetInfo)
		{
			register s32 ioFlags CTR_PSX_REGISTER("$2");
			desiredResult = MC_RESULT_READY_LOAD;
			CTR_PSX_LOAD_WORD(ioFlags, card->memcardUnk1);
#if defined(CTR_NATIVE)
			ioFlags &= 8;
#else
			// NOTE(aalhendi): Keep the mask in v0; GCC otherwise tests v1 and
			// cannot fill the branch delay slot with the ready-load result.
			__asm__("andi %0,%0,8" : "+r"(ioFlags));
#endif
			if (ioFlags == 0)
			{
				desiredResult = MC_RESULT_READY_SAVE;
			}
			else
			{
				desiredResult = MC_RESULT_READY_LOAD;
			}
		}
		else
		{
			desiredResult = MC_RESULT_READY_SAVE;
		}
		goto set_result;
	case MC_RETURN_TIMEOUT:
		desiredResult = MC_RESULT_ERROR_TIMEOUT;
		goto set_result;
	case MC_RETURN_NOCARD:
		card->desired_memcardResult = MC_RESULT_ERROR_NOCARD;
		card->frame1_memcardAction = 0;
		goto try_next_action;
	case MC_RETURN_NEWCARD:
	{
		register s32 actionValue CTR_PSX_REGISTER("$3") = card->frame1_memcardAction;
		register s32 formatAction CTR_PSX_REGISTER("$2");
		CTR_PSX_LOAD_IMMEDIATE(formatAction, MC_ACTION_Format);
		if (actionValue == formatAction)
		{
			// NOTE(aalhendi): Keep this arm separate from the IO-error
			// result store; merging them changes retail's branch layout.
			CTR_PSX_MEMORY_BARRIER();
			desiredResult = MC_RESULT_READY_SAVE;
		}
		else
		{
			desiredResult = MC_RESULT_NEWCARD;
		}
	}
		goto set_result;
	case MC_RETURN_FULL:
		desiredResult = MC_RESULT_FULL;
		goto set_result;
	case MC_RETURN_UNFORMATTED:
		desiredResult = MC_RESULT_ERROR_UNFORMATTED;
		goto set_result;
	case MC_RETURN_NODATA:
		desiredResult = MC_RESULT_ERROR_NODATA;
		goto set_result;
	set_result:
		card->desired_memcardResult = desiredResult;
		card->frame1_memcardAction = 0;
		goto try_next_action;
	case MC_RETURN_PENDING:
		card->desired_memcardResult = MC_RESULT_PENDING;
		goto try_next_action;
	default:
		goto try_next_action;
	}

try_next_action:
	if ((card->frame1_memcardAction == 0) && (card->frame2_memcardAction != 0))
	{
		card->frame1_memcardAction = card->frame2_memcardAction;
		card->frame2_memcardAction = 0;
		card->frame1_memcardSlot = card->frame2_memcardSlot;
		card->memcardUnk1 = (card->memcardUnk1 | 1) & ~2;
	}
}


void RefreshCard_Entry(void)
{
	// NOTE(aalhendi): Direct storage makes retail load the tracker before opening its stack frame.
	if ((sdata_static.gGT->gameMode1 & DEBUG_MENU) == 0)
	{
		RefreshCard_Unknown4();
		RefreshCard_Unknown3();
	}
}
