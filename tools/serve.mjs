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
  // the track editor's page code, straight from the source (no build step)
  ['/editor/', path.join(ROOT, 'web/editor')],
  ['/', path.resolve(process.env.WEB_DIR || path.join(ROOT, 'build/web'))],
];
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript',
  '.wasm': 'application/wasm', '.json': 'application/json', '.png': 'image/png', '.jpg': 'image/jpeg',
  '.css': 'text/css', '.svg': 'image/svg+xml' };

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

// The track editor's tracks (web/editor/): GET /tracks/ lists them, GET and PUT
// /tracks/NAME.json read and save one, in TRACKS_DIR (default: tracks/ by this repo).
const TRACKS = path.resolve(process.env.TRACKS_DIR || path.join(ROOT, 'tracks'));
const TRACK_NAME = /^[A-Za-z0-9 _.-]{1,64}$/;

function tracks(req, res, url) {
  const send = (code, body, type = 'application/json') => {
    res.writeHead(code, { 'Content-Type': type, 'Cache-Control': 'no-store', 'X-Ctr-Dust2': '1' });
    res.end(typeof body === 'string' ? body : JSON.stringify(body));
  };
  const rest = url.slice('/tracks/'.length);
  if (rest === '') {
    if (req.method !== 'GET') return send(405, { error: 'GET only' });
    let list = [];
    try {
      list = fs.readdirSync(TRACKS).filter((f) => f.endsWith('.json')).map((f) => {
        const st = fs.statSync(path.join(TRACKS, f));
        return { name: f.slice(0, -5), mtime: st.mtimeMs, size: st.size };
      }).sort((a, b) => b.mtime - a.mtime);
    } catch { /* none yet */ }
    return send(200, list);
  }
  if (!rest.endsWith('.json') || !TRACK_NAME.test(rest.slice(0, -5))) return send(400, { error: 'bad track name' });
  const file = path.join(TRACKS, rest);
  if (req.method === 'GET') {
    if (!fs.existsSync(file)) return send(404, { error: 'no such track' });
    return send(200, fs.readFileSync(file, 'utf8'));
  }
  if (req.method === 'PUT') {
    const chunks = [];
    let size = 0;
    req.on('data', (c) => { size += c.length; if (size <= 8 << 20) chunks.push(c); });
    req.on('end', () => {
      if (size > 8 << 20) return send(413, { error: 'too big' });
      const text = Buffer.concat(chunks).toString('utf8');
      try { JSON.parse(text); } catch { return send(400, { error: 'not JSON' }); }
      fs.mkdirSync(TRACKS, { recursive: true });
      fs.writeFileSync(file + '.tmp', text);
      fs.renameSync(file + '.tmp', file);
      send(200, { ok: true });
    });
    return undefined;
  }
  if (req.method === 'DELETE') {
    if (fs.existsSync(file)) fs.renameSync(file, file + '.deleted');
    return send(200, { ok: true });
  }
  return send(405, { error: 'GET, PUT or DELETE' });
}

http.createServer((req, res) => {
  let url;
  try { url = decodeURIComponent(new URL(req.url, 'http://x').pathname); } catch { url = null; }
  if (url && url.startsWith('/tracks/')) { tracks(req, res, url); return; }
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
