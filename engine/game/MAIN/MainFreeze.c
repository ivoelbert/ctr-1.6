#include <common.h>

// NOTE(aalhendi): The resident build binds this table to its linked symbol;
// native uses the shared runtime table directly.
#ifndef MAIN_FREEZE_LOAD_TRIG_BASE
#define MAIN_FREEZE_LOAD_TRIG_BASE(page, base, offset) \
	do                                                 \
	{                                                  \
		(void)sizeof(page);                            \
		(void)sizeof(offset);                          \
		(base) = (u8 *)data.trigApprox;                \
	} while (0)
#endif


void MainFreeze_ConfigDrawNPC105(s16 startX, s16 startY, s16 radius, int angleStepInput, s16 angle, char *color, u32 *otMem, struct PrimMem *primMem)
{
	register int angleStep CTR_PSX_REGISTER("$20") = angleStepInput;
	Color colors[3];
	s16 pos[6];
	int scaledRadiusX;
	int scaledNumerator;
	int currAngleStep;
	u32 currAngle;
	register u32 trigPacked CTR_PSX_REGISTER("$3");
	register u32 trigPage CTR_PSX_REGISTER("$9");
	u32 trigOffset;
	register u8 *trigBase CTR_PSX_REGISTER("$9");
	u8 *trigAddress;
	int sine;
	int cosine;
	// NOTE(aalhendi): The products and shared shift have the retail v0/v1 lifetimes.
	register int xProduct CTR_PSX_REGISTER("$2");
	register int shifted CTR_PSX_REGISTER("$2");
	register int yProduct CTR_PSX_REGISTER("$3");
	int nextStep;

	pos[0] = startX;
	pos[1] = startY;

	scaledNumerator = radius * 8;
	// NOTE(aalhendi): GCC 2.8.1 then places the divide-by-five constant in a3.
	CTR_PSX_BIND_VALUE_CLOBBER(scaledNumerator, "$2");
	scaledRadiusX = scaledNumerator / 5;
	currAngleStep = 0;

	// NOTE(aalhendi): Retail repeats one packed color across all three vertices.
	colors[2] = ColorCode_Load(color);
	colors[1] = colors[2];
	colors[0] = colors[1];

	while (true)
	{
		currAngle = (s16)currAngleStep + (s16)angle;
		// NOTE(aalhendi): Retail reads one table word for both sine and cosine.
		trigOffset = ANG_MODULO_HALF_PI(currAngle) * sizeof(struct TrigTable);
		MAIN_FREEZE_LOAD_TRIG_BASE(trigPage, trigBase, trigOffset);
		CTR_PSX_ADD_POINTER_OFFSET_OFFSET_FIRST(trigAddress, trigBase, trigOffset);
		trigPacked = CTR_ReadU32LE(trigAddress);
		if ((currAngle & ANG_QUADRANT_BIT) != 0)
		{
			cosine = (s16)trigPacked;
			sine = (s16)(trigPacked >> 16);
			if ((currAngle & ANG_SIGN_BIT) != 0)
			{
				sine = -sine;
			}
			else
			{
				cosine = -cosine;
			}
		}
		else
		{
			cosine = (s16)(trigPacked >> 16);
			sine = (s16)trigPacked;
			if ((currAngle & ANG_SIGN_BIT) != 0)
			{
				cosine = -cosine;
				sine = -sine;
			}
		}

		xProduct = scaledRadiusX * cosine;
		shifted = xProduct >> 0xc;
		// NOTE(aalhendi): The result is stored as s16; a low-word add preserves it.
		CTR_PSX_ADD_U32(shifted, startX, shifted);
		pos[4] = shifted;
		yProduct = radius * sine;
		shifted = yProduct >> 0xc;
		pos[5] = startY + (s16)shifted;

		if ((s16)currAngleStep != 0)
		{
			RECTMENU_DrawRwdTriangle(pos, (char *)colors, otMem, primMem);
		}

		nextStep = currAngleStep + angleStep;
		CTR_PSX_COPY_VALUE(currAngleStep, nextStep);
		CTR_PSX_KEEP_VALUE_RELAXED(currAngleStep);

		pos[2] = pos[4];
		pos[3] = pos[5];

		if ((s16)nextStep > 0x1000)
		{
			return;
		}
	}
}

void MainFreeze_ConfigDrawArrows(s16 offsetX, s16 offsetY, char *str)
{
	register int lineWidth CTR_PSX_REGISTER("$18");
	int rawWidth;
	int arrowX;
	int color;
	u32 **colorSlot;

	// orange color
	color = 0;

	if ((GAME_FRAME_COUNTER_LOW & 4) == 0)
	{
		// red color
		color = 3;
	}

	// NOTE(aalhendi): Retail narrows the measured width before halving it;
	// materializing x between those steps preserves the MIPS call-result order.
	rawWidth = DecalFont_GetLineWidth(str, 1);
	arrowX = offsetX;
	lineWidth = (s16)rawWidth / 2;

	// NOTE(aalhendi): Keep the palette slot so both draws reload its pointer.
	colorSlot = &data.ptrColor[color];

	// Draw left arrow
	DecalHUD_Arrow2D(
	    // largeFont
	    (ICONGROUP_GETICONS(GAME_TRACKER->iconGroup[4]))[0x38],

	    (arrowX - lineWidth) - 0x14, (int)offsetY + 7,

	    // pointer to PrimMem struct
	    &GAME_TRACKER->backBuffer->primMem,

	    // pointer to OT memory
	    GAME_TRACKER->pushBuffer_UI.ptrOT,

	    // color data
	    ColorCode_Load(&(*colorSlot)[0]), ColorCode_Load(&(*colorSlot)[1]), ColorCode_Load(&(*colorSlot)[2]), ColorCode_Load(&(*colorSlot)[3]),

	    0, FP(1.0), 0x800);

	// Draw right arrow
	DecalHUD_Arrow2D(
	    // largeFont
	    (ICONGROUP_GETICONS(GAME_TRACKER->iconGroup[4]))[0x38],

	    (arrowX + lineWidth) + 0x12, (int)offsetY + 7,

	    // pointer to PrimMem struct
	    &GAME_TRACKER->backBuffer->primMem,

	    // pointer to OT memory
	    GAME_TRACKER->pushBuffer_UI.ptrOT,

	    // color data
	    ColorCode_Load(&(*colorSlot)[0]), ColorCode_Load(&(*colorSlot)[1]), ColorCode_Load(&(*colorSlot)[2]), ColorCode_Load(&(*colorSlot)[3]),

	    0, FP(1.0), 0);

	return;
}

static inline void MainFreeze_ConfigDrawWire(s16 x1, s16 y1, s16 x2, s16 y2, u8 r, u8 g, u8 b, void *ot)
{
	CTR_Box_DrawWirePrims(x1, y1, x2, y2, r, g, b, ot, &sdata->gGT->backBuffer->primMem);
}

