// Teleports the kart to each Dust 2 landmark (build/lev/dust2.json) and screenshots it.
//   node tools/e2e/tour.mjs [names...]      OUT=build/shots/tour
import fs from 'node:fs';
import { launch, sleep } from './lib.mjs';

const meta = JSON.parse(fs.readFileSync('build/lev/dust2.json', 'utf8'));
const names = process.argv.slice(2).length ? process.argv.slice(2) : Object.keys(meta.landmarks);
const outDir = process.env.OUT || 'build/shots/tour';
fs.mkdirSync(outDir, { recursive: true });

const { browser, page } = await launch({ query: '?level=0&mode=0&dust2=1', log: !!process.env.LOG });
await page.waitForFunction(() => window.ctr && ctr.state().eventTime > 0, { timeout: 120000, polling: 250 });
for (const name of names) {
  const [x, y, z, angle] = meta.landmarks[name];
  await page.evaluate((x, y, z, a) => ctr.teleport(x, y, z, a), x, (y ?? 0) + 80, z, angle);
  await sleep(1500);
  const s = await page.evaluate(() => ctr.state());
  console.log(name, JSON.stringify({ x: s.kart.x | 0, y: s.kart.y | 0, z: s.kart.z | 0, quad: s.kart.quad, state: s.kart.state }));
  await page.screenshot({ path: `${outDir}/${name}.png` });
}
await browser.close();
