#ifndef CTR_MATCHING_RETAIL_BINDINGS_H
#define CTR_MATCHING_RETAIL_BINDINGS_H

// NOTE(aalhendi): Shared resident addresses for private matching bindings.
// Access widths and addressing forms may still differ by compilation unit.
#define RETAIL_GAME_TRACKER_ASM_NAME       "sdata_static+832"
#define RETAIL_LANGUAGE_STRINGS_ASM_NAME   "sdata_static+2316"
#define RETAIL_CHARACTER_METADATA_ASM_NAME "data+25572"
#define RETAIL_CHARACTER_IDS_ASM_NAME      "data+25828"
#define RETAIL_2P_AI_SETS_ASM_NAME         "data+12468"
#define RETAIL_OVERLAY_CALLBACKS_ASM_NAME  "data+12496"
#define RETAIL_CURR_SLOT_ASM_NAME          "data+12444"
#define RETAIL_QUEUE_SLOTS_ASM_NAME        "sdata_static+37848"
#define RETAIL_LEVEL_METADATA_ASM_NAME     "data+12512"
#define RETAIL_BOSS_WEAPON_META_ASM_NAME   "data+20528"
#define RETAIL_GAME_SAVE_ASM_NAME          "sdata_static+6012"
#define RETAIL_ADD_CONFIG_0_ASM_NAME       "sdata_static+404"
#define RETAIL_HOWL_MAGIC_ASM_NAME         "sdata_static+244"

// NOTE(aalhendi): LOAD_TenStages materializes these link addresses in a
// particular order. Keep the retail page and signed lows in the private ABI;
// native uses the corresponding GAME_* objects instead.
#define RETAIL_LOAD_PREFIX_PAGE            0x80090000
#define RETAIL_LOAD_PREFIX_ENDING_LOW      -12092
#define RETAIL_LOAD_PREFIX_INTRO_LOW       -12084
#define RETAIL_LOAD_PREFIX_SCREEN_LOW      -12076
#define RETAIL_LOAD_PREFIX_GARAGE_LOW      -12068
#define RETAIL_LOAD_PREFIX_HUB_LOW         -12060
#define RETAIL_LOAD_PREFIX_CREDIT_LOW      -12056
#define RETAIL_LOAD_PREFIX_GARAGE_ASM_NAME "sdata_static+368"
#define RETAIL_LOAD_DRIVER_CALLBACK_ASM_NAME "LOAD_Callback_DriverModels"
#define RETAIL_LOAD_DRIVER_CALLBACK_LOW    0x1b00
#define RETAIL_LOAD_PATCH_MEMORY_ASM_NAME  "rdata+4552"
#define RETAIL_LOAD_PATCH_MEMORY_LOW       4552

