// Boots a level and prints window.ctr.state() a few times: node tools/e2e/probe.mjs "query" [seconds]
import { launch, sleep } from './lib.mjs';
const query = process.argv[2] ?? '';
const seconds = Number(process.argv[3] ?? 20);
const { browser, page } = await launch({ query: `?${query}`, log: !!process.env.LOG });
await page.waitForFunction(() => window.ctr && Module._NativeWeb_GetState, { timeout: 120000 });
if (process.env.HOLD) await page.evaluate((h) => ctr.hold(...h.split(',')), process.env.HOLD);
for (let t = 0; t < seconds; t += 2) {
  await sleep(2000);
  console.log(JSON.stringify(await page.evaluate(() => ctr.state())));
}
if (process.env.SHOT) await page.screenshot({ path: process.env.SHOT });
await browser.close();
