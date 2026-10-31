/* The 3D stage: a corridor with one station per scene and a camera that drifts at each station and glides to
   the next between scenes. What stands at a station:
     - the brand's own 3D models (glTF), where the brand has shared some and the plan assigns one to the scene:
       placed where the scene's content leaves room, scaled to fit, playing their own animations (seeked to the
       scene's clock) or turning slowly when they have none;
     - on title and closing scenes without a model, the brand's logo mark extruded in 3D;
     - otherwise a few abstract shapes in the brand's colors, on the side the text doesn't start from.
   Nothing here knows about any business: what a model is and where it goes comes from the brand and the plan.
   Fog fades the stations ahead into the page color. Everything is a function of time (the hf-seek event) and a
   seeded layout, so frames render the same in any order. */
import * as THREE from "../js/three.module.min.js";
import { SVGLoader } from "../js/SVGLoader.js";
import { GLTFLoader } from "../js/GLTFLoader.js";
import { RoomEnvironment } from "../js/RoomEnvironment.js";

const S = window.TF_DEPTH;
const canvas = document.getElementById("tf-depth");
if (S && canvas) {
  // models load asynchronously; the renderer waits for this before the first frame
  let ready;
  const whenReady = new Promise((r) => (ready = r));
  window.__hf = window.__hf || {};
  window.__hf.buildReady = window.__hf.buildReady || {};
  window.__hf.buildReady["tf-depth"] = whenReady;

  const rich = S.level === "rich";
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.setSize(S.W, S.H, false);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene();
  const aspect = S.W / S.H, portrait = aspect < 1;
  const FOV = 38, D = 9, CAM = 8;  // field of view, distance between stations, camera distance to a station
  const camera = new THREE.PerspectiveCamera(FOV, aspect, 0.1, 200);
  scene.add(new THREE.HemisphereLight(0xffffff, S.dark ? 0x1a1f2b : 0x8a90a0, S.dark ? 1.7 : 2.1));
  const key = new THREE.DirectionalLight(0xffffff, 1.7);
  key.position.set(4, 6, 8);
  scene.add(key);
  const bg = new THREE.Color(S.bg);
  scene.fog = new THREE.Fog(bg, CAM + 2.5, CAM + D * 0.8);  // the stations ahead wait in the page color

  let seed = (S.seed * 2654435761 + 12345) >>> 0;
  const rnd = () => {  // mulberry32
    seed = (seed + 0x6d2b79f5) >>> 0;
    let t = seed;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const clamp = (v) => Math.min(1, Math.max(0, v));
  const ease = (u) => (u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2);
  const easeOut = (u) => 1 - Math.pow(1 - clamp(u), 3);
  const back = (u) => { u = clamp(u); const c = 1.7; return 1 + (c + 1) * Math.pow(u - 1, 3) + c * Math.pow(u - 1, 2); };

  // abstract shapes are softened toward the page color so they stay behind the words
  const soften = rich ? 0.25 : 0.42;
  const tint = (c, k = soften) => new THREE.Color(c).lerp(bg, k);
  const C = S.colors;  // brand fill, accent, second fill, soft surface
  const flat = C.map((c) => new THREE.MeshStandardMaterial({ color: tint(c), roughness: 0.45, metalness: 0.06, flatShading: true }));

  const n = S.scenes.length;
  const open = S.rtl ? -1 : 1;  // the side text doesn't start from
  const halfH = (dist) => Math.tan(THREE.MathUtils.degToRad(FOV / 2)) * dist;
  const anims = [];  // (t) => void, run every frame

  // How much of each scene's frame its content leaves free. Measured once, before the first frame, with every
  // scene shown and the motion's transforms switched off, so it's the layout as it settles: text by its line
  // boxes (a headline block may be full width while its words are not), boxes by their edges.
  const root = document.getElementById("root");
  const style = document.createElement("style");
  style.textContent = ".tf-measure .scene{display:block!important;visibility:visible!important}" +
    ".tf-measure .scene *{transform:none!important;translate:none!important;scale:none!important;rotate:none!important}";
  document.head.appendChild(style);
  root.classList.add("tf-measure");
  const BOXES = ".box, .card, .ill, .win, .app, .mock, .chart, .plot, .ph, .q, .bub, .av, .img, figure";
  const rootBox = root.getBoundingClientRect();
  const free = S.scenes.map((sc) => {
    const sec = sc.id && document.getElementById(sc.id);
    if (!sec) return { side: 0, bottom: 0, top: 1 };
    let lo = S.W, hi = 0, bot = 0;
    const take = (r) => {
      if (r.width > 1 && r.height > 1) {
        lo = Math.min(lo, r.left - rootBox.left);
        hi = Math.max(hi, r.right - rootBox.left);
        bot = Math.max(bot, r.bottom - rootBox.top);
      }
    };
    sec.querySelectorAll(".stage .tx").forEach((el) => {
      const range = document.createRange();
      range.selectNodeContents(el);
      for (const r of range.getClientRects()) take(r);
    });
    // and everything else that paints: boxes, rules, images, icons (whatever the component calls them)
    sec.querySelectorAll(".stage *").forEach((el) => {
      if (el.closest("svg") && el.tagName.toLowerCase() !== "svg") return;
      const cs = getComputedStyle(el);
      if (cs.visibility === "hidden" || cs.display === "none") return;
      const paints = /^(svg|img|canvas|video|picture)$/i.test(el.tagName) || el.matches(BOXES) ||
        !/rgba\(.*,\s*0\)|transparent/.test(cs.backgroundColor) || cs.backgroundImage !== "none" ||
        ["Top", "Right", "Bottom", "Left"].some((k) => parseFloat(cs["border" + k + "Width"]) > 0 && !/rgba\(.*,\s*0\)|transparent/.test(cs["border" + k + "Color"]));
      if (paints) take(el.getBoundingClientRect());
    });
    if (hi <= lo) return { side: 0, bottom: 0, top: 1 };
    // the band under the content ends above the progress bar and captions
    const floor = S.H * (S.caps ? 0.8 : 0.9);
    return { side: Math.max(0, open > 0 ? (S.W - hi) / S.W : lo / S.W), bottom: Math.max(0, (floor - bot) / S.H), top: bot / S.H };
  });
  root.classList.remove("tf-measure");
  style.remove();

  // Where an object can stand at station i, at distance `dist` from the parked camera: a box (center, width,
  // height, in world units) in the strip on the open side, else in the band under the content; null: no room.
  // A small margin allows for the page's own camera moves, which grow the content a little as a scene plays.
  // `big`: the object is the scene's feature (a brand model or the logo), so a sliver of room isn't enough.
  function room(i, dist, minSide = 0.16, big = false) {
    const hh = halfH(dist), hw = hh * aspect;
    const fr = free[Math.min(i, n - 1)] || { side: 0, bottom: 0, top: 1 };
    const side = fr.side - 0.035, bottom = fr.bottom - 0.03;
    if (!portrait && side >= minSide) {
      const f = Math.min(0.42, side);
      return { x: open * (1 - f) * hw, y: 0.02 * hh, w: 2 * f * hw * 0.72, h: 2 * hh * 0.5 };
    }
    if (bottom >= (big ? 0.26 : 0.16)) {
      const b = Math.min(0.34, bottom), mid = fr.top + 0.015 + b / 2;  // fractions of the height, from the top
      return { x: portrait ? 0 : open * hw * 0.3, y: (1 - mid * 2) * hh, w: hw * (portrait ? 1.3 : 0.7), h: 2 * b * hh * 0.78 };
    }
    return null;
  }

  // ------------------------------------------------------------------ abstract pieces
  const geos = [
    new THREE.IcosahedronGeometry(0.75, 0), new THREE.TorusGeometry(0.6, 0.22, 24, 64),
    new THREE.SphereGeometry(0.62, 40, 24), new THREE.BoxGeometry(0.95, 0.95, 0.95),
    new THREE.OctahedronGeometry(0.75, 0), new THREE.CylinderGeometry(0.45, 0.45, 1.0, 40),
  ];
  function floater(x, y, z, s) {
    const m = new THREE.Mesh(geos[Math.floor(rnd() * geos.length)], flat[Math.floor(rnd() * 4)]);
    m.scale.setScalar(s);
    m.position.set(x, y, z);
    scene.add(m);
    const rx = rnd() * 6.28, ry = rnd() * 6.28, sx = (rnd() - 0.5) * 0.5, sy = 0.15 + rnd() * 0.35, ph = rnd() * 6.28;
    anims.push((t) => {
      m.rotation.set(rx + t * sy, ry + t * (sy * 0.8 + sx), 0);
      m.position.y = y + Math.sin(t * (rich ? 0.7 : 0.5) + ph) * (rich ? 0.18 : 0.08);
    });
  }
  function edges(i, dist) {
    const hh = halfH(dist);
    return { hh, hw: hh * aspect, z: -i * D - (dist - CAM) };
  }
  function abstract(i) {
    for (let j = 0; j < (rich ? 4 : 3); j++) {
      const z = edges(i, CAM + rnd() * D * 0.5);
      // as far out as the scene's content needs: right at the edge when the content runs nearly full width
      const from = Math.max(0.84, Math.min(1.02, 1.08 - 2 * (free[Math.min(i, n - 1)] || { side: 0 }).side));
      const x = portrait ? (rnd() * 2 - 1) * z.hw * 0.9 : open * z.hw * (from + rnd() * 0.26);
      const y = portrait ? -z.hh * (0.8 + rnd() * 0.22) : (rnd() * 2 - 1) * z.hh * 0.6;
      floater(x, y, z.z, 0.55 + rnd() * (rich ? 0.7 : 0.45));
    }
  }
  function peekers(i) {  // a shape or two peeking in from beyond the far edge, for depth
    if (portrait) return;
    for (let j = 0; j < (rich ? 2 : 1); j++) {
      const z = edges(i, CAM + 1 + rnd() * D * 0.4);
      floater(-open * z.hw * (1.06 + rnd() * 0.1), (rnd() * 2 - 1) * z.hh * 0.55, z.z, 0.6 + rnd() * 0.4);
    }
  }

  // ------------------------------------------------------------------ camera
  const push = rich ? 1.6 : 0.9, travel = 0.9;
  function base(i, t) {  // parked at station i, pushing in slowly while the scene plays
    const sc = S.scenes[i];
    return -i * D + CAM - clamp((t - sc.start) / Math.max(0.5, sc.end - sc.start)) * push;
  }
  function camZ(t) {  // ...and gliding to the next station across each cut
    let i = 0;
    while (i < n - 1 && t >= S.scenes[i + 1].start) i++;
    if (i > 0 && t < S.scenes[i].start + travel) {
      const v = ease(clamp((t - (S.scenes[i].start - travel)) / (2 * travel)));
      return base(i - 1, t) + (base(i, t) - base(i - 1, t)) * v;
    }
    if (i < n - 1 && t > S.scenes[i + 1].start - travel) {
      const v = ease(clamp((t - (S.scenes[i + 1].start - travel)) / (2 * travel)));
      return base(i, t) + (base(i + 1, t) - base(i, t)) * v;
    }
    return base(i, t);
  }

  // An object that belongs to scene i's frame: it rides the camera's slow push so it holds its place, stays
  // behind when the camera glides on, turns in when the scene starts and settles. `obj` is centered at the
  // origin and `unit` scales it to a height of 1.
  function stage(i, obj, box, dist, unit, { spin = true, turnIn = true } = {}) {
    const sc = S.scenes[i];
    const g = new THREE.Group();
    g.add(obj);
    g.position.set(box.x, box.y, -i * D + CAM - dist);
    scene.add(g);
    const hold = Math.max(sc.start, sc.end - travel);
    const ph = rnd() * 6.28;
    anims.push((t) => {
      g.position.z = camZ(Math.min(Math.max(t, sc.start), hold)) - dist;
      const u = (t - sc.start - 0.25) / 1.4;
      const k = unit * Math.max(0.001, back(u));
      g.scale.setScalar(k);
      const turn = turnIn ? open * -Math.PI * 0.85 * (1 - easeOut(u)) : 0;
      g.rotation.y = turn + (spin ? (t - sc.start) * 0.35 * open : Math.sin((t - sc.start) * 0.7 + ph) * 0.22 * clamp(u));
      g.rotation.x = Math.sin((t - sc.start) * 0.5 + ph) * 0.05;
      g.visible = t > sc.start - 1 && t < sc.end + 1.2;
    });
    return g;
  }

  // ------------------------------------------------------------------ the brand's own models
  const placed = new Set();  // scenes that got a model or the logo
  const jobs = [];
  const models = S.models || {};
  // Which model stands where: each scene takes its best candidate that has room and isn't on a neighbouring
  // scene; then models not shown yet take scenes that have room and nothing else, so each appears once.
  const dist = CAM - 0.8;
  const pick = {};
  const nextTo = (i, id) => pick[i - 1] === id || pick[i + 1] === id;
  S.scenes.forEach((sc, i) => {
    if (!room(i, dist, sc.hero ? 0.18 : 0.16, true)) return;
    const id = (sc.models || []).find((m) => models[m] && !nextTo(i, m));
    if (id) pick[i] = id;
  });
  for (const id of S.spare || []) {
    if (!models[id] || Object.values(pick).includes(id)) continue;
    const i = S.scenes.findIndex((sc, j) => !sc.hero && pick[j] === undefined && !nextTo(j, id) && room(j, dist, 0.16, true));
    if (i >= 0) pick[i] = id;
  }
  const want = Object.keys(pick).map(Number);
  if (want.length) {
    // image-based light so materials made for real-world lighting (metal, glass) look as designed
    try {
      const pmrem = new THREE.PMREMGenerator(renderer);
      scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
      scene.environmentIntensity = 0.8;
    } catch (e) {
      console.warn("kinetry: no environment light", e);
    }
    const loader = new GLTFLoader();
    const files = {};
    const load = (id) => (files[id] = files[id] || fetch(models[id].src).then((r) => {
      if (!r.ok) throw new Error(`${models[id].src}: ${r.status}`);
      return r.arrayBuffer();
    }));
    // each scene parses its own copy, so animated and skinned models keep their own skeletons and clocks
    const parse = (buf) => new Promise((res, rej) => loader.parse(buf.slice(0), "", res, rej));
    for (const i of want) {
      const box = room(i, dist, 0.16, true);
      placed.add(i);
      const sc = S.scenes[i], m = models[pick[i]];
      jobs.push(load(pick[i]).then(parse).then((gltf) => {
        const obj = gltf.scene;
        const bb = new THREE.Box3().setFromObject(obj), size = new THREE.Vector3(), mid = new THREE.Vector3();
        bb.getSize(size);
        bb.getCenter(mid);
        obj.position.sub(mid);
        // fit the box: turning, it's as wide as its footprint's diagonal, and its near side comes closer
        const wide = Math.max(Math.hypot(size.x, size.z), 1e-6), tall = Math.max(size.y, 1e-6);
        const unit = Math.min(box.w / wide, box.h / tall) * 0.92;
        const animated = gltf.animations && gltf.animations.length;
        stage(i, obj, box, dist, unit, { spin: !animated && m.role !== "logo", turnIn: true });
        if (animated) {
          const mixer = new THREE.AnimationMixer(obj);
          for (const clip of gltf.animations) mixer.clipAction(clip).play();
          anims.push((t) => mixer.setTime(Math.max(0, t - sc.start)));
        }
      }).catch((e) => {
        placed.delete(i);
        console.warn("kinetry: a 3D model could not be shown", e);
        abstract(i);
      }));
    }
  }

  // ------------------------------------------------------------------ the logo mark, in 3D
  if (S.mark && typeof DOMParser !== "undefined") {
    try {
      const data = new SVGLoader().parse(S.mark);
      const shapes = [];
      for (const p of data.paths) shapes.push(...SVGLoader.createShapes(p));
      if (shapes.length) {
        const geo = new THREE.ExtrudeGeometry(shapes, { depth: 60, bevelEnabled: true, bevelThickness: 8, bevelSize: 5, bevelSegments: 4, curveSegments: 18 });
        geo.scale(1, -1, 1);
        geo.computeBoundingBox();
        const bb = geo.boundingBox, size = new THREE.Vector3();
        bb.getSize(size);
        geo.translate(-(bb.min.x + size.x / 2), -(bb.min.y + size.y / 2), -(bb.min.z + size.z / 2));
        geo.computeVertexNormals();
        const face = new THREE.MeshStandardMaterial({ color: new THREE.Color(C[0]), roughness: 0.32, metalness: 0.25 });
        const side = new THREE.MeshStandardMaterial({ color: new THREE.Color(C[0]).lerp(new THREE.Color("#000000"), 0.25), roughness: 0.4, metalness: 0.2 });
        S.scenes.forEach((sc, i) => {
          if (!sc.hero || placed.has(i)) return;
          const box = room(i, dist, 0.18, true);
          if (!box || portrait) return;
          placed.add(i);
          const h = Math.min(box.h, box.w) * 0.85;
          const logo = new THREE.Mesh(geo, [face, side]);
          logo.scale.z = 0.9;
          stage(i, logo, box, dist, h / Math.max(size.x, size.y), { spin: false });
        });
      }
    } catch (e) {
      console.warn("kinetry: logo mark could not be built in 3D", e);
    }
  }

  // scenes without a model or the logo get a few abstract shapes; the rest one shape peeking from the far side
  for (let i = 0; i < n; i++) {
    if (placed.has(i)) peekers(i);
    else abstract(i);
  }

  function renderAt(time) {
    const t = Math.max(0, Number(time) || 0);
    camera.position.set(rich ? Math.sin(t * 0.21) * 0.35 : 0, rich ? Math.sin(t * 0.17) * 0.2 : 0, camZ(t));
    camera.lookAt(camera.position.x * 0.5, camera.position.y * 0.5, camera.position.z - 10);
    for (const a of anims) a(t);
    renderer.render(scene, camera);
  }
  let last = window.__hfThreeTime || 0;
  window.addEventListener("hf-seek", (e) => { last = e.detail && e.detail.time; renderAt(last); });
  renderAt(last);
  Promise.allSettled(jobs).then(() => { renderAt(last); ready(); });
}
