// The editor's 3D view (three.js): the field, the pieces as the game will draw them (the same
// quadblocks, compile.localQuads), a ghost of the piece being placed, the grid at the build
// height, the track's open ends, its route, and the gizmo that moves a selection freely.

import * as THREE from 'three';
import { OrbitControls } from './vendor/three/OrbitControls.js';
import { TransformControls } from './vendor/three/TransformControls.js';
import { localQuads, vertexShades, FIELD, GROUND_Y } from './compile.js';
import { BLOCK, LEVEL, signKey, signSlotsOf } from './pieces.js';
import { DEG, dot, norm, transformOf } from './geom.js';

const SUBFACES = [[0, 4, 5, 6], [4, 1, 6, 7], [5, 6, 2, 8], [6, 7, 8, 3]];

export class View {
  constructor(container, textures) {
    this.container = container;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    this.renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    this.renderer.domElement.className = 'ed-canvas';
    container.appendChild(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x6fa8dc);
    this.scene.fog = new THREE.Fog(0x9cc4e6, 30000, 90000);
    this.camera = new THREE.PerspectiveCamera(55, 1, 20, 200000);
    this.camera.position.set(6000, 7000, 9000);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    // left click is the editor's (place, select): the camera turns with the right button and
    // pans with the middle one (or shift + right)
    this.controls.mouseButtons = { LEFT: -1, MIDDLE: THREE.MOUSE.PAN, RIGHT: THREE.MOUSE.ROTATE };
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.15;
    this.controls.screenSpacePanning = false;
    this.controls.maxPolarAngle = Math.PI * 0.495;
    this.controls.minPolarAngle = 0;
    this.controls.minDistance = 300;
    this.controls.maxDistance = 80000;
    this.controls.zoomSpeed = 1.4;
    this.controls.zoomToCursor = true;     // the wheel zooms towards what's under the mouse
    this.controls.target.set(0, 0, 0);

    // the textures, as the game samples them (repeating, 256 texels)
    this.materials = new Map();
    this.textureById = new Map();
    for (const t of textures) {
      const tex = new THREE.CanvasTexture(t.canvas);
      tex.flipY = false;     // v counts down the image, as the game's atlas does
      tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
      this.textureById.set(t.id, tex);
    }

    this.ground = this.makeGround('grass');
    this.scene.add(this.ground);
    this.grid = new THREE.Group();
    this.scene.add(this.grid);
    this.buildGrid(0);
    this.pieces = new Map();        // id -> Object3D
    this.pieceGroup = new THREE.Group();
    this.scene.add(this.pieceGroup);
    this.overlay = new THREE.Group();   // open ends, route, selection boxes, the drive trail
    this.scene.add(this.overlay);
    this.ghost = null;

    // the gizmo for free moves: on a pivot the selection follows
    this.pivot = new THREE.Object3D();
    this.scene.add(this.pivot);
    this.gizmo = new TransformControls(this.camera, this.renderer.domElement);
    this.gizmo.setSize(0.9);
    this.gizmo.addEventListener('dragging-changed', (e) => { this.controls.enabled = !e.value; });
    this.scene.add(this.gizmo);

    this.raycaster = new THREE.Raycaster();
    this.clock = new THREE.Clock();
    this.resize();
    window.addEventListener('resize', () => this.resize());
    this.running = true;
    const loop = () => {
      if (!this.running) return;
      requestAnimationFrame(loop);
      if (!this.visible) return;
      this.tick?.(this.clock.getDelta());
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
    };
    this.visible = true;
    loop();
  }

  resize() {
    const w = this.container.clientWidth || window.innerWidth, h = this.container.clientHeight || window.innerHeight;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    // the bars over the view: its middle in the middle of what they leave
    const shift = ((this.insets ? this.insets[1] - this.insets[0] : 0) / 2) | 0;
    if (shift) this.camera.setViewOffset(w, h, 0, shift, w, h);
    else this.camera.clearViewOffset();
    this.camera.updateProjectionMatrix();
  }

  setInsets(top, bottom) {
    this.insets = [top, bottom];
    this.resize();
  }

  material(texId, opts = {}) {
    const key = `${texId}|${opts.ghost ? 'g' : ''}|${opts.double ? 'd' : ''}|${opts.tint || ''}`;
    let m = this.materials.get(key);
    if (!m) {
      m = new THREE.MeshBasicMaterial({
        map: this.textureById.get(texId) || this.textureById.get('white'),
        vertexColors: true,
        side: opts.double || opts.ghost ? THREE.DoubleSide : THREE.FrontSide,
        transparent: !!opts.ghost,
        opacity: opts.ghost ? 0.6 : 1,
        depthWrite: !opts.ghost,
      });
      if (opts.tint) m.color = new THREE.Color(opts.tint);
      else if (!opts.ghost) m.color.setScalar(this.light ?? 1);
      this.materials.set(key, m);
    }
    return m;
  }