#define GAME_TRACKER                       ctr_gameTrackerPtr
#define GAME_LOADING_STAGE                 ctr_loadingStage
#define GAME_LOAD_IN_PROGRESS              ctr_loadInProgress
#define GAME_LANGUAGE_STRINGS              ctr_languageStrings
#define GAME_CHARACTER_METADATA            ctr_characterMetadata
#define GAME_CHARACTER_IDS                 ctr_characterIDs
#define GAME_2P_AI_SETS                    ctr_2pAiSets
#define GAME_OVERLAY_CALLBACKS             ctr_overlayCallbacks
#define GAME_LEVEL_BIG_LOD_INDEX           ctr_levelBigLodIndex
#define GAME_LEVEL_METADATA                ctr_levelMetadata
#define GAME_LEVEL_PREFIX_NDI              ctr_levelPrefixNdi
#define GAME_LEVEL_PREFIX_ENDING           ctr_levelPrefixEnding
#define GAME_LEVEL_PREFIX_INTRO            ctr_levelPrefixIntro
#define GAME_LEVEL_PREFIX_SCREEN           ctr_levelPrefixScreen
#define GAME_LEVEL_PREFIX_GARAGE           ctr_levelPrefixGarage
#define GAME_LEVEL_PREFIX_HUB              ctr_levelPrefixHub
#define GAME_LEVEL_PREFIX_CREDIT           ctr_levelPrefixCredit
#define GAME_RDATA_NAME(name)               ctr_retail_##name
#define GAME_MAIN_MENU_STATE                ctr_mainMenuState
#define GAME_XA_STATE                       ctr_xaState
#define GAME_BOSS_WEAPON_METADATA          ctr_bossWeaponMetaPtr
#define GAME_FRAMES_SINCE_RACE_ENDED       ctr_framesSinceRaceEnded
#define GAME_MENU_READY                    ctr_menuReady
#define GAME_ANY_PLAYER_TAP                ctr_anyPlayerTap
#define GAME_ADV_PROGRESS                  ctr_advProgress
#define GAME_ADV_RNG                       ctr_advRng
#define GAME_SAVE                          ctr_gameSave
#define GAME_PROGRESS                      (GAME_SAVE.progress)
#define GAMEPADS                           ctr_gamepads
#define GAME_MENU_HIGHLIGHT                ctr_menuHighlight
#define GAME_TOKEN                         ctr_token
#define GAME_ADD_CONFIG_0                  ctr_addConfig0
#define GAME_REMOVE_CONFIG_0               ctr_removeConfig0
#define GAME_DOOR_ACCESS_FLAGS             ctr_doorAccessFlags
#define GAME_DRIVER_MODEL_EXTRAS           ctr_driverModelExtras
#define GAME_PLAYER_OBJECT_LIST            ctr_playerObjectList
#define GAME_SONG_SEQUENCES                ctr_songSequences
#define GAME_SONG_POOL                     ctr_songPool
#define GAME_NOTE_FREQUENCY                ctr_noteFrequency
#define GAME_DISTORT_CONST_MUSIC           ctr_distortConstMusic
#define GAME_CHANNEL_UPDATE_FLAGS          ctr_channelUpdateFlags
#define GAME_CHANNEL_ATTR_NEW              ctr_channelAttrNew
#define GAME_VOLUME_LR                     ctr_volumeLR
#define GAME_WRONG_WAY_DIRECTION           ctr_wrongWayDirection
#define GAME_SAME_DIRECTION_FRAMES         ctr_framesDrivingSameDirection
#define GAME_DISTORT_CONST_OTHER_FX        ctr_distortConstOtherFX
#define GAME_HOWL_REVERB_PARAMS            ctr_howlReverbParams
#define GAME_CHANNEL_TAKEN                 ctr_channelTaken
#define GAME_CHANNEL_FREE                  ctr_channelFree
#define GAME_HOWL_CD_FILE                  ctr_howlCdFile
#define GAME_AUDIO_ENABLED                 ctr_audioEnabled
#define GAME_HOWL_BANK_OFFSETS             ctr_howlBankOffsets
#define GAME_HOWL_HEADER                   ctr_howlHeader
#define GAME_CSEQ_HEADER                   ctr_cseqHeader
#define GAME_HOWL_SPU_ADDRS                ctr_howlSpuAddrs
#define GAME_GARAGE_SOUND_POOL             ctr_garageSoundPool
#define GAME_MEMCARD_STATE                 ctr_memcardState
#define GAME_MEMCARD_DIR_HEADER            ctr_memcardDirHeader
#define GAME_MEMCARD_SW_IOE                ctr_memcardSwIOE
#define GAME_MEMCARD_HW_IOE                ctr_memcardHwIOE
#define GAME_MEMCARD_ICON_CRASH            ctr_memcardIconCrash
#define GAME_MEMCARD_ICON_GHOST            ctr_memcardIconGhost
#define GAME_AUDIO_BANKS                   ctr_audioBanks
#define GAME_AUDIO_BANK_COUNT              ctr_audioBankCount

// NOTE(aalhendi): Count is at 2048($gp); keep that ABI displacement out of game source.
#define GAME_AUDIO_BANK_COUNT_LOAD_AFTER(result, dependency) CTR_PSX_LOAD_GP_UNSIGNED_BYTE_AFTER(result, 2048, GAME_AUDIO_BANK_COUNT, dependency)

#define GAME_HOWL_SAMPLE_BLOCK_NAME        ctr_howlLoadSampleBlockName

#include <common.h>

// NOTE(aalhendi): These declarations name existing resident storage. Native
// accesses the same fields through the canonical sData and Data aggregates.
extern struct GameTracker *ctr_gameTrackerPtr asm(RETAIL_GAME_TRACKER_ASM_NAME);
extern LoadStage ctr_loadingStage asm("sdata_static+396");
extern s32 ctr_loadInProgress asm("312($28)");
extern char **ctr_languageStrings asm(RETAIL_LANGUAGE_STRINGS_ASM_NAME);
extern struct MetaDataCHAR ctr_characterMetadata[16] asm(RETAIL_CHARACTER_METADATA_ASM_NAME);
extern s16 ctr_characterIDs[8] asm(RETAIL_CHARACTER_IDS_ASM_NAME);
extern u8 ctr_2pAiSets[LOAD_2P_AI_SET_COUNT][LOAD_2P_AI_SET_RACER_COUNT] asm(RETAIL_2P_AI_SETS_ASM_NAME);
extern void *ctr_overlayCallbacks[4] asm(RETAIL_OVERLAY_CALLBACKS_ASM_NAME);
extern u8 ctr_levelBigLodIndex[8] asm("sdata_static+328");
extern struct MetaDataLEV ctr_levelMetadata[0x41] asm(RETAIL_LEVEL_METADATA_ASM_NAME);
extern char ctr_levelPrefixNdi[4] asm("sdata_static+340");
extern char ctr_levelPrefixEnding[8] asm("sdata_static+344");
extern char ctr_levelPrefixIntro[8] asm("sdata_static+352");
extern char ctr_levelPrefixScreen[8] asm("sdata_static+360");
extern char ctr_levelPrefixGarage[8] asm(RETAIL_LOAD_PREFIX_GARAGE_ASM_NAME);
extern char ctr_levelPrefixHub[4] asm("sdata_static+376");
extern char ctr_levelPrefixCredit[8] asm("sdata_static+380");
extern char ctr_retail_s_circle[] asm("rdata+4572");
extern char ctr_retail_s_HUB_ALLOC[] asm("rdata+4540");
extern char ctr_retail_s_Patch_Table_Memory[] asm(RETAIL_LOAD_PATCH_MEMORY_ASM_NAME);
extern char ctr_retail_s_clod[] asm("rdata+4588");
extern char ctr_retail_s_dustpuff[] asm("rdata+4604");
extern char ctr_retail_s_smokering[] asm("rdata+4620");
extern char ctr_retail_s_sparkle[] asm("rdata+4636");
extern char ctr_retail_s_lightredoff[] asm("rdata+4652");
extern char ctr_retail_s_lightredon[] asm("rdata+4680");
extern char ctr_retail_s_lightgreenoff[] asm("rdata+4708");
extern char ctr_retail_s_lightgreenon[] asm("rdata+4740");
extern s16 ctr_mainMenuState asm("sdata_static+2576");
extern XAState ctr_xaState asm("sdata_static+1948");
extern struct MetaDataBOSS *ctr_bossWeaponMetaPtr[5] asm(RETAIL_BOSS_WEAPON_META_ASM_NAME);

