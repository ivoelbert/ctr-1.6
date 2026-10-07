// Screenshots player 1 at a list of spots in one session (free drive), for checking the level's
// looks: node tools/e2e/spots.mjs OUT_DIR [spot names...]      QUERY=... to change the level
// Spots are CTR positions (x, y, z) and a yaw (4096 = full turn, 0 = +z): a few by hand, the rest
// the track builder's landmarks.
import fs from 'node:fs';
import { launch, sleep } from './lib.mjs';

export const SPOTS = {
  'long-doors-outside': [3840, 100, 5200, 2048],
  'long-doors-inside': [3880, 100, 2600, 0],
  'long-doors-east': [3700, 100, 3500, 1024],
  'long-doors-west': [4000, 100, 3500, 3072],
  'long-doors-threshold': [3840, 100, 3700, 2048],
  'passage-crate': [3840, 100, 3000, 2048],
  'short-a-stairs': [2680, 150, -1700, 2048],
  'short-a-stairs-side': [3200, 150, -2000, 2560],
  'long-a': [7000, 200, -2000, 2048],
  'long-a-top': [6900, 150, -3900, 2048],
  'mid-doors': [-440, -400, -1000, 2048],
};
// and the track builder's landmarks (build/lev/dust2.json): on a floor, facing along the map
const meta = JSON.parse(fs.readFileSync('build/lev/dust2.json', 'utf8'));
for (const [name, [x, y, z, yaw]] of Object.entries(meta.landmarks)) {
  if (y !== null) SPOTS[name.replace(/_/g, '-')] = [x, y + 100, z, yaw];
}

const outDir = process.argv[2] ?? 'build/shots/spots';
const names = process.argv.slice(3).length ? process.argv.slice(3) : Object.keys(SPOTS);
fs.mkdirSync(outDir, { recursive: true });
const { browser, page } = await launch({ query: process.env.QUERY ?? '?dust2=free&level=0&mode=0', log: false });
await page.waitForFunction(() => window.ctr && Module._NativeWeb_GetState && ctr.state().eventTime > 0 &&
  (ctr.state().gameMode1 & 0x40) === 0, { timeout: 180000, polling: 250 });
for (const [i, name] of names.entries()) {
  const [x, y, z, yaw] = SPOTS[name];
  for (let k = 0; k < 3; k++) {
    await page.evaluate((x, y, z, a) => ctr.teleport(x, y, z, a), x, y, z, yaw);
    await sleep(500);
  }
  await sleep(Number(process.env.WAIT ?? 1200));
  await page.screenshot({ path: `${outDir}/${String(i).padStart(2, '0')}-${name}.png` });
}
await browser.close();
