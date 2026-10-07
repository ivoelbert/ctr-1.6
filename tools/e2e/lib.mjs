// Headless Chrome for the CTR web build (GPU via Metal on a Mac: real 60 Hz frames).
import puppeteer from 'puppeteer-core';

export const BASE_URL = process.env.BASE_URL ?? 'http://localhost:8642';
const CHROME = process.env.CHROME ??
  (process.platform === 'darwin'
    ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    : '/usr/bin/google-chrome');
const RENDER_ARGS = process.platform === 'darwin' ? ['--use-angle=metal'] : ['--use-angle=swiftshader'];

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Fake gamepads (the Gamepad API, standard mapping) for split-screen tests: window.__pads[i]
// has axes and buttons to set; they connect a few seconds after load, once SDL listens.
function fakeGamepads(count) {
  const pads = [];
  for (let i = 0; i < count; i++) {
    pads.push({
      id: `Fake pad ${i} (STANDARD GAMEPAD Vendor: 045e Product: 028e)`, index: i, connected: true,
      mapping: 'standard', timestamp: 0, axes: [0, 0, 0, 0],
      buttons: Array.from({ length: 17 }, () => ({ pressed: false, touched: false, value: 0 })),
    });
  }
  window.__pads = pads;
  navigator.getGamepads = () => [0, 1, 2, 3].map((i) => (window.__padsLive && pads[i]) || null);
  window.__press = (i, button, on = true) => {
    pads[i].buttons[button] = { pressed: on, touched: on, value: on ? 1 : 0 };
    pads[i].timestamp++;
  };
  window.addEventListener('load', () => setTimeout(() => {
    window.__padsLive = true;
    for (const pad of pads) {
      const e = new Event('gamepadconnected');
      e.gamepad = pad;
      window.dispatchEvent(e);
    }
  }, 4000));
}

export async function launch({ query = '', width = 960, height = 720, log = true, pads = 0 } = {}) {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: [...RENDER_ARGS, '--autoplay-policy=no-user-gesture-required', '--enable-unsafe-webgpu'],
    defaultViewport: { width, height },
    protocolTimeout: 600000,
  });
  const page = await browser.newPage();
  if (pads) await page.evaluateOnNewDocument(fakeGamepads, pads);
  const lines = [];
  page.on('console', (m) => { const t = m.text(); lines.push(t); if (log) console.log('[page]', t); });
  page.on('pageerror', (e) => {
    lines.push('PAGEERROR ' + e.message);
    console.log('[pageerror]', e.stack || e.message);
    if (process.env.KEEP_GOING !== '1') { browser.close().finally(() => process.exit(2)); }
  });
  await page.goto(`${BASE_URL}/${query}`, { waitUntil: 'load' });
  return { browser, page, lines };
}
