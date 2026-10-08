// Screenshots player 1 at places on a map, in one free-drive session, for checking its looks:
//   node tools/e2e/shots.mjs MAP OUT_DIR [name=x,y,z,yaw ...]
// Places are CTR positions (x, y a little over the floor, z) and a yaw (4096 = full turn, 0 =
// +z); by default the map's landmarks (build/lev/MAP.json).
import fs from 'node:fs';
import { launch, sleep } from './lib.mjs';
const [map, outDir, ...specs] = process.argv.slice(2);
const spots = specs.length ? specs.map((s) => { const [name, pos] = s.split('='); return [name, pos.split(',').map(Number)]; })
  : Object.entries(JSON.parse(fs.readFileSync(`build/lev/${map}.json`, 'utf8')).landmarks)
    .filter(([, [, y]]) => y !== null).map(([name, [x, y, z, yaw]]) => [name, [x, y + 100, z, yaw]]);
fs.mkdirSync(outDir, { recursive: true });
const { browser, page } = await launch({ query: `?map=${map}`, log: false });
await page.waitForFunction(() => window.ctr && Module._NativeWeb_GetState && ctr.state().eventTime > 0 &&
  (ctr.state().gameMode1 & 0x40) === 0, { timeout: 180000, polling: 250 });
for (const [i, [name, [x, y, z, yaw]]] of spots.entries()) {
  for (let k = 0; k < 3; k++) {
    await page.evaluate((x, y, z, a) => ctr.teleport(x, y, z, a), x, y, z, yaw);
    await sleep(400);
  }
  await sleep(Number(process.env.WAIT ?? 1200));
  await page.screenshot({ path: `${outDir}/${String(i).padStart(2, '0')}-${name}.png` });
  console.log(name, await page.evaluate(() => ctr.where()));
}
await browser.close();
process.exit(0);
