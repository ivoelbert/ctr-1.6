// Puts player 1's kart somewhere (CTR units, yaw 0..4095) once the race runs and screenshots it.
//   node tools/e2e/place.mjs "QUERY" OUT.png X Y Z YAW     PADS=n (fake gamepads, lib.mjs)
import { launch, sleep } from './lib.mjs';

const [query, out, x, y, z, yaw] = process.argv.slice(2);
const pads = Number(process.env.PADS || 0);
const { browser, page } = await launch({ query, pads, log: false });
// once the race runs: the clock going and the start (fly-in, countdown) over
await page.waitForFunction(() => window.ctr && Module._NativeWeb_GetState && ctr.state().eventTime > 0 &&
  (ctr.state().gameMode1 & 0x40) === 0, { timeout: 180000, polling: 250 });
for (let i = 0; i < 3; i++) {
  await page.evaluate((x, y, z, a) => ctr.teleport(x, y, z, a), Number(x), Number(y), Number(z), Number(yaw));
  await sleep(700);
}
await sleep(Number(process.env.WAIT || 1500));
await page.screenshot({ path: out });
console.log(JSON.stringify((await page.evaluate(() => { const s = ctr.state(); return { kart: s.kart, camera: s.camera }; }))));
await browser.close();
