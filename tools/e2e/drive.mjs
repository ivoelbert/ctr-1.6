// Boots into a Time Trial and holds the gas, screenshotting as it goes:
//   node tools/e2e/drive.mjs [level] [seconds] [extra query]
//   OUT=build/shots/x  where the screenshots go
import { launch, sleep } from './lib.mjs';
const level = Number(process.argv[2] ?? 3);
const seconds = Number(process.argv[3] ?? 25);
const extra = process.argv[4] ? `&${process.argv[4]}` : '';
const outDir = process.env.OUT || 'build/shots';
const { browser, page } = await launch({ query: `?level=${level}&mode=0${extra}` });
await sleep(4000);
await page.click('canvas');
await page.keyboard.down('KeyC'); // cross: gas
for (let t = 0; t < seconds; t += 3) {
  await sleep(3000);
  if (t === 9) await page.keyboard.down('ArrowLeft');
  if (t === 12) await page.keyboard.up('ArrowLeft');
  await page.screenshot({ path: `${outDir}/drive-${level}-${String(t + 3).padStart(2, '0')}.png` });
}
await browser.close();