static inline void MainFreeze_ConfigDrawRaceWheel(int value, struct GameTracker *gGT)
{
	s16 triangle[8];
	RECT rect;
	int i;
	int tri;
	int point;
	int sin;
	void *ot;
	s16 y;
	u32 wave;
	int angle;
	int angleSin;
	int base;

	for (i = 0; i < 3; i++)
	{
		sin = MATH_Sin(value);
		ot = gGT->pushBuffer_UI.ptrOT;

		if ((i != 1) && (value == 0x600))
		{
			ot = (void *)((s32)ot + 0xc);
		}

		y = sdata->analogConfigY[0] + ((sin * (i - 1) * 0x20) >> 0xc) + 0x20;
		MainFreeze_ConfigDrawWire(0xe2, y, 0x11e, y, 0, 0xff, 0, ot);
	}

	for (tri = 0; tri < 2; tri++)
	{
		wave = ((u32)sdata->frameCounter << 6) + (tri * 0x800);
		sin = MATH_Sin(wave);
		angle = (value * sin) >> 0xc;
		angleSin = MATH_Sin(angle);

		for (point = 0; point < 3; point++)
		{
			base = tri * 6 + point * 2;
			triangle[point * 2] = data.raceConfig_unk80084290[base + 2] + ((tri == 0) ? 0x114 : 0xec);
			triangle[(point * 2) + 1] = sdata->analogConfigY[0] + ((angleSin << 5) >> 0xc) + 0x20 + data.raceConfig_unk80084290[base + 3];
		}

		RECTMENU_DrawRwdTriangle(triangle, (char *)data.raceConfig_colors_arrows, gGT->pushBuffer_UI.ptrOT, &gGT->backBuffer->primMem);
	}

	rect.x = 0xec;
	rect.y = sdata->analogConfigY[0];
	rect.w = 0x28;
	rect.h = 0x41;
	RECTMENU_DrawRwdBlueRect(&rect, (char *)data.raceConfig_colors_blueRect, gGT->pushBuffer_UI.ptrOT, &gGT->backBuffer->primMem);

	rect.x = -0x14;
	rect.y = sdata->analogConfigY[0] - 0x14;
	rect.w = 0x228;
	rect.h = 0x91;
	RECTMENU_DrawInnerRect(&rect, 4, gGT->pushBuffer_UI.ptrOT);
}

static inline void MainFreeze_ConfigDrawNamco(int value, struct GameTracker *gGT)
{
	int mirrorValue = -value;
	RECT rect;
	int i;
	int currValue;
	u32 angle;
	int sin;
	int cos;
	u32 frameAngle;
	u32 baseAngle;
	int baseSin;
	int baseCos;
	int point;
	int offset;
	int row;
	int wireAngle;
	u8 color;
	u32 currAngle;
	u16 iconRow;
	int rowOffset;
	int pointOffset;
	s16 scale;

	for (i = 0; i < 2; i++)
	{
		currValue = (i == 0) ? mirrorValue : value;
		angle = (currValue - 0x400) & 0xfff;
		sin = MATH_Sin(angle);
		cos = MATH_Cos(angle);

		MainFreeze_ConfigDrawWire(0x100 + ((cos * 400) / 0x5000), sdata->analogConfigY[1] + ((sin * 0x32) >> 0xc), 0x100 + ((cos * 0x118) / 0x5000),
		                          sdata->analogConfigY[1] + ((sin * 0x23) >> 0xc), 0, 0xff, 0, gGT->pushBuffer_UI.ptrOT);
	}

	frameAngle = (u32)sdata->frameCounter << 6;
	baseAngle = (((MATH_Sin(frameAngle) * value) >> 0xc) - 0x400) & 0xfff;
	baseSin = MATH_Sin(baseAngle);
	baseCos = MATH_Cos(baseAngle);

	for (point = 0; point < 3; point++)
	{
		int colorOffset = point * 4;
		offset = point * 2;
		MainFreeze_ConfigDrawNPC105(data.unkNamcoGamepad_800842DC[offset] + ((baseCos * 200) / 0x5000) + 0x100,
		                            data.unkNamcoGamepad_800842DC[offset + 1] + sdata->analogConfigY[1] + ((baseSin * 0x19) >> 0xc), 10, 0x80, baseAngle,
		                            (char *)&data.jogConTriangleColors[colorOffset], gGT->pushBuffer_UI.ptrOT, &gGT->backBuffer->primMem);
	}

	for (row = 0; row < 0x400; row += 0xaa)
	{
		for (wireAngle = 0; wireAngle < 0x1000; wireAngle += 0x400)
		{
			color = (row != 0) ? 0x50 : 0x32;
			currAngle = (baseAngle + wireAngle + row) & 0xfff;
			sin = MATH_Sin(currAngle);
			cos = MATH_Cos(currAngle);

			MainFreeze_ConfigDrawWire(0x100 + ((cos < 0 ? cos + 0x3f : cos) >> 6), sdata->analogConfigY[1] + ((sin * 0x28) >> 0xc),
			                          0x100 + ((cos * 0x120) / 0x5000), sdata->analogConfigY[1] + ((sin * 0x24) >> 0xc), color, color, color,
			                          gGT->pushBuffer_UI.ptrOT);
		}
	}

	for (iconRow = 0; iconRow < 3; iconRow++)
	{
		rowOffset = iconRow * 2;
		for (point = 0; point < 3; point++)
		{
			pointOffset = point * 2;
			scale = data.unkNamcoGamepad_800842DC[rowOffset + 7];
			MainFreeze_ConfigDrawNPC105(data.unkNamcoGamepad_800842DC[pointOffset + 18] * scale + 0x100,
			                            sdata->analogConfigY[1] + (data.unkNamcoGamepad_800842DC[pointOffset + 19] * scale),
			                            data.unkNamcoGamepad_800842DC[rowOffset + 6], 0x80, baseAngle, (char *)&data.unkNamcoGamepad_800842DC[pointOffset + 12],
			                            gGT->pushBuffer_UI.ptrOT, &gGT->backBuffer->primMem);
		}
	}

	rect.x = -0x14;
	rect.y = sdata->analogConfigY[1] - 0x3c;
	rect.w = 0x228;
	rect.h = 0xa0;
	RECTMENU_DrawInnerRect(&rect, 4, gGT->pushBuffer_UI.ptrOT);
}

