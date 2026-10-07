#include <common.h>
#include <stdlib.h>

// NOTE(ctr-dust2): the level renderer lists the quadblocks it defers to its near/clipped pass
// (the ones whose corners project out of the GTE's range) at
// data.ptrRenderedQuadblockDestination_*[player]: retail points those at
// sdata_static.quadBlocksRendered, 64 per player, 256 in all, and nothing checks the end -
// past it lie the gamepads and the GameTracker. Retail tracks stay inside that; a Dust 2 view
// lists up to about 60 (measured at the landmarks), at the edge of a split-screen player's 64.
// Every player gets a list with room for all of the level's quadblocks (each is listed at most
// once a frame), on the host heap.
static void CTR_RenderLists_EnsureRenderedRoom(struct GameTracker *gGT)
{
	static struct QuadBlock **lists[4];
	static int capacity;
	int need = 0x100;

	if ((gGT->level1 != NULL) && (gGT->level1->ptr_mesh_info != NULL))
	{
		need = 2 * gGT->level1->ptr_mesh_info->numQuadBlock + 0x40;
	}

	if (need > capacity)
	{
		for (int i = 0; i < 4; i++)
		{
			free(lists[i]);
			lists[i] = calloc(need, sizeof(struct QuadBlock *));
		}
		capacity = need;
	}

	for (int i = 0; i < 4; i++)
	{
		data.ptrRenderedQuadblockDestination_forEachPlayer[i] = lists[i];
		data.ptrRenderedQuadblockDestination_again[i] = lists[i];
	}
}

// NOTE(aalhendi): Keep the slot writes explicit. Retail reloads the player's rendered-block
// pointer after each slot, so caching it across the writes changes the MIPS code.
void CTR_ClearRenderLists_1P2P(struct GameTracker *gGT, int numPlyrCurrGame)
{
	int i;
	void **rendered;
	void *quadBlocksRendered;

	if (numPlyrCurrGame <= 0)
	{
		return;
	}

	CTR_RenderLists_EnsureRenderedRoom(gGT);
	i = 0;
	rendered = data.ptrRenderedQuadblockDestination_forEachPlayer;
	do
	{
		quadBlocksRendered = *rendered;
		gGT->LevRenderLists[i].list[0].bspListStart = 0;
		gGT->LevRenderLists[i].list[0].ptrQuadBlocksRendered = quadBlocksRendered;
		quadBlocksRendered = *rendered;
		gGT->LevRenderLists[i].list[1].bspListStart = 0;
		gGT->LevRenderLists[i].list[1].ptrQuadBlocksRendered = quadBlocksRendered;
		quadBlocksRendered = *rendered;
		gGT->LevRenderLists[i].list[2].bspListStart = 0;
		gGT->LevRenderLists[i].list[2].ptrQuadBlocksRendered = quadBlocksRendered;
		quadBlocksRendered = *rendered;
		gGT->LevRenderLists[i].list[3].bspListStart = 0;
		gGT->LevRenderLists[i].list[3].ptrQuadBlocksRendered = quadBlocksRendered;
		quadBlocksRendered = *rendered;
		rendered++;
		gGT->LevRenderLists[i].list[4].bspListStart = 0;
		gGT->LevRenderLists[i].list[4].ptrQuadBlocksRendered = quadBlocksRendered;

		gGT->LevRenderLists[i].bspListStart_FullDynamic = 0;
		gGT->LevRenderLists[i].ptrQuadBlocksRendered_FullDynamic = 0;
		i++;
	} while (i < numPlyrCurrGame);
}

void CTR_ClearRenderLists_3P4P(struct GameTracker *gGT, int numPlyrCurrGame)
{
	int i;
	void **rendered;
	void *quadBlocksRendered;

	if (numPlyrCurrGame <= 0)
	{
		return;
	}

	CTR_RenderLists_EnsureRenderedRoom(gGT);
	i = 0;
	rendered = data.ptrRenderedQuadblockDestination_again;
	do
	{
		quadBlocksRendered = *rendered;
		gGT->LevRenderLists[i].list[0].bspListStart = 0;
		gGT->LevRenderLists[i].list[0].ptrQuadBlocksRendered = quadBlocksRendered;
		quadBlocksRendered = *rendered;
		gGT->LevRenderLists[i].list[1].bspListStart = 0;
		gGT->LevRenderLists[i].list[1].ptrQuadBlocksRendered = quadBlocksRendered;
		quadBlocksRendered = *rendered;
		gGT->LevRenderLists[i].list[2].bspListStart = 0;
		gGT->LevRenderLists[i].list[2].ptrQuadBlocksRendered = quadBlocksRendered;
		quadBlocksRendered = *rendered;
		rendered++;
		gGT->LevRenderLists[i].list[3].bspListStart = 0;
		gGT->LevRenderLists[i].list[3].ptrQuadBlocksRendered = quadBlocksRendered;

		gGT->LevRenderLists[i].list[4].ptrQuadBlocksRendered = 0;
		i++;
	} while (i < numPlyrCurrGame);
}

void CTR_EmptyFunc_MainFrame_ResetDB(void)
{
}
