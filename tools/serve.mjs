// Static server for the web build: build/web at /, the disc image at /game-data/ctr-u.bin,
// generated levels at /lev/ (build/lev).
//   node tools/serve.mjs [port]      CTR_DISC=/path/to/ctr.bin overrides the disc path
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PORT = Number(process.argv[2] || process.env.PORT || 8642);
const DISC = process.env.CTR_DISC ||
  path.join(process.env.HOME, 'Documents/CTRDUST2/CTR - Crash Team Racing/CTR - Crash Team Racing.bin');

const MOUNTS = [
  ['/game-data/ctr-u.bin', DISC],
  ['/lev/', path.join(ROOT, 'build/lev') + '/'],
  ['/', path.join(ROOT, 'build/web') + '/'],
];
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript',
  '.wasm': 'application/wasm', '.json': 'application/json', '.png': 'image/png' };

http.createServer((req, res) => {
  const url = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  let file = null;
  for (const [prefix, target] of MOUNTS) {
    if (url === prefix || (prefix.endsWith('/') && url.startsWith(prefix))) {
      file = prefix.endsWith('/') ? path.join(target, url.slice(prefix.length) || 'index.html') : target;
      break;
    }
  }
  if (!file || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    res.writeHead(404); res.end('not found'); return;
  }
  const stat = fs.statSync(file);
  res.writeHead(200, {
    'Content-Type': TYPES[path.extname(file)] || 'application/octet-stream',
    'Content-Length': stat.size,
    'Cache-Control': 'no-store',
  });
  fs.createReadStream(file).pipe(res);
}).listen(PORT, () => console.log(`http://localhost:${PORT}/`));