void MainFreeze_ConfigSetupEntry(void)
{
	struct GameTracker *gGT = sdata->gGT;
	int gamepadID;
	struct GamepadBuffer *gamepad;
	struct ControllerPacket *controller;
	int isNamco;
	int posIndex;

	if ((sdata->AnyPlayerTap & (BTN_TRIANGLE | BTN_SQUARE_one)) != 0)
	{
		sdata->boolOpenWheelConfig = false;
		return;
	}

	gamepadID = sdata->gamepadID_OwnerRaceWheelConfig;
	gamepad = &sdata->gGamepads->gamepad[gamepadID];
	controller = gamepad->ptrControllerPacket;

	if ((controller == NULL) || (controller->plugged != PLUGGED))
	{
		sdata->boolOpenWheelConfig = false;
		return;
	}

	isNamco = controller->controllerData == ((PAD_ID_JOGCON << 4) | 3);
	posIndex = isNamco * 2;

	if (sdata->raceWheelConfigPageIndex == 1)
	{
		u32 tap = sdata->buttonTapPerPlayer[gamepadID];

		if ((tap & (BTN_UP | BTN_LEFT)) != 0)
		{
			sdata->WheelConfigOption--;
			if ((s16)sdata->WheelConfigOption < 0)
			{
				sdata->WheelConfigOption = 3;
			}
		}
		else if ((tap & (BTN_DOWN | BTN_RIGHT)) != 0)
		{
			sdata->WheelConfigOption++;
			if ((s16)sdata->WheelConfigOption > 3)
			{
				sdata->WheelConfigOption = 0;
			}
		}
		else if ((tap & (BTN_CIRCLE | BTN_CROSS_one)) != 0)
		{
			sdata->raceWheelConfigPageIndex = 2;
			data.rwd[gamepadID].deadZone = data.raceConfig_DeadZone[(s16)sdata->WheelConfigOption].hi1;
		}

		DecalFont_DrawMultiLine(sdata->lngStrings[LNG_SELECT_DEAD_ZONE_AND_PRESS_BUTTON], 0x100, sdata->posY_MultiLine[posIndex], 0x1cc, FONT_BIG,
		                        JUSTIFY_CENTER);
		DecalFont_DrawLine(sdata->lngStrings[data.raceConfig_DeadZone[(s16)sdata->WheelConfigOption].lngIndex], 0x100, sdata->posY_Arrows[posIndex], FONT_BIG,
		                   JUSTIFY_CENTER);
		MainFreeze_ConfigDrawArrows(0x100, sdata->posY_Arrows[posIndex], sdata->lngStrings[data.raceConfig_DeadZone[(s16)sdata->WheelConfigOption].lngIndex]);
		sdata->unk_RaceWheelConfig[0] = data.raceConfig_DeadZone[(s16)sdata->WheelConfigOption].lo16;
	}
	else if (sdata->raceWheelConfigPageIndex < 2)
	{
		if (sdata->raceWheelConfigPageIndex == 0)
		{
			DecalFont_DrawMultiLine(sdata->lngStrings[LNG_CENTER_THE_CONTROLLER_AND_PRESS_BUTTON], 0x100, sdata->posY_MultiLine[posIndex], 0x1cc, FONT_BIG,
			                        JUSTIFY_CENTER);

			if ((sdata->buttonTapPerPlayer[gamepadID] & (BTN_CIRCLE | BTN_CROSS_one)) != 0)
			{
				sdata->raceWheelConfigPageIndex++;
				if (!isNamco)
				{
					data.rwd[gamepadID].gamepadCenter = controller->payload.analog.rightX;
				}
				else
				{
					gamepad->jogCenteringFrames = 4;
					data.rwd[sdata->gamepadID_OwnerRaceWheelConfig].gamepadCenter = 0x80;
				}
				RECTMENU_ClearInput();
			}

			sdata->unk_RaceWheelConfig[0] = 0;
		}
	}
	else if (sdata->raceWheelConfigPageIndex == 2)
	{
		u32 tap = sdata->buttonTapPerPlayer[gamepadID];

		if ((tap & (BTN_UP | BTN_LEFT)) != 0)
		{
			sdata->raceWheelConfigOptionIndex--;
			if ((s16)sdata->raceWheelConfigOptionIndex < 0)
			{
				sdata->raceWheelConfigOptionIndex = data.raceConfig_unk80084290[isNamco];
			}
		}
		else if ((tap & (BTN_DOWN | BTN_RIGHT)) != 0)
		{
			sdata->raceWheelConfigOptionIndex++;
			if ((s16)data.raceConfig_unk80084290[isNamco] < (s16)sdata->raceWheelConfigOptionIndex)
			{
				sdata->raceWheelConfigOptionIndex = 0;
			}
		}
		else if ((tap & (BTN_CIRCLE | BTN_CROSS_one)) != 0)
		{
			sdata->boolOpenWheelConfig = false;
			data.rwd[gamepadID].range = data.raceConfig_Range[(s16)sdata->raceWheelConfigOptionIndex].hi1;
			RECTMENU_ClearInput();
		}

		sdata->unk_RaceWheelConfig[0] = data.raceConfig_Range[(s16)sdata->raceWheelConfigOptionIndex].lo16;
		DecalFont_DrawMultiLine(sdata->lngStrings[LNG_SELECT_RANGE_AND_PRESS_BUTTON], 0x100, sdata->posY_MultiLine[posIndex], 0x1cc, FONT_BIG, JUSTIFY_CENTER);
		DecalFont_DrawLine(sdata->lngStrings[data.raceConfig_Range[(s16)sdata->raceWheelConfigOptionIndex].lngIndex], 0x100, sdata->posY_Arrows[posIndex],
		                   FONT_BIG, JUSTIFY_CENTER);
		MainFreeze_ConfigDrawArrows(0x100, sdata->posY_Arrows[posIndex],
		                            sdata->lngStrings[data.raceConfig_Range[(s16)sdata->raceWheelConfigOptionIndex].lngIndex]);
	}

	if (!isNamco)
	{
		MainFreeze_ConfigDrawRaceWheel(sdata->unk_RaceWheelConfig[0], gGT);
	}
	else
	{
		MainFreeze_ConfigDrawNamco(sdata->unk_RaceWheelConfig[0], gGT);
	}
}


typedef struct
{
	int numGamepads;
	int numAnalogs;
	int gamepadId[4];
	int analogId[4];
	int isGamepadAnalog[4];
	int menuRowsToRemove;
} GAMEPAD_MainFreeze_MenuPtrOptions;

static void IDENTIFYGAMEPADS_MainFreeze_MenuPtrOptions(struct RectMenu *menu, GAMEPAD_MainFreeze_MenuPtrOptions *gamepad)
{
	struct GameTracker *gGT = sdata->gGT;
	b32 areBothControllerLabelsNecessary;
	int i;
	(void)menu;

	// get number of ordinary gamepads and/or "analog controllers" connected, and which players are using which

	for (i = 0; i < gGT->numPlyrCurrGame; i++)
	{
		struct ControllerPacket *ptrControllerPacket = sdata->gGamepads->gamepad[i].ptrControllerPacket;

		// if gamepad is not an "analog controller", as CTR uses to refer to jogcons and negcons
		if (
		    // this function needs to display menu graphics for digital controllers at all times,
		    // even if they're unplugged; this is simply an additional check for if
		    // an "analog controller" is connected or not
		    ((ptrControllerPacket == 0) || (ptrControllerPacket->plugged != PLUGGED)) ||

		    ((ptrControllerPacket->controllerData != ((PAD_ID_JOGCON << 4) | 3)) && (ptrControllerPacket->controllerData != ((PAD_ID_NEGCON << 4) | 3))))
		{
			gamepad->gamepadId[gamepad->numGamepads] = i;
			gamepad->isGamepadAnalog[i] = false;
			gamepad->numGamepads++;
		}
		else
		{
			gamepad->analogId[gamepad->numAnalogs] = i;
			gamepad->isGamepadAnalog[i] = true;
			gamepad->numAnalogs++;
		}
	}

	// the menu buttons for configuring dualshocks and analog controllers are accompanied by labels each
	// these labels can appear at once
	areBothControllerLabelsNecessary = false;
	if (gamepad->numGamepads != 0)
	{
		areBothControllerLabelsNecessary = (gamepad->numAnalogs != 0);
	}

	// set amount of menu rows to hide/remove
	// used for the dualshock and/or "analog" rows which are variable

	// in singleplayer, regardless of gamepad, 2 of these rows are always visible
	// (dualshock label + 1 gamepad)

	// with 4 regular gamepads connected, in multiplayer, there's 5 rows visible
	// (dualshock label + 4 gamepads)

	// maximum amount of rows is 6, which happens if there's 4 controllers and one of them is analog
	// (dualshock label + analog label + 4 gamepads)

	// in the last scenario, menuRowsToRemove will equal -1
	gamepad->menuRowsToRemove = (4 - areBothControllerLabelsNecessary) - gGT->numPlyrCurrGame;
}

