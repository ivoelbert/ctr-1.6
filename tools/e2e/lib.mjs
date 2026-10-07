// Headless Chrome for the CTR web build (GPU via Metal on a Mac: real 60 Hz frames).
import puppeteer from 'puppeteer-core';

export const BASE_URL = process.env.BASE_URL ?? 'http://localhost:8642';
const CHROME = process.env.CHROME ??
  (process.platform === 'darwin'
    ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    : '/usr/bin/google-chrome');
const RENDER_ARGS = process.platform === 'darwin' ? ['--use-angle=metal'] : ['--use-angle=swiftshader'];

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function launch({ query = '', width = 960, height = 720, log = true } = {}) {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: [...RENDER_ARGS, '--autoplay-policy=no-user-gesture-required', '--enable-unsafe-webgpu'],
    defaultViewport: { width, height },
    protocolTimeout: 600000,
  });
  const page = await browser.newPage();
  const lines = [];
  page.on('console', (m) => { const t = m.text(); lines.push(t); if (log) console.log('[page]', t); });
  page.on('pageerror', (e) => { lines.push('PAGEERROR ' + e.message); console.log('[pageerror]', e.message); });
  await page.goto(`${BASE_URL}/${query}`, { waitUntil: 'load' });
  return { browser, page, lines };
}
