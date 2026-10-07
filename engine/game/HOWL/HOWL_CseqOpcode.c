#include <common.h>

void cseq_opcode01_noteoff(struct SongSeq *seq)
{
	struct ChannelStats *curr, *backupNext;
	u8 *currNote = seq->currNote;

	for (curr = (struct ChannelStats *)GAME_CHANNEL_TAKEN.first; curr != NULL; curr = backupNext)
	{
		backupNext = curr->link.links.next;

		if (curr->type != HOWL_CHANNEL_TYPE_MUSIC)
		{
			continue;
		}

		// only update this sequence's channels
		if (curr->soundID != seq->soundID)
		{
			continue;
		}

		// need a struct for Note offset 0x1
		if (curr->drumIndex_pitchIndex != currNote[1])
		{
			continue;
		}

		// enable OFF flag, disable ON flag
		GAME_CHANNEL_UPDATE_FLAGS[curr->channelID] |= HOWL_CHANNEL_UPDATE_OFF;
		// NOTE(aalhendi): Retail rereads the word for the second flag update.
		*(volatile u32 *)&GAME_CHANNEL_UPDATE_FLAGS[curr->channelID] &= ~HOWL_CHANNEL_UPDATE_KEY_ON;

		curr->flags &= (u8)~1;

		// recycle: remove from taken, put on free
		LIST_RemoveMember(&GAME_CHANNEL_TAKEN, (struct Item *)curr);
		LIST_AddBack(&GAME_CHANNEL_FREE, (struct Item *)curr);
	}
}

void cseq_opcode02_empty(struct SongSeq *seq)
{
	(void)seq;
	// left empty by ND
}

// "end of song" opcode
void cseq_opcode03(struct SongSeq *seq)
{
	// if song loops
	if ((seq->flags & 2) != 0)
	{
		seq->flags |= 8;
	}

	// if song does not loop
	else
	{
		SongPool_StopAllCseq(&GAME_SONG_POOL[seq->songPoolIndex]);
	}
}

void cseq_opcode04_empty(struct SongSeq *seq)
{
	(void)seq;
	// left empty by ND
}

void howl_InitChannelAttr_Music(struct SongSeq *seq, struct ChannelAttr *attr, int index, int channelVol)
{
	int pitch;
	s32 sampleVol;
	int songIndex = seq->songPoolIndex;

	sampleVol = CTR_MipsSra(CTR_MipsMulLo(CTR_MipsMulLo(sdata->vol_Music, sdata->songPool[songIndex].vol_Curr), seq->vol_Curr), 10);

	// instrument
	if ((seq->flags & 4) == 0)
	{
		struct SampleInstrument *longSample = &sdata->ptrCseqLongSamples[seq->instrumentID];

		pitch = howl_InstrumentPitch(longSample->basePitch, index, seq->distort);

		attr->spuStartAddr = (void *)(sdata->howl_spuAddrs[longSample->spuIndex].spuAddr << 3);

		// audio ADSR
		attr->ad = longSample->ad;
		attr->sr = longSample->sr;

		sampleVol = CTR_MipsMulLo(sampleVol, longSample->volume);
	}

	// drums
	else
	{
		struct SampleDrums *shortSample = &sdata->ptrCseqShortSamples[index];

		if (seq->distort == HOWL_SFX_DISTORTION_NONE)
		{
			pitch = shortSample->pitch;
		}

		else
		{
			pitch = CTR_MipsSrl(CTR_MipsMulLo((u16)shortSample->pitch, data.distortConst_OtherFX[seq->distort]), 16);
		}

		attr->spuStartAddr = (void *)(sdata->howl_spuAddrs[shortSample->spuIndex].spuAddr << 3);

		// audio ADSR
		attr->ad = 0x80ff;
		attr->sr = 0x1fc2;

		sampleVol = CTR_MipsMulLo(sampleVol, shortSample->volume);
	}

	Channel_SetVolume(attr, CTR_MipsSrl(CTR_MipsMulLo(sampleVol, channelVol), 15), seq->LR);

	attr->pitch = pitch;
	attr->reverb = seq->reverb;
}

// change volume
void cseq_opcode_from06and07(struct SongSeq *seq)
{
	struct ChannelStats *curr;

	for (curr = (struct ChannelStats *)GAME_CHANNEL_TAKEN.first; curr != NULL; curr = (struct ChannelStats *)curr->link.links.next)
	{
		int sampleVol;

		if (curr->type != HOWL_CHANNEL_TYPE_MUSIC)
		{
			continue;
		}

		// only update this sequence's channels
		if (curr->soundID != seq->soundID)
		{
			continue;
		}

		// NOTE(aalhendi): Retail samples the current song volume for each matching channel.
		sampleVol = CTR_MipsMulLo(CTR_MipsMulLo(sdata->vol_Music, GAME_SONG_POOL[seq->songPoolIndex].vol_Curr), seq->vol_Curr);
		Channel_SetVolume(&GAME_CHANNEL_ATTR_NEW[curr->channelID], CTR_MipsSra(CTR_MipsMulLo(sampleVol, curr->vol), 18), seq->LR);

		// update volume
		GAME_CHANNEL_UPDATE_FLAGS[curr->channelID] |= HOWL_CHANNEL_UPDATE_VOLUME;
	}
}