static b32 PROCESSINPUTS_MainFreeze_MenuPtrOptions(struct RectMenu *menu, GAMEPAD_MainFreeze_MenuPtrOptions *gamepad)
{
	struct GameTracker *gGT = sdata->gGT;
	b32 exitMenu = false;

	if (sdata->AnyPlayerTap & (BTN_UP | BTN_DOWN))
	{
		// play sound for when you're moving around in the menu
		OtherFX_Play(0, 1);

		// there are only 9 rows total
		if (sdata->AnyPlayerTap & BTN_UP)
		{
			menu->rowSelected = (menu->rowSelected + (9 - 1)) % 9;
			if (menu->rowSelected == 7)
			{
				menu->rowSelected = gGT->numPlyrCurrGame + 3;
			}
		}
		else if (sdata->AnyPlayerTap & BTN_DOWN)
		{
			menu->rowSelected = (menu->rowSelected + 1) % 9;
			if (menu->rowSelected > (gGT->numPlyrCurrGame + 3))
			{
				menu->rowSelected = 8;
			}
		}
	}
	else
	{
		switch (menu->rowSelected)
		{
		// 0: FX slider
		// 1: Music slider
		// 2: Voice slider
		case 0:
		case 1:
		case 2:
			OptionsMenu_TestSound(menu->rowSelected, 1);
			if (sdata->AnyPlayerHold & (BTN_LEFT | BTN_RIGHT))
			{
				int volume = howl_VolumeGet(menu->rowSelected) & 0xff;

				if (sdata->AnyPlayerHold & BTN_LEFT)
				{
					volume -= 4;
				}
				else if (sdata->AnyPlayerHold & BTN_RIGHT)
				{
					volume += 4;
				}

				if (volume < 0)
				{
					volume = 0;
				}
				if (volume > 0xff)
				{
					volume = 0xff;
				}

				howl_VolumeSet(menu->rowSelected, volume);
			}
			break;

		// Mode	(Stereo/Mono)
		case 3:
			// clear test sound
			OptionsMenu_TestSound(0, 0);

			if (sdata->AnyPlayerTap & (BTN_CIRCLE | BTN_CROSS_one))
			{
				int mode;
				OtherFX_Play(1, 1);
				mode = howl_ModeGet();
				howl_ModeSet(mode == 0);
			}
			break;

		// DualShock/"Analog controller" settings
		case 4:
		case 5:
		case 6:
		case 7:
			// clear test sound
			OptionsMenu_TestSound(0, 0);

			if (sdata->AnyPlayerTap & (BTN_CIRCLE | BTN_CROSS_one))
			{
				int gamepadRow;
				OtherFX_Play(1, 1);

				gamepadRow = menu->rowSelected - 4;

				if (gamepadRow < gamepad->numGamepads)
				{
					// selecting dualshock row
					// toggle gamepad vibration
					gGT->gameMode1 ^= data.gGT_gameMode1_VibPerPlayer[gamepad->gamepadId[gamepadRow]];
				}
				else
				{
					// selecting "analog controller" row
					// this will open the analog controller config menu
					sdata->gamepadID_OwnerRaceWheelConfig = gamepad->analogId[gamepadRow - gamepad->numGamepads];
					sdata->boolOpenWheelConfig = true;
					sdata->raceWheelConfigPageIndex = 0;
				}
			}
			break;

		// Exit
		case 8:
			// clear test sound
			OptionsMenu_TestSound(0, 0);

			if (sdata->AnyPlayerTap & (BTN_CIRCLE | BTN_CROSS_one))
			{
				OtherFX_Play(1, 1);
				exitMenu = true;
			}
			break;
		}
	}

	return exitMenu;
}

