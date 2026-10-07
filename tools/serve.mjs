// Static server for the web build: build/web at /, the disc image at /game-data/ctr-u.bin,
// generated levels at /lev/ (build/lev). Listens on localhost only: it serves your disc.
//   node tools/serve.mjs [port]      CTR_DISC=/path/to/ctr.bin overrides the disc path
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PORT = Number(process.argv[2] || process.env.PORT || 8642);
const HOST = process.env.HOST || '127.0.0.1';
const DISC = process.env.CTR_DISC ||
  path.join(process.env.HOME, 'Documents/CTRDUST2/CTR - Crash Team Racing/CTR - Crash Team Racing.bin');

// WEB_DIR / LEV_DIR serve another build (an experiment) beside the playable one
const MOUNTS = [
  ['/game-data/ctr-u.bin', DISC],
  ['/lev/', path.resolve(process.env.LEV_DIR || path.join(ROOT, 'build/lev'))],
  ['/', path.resolve(process.env.WEB_DIR || path.join(ROOT, 'build/web'))],
];
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript',
  '.wasm': 'application/wasm', '.json': 'application/json', '.png': 'image/png', '.jpg': 'image/jpeg' };

function resolve(url) {
  for (const [prefix, target] of MOUNTS) {
    if (!prefix.endsWith('/')) {
      if (url === prefix) return target;
      continue;
    }
    if (!url.startsWith(prefix)) continue;
    const file = path.resolve(target, '.' + path.posix.normalize('/' + url.slice(prefix.length)));
    if (file !== target && !file.startsWith(target + path.sep)) return null;
    return file === target ? path.join(target, 'index.html') : file;
  }
  return null;
}

http.createServer((req, res) => {
  let url;
  try { url = decodeURIComponent(new URL(req.url, 'http://x').pathname); } catch { url = null; }
  let file = url && resolve(url);
  if (file && fs.existsSync(file) && fs.statSync(file).isDirectory()) file = path.join(file, 'index.html');
  if (!file || !fs.existsSync(file)) {
    res.writeHead(404, { 'X-Ctr-Dust2': '1' }); res.end('not found'); return;
  }
  const stat = fs.statSync(file);
  res.writeHead(200, {
    'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream',
    'Content-Length': stat.size,
    'Cache-Control': 'no-store',
    'X-Ctr-Dust2': '1',
  });
  if (req.method === 'HEAD') { res.end(); return; }
  fs.createReadStream(file).pipe(res);
}).listen(PORT, HOST, () => console.log(`http://localhost:${PORT}/`));
