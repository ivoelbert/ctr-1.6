"""Need for Speed: Underground 2 (PS2, NTSC-U) world data: Bayview, read from your disc.

disc      the game's files on the disc image (ZDIR.BIN / ZZDATA*.BIN)
bun       EA's chunk files (.BUN), the city's streaming sections (TRACKS\\L4RA.BUN)
mesh      the PS2 meshes: VIF packets for the vector unit, unpacked into triangle strips
gs        the GS's local memory layouts, to read textures as the console stores them
textures  texture packs: palettized 4- and 8-bit images
world     the city put together: each section's scenery instances, their meshes and textures
"""
