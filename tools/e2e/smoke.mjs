// Boots the game and screenshots it every few seconds: node tools/e2e/smoke.mjs [seconds] [query]
//   OUT=dir   HOLD=cross,right   (pad 1 buttons held once the race clock runs)
//   PADS=n    n fake gamepads (lib.mjs); PAD_GAS=1 holds A (cross) on each
import { launch, sleep } from './lib.mjs';
const seconds = Number(process.argv[2] || 20);
const query = process.argv[3] || '';
const outDir = process.env.OUT || '/tmp';
const hold = (process.env.HOLD || '').split(',').filter(Boolean);
const pads = Number(process.env.PADS || 0);
const { browser, page } = await launch({ query, pads });
if (pads && process.env.PAD_GAS) {
  await page.evaluate((n) => setTimeout(() => { for (let i = 0; i < n; i++) window.__press(i, 0); }, 6000), pads);
}
let held = false;
for (let t = 0; t < seconds; t += 5) {
  await sleep(5000);
  if (hold.length && !held) {
    held = await page.evaluate((hold) => {
      if (!window.ctr || !Module._NativeWeb_GetState || ctr.state().eventTime <= 0) return false;
      ctr.hold(...hold);
      return true;
    }, hold);
  }
  await page.screenshot({ path: `${outDir}/ctr-smoke-${String(t + 5).padStart(3, '0')}.png` });
}
await browser.close();