void cseq_opcode05_noteon(struct SongSeq *seq)
{
	u8 *currNote;
	int songIndex = seq->songPoolIndex;
	struct ChannelStats *stats;
	struct ChannelAttr attr;

	if (sdata->vol_Music == 0)
	{
		return;
	}
	if (sdata->songPool[songIndex].vol_Curr == 0)
	{
		return;
	}
	if (seq->vol_Curr == 0)
	{
		return;
	}

	currNote = seq->currNote;

	howl_InitChannelAttr_Music(seq, &attr, currNote[1], currNote[2]);

	stats = Channel_AllocSlot(HOWL_CHANNEL_UPDATE_ALL_ATTRS, &attr);

	if (stats == 0)
	{
		return;
	}

	stats->flags |= 0xe;

	stats->type = HOWL_CHANNEL_TYPE_MUSIC;
	stats->unk2 = 0;

	// dang, what?
	stats->unk1 = seq->unk;

	// echo and reverb is same thing, needs rename
	stats->echo = seq->reverb;

	stats->vol = currNote[2];

	stats->distort = seq->distort;
	stats->LR = seq->LR;
	stats->timeLeft = 0;
	stats->drumIndex_pitchIndex = currNote[1];
	stats->soundID = seq->soundID;

	seq->unk0A = (u8)CTR_MipsAddLo(seq->unk0A, 1);
}

void cseq_opcode06(struct SongSeq *seq)
{
	u8 *note = seq->currNote;
	seq->vol_Curr = note[1];
	cseq_opcode_from06and07(seq);
}

void cseq_opcode07(struct SongSeq *seq)
{
	u8 *note = seq->currNote;
	seq->LR = note[1];
	cseq_opcode_from06and07(seq);
}

void cseq_opcode08(struct SongSeq *seq)
{
	struct ChannelStats *curr;
	u8 *currNote = seq->currNote;

	for (curr = (struct ChannelStats *)GAME_CHANNEL_TAKEN.first; curr != NULL; curr = (struct ChannelStats *)curr->link.links.next)
	{
		if (curr->type != HOWL_CHANNEL_TYPE_MUSIC)
		{
			continue;
		}

		// only update this sequence's channels
		if (curr->soundID != seq->soundID)
		{
			continue;
		}

		// set reverb
		GAME_CHANNEL_ATTR_NEW[curr->channelID].reverb = currNote[1];

		// update Reverb (reverberation = echo)
		GAME_CHANNEL_UPDATE_FLAGS[curr->channelID] |= HOWL_CHANNEL_UPDATE_REVERB;
	}
}

void cseq_opcode09(struct SongSeq *seq)
{
	u8 *currNote = seq->currNote;
	seq->instrumentID = currNote[1];
}

void cseq_opcode0a(struct SongSeq *seq)
{
	struct ChannelStats *curr;

	u8 *currNote = seq->currNote;
	seq->distort = currNote[1];

	for (curr = (struct ChannelStats *)GAME_CHANNEL_TAKEN.first; curr != NULL; curr = (struct ChannelStats *)curr->link.links.next)
	{
		if (curr->type != HOWL_CHANNEL_TYPE_MUSIC)
		{
			continue;
		}

		// only update this sequence's channels
		if (curr->soundID != seq->soundID)
		{
			continue;
		}

		// drums
		if ((seq->flags & 4) != 0)
		{
			struct SampleDrums *shortSample = &sdata->ptrCseqShortSamples[curr->drumIndex_pitchIndex];

			if (seq->distort != HOWL_SFX_DISTORTION_NONE)
			{
				// NOTE(aalhendi): Resolve the destination before the table lookup for retail page order.
				struct ChannelAttr *attr = &GAME_CHANNEL_ATTR_NEW[curr->channelID];
				attr->pitch = CTR_MipsSrl(CTR_MipsMulLo((u16)shortSample->pitch, GAME_DISTORT_CONST_OTHER_FX[seq->distort]), 16);
			}
			else
			{
				GAME_CHANNEL_ATTR_NEW[curr->channelID].pitch = (u16)shortSample->pitch;
			}
		}

		// instrument
		else
		{
			struct SampleInstrument *longSample = &sdata->ptrCseqLongSamples[seq->instrumentID];
			GAME_CHANNEL_ATTR_NEW[curr->channelID].pitch = howl_InstrumentPitch(longSample->basePitch, curr->drumIndex_pitchIndex, seq->distort);
		}

		// update pitch
		GAME_CHANNEL_UPDATE_FLAGS[curr->channelID] |= HOWL_CHANNEL_UPDATE_PITCH;
	}
}