// stuff is drawn last to first
static void DISPLAYRECTMENU_MainFreeze_MenuPtrOptions(struct RectMenu *menu, GAMEPAD_MainFreeze_MenuPtrOptions *gamepad)
{
	struct GameTracker *gGT = sdata->gGT;
	int volumeSliderTriangleLeftMargin;
	int volumeSliderWidth;
	u32 *ot;
	struct PrimMem *primMem;
	Color color;
	int mode;
	int i;
	RECT cursor;
	RECT titleSeparatorLine;
	RECT menuBG;

	// note: multitap only works if it's connected to the P1 slot
	int multitapStringOffset = (sdata->gGamepads->slotBuffer[0].controller.controllerData == (PAD_ID_MULTITAP << 4)) ? 2 : 0;

	// a menu row is 10 pixels
	int menuRowsNegativePadding = gamepad->menuRowsToRemove * 10;

	int analogRowPosY = 0;
	if (gamepad->numGamepads != 0)
	{
		analogRowPosY = (gamepad->numGamepads + 1) * 10;
	}

	// cursor location for exit button, which will change depending on how many dualshock rows there need to be
	data.Options_HighlightBar[8].posY = gamepad->menuRowsToRemove * -10 + 119;

	// cursor location for dualshock rows
	if (gamepad->numGamepads > 0)
	{
		for (i = 0; i < gamepad->numGamepads; i++)
		{
			data.Options_HighlightBar[i + 4].posY = (i * 10) + 79;
		}
	}

	// cursor location for "analog" rows
	if (gamepad->numAnalogs > 0)
	{
		for (i = 0; i < gamepad->numAnalogs; i++)
		{
			b32 areBothControllerLabelsNecessary = false;
			if (gamepad->numGamepads != 0)
			{
				areBothControllerLabelsNecessary = (gamepad->numAnalogs != 0);
			}

			data.Options_HighlightBar[gamepad->numGamepads + i + 4].posY = ((gamepad->numGamepads + i + areBothControllerLabelsNecessary) * 10) + 79;
		}
	}

	menu->drawStyle &= ~RECTMENU_DRAW_STYLE_3P4P_LAYOUT;
	if (gGT->numPlyrCurrGame > 2)
	{
		menu->drawStyle |= RECTMENU_DRAW_STYLE_3P4P_LAYOUT;
	}

	volumeSliderTriangleLeftMargin = 0;

	for (i = 0; i < 3; i++)
	{
		//"FX:", "MUSIC:", "VOICE:"
		int lineWidth = DecalFont_GetLineWidth(sdata->lngStrings[data.Options_StringIDs_Audio[i]], FONT_SMALL);
		if (volumeSliderTriangleLeftMargin < lineWidth)
		{
			volumeSliderTriangleLeftMargin = lineWidth;
		}
	}

	DecalFont_DrawLine(sdata->lngStrings[LNG_OPTIONS_TITLE], 256, 26 + (menuRowsNegativePadding / 2), FONT_BIG, (JUSTIFY_CENTER | ORANGE));

	volumeSliderWidth = 380 - (30 + volumeSliderTriangleLeftMargin);

	ot = gGT->backBuffer->otMem.uiOT;
	primMem = &gGT->backBuffer->primMem;

	// draw volume sliders
	for (i = 0; i < 3; i++)
	{
		int volume;
		int volumeSliderValue;
		s16 volumeSliderPosY;
		int volumeSliderTriangleLeftPosX;
		int volumeSliderBarPosX;
		s16 volumeSliderTriangle[8];
		RECT volumeSliderBar;
		RECT volumeSliderBarOutline;

		volume = howl_VolumeGet(i) & 0xff;
		volumeSliderValue = volume * (volumeSliderWidth - 5);
		volumeSliderPosY = (menuRowsNegativePadding / 2) + (i * 10);

		if (volumeSliderValue < 0)
		{
			volumeSliderValue += 0xff;
		}

		volumeSliderTriangleLeftPosX = 30 + volumeSliderTriangleLeftMargin;
		volumeSliderBarPosX = 0x38 + volumeSliderTriangleLeftPosX + (s16)((u32)volumeSliderValue >> 8);

		volumeSliderTriangle[0] = volumeSliderTriangleLeftPosX + 56;
		volumeSliderTriangle[1] = volumeSliderPosY + 58;
		volumeSliderTriangle[2] = volumeSliderTriangleLeftPosX + volumeSliderWidth + 56;
		volumeSliderTriangle[3] = volumeSliderPosY + 48;
		volumeSliderTriangle[6] = 0;
		volumeSliderTriangle[7] = 0;

		volumeSliderTriangle[4] = volumeSliderTriangle[2];
		volumeSliderTriangle[5] = volumeSliderTriangle[1];

		volumeSliderBar.x = volumeSliderBarPosX + 1;
		volumeSliderBar.y = volumeSliderPosY + 48;
		volumeSliderBar.w = 3;
		volumeSliderBar.h = 10;
		color = *(Color *)(data.Options_VolumeSlider_Colors + 0xc);
		CTR_Box_DrawSolidBox(&volumeSliderBar, &color, ot, primMem);

		volumeSliderBarOutline.x = volumeSliderBarPosX;
		volumeSliderBarOutline.y = volumeSliderPosY + 47;
		volumeSliderBarOutline.w = 5;
		volumeSliderBarOutline.h = 12;

		color = *(Color *)(data.Options_VolumeSlider_Colors + 0x10);
		CTR_Box_DrawSolidBox(&volumeSliderBarOutline, &color, ot, primMem);

		RECTMENU_DrawRwdTriangle(volumeSliderTriangle, data.Options_VolumeSlider_Colors, ot, primMem);

		// "FX:" "MUSIC:" "VOICE:"
		DecalFont_DrawLine(sdata->lngStrings[data.Options_StringIDs_Audio[i]], 76, 50 + (menuRowsNegativePadding / 2) + (i * 10), FONT_SMALL, ORANGE);
	}

	DecalFont_DrawLine(sdata->lngStrings[LNG_MODE], 76, 80 + (menuRowsNegativePadding / 2), FONT_SMALL, ORANGE);

	// 333: MONO
	// 334: STEREO
	mode = howl_ModeGet();

	// "MONO", "STEREO"
	DecalFont_DrawLine(sdata->lngStrings[333 + mode], 436, 80 + (menuRowsNegativePadding / 2), FONT_SMALL, (JUSTIFY_RIGHT | WHITE));

	if (gamepad->numGamepads != 0)
	{
		int lineWidth_controller1A;
		int lineWidth_vibrateOff;
		int lineWidth_vibrateOn;
		DecalFont_DrawLine(sdata->lngStrings[LNG_DUAL_SHOCK], 76, 90 + (menuRowsNegativePadding / 2), FONT_SMALL, ORANGE);

		lineWidth_controller1A = DecalFont_GetLineWidth(sdata->lngStrings[data.Options_StringIDs_Gamepads[2]], FONT_SMALL);

		// width can change depending on language
		lineWidth_vibrateOff = DecalFont_GetLineWidth(sdata->lngStrings[LNG_VIBRATE_OFF], FONT_SMALL);
		lineWidth_vibrateOn = DecalFont_GetLineWidth(sdata->lngStrings[LNG_VIBRATE_ON], FONT_SMALL);
		if (lineWidth_vibrateOn < lineWidth_vibrateOff)
		{
			lineWidth_vibrateOn = lineWidth_vibrateOff;
		}

		lineWidth_vibrateOn = (lineWidth_controller1A + lineWidth_vibrateOn + 10);
		lineWidth_vibrateOn = 256 - (lineWidth_vibrateOn >> 1);

		for (i = 0; i < gamepad->numGamepads; i++)
		{
			int dualShockRowColor = ORANGE;
			int currPad = gamepad->gamepadId[i];
			struct ControllerPacket *ptrControllerPacket = sdata->gGamepads->gamepad[currPad].ptrControllerPacket;
			int rowY;
			b32 boolDisabled;

			if (ptrControllerPacket == 0 || ptrControllerPacket->plugged != PLUGGED)
			{
				dualShockRowColor = GRAY;
			}

			rowY = 100 + (menuRowsNegativePadding / 2) + (i * 10);

			// "CONTROLLER 1", "CONTROLLER 2",
			// "CONTROLLER 1A", "CONTROLLER 1B",
			// "CONTROLLER 1C", "CONTROLLER 1D"
			DecalFont_DrawLine(sdata->lngStrings[data.Options_StringIDs_Gamepads[currPad + multitapStringOffset]], lineWidth_vibrateOn, rowY, FONT_SMALL,
			                   dualShockRowColor);

			boolDisabled = (gGT->gameMode1 & data.gGT_gameMode1_VibPerPlayer[currPad]) != 0;

			if (dualShockRowColor != GRAY)
			{
				dualShockRowColor = boolDisabled ? RED : WHITE;
			}

			// 325: "VIBRATE ON"
			// 326: "VIBRATE OFF"

			DecalFont_DrawLine(sdata->lngStrings[325 + boolDisabled], lineWidth_vibrateOn + lineWidth_controller1A + 10, rowY, FONT_SMALL, dualShockRowColor);
		}
	}

	if (gamepad->numAnalogs != 0)
	{
		DecalFont_DrawLine(sdata->lngStrings[LNG_CONFIGURE_ANALOG], 76, 90 + (menuRowsNegativePadding / 2) + analogRowPosY, FONT_SMALL, ORANGE);

		for (i = 0; i < gamepad->numAnalogs; i++)
		{
			DecalFont_DrawLine(sdata->lngStrings[data.Options_StringIDs_Gamepads[gamepad->analogId[i] + multitapStringOffset]], 256,
			                   100 + (menuRowsNegativePadding / 2) + analogRowPosY + (i * 10), FONT_SMALL, (JUSTIFY_CENTER | ORANGE));
		}
	}

	DecalFont_DrawLine(sdata->lngStrings[LNG_OPTIONS_EXIT], 76, 140 - (menuRowsNegativePadding / 2), FONT_SMALL, ORANGE);

	cursor.x = 74;
	cursor.y = data.Options_HighlightBar[menu->rowSelected].posY + (menuRowsNegativePadding / 2) + 20;
	cursor.w = 364;
	cursor.h = data.Options_HighlightBar[menu->rowSelected].sizeY;

	CTR_Box_DrawClearBox(&cursor, &sdata->menuRowHighlight_Normal, TRANS_50_DECAL, ot, primMem);

	titleSeparatorLine.x = 66;
	titleSeparatorLine.y = (menuRowsNegativePadding / 2) + 43;
	titleSeparatorLine.w = 380;
	titleSeparatorLine.h = 2;

	ColorCode_SetPacked(&color, sdata->battleSetup_Color_UI_1);
	RECTMENU_DrawOuterRect_Edge(&titleSeparatorLine, &color, 0x20, ot);

	menuBG.x = 56;
	menuBG.y = (menuRowsNegativePadding / 2) + 20;
	menuBG.w = 400;
	menuBG.h = 135 - menuRowsNegativePadding;

	RECTMENU_DrawInnerRect(&menuBG, 4, ot);
}

