// Boots the game and screenshots it every few seconds: node tools/e2e/smoke.mjs [seconds] [query]
import { launch, sleep } from './lib.mjs';
const seconds = Number(process.argv[2] || 20);
const query = process.argv[3] || '';
const outDir = process.env.OUT || '/tmp';
const { browser, page } = await launch({ query });
for (let t = 0; t < seconds; t += 5) {
  await sleep(5000);
  await page.screenshot({ path: `${outDir}/ctr-smoke-${t + 5}.png` });
}
await browser.close();