  makeGround(texId) {
    const size = 2 * (FIELD + 4096);      // with the ring round the field, as the game's (compile.js)
    const geo = new THREE.PlaneGeometry(size, size, 1, 1);
    geo.rotateX(-Math.PI / 2);
    const uv = geo.attributes.uv;
    for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) * size / 1024, uv.getY(i) * size / 1024);
    const tex = this.textureById.get(texId) || this.textureById.get('grass');
    const mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ map: tex, color: new THREE.Color(0.86, 0.86, 0.86) }));
    mesh.position.y = GROUND_Y;
    mesh.userData.ground = true;
    return mesh;
  }

  // the sky's colour and the light (day 1 .. night 0.4): the game's are the track's (compile.js)
  setEnvironment(sky, light) {
    if (this.envKey === `${sky}|${light}`) return;
    this.envKey = `${sky}|${light}`;
    this.light = light;
    this.scene.background = new THREE.Color(sky);
    this.scene.fog.color = new THREE.Color(sky).lerp(new THREE.Color(0xffffff), 0.25 * light);
    for (const m of this.materials.values()) if (!m.transparent) m.color.setScalar(light);
    this.ground.material.color.setScalar(0.86 * light);
  }

  // a texture's canvas was redrawn (a sign's)
  refreshTexture(id) {
    const tex = this.textureById.get(id);
    if (tex) tex.needsUpdate = true;
  }

  setGround(on, texId) {
    this.ground.visible = on;
    const tex = this.textureById.get(texId) || this.textureById.get('grass');
    if (this.ground.material.map !== tex) {
      this.ground.material.map = tex;
      this.ground.material.needsUpdate = true;
    }
  }

  // the grid at the build height: blocks, every fourth line stronger, the field's edge
  buildGrid(y) {
    this.grid.clear();
    const n = (2 * FIELD) / BLOCK;
    const fine = [], strong = [];
    for (let i = 0; i <= n; i++) {
      const v = -FIELD + i * BLOCK;
      const arr = i % 4 === 0 ? strong : fine;
      arr.push(-FIELD, 0, v, FIELD, 0, v, v, 0, -FIELD, v, 0, FIELD);
    }
    const mk = (arr, color, opacity) => {
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(arr, 3));
      return new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color, transparent: true, opacity, depthWrite: false }));
    };
    this.grid.add(mk(fine, 0xffffff, 0.22));
    this.grid.add(mk(strong, 0xffffff, 0.45));
    const edge = [-FIELD, 0, -FIELD, FIELD, 0, -FIELD, FIELD, 0, -FIELD, FIELD, 0, FIELD, FIELD, 0, FIELD, -FIELD, 0, FIELD, -FIELD, 0, FIELD, -FIELD, 0, -FIELD];
    this.grid.add(mk(edge, 0xffd34d, 0.9));
    this.grid.position.y = y + (y === 0 ? 2 : 0);
    this.gridY = y;
  }

  // a piece's mesh (its own coordinates; the object carries its place)
  pieceObject(pc, ghost = false, tint = null) {
    const quads = localQuads(pc, this.ground.visible);
    const T = transformOf({ yaw: pc.yaw, pitch: pc.pitch, roll: pc.roll });
    const byTex = new Map();
    for (const q of quads) {
      const key = q.tex + (q.double ? '|d' : '');
      if (!byTex.has(key)) byTex.set(key, { tex: q.tex, double: q.double, pos: [], uv: [], col: [] });
      const b = byTex.get(key);
      // the game multiplies the texture by the shade as it's shown (0x80 = 1); three.js by
      // linear colours: the shade in its terms
      const shades = vertexShades(q, 1, T.dir).map((v) => Math.pow(q.kind === 'boost' ? 1.1 : v / 128, 2.2));
      for (const [a, b1, c1, d] of SUBFACES) {
        for (const tri of [[a, b1, c1], [b1, d, c1]]) {
          const p = tri.map((s) => q.pos[s]);
          const e1 = [p[1][0] - p[0][0], p[1][1] - p[0][1], p[1][2] - p[0][2]];
          const e2 = [p[2][0] - p[0][0], p[2][1] - p[0][1], p[2][2] - p[0][2]];
          const tn = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]];
          const order = dot(tn, q.n) >= 0 ? tri : [tri[0], tri[2], tri[1]];
          for (const s of order) {
            b.pos.push(q.pos[s][0], q.pos[s][1], q.pos[s][2]);
            b.uv.push(q.uv[s][0] / 256, q.uv[s][1] / 256);
            b.col.push(shades[s], shades[s], shades[s]);
          }
        }
      }
    }
    const obj = new THREE.Group();
    for (const b of byTex.values()) {
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(b.pos, 3));
      g.setAttribute('uv', new THREE.Float32BufferAttribute(b.uv, 2));
      g.setAttribute('color', new THREE.Float32BufferAttribute(b.col, 3));
      g.computeBoundingSphere();
      const mesh = new THREE.Mesh(g, this.material(b.tex, { ghost, double: b.double, tint }));
      mesh.userData.piece = pc.id;
      obj.add(mesh);
    }
    this.place(obj, pc);
    obj.userData.piece = pc.id;
    return obj;
  }

  place(obj, pc) {
    obj.position.set(pc.x || 0, pc.y || 0, pc.z || 0);
    obj.rotation.set((pc.pitch || 0) * DEG, (pc.yaw || 0) * DEG, (pc.roll || 0) * DEG, 'YXZ');
  }

  // the pieces drawn: rebuilt where they changed (sig: what their geometry depends on)
  sync(track) {
    const seen = new Set();
    const signs = signSlotsOf(track.pieces);
    for (const raw of track.pieces) {
      const pc = raw.kind === 'sign' ? { ...raw, signTex: signs.get(signKey(raw)) } : raw;
      seen.add(pc.id);
      const sig = JSON.stringify({ ...pc, x: 0, z: 0, onGround: Math.abs(pc.y || 0) < 8, ground: this.ground.visible });
      let obj = this.pieces.get(pc.id);
      if (!obj || obj.userData.sig !== sig) {
        if (obj) { this.pieceGroup.remove(obj); dispose(obj); }
        obj = this.pieceObject(pc);
        obj.userData.sig = sig;
        this.pieces.set(pc.id, obj);
        this.pieceGroup.add(obj);
      } else {
        this.place(obj, pc);
      }
    }
    for (const [id, obj] of this.pieces) {
      if (!seen.has(id)) { this.pieceGroup.remove(obj); dispose(obj); this.pieces.delete(id); }
    }
  }

  setGhost(pc, tint) {
    const sig = pc ? JSON.stringify({ ...pc, x: 0, y: 0, z: 0, id: '' }) + tint : null;
    if (this.ghost && this.ghost.userData.sig === sig) {
      this.place(this.ghost, pc);
      this.guideTo(pc);
      return;
    }
    if (this.ghost) { this.scene.remove(this.ghost); dispose(this.ghost, true); this.ghost = null; }
    this.guideTo(pc);
    if (!pc) return;
    this.ghost = this.pieceObject(pc, true, tint);
    this.ghost.userData.sig = sig;
    this.ghost.traverse((o) => { o.userData.piece = null; });
    this.scene.add(this.ghost);
  }

  // a line from the ghost down to the ground, when it's up in the air
  guideTo(pc) {
    if (!this.guide) {
      const g = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(0, 1, 0)]);
      this.guide = new THREE.Line(g, new THREE.LineDashedMaterial({ color: 0xffd34d, dashSize: 80, gapSize: 60, depthTest: false, transparent: true }));
      this.guide.renderOrder = 10;
      this.scene.add(this.guide);
    }
    const on = pc && (pc.y || 0) > 64;
    this.guide.visible = !!on;
    if (!on) return;
    const pos = this.guide.geometry.attributes.position;
    pos.setXYZ(0, pc.x, GROUND_Y, pc.z);
    pos.setXYZ(1, pc.x, pc.y, pc.z);
    pos.needsUpdate = true;
    this.guide.geometry.computeBoundingSphere();
    this.guide.computeLineDistances();
  }

  // the mouse's ray: the piece under it, and where it meets the build plane
  pick(ev, y = this.gridY) {
    const r = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.camera);
    const hits = this.raycaster.intersectObjects(this.pieceGroup.children, true);
    const hit = hits.find((h) => h.object.userData.piece);
    const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -y);
    const at = new THREE.Vector3();
    const onPlane = this.raycaster.ray.intersectPlane(plane, at) ? [at.x, at.y, at.z] : null;
    return { piece: hit ? hit.object.userData.piece : null, point: hit ? [hit.point.x, hit.point.y, hit.point.z] : null, plane: onPlane };
  }

  // open ends: arrows where the track goes on; the route: a line round it
  showOverlay({ ends = [], route = null, selected = [], trail = null, spawn = null }) {
    this.overlay.clear();
    for (const c of ends) {
      const dir = new THREE.Vector3(c.f[0], c.f[1], c.f[2]).normalize();
      const arrow = new THREE.ArrowHelper(dir, new THREE.Vector3(c.p[0], c.p[1] + 80, c.p[2]), 520, 0x3dff8a, 220, 180);
      this.overlay.add(arrow);
    }
    if (route && route.samples.length > 1) {
      const color = route.closed ? 0x3dff8a : 0xffa53d;
      const pts = route.samples.map((s) => new THREE.Vector3(s.p[0], s.p[1] + 40, s.p[2]));
      const g = new THREE.BufferGeometry().setFromPoints(pts);
      this.overlay.add(new THREE.Line(g, new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.85, depthTest: false })));
      // which way round: a chevron every couple of blocks
      if (!this.chevron) {
        const shape = new THREE.Shape([new THREE.Vector2(-180, -120), new THREE.Vector2(0, 120), new THREE.Vector2(180, -120), new THREE.Vector2(0, -40)]);
        this.chevron = new THREE.ShapeGeometry(shape);
        this.chevron.rotateX(-Math.PI / 2);
      }
      const mat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.9, depthTest: false, side: THREE.DoubleSide });
      let next = 0;
      for (let i = 0; i < route.samples.length - 1; i++) {
        if (route.arc[i] < next) continue;
        next = route.arc[i] + 2048;
        const s = route.samples[i];
        const m = new THREE.Mesh(this.chevron, mat);
        m.position.set(s.p[0], s.p[1] + 44, s.p[2]);
        m.rotation.y = Math.atan2(s.f[0], s.f[2]) + Math.PI;
        m.renderOrder = 5;
        this.overlay.add(m);
      }
    }
    if (trail && trail.length > 1) {
      const g = new THREE.BufferGeometry().setFromPoints(trail.map((p) => new THREE.Vector3(p[0], p[1] + 60, p[2])));
      this.overlay.add(new THREE.Line(g, new THREE.LineBasicMaterial({ color: 0xff3df2, transparent: true, opacity: 0.9 })));
    }
    if (spawn) {
      const cone = new THREE.Mesh(new THREE.ConeGeometry(120, 360, 12), new THREE.MeshBasicMaterial({ color: 0xffd34d }));
      cone.position.set(spawn.p[0], spawn.p[1] + 200, spawn.p[2]);
      cone.rotation.x = Math.PI;
      this.overlay.add(cone);
    }
    for (const id of selected) {
      const obj = this.pieces.get(id);
      if (!obj) continue;
      const box = new THREE.BoxHelper(obj, 0xffd34d);
      box.material.depthTest = false;
      box.material.transparent = true;
      this.overlay.add(box);
    }
  }

  focus(points) {
    if (!points.length) return;
    const box = new THREE.Box3();
    for (const p of points) box.expandByPoint(new THREE.Vector3(...p));
    const c = box.getCenter(new THREE.Vector3());
    const size = Math.max(2000, box.getSize(new THREE.Vector3()).length());
    const dir = this.camera.position.clone().sub(this.controls.target).normalize();
    this.controls.target.copy(c);
    this.camera.position.copy(c.clone().add(dir.multiplyScalar(size * 0.9)));
  }

  // moves the camera's target along the ground (WASD), by the camera's heading
  pan(dx, dz) {
    const f = new THREE.Vector3();
    this.camera.getWorldDirection(f);
    f.y = 0;
    f.normalize();
    const r = new THREE.Vector3(-f.z, 0, f.x);
    const d = r.multiplyScalar(dx).add(f.multiplyScalar(dz));
    this.controls.target.add(d);
    this.camera.position.add(d);
  }

  // small pictures of each piece for the palette
  thumbnails(pieces, w = 96, h = 72) {
    const r = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true, alpha: true });
    r.setSize(w, h);
    const scene = new THREE.Scene();
    const cam = new THREE.PerspectiveCamera(40, w / h, 10, 100000);
    const out = {};
    for (const [type, pc] of Object.entries(pieces)) {
      const obj = this.pieceObject({ ...pc, x: 0, y: 0, z: 0, yaw: 0, pitch: 0, roll: 0, id: 'thumb' });
      scene.add(obj);
      const box = new THREE.Box3().setFromObject(obj);
      const c = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3()).length();
      cam.position.set(c.x + size * 0.75, c.y + size * 0.65, c.z + size * 0.75);
      cam.lookAt(c);
      r.render(scene, cam);
      out[type] = r.domElement.toDataURL();
      scene.remove(obj);
      dispose(obj);
    }
    r.dispose();
    return out;
  }
}

function dispose(obj, materials = false) {
  obj.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    if (materials && o.material && o.material.opacity < 1) { /* shared: kept */ }
  });
}