void MainFreeze_MenuPtrOptions(struct RectMenu *menu)
{
	MainFreeze_SafeAdvDestroy();

	// open racing wheel config menu instead
	if (sdata->boolOpenWheelConfig != 0)
	{
		MainFreeze_ConfigSetupEntry();
		return;
	}

	// the options menu has gamepad-related settings
	// specificially for DualShock controllers
	// as well as what CTR refers to as "analog controllers", which are jogcons and negcons
	// this struct will be filled out in IDENTIFYGAMEPADS
	{
		GAMEPAD_MainFreeze_MenuPtrOptions gamepad = {0, 0, {-1, -1, -1, -1}, {-1, -1, -1, -1}, {false, false, false, false}, 0};
		b32 exitMenu;

		IDENTIFYGAMEPADS_MainFreeze_MenuPtrOptions(menu, &gamepad);
		exitMenu = PROCESSINPUTS_MainFreeze_MenuPtrOptions(menu, &gamepad);
		DISPLAYRECTMENU_MainFreeze_MenuPtrOptions(menu, &gamepad);

		if (exitMenu || (sdata->AnyPlayerTap & (BTN_TRIANGLE | BTN_START | BTN_SQUARE_one)))
		{
			OtherFX_Play(1, 1);
			OptionsMenu_TestSound(0, 0);
			RECTMENU_ClearInput();
			sdata->ptrDesiredMenu = MainFreeze_GetMenuPtr();
		}
	}
}

void MainFreeze_MenuPtrQuit(struct RectMenu *menu)
{
	s16 row;
	// NOTE(aalhendi): Keep the menu pointer in v1 across the opening branch;
	// the retail row dispatch then reuses that register for the selected row.
	register struct RectMenu *menuCopy CTR_PSX_REGISTER("$3") = menu;

	if (menu->funcState != RECTMENU_FUNC_STATE_INPUT)
	{
		menu->drawStyle &= ~RECTMENU_DRAW_STYLE_3P4P_LAYOUT;

		// if more than 2 screens
		if (GAME_TRACKER->numPlyrCurrGame > 2)
		{
			menu->drawStyle |= RECTMENU_DRAW_STYLE_3P4P_LAYOUT;
		}

		MainFreeze_SafeAdvDestroy();
		return;
	}

	row = menuCopy->rowSelected;
	switch (row)
	{
	case 1:
	case -1:
	{
		GAME_DESIRED_MENU = MainFreeze_GetMenuPtr();
		break;
	}
	case 0:
	{
		// Erase ghost of previous race from RAM
		GhostTape_Destroy();

		// Add bit for "in menu" when loading is done
		sdata->Loading.OnBegin.AddBitsConfig0 |= MAIN_MENU;

		// Go to main menu
		GAME_MAIN_MENU_STATE = MAIN_MENU_TITLE;

		// Remove bit for "In Adventure Arena" when loading is done
		sdata->Loading.OnBegin.RemBitsConfig0 |= ADVENTURE_ARENA;

		// Unpause game
		GAME_TRACKER->gameMode1 &= ~PAUSE_1;

		// Level ID for main menu (39)
		MainRaceTrack_RequestLoad(0x27);
		break;
	}
	default:
	{
		break;
	}
	}
	return;
}

void MainFreeze_SafeAdvDestroy(void)
{
	// If you're in Adventure Arena
	if ((GAME_TRACKER->gameMode1 & ADVENTURE_ARENA) == 0)
	{
		return;
	}

	// check if Adv Hub is loaded
	if (!LOAD_IsOpen_AdvHub())
	{
		return;
	}

	AH_Pause_Destroy();
	return;
}

