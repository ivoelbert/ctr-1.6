// Goes to spots on a map (P lines from a bug report) and screenshots each, with what the game
// says there; optionally drives on from it.
//
//   node tools/e2e/spot.mjs MAP OUTDIR SPOT...
//
//   SPOT     a P line ("bayview_free 15303,958,8413,2505 level 0 mode 20000") or its "x,y,z,angle",
//            in the world's coordinates (ctr.goto)
//   DRIVE=MS hold the gas that long after the shot, then report speed, item, fruit and where
//   QUERY    more of the page's query (QUERY='&depth=0')
//   BASE_URL the server (default http://localhost:8642)
//
// Prints a line per spot (its shot OUTDIR/NNN.png, frames a second, the world's tile) and
// exits 1 when the map doesn't start.
import fs from 'node:fs';
import { launch, sleep } from './lib.mjs';

const [map, outdir, ...args] = process.argv.slice(2);
if (!map || !outdir || !args.length) {
  console.error('usage: node tools/e2e/spot.mjs MAP OUTDIR SPOT...');
  process.exit(2);
}
// a P line's numbers, or the numbers given
const spots = args.join(' ').match(/-?\d+,-?\d+,-?\d+(,-?\d+)?/g).map((s) => s.split(',').map(Number));
const drive = Number(process.env.DRIVE ?? 0);
fs.mkdirSync(outdir, { recursive: true });

const { browser, page } = await launch({ query: `?map=${map}${process.env.QUERY ?? ''}`, width: 960, height: 720, log: false });
try {
  await page.waitForFunction(() => window.ctr && Module._NativeWeb_GetState && ctr.state().eventTime > 0 && (ctr.state().gameMode1 & 0x40) === 0,
    { timeout: 300000, polling: 250 });
} catch (e) {
  console.error(`${map} didn't start: ${e.message}`);
  await browser.close();
  process.exit(1);
}
await page.evaluate(() => ctr.turbo(false));
let n = 0;
for (const [x, y, z, angle = 0] of spots) {
  const reached = await page.evaluate((x, y, z, a) => ctr.goto(x, y, z, a), x, y, z, angle);
  await sleep(1200);
  const t0 = await page.evaluate(() => ctr.state().vblank);
  await sleep(1000);
  const s = await page.evaluate(() => ({ s: ctr.state(), where: ctr.where(), world: ctr.world() }));
  const shot = `${outdir}/${String(n++).padStart(3, '0')}.png`;
  await page.screenshot({ path: shot });
  const fps = s.s.vblank - t0;
  const tile = s.world.active ? ` tile ${s.world.tile} (${s.world.loaded}/${s.world.tiles} loaded)` : '';
  console.log(`${shot}: ${reached ? '' : 'NOT REACHED '}${s.where}, ${fps} fps${tile}`);
  if (drive > 0) {
    const k0 = s.s.kart;
    let top = 0;
    await page.evaluate(() => ctr.hold('cross'));
    for (let t = 0; t < drive; t += 100) {
      await sleep(100);
      top = Math.max(top, await page.evaluate(() => ctr.state().kart.speedApprox));
    }
    await page.evaluate(() => ctr.release());
    await sleep(300);
    const k1 = await page.evaluate(() => ({ k: ctr.state().kart, where: ctr.where() }));
    console.log(`  drove ${drive} ms: top speed ${top}, item ${k0.item} -> ${k1.k.item}, fruit ${k0.wumpa} -> ${k1.k.wumpa}, now ${k1.where}`);
  }
}
await browser.close();
