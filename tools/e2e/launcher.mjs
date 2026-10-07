// Screenshots the launcher, then starts a mode from it: node tools/e2e/launcher.mjs [mode] [seconds]
import { launch, sleep } from './lib.mjs';
const mode = process.argv[2] ?? 'race';
const seconds = Number(process.argv[3] ?? 20);
const outDir = process.env.OUT || 'build/shots/launcher';
const fs = await import('node:fs');
fs.mkdirSync(outDir, { recursive: true });
const { browser, page } = await launch({ query: '', width: 1100, height: 760 });
await sleep(1500);
await page.screenshot({ path: `${outDir}/launcher.png` });
await page.click(`.mode[data-mode="${mode}"]`);
await page.click('#go');
for (let t = 0; t < seconds; t += 4) {
  await sleep(4000);
  await page.screenshot({ path: `${outDir}/${mode}-${String(t + 4).padStart(2, '0')}.png` });
}
await browser.close();
