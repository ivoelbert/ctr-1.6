// Screenshots the launcher, then drives a map from it: node tools/e2e/launcher.mjs [map] [players] [seconds]
//   OUT=dir (build/shots/launcher)
import fs from 'node:fs';
import { launch, sleep } from './lib.mjs';
const map = process.argv[2] ?? 'dust2';
const players = process.argv[3] ?? '1';
const seconds = Number(process.argv[4] ?? 20);
const outDir = process.env.OUT || 'build/shots/launcher';
fs.mkdirSync(outDir, { recursive: true });
const { browser, page } = await launch({ query: '', width: 1100, height: 760 });
await page.waitForFunction(() => document.getElementById('map').options.length > 0, { timeout: 30000 });
await page.screenshot({ path: `${outDir}/launcher.png` });
await page.select('#map', map);
await page.select('#players', players);
await page.click('#go');
for (let t = 0; t < seconds; t += 4) {
  await sleep(4000);
  await page.screenshot({ path: `${outDir}/${map}-${String(t + 4).padStart(2, '0')}.png` });
}
console.log(await page.evaluate(() => (window.ctr ? ctr.where() : 'no game')));
await browser.close();