void MainFreeze_MenuPtrDefault(struct RectMenu *menu)
{
	register struct GameTracker *tracker CTR_PSX_REGISTER("$6") = GAME_TRACKER;
	register s32 signedStringID CTR_PSX_REGISTER("$5");
	register u32 stringID CTR_PSX_REGISTER("$16");
	register s32 optionsID CTR_PSX_REGISTER("$3");
	register struct RectMenu *activeMenu CTR_PSX_REGISTER("$7") = menu;
	s16 levID = 0; // dingo canyon
	s16 selectedOption;
	s32 replayHuman;
	register u32 addBits0 CTR_PSX_REGISTER("$2");
	register u32 remSource CTR_PSX_REGISTER("$3");
	register u32 remMask CTR_PSX_REGISTER("$2");
	register u32 remBits0 CTR_PSX_REGISTER("$6");
	register u32 tokenBits CTR_PSX_REGISTER("$2");
	register struct GameTracker *mapTracker CTR_PSX_REGISTER("$5");
	register u32 gameMode CTR_PSX_REGISTER("$2");
	register u32 pauseMask CTR_PSX_REGISTER("$3");
	register u32 modeForBranch CTR_PSX_REGISTER("$4");
	register u32 cupRemBits CTR_PSX_REGISTER("$3");
	register u32 bossMask CTR_PSX_REGISTER("$3");
	register u32 bossRemBits CTR_PSX_REGISTER("$3");
	register u32 bossAddBits8 CTR_PSX_REGISTER("$2");
	register s32 cupLevel CTR_PSX_REGISTER("$4");
	register s32 cupID CTR_PSX_REGISTER("$2");
	register struct MenuRow *row CTR_PSX_REGISTER("$2");
	register struct MenuRow *rows CTR_PSX_REGISTER("$3");
	u32 rowOffset;
	struct RectMenu *quitMenu;

	// if you have not waited 5 frames since the game was paused then quit
	if (tracker->cooldownfromPauseUntilUnpause != 0)
	{
		return;
	}
	CTR_PSX_KEEP_VALUE_RELAXED(activeMenu);
	// assume 5 frames have passed since paused

	if (menu->funcState != RECTMENU_FUNC_STATE_INPUT)
	{
		menu->drawStyle &= ~RECTMENU_DRAW_STYLE_3P4P_LAYOUT;

		// if more than 2 screens
		if (2 < tracker->numPlyrCurrGame)
		{
			menu->drawStyle |= RECTMENU_DRAW_STYLE_3P4P_LAYOUT;
		}

		if (((GAME_TRACKER->gameMode1 & ADVENTURE_ARENA) == 0) || (menu->state & NEEDS_TO_CLOSE))
		{
			return;
		}

		// quit adv hub if it's not loaded
		if (!LOAD_IsOpen_AdvHub())
		{
			return;
		}

		AH_Pause_Update();
		return;
	}

	if (menu->rowSelected < 0)
	{
		return;
	}

	// NOTE(aalhendi): Keep retail's six-byte row stride and two halfword reads;
	// the signed read drives the early menu cases, the unsigned read the dispatch.
	rowOffset = menu->rowSelected * 3;
	CTR_PSX_KEEP_VALUE_RELAXED(rowOffset);
	CTR_PSX_LOAD_WORD(rows, menu->rows);
	CTR_PSX_DEPEND_VALUE(rowOffset, rows);
	rowOffset <<= 1;
	CTR_PSX_ADD_POINTER_OFFSET_OFFSET_FIRST(row, rows, rowOffset);
	optionsID = 14;
	CTR_PSX_KEEP_VALUE_RELAXED(optionsID);
	CTR_PSX_LOAD_SIGNED_HALF(signedStringID, row, 0, row->stringIndex);
	CTR_PSX_LOAD_UNSIGNED_HALF(stringID, row, 0, row->stringIndex);

	// stringID 14: "OPTIONS"
	if (signedStringID == optionsID)
	{
		// Set Menu to Options
		GAME_DESIRED_MENU = &data.menuRacingWheelConfig;

		data.menuRacingWheelConfig.rowSelected = 8;
		return;
	}

	// stringID 11: "AKU AKU HINTS"
	// stringID 12: "UKA UKA HINTS"
	if ((u16)(stringID - 11) < 2)
	{
		// Set Menu to Hints
		GAME_DESIRED_MENU = &D232.menuHintMenu; // in 232
		return;
	}

	// stringID 3: "QUIT"
	if (signedStringID == 3)
	{
		// Set Menu to Quit
		quitMenu = &data.menuQuit;
		quitMenu->rowSelected = 1;
		GAME_DESIRED_MENU = quitMenu;
		return;
	}

	// must wait 5 frames until next pause
	GAME_TRACKER->cooldownFromUnpauseUntilPause = 5;
	CTR_PSX_MEMORY_BARRIER();

	// hide Menu
	RECTMENU_Hide(activeMenu);

	MainFreeze_SafeAdvDestroy();
	CTR_PSX_MEMORY_BARRIER();

	// The retail dispatch indexes the menu rows from zero.
	selectedOption = stringID - 1;
	CTR_PSX_KEEP_VALUE(stringID);
	switch (selectedOption)
	{
	// stringID 1: "RESTART"
	case 0:

	// stringID 4: "RETRY"
	case 3:
	{
		// get rid of pause flag
		GAME_TRACKER->gameMode1 &= ~PAUSE_1;

		if (RaceFlag_IsFullyOffScreen() == 1)
		{
			// checkered flag, begin transition on-screen
			RaceFlag_BeginTransition(1);
		}

		replayHuman = GHOST_REPLAY_HUMAN;
		CTR_PSX_KEEP_VALUE_RELAXED(replayHuman);
		// restart race
		sdata->Loading.stage = LOAD_RESTART;
		CTR_PSX_MEMORY_BARRIER();

		// if you are not showing a ghost during a race
		if (replayHuman == 0)
		{
			return;
		}

		// If the ghost playing buffer is nullptr
		if (GHOST_PLAYING == 0)
		{
			return;
		}

		// Make P2 the character that is saved in the header of the
		// ghost that you will see in the race
		data.characterIDs[1] = GHOST_PLAYING->characterID;
		return;
	}

	// stringID 2: "RESUME"
	case 1:
	{
		// unpause game
		ElimBG_Deactivate(GAME_TRACKER);

		// get rid of pause flag
		GAME_TRACKER->gameMode1 &= ~PAUSE_1;

		// unpause audio
		MainFrame_TogglePauseAudio(0);

		// play pause/unpause sound
		OtherFX_Play(1, 1);
		return;
	}

	// stringID 5: "CHANGE CHARACTER"
	case 4:
	{
		// erase ghost of previous race from RAM
		GhostTape_Destroy();

		// set level ID to main menu
		levID = MAIN_MENU_LEVEL;

		// return to character selection
		GAME_MAIN_MENU_STATE = MAIN_MENU_CHARACTERS;

		// when loading is done, add bit for "in mb"
		sdata->Loading.OnBegin.AddBitsConfig0 |= MAIN_MENU;

		// get rid of pause flag
		GAME_TRACKER->gameMode1 &= ~PAUSE_1;
		MainRaceTrack_RequestLoad(levID);
		return;
	}

	// stringID 6: "CHANGE LEVEL"
	case 5:
	{
		// erase ghost of previous race from RAM
		GhostTape_Destroy();

		// level ID of main mb
		levID = MAIN_MENU_LEVEL;

		// return to track selection
		GAME_MAIN_MENU_STATE = MAIN_MENU_TRACK_SELECT;

		// when loading is done
		// add bit for "in mb"
		sdata->Loading.OnBegin.AddBitsConfig0 |= MAIN_MENU;

		// get rid of pause flag
		GAME_TRACKER->gameMode1 &= ~PAUSE_1;
		MainRaceTrack_RequestLoad(levID);
		return;
	}

	// stringID 10: "CHANGE SETUP"
	case 9:
	{
		// set level ID to main menu
		levID = MAIN_MENU_LEVEL;

		// return to battle setup
		GAME_MAIN_MENU_STATE = MAIN_MENU_BATTLE_SETUP;

		// when loading is done
		// add bit for "in mb"
		sdata->Loading.OnBegin.AddBitsConfig0 |= MAIN_MENU;

		// get rid of pause flag
		GAME_TRACKER->gameMode1 &= ~PAUSE_1;
		MainRaceTrack_RequestLoad(levID);
		return;
	}

	// stringID 13: "EXIT TO MAP"
	case 12:
	{
		// when loading is done
		// add this bit for In Adventure Arena
		addBits0 = sdata->Loading.OnBegin.AddBitsConfig0;
		CTR_PSX_KEEP_VALUE_RELAXED(addBits0);
		addBits0 |= ADVENTURE_ARENA;
		CTR_PSX_MEMORY_BARRIER();

		// when loading is done
		// remove bits for Relic Race or Crystal Challenge
		remSource = sdata->Loading.OnBegin.RemBitsConfig0;
		CTR_PSX_KEEP_VALUE_RELAXED(remSource);
		sdata->Loading.OnBegin.AddBitsConfig0 = addBits0;
		CTR_PSX_MEMORY_BARRIER();
		remMask = RELIC_RACE | CRYSTAL_CHALLENGE;
		CTR_PSX_KEEP_VALUE_RELAXED(remMask);
		remBits0 = remSource | remMask;

		// when loading is done
		// remove bit for CTR Token Challenge
		tokenBits = sdata->Loading.OnBegin.RemBitsConfig8;
		CTR_PSX_KEEP_VALUE_RELAXED(tokenBits);

		mapTracker = GAME_TRACKER;
		CTR_PSX_KEEP_VALUE_RELAXED(mapTracker);
		tokenBits |= TOKEN_RACE;
		sdata->Loading.OnBegin.RemBitsConfig8 = tokenBits;
		gameMode = mapTracker->gameMode1;
		CTR_PSX_KEEP_VALUE_RELAXED(gameMode);
		pauseMask = ~PAUSE_1;
		CTR_PSX_KEEP_VALUE_RELAXED(pauseMask);
		sdata->Loading.OnBegin.RemBitsConfig0 = remBits0;
		CTR_PSX_MEMORY_BARRIER();
		// get rid of pause flag
		gameMode &= pauseMask;
		mapTracker->gameMode1 = gameMode;
		CTR_PSX_MEMORY_BARRIER();
		CTR_PSX_COPY_VALUE(modeForBranch, gameMode);

		// Adventure Cup returns to Gem Stone Valley.
		if ((modeForBranch & ADVENTURE_CUP) != 0)
		{
			// when loading is done remove bits for Adventure Cup, relic, and crystal challenge
			cupRemBits = remBits0 | ADVENTURE_CUP;
			CTR_PSX_KEEP_VALUE_RELAXED(cupRemBits);
			cupLevel = GEM_STONE_VALLEY;
			CTR_PSX_LOAD_WORD_AFTER(cupID, mapTracker->cup.cupID, cupLevel);
			sdata->Loading.OnBegin.RemBitsConfig0 = cupRemBits;
			CTR_PSX_MEMORY_BARRIER();
			CTR_PSX_KEEP_VALUE_RELAXED(cupID);

			// Level ID
			mapTracker->levelID = cupID + ADVENTURE_CUP_SYNTHETIC_LEVEL_ID_BASE;
			MainRaceTrack_RequestLoad(cupLevel);
			return;
		}

		// A boss race also marks the return spawn point.
		if ((s32)modeForBranch < 0)
		{
			// NOTE(aalhendi): The spawn-flag load sits between the boss mask
			// and its OR; the clear-mask store precedes the spawn-bit OR.
			// when loading is done remove bit for Boss Race, relic, and crystal challenge
			bossMask = ADVENTURE_BOSS;
			CTR_PSX_KEEP_VALUE_RELAXED(bossMask);
			CTR_PSX_LOAD_WORD_AFTER(bossAddBits8, sdata->Loading.OnBegin.AddBitsConfig8, bossMask);
			CTR_PSX_DEPEND_VALUE(bossMask, bossAddBits8);
			bossRemBits = remBits0 | bossMask;
			CTR_PSX_KEEP_VALUE_RELAXED(bossRemBits);
			sdata->Loading.OnBegin.RemBitsConfig0 = bossRemBits;
			CTR_PSX_MEMORY_BARRIER();

			// When loading is done add bit to spawn driver near boss door
			bossAddBits8 |= SPAWN_AT_BOSS;
			sdata->Loading.OnBegin.AddBitsConfig8 = bossAddBits8;
		}

		// Return to the level you were in previously.
		MainRaceTrack_RequestLoad(CTR_ReadS16LE(&mapTracker->prevLEV));
		return;
	}
	default:
	{
		return;
	}
	}
}