extern s32 ctr_framesSinceRaceEnded asm("sdata_static+1472");
extern s32 ctr_menuReady asm("sdata_static+1360");
extern s32 ctr_anyPlayerTap asm("sdata_static+2532");
extern struct AdvProgress ctr_advProgress asm("sdata_static+11320");
extern struct RngDeadCoedState ctr_advRng asm("sdata_static+1788");
extern struct GameSave ctr_gameSave asm(RETAIL_GAME_SAVE_ASM_NAME);
extern struct GamepadSystem *ctr_gamepads asm("sdata_static+836");
extern Color ctr_menuHighlight asm("sdata_static+2528");
extern struct Instance *ctr_token asm("sdata_static+2660");
extern u32 ctr_addConfig0 asm(RETAIL_ADD_CONFIG_0_ASM_NAME);
extern u32 ctr_removeConfig0 asm("sdata_static+408");
extern u32 ctr_doorAccessFlags asm("sdata_static+1980");
extern DriverModelExtraSlot ctr_driverModelExtras[LOAD_DRIVER_MODEL_EXTRA_COUNT] asm("data+12400");
extern struct Model **ctr_playerObjectList asm("sdata_static+2308");
extern struct SongSeq ctr_songSequences[NUM_SFX_CHANNELS] asm("sdata_static+13152");
extern struct Song ctr_songPool[2] asm("sdata_static+36376");
extern u16 ctr_noteFrequency[0x6c] asm("data+9484");
extern u16 ctr_distortConstMusic[0x40] asm("data+9700");
extern u32 ctr_channelUpdateFlags[NUM_SFX_CHANNELS] asm("sdata_static+11520");
extern struct ChannelAttr ctr_channelAttrNew[NUM_SFX_CHANNELS] asm("sdata_static+11616");
extern u8 ctr_volumeLR[0x100] asm("data+9228");
extern u8 ctr_wrongWayDirection asm("sdata_static+2672");
extern s32 ctr_framesDrivingSameDirection asm("sdata_static+2680");
extern s32 ctr_distortConstOtherFX[0x100] asm("data+8204");
extern SpuReverbAttr ctr_howlReverbParams[5] asm("data+7080");
extern struct LinkedList ctr_channelTaken asm("sdata_static+13824");
extern struct LinkedList ctr_channelFree asm("sdata_static+13836");
extern CdlFILE ctr_howlCdFile asm("sdata_static+36624");
extern u8 ctr_audioEnabled asm("sdata_static+240");
extern u16 *ctr_howlBankOffsets asm("sdata_static+2168");
extern struct HowlHeader *ctr_howlHeader asm("sdata_static+2132");
extern struct CseqHeader *ctr_cseqHeader asm("sdata_static+2116");
extern struct SpuAddrEntry *ctr_howlSpuAddrs asm("sdata_static+2160");
extern struct GarageFX ctr_garageSoundPool[8] asm("sdata_static+37752");
extern struct MemcardState ctr_memcardState asm("sdata_static+56004");
extern char ctr_memcardDirHeader[8] asm("sdata_static+1192");
// NOTE(aalhendi): Link these as plain small-data symbols so GCC emits the
// retail GP-relative event-handle loads before the stack frame is opened.
extern int ctr_memcardSwIOE;
extern int ctr_memcardHwIOE;
extern int ctr_memcardIconCrash[0x40] asm("data+19456");
extern int ctr_memcardIconGhost[0x40] asm("data+19712");
extern struct Bank ctr_audioBanks[8] asm("sdata_static+11456");
// NOTE(aalhendi): The lifecycle namespace resolves this byte and _gp together for GP-relative loads.
extern u8 ctr_audioBankCount;
extern char ctr_howlLoadSampleBlockName[] asm("rdata+4300");

#endif
