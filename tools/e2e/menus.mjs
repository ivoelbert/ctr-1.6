// Through CTR's own menus to a track, with both Dust 2 tracks in (the launcher's CTR menus mode):
//   node tools/e2e/menus.mjs        OUT=dir   PRESSES="down cross cross down ..." (after the title)
// By default: Arcade, single race, 1P, easy, Crash, down the track list to Dust 2 Tunnels (Dragon
// Mines' slot), and into the race.
// Presses go through the pad hook, a few frames each, timed off the VBlank clock.
import fs from 'node:fs';
import { launch, sleep } from './lib.mjs';

const outDir = process.env.OUT || 'build/shots/menus';
fs.mkdirSync(outDir, { recursive: true });
const { browser, page } = await launch({ query: '?dust2=menus', log: false });
await page.waitForFunction(() => window.ctr && Module._NativeWeb_GetState, { timeout: 120000 });

// one press: hold for 3 frames (6 VBlanks), then wait
async function press(button, waitVBlanks = 40) {
  await page.evaluate((button, waitVBlanks) => new Promise((done) => {
    let n = 0;
    ctr.hold(button);
    Module.ctrOnVBlank = () => {
      n++;
      if (n === 6) ctr.release();
      if (n >= 6 + waitVBlanks) { Module.ctrOnVBlank = null; done(); }
    };
  }), button, waitVBlanks);
}
const shot = (name) => page.screenshot({ path: `${outDir}/${name}.png` });

// the intro runs until the main menu's level is up (MAIN_MENU)
await page.waitForFunction(() => (ctr.state().gameMode1 & 0x2000) !== 0 && (ctr.state().gameMode1 & 0x40000000) === 0,
  { timeout: 180000, polling: 250 });
// the title animation (Crash, the trophy) plays before the menu takes presses
await sleep(Number(process.env.WAIT ?? 10000));
await shot('01-main');
// main menu: Adventure, Time Trial, Arcade, ... -> Arcade, single race, one player, then the
// character select (Crash), then the track list, down to Dingo Canyon's slot
const presses = (process.env.PRESSES ?? 'down down cross cross cross cross cross down down down down down down down down down').split(' ');
for (const [i, p] of presses.entries()) {
  await press(p, 60);
  await shot(`03-${String(i).padStart(2, '0')}-${p}`);
}
// then into the race on the track the list stopped at
await press('cross', 120);
await shot('04-picked');
await press('cross', 120);
await sleep(Number(process.env.RACE_WAIT ?? 25000));
await shot('05-race');
console.log(JSON.stringify(await page.evaluate(() => { const s = ctr.state(); return { level: s.level, eventTime: s.eventTime, kart: s.kart && [s.kart.x | 0, s.kart.z | 0] }; })));
await browser.close();