struct RectMenu *MainFreeze_GetMenuPtr(void)
{
	struct GameTracker *gGT = GAME_TRACKER;
	u32 gameMode = gGT->gameMode1;

	if ((gameMode & ADVENTURE_ARENA) != 0)
	{
		struct MenuRow *rows = data.rowsAdvHub;
		struct RectMenu *menuResult;
		u32 menuPage;
		s16 hintString;
		// NOTE(aalhendi): Retail branches on the low half of the mask result.
		s16 boolGoodGuy = (s16)VehPickupItem_MaskBoolGoodGuy(gGT->drivers[0]);

		hintString = LNG_UKA_UKA_HINTS;
		if (boolGoodGuy != 0)
		{
			hintString = LNG_AKU_AKU_HINTS;
		}

		rows[1].stringIndex = hintString;
		// NOTE(aalhendi): Materialize the menu address independently of the row
		// pointer; the low-offset add fills the retail return branch delay slot.
		CTR_PSX_LOAD_SYMBOL_PAGE(menuPage, "data+14824");
		CTR_PSX_ADD_PAGE_OFFSET(menuResult, menuPage, 0x4388, &data.menuAdvHub);
		return menuResult;
	}

	if ((gameMode & ADVENTURE_MODE) != 0)
	{
		if ((gameMode & ADVENTURE_CUP) != 0)
		{
			return &data.menuAdvCup;
		}

		return &data.menuAdvRace;
	}

	if ((gameMode & BATTLE_MODE) != 0)
	{
		return &data.menuBattle;
	}

	if ((gGT->gameMode2 & CUP_ANY_KIND) != 0)
	{
		return &data.menuArcadeCup;
	}

	return &data.menuArcadeRace;
}

void MainFreeze_IfPressStart(void)
{
	struct GameTracker *gGT;
	u32 gameMode1;
	struct RectMenu *menu;
	struct RectMenu *activeMenu;
	u32 absolutePage;
	s32 loadInProgress;

	if (RaceFlag_IsFullyOnScreen())
	{
		return;
	}

	gGT = GAME_TRACKER;

	if ((gGT->renderFlags & RENDER_FLAG_CHECKERED_FLAG) != 0)
	{
		return;
	}

	if (sdata->AkuAkuHintState != 0)
	{
		return;
	}

	// NOTE(aalhendi): These two fields use absolute pages in retail, unlike
	// the nearby tracker and hint fields accessed relative to $gp.
	CTR_PSX_LOAD_SYMBOL_PAGE(absolutePage, "sdata_static+2460");
	CTR_PSX_LOAD_WORD_FROM_PAGE(activeMenu, absolutePage, "sdata_static+2460", sdata->ptrActiveMenu);
	if (activeMenu != NULL)
	{
		return;
	}

	gameMode1 = gGT->gameMode1;

	if ((gameMode1 & (END_OF_RACE | PAUSE_ALL)) != 0)
	{
		return;
	}

	if (gGT->levelID == MAIN_MENU_LEVEL)
	{
		return;
	}

	if ((gameMode1 & GAME_CUTSCENE) != 0)
	{
		return;
	}

	if (gGT->boolDemoMode != 0)
	{
		return;
	}

	if ((u32)(gGT->levelID - OXIDE_ENDING) < 2)
	{
		return;
	}

	CTR_PSX_LOAD_SYMBOL_PAGE(absolutePage, "sdata_static+312");
	CTR_PSX_LOAD_WORD_FROM_PAGE(loadInProgress, absolutePage, "sdata_static+312", sdata->load_inProgress);
	if (loadInProgress != 0)
	{
		return;
	}

	if ((gGT->gameMode2 & VEH_FREEZE_PODIUM) != 0)
	{
		return;
	}

	gGT->gameMode1 = gameMode1 | PAUSE_1;

	menu = MainFreeze_GetMenuPtr();
	menu->rowSelected = 0;

	RECTMENU_Show(menu);
	MainFrame_TogglePauseAudio(1);
	OtherFX_Play(1, 1);
	ElimBG_Activate(GAME_TRACKER);
}
