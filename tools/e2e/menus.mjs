// Through CTR's own menus to the Arcade track select: node tools/e2e/menus.mjs
import { launch, sleep } from './lib.mjs';
const outDir = process.env.OUT || 'build/shots/menus';
const fs = await import('node:fs');
fs.mkdirSync(outDir, { recursive: true });
const { browser, page } = await launch({ query: '?dust2=1', log: false });
await page.waitForFunction(() => window.ctr, { timeout: 120000 });
const press = async (key, wait = 700) => { await page.keyboard.down(key); await sleep(120); await page.keyboard.up(key); await sleep(wait); };
await sleep(Number(process.env.WAIT ?? 30000));
await page.click('canvas');
await press('Enter', 2500);           // skip the intro
await page.screenshot({ path: `${outDir}/01.png` });
await press('Enter', 2500);           // press start on the title
await page.screenshot({ path: `${outDir}/02.png` });
// Time Trial, Crash, then down the track list to Dingo Canyon's slot (Dust 2)
const keys = (process.env.KEYS ?? 'ArrowDown KeyC KeyC ArrowDown ArrowDown ArrowDown ArrowDown ArrowDown ArrowDown ArrowDown').split(' ');
for (const [i, k] of keys.entries()) {
  await press(k, 900);
}
await page.screenshot({ path: `${outDir}/03-trackselect.png` });
await press('KeyC', 1500);
await page.screenshot({ path: `${outDir}/04.png` });
await press('KeyC', 1500);
await sleep(15000);
await page.screenshot({ path: `${outDir}/05-race.png` });
await browser.close();
