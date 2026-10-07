// Screenshots the game from a kart placed at a Hammer position, facing a compass heading
// (0 = north, 90 = east).
//   node tools/e2e/view.mjs OUT.png HX HY HEADING_DEG [HZ]
import fs from 'node:fs';
import { launch, sleep } from './lib.mjs';

const [out, hx, hy, deg, hz] = process.argv.slice(2);
const meta = JSON.parse(fs.readFileSync('build/lev/dust2.json', 'utf8'));
const S = meta.scale;
const [CX, CY] = meta.center;
const x = (Number(hx) - CX) * S;
const z = -(Number(hy) - CY) * S;
const y = Number(hz ?? 100) * S + 80;
const angle = (Math.round(2048 - (Number(deg) * 4096) / 360) % 4096 + 4096) % 4096;
const { browser, page } = await launch({ query: '?level=0&mode=0&dust2=1', log: false });
await page.waitForFunction(() => window.ctr && ctr.state().eventTime > 0, { timeout: 120000, polling: 250 });
await page.evaluate((x, y, z, a) => ctr.teleport(x, y, z, a), x, y, z, angle);
await sleep(1500);
await page.screenshot({ path: out });
console.log(JSON.stringify((await page.evaluate(() => ctr.state())).kart));
await browser.close();
