/* LoanMitra 3D stage — an original "ice vault" sculpture that tells the eligibility story as you scroll.
   Three.js r160 (MIT), served locally. Decorative only: all content is accessible HTML. */
import * as THREE from "/static/vendor/three.module.min.js";
import { RoomEnvironment } from "/static/vendor/RoomEnvironment.js";

const INK = 0x484860, LAVENDER = 0xa8a8c0, ICE = 0xdceeff, FOG = 0xa0a5b1;
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const smooth = (t) => t * t * (3 - 2 * t);
const easeOut = (t) => 1 - (1 - t) ** 3;
const fmtINR = (n) => (n >= 1e7 ? `₹${(Math.floor(n / 1e5) / 100)} Cr` : n >= 1e5 ? `₹${(Math.floor(n / 1e3) / 100)} L` : `₹${Math.round(n).toLocaleString("en-IN")}`);

// Camera / sculpture choreography per chapter: 0 hero, 1 trust, 2 profile, 3 engine, 4 explanation, 5 EMI
const KEYS = [
  { cam: [0, 0.4, 11.5], look: [0.9, 0, 0], gx: 3.0, s: 0.78 },
  { cam: [0.6, 0.8, 9.6], look: [1.6, 0, 0], gx: 2.9, s: 0.85 },
  { cam: [-1.4, 1.6, 10.0], look: [1.4, 0.2, 0], gx: 2.6, s: 0.8 },
  { cam: [0.2, 4.0, 10.6], look: [1.8, 0, 0], gx: 2.7, s: 0.8 },
  { cam: [2.4, 0.6, 10.0], look: [2.8, 0, 0], gx: 3.6, s: 0.7 },
  { cam: [0.5, 0.3, 12.5], look: [2.6, 0, 0], gx: 3.7, s: 0.68 },
];

export function initScene(canvas, labelsEl, progressFn) {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75));
  renderer.setSize(innerWidth, innerHeight, false);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(FOG, 0.05);
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(renderer), 0.04).texture;

  const camera = new THREE.PerspectiveCamera(35, innerWidth / innerHeight, 0.1, 100);
  camera.position.set(...KEYS[0].cam);
  const look = new THREE.Vector3(...KEYS[0].look);

  // ---------- light: soft ambient + key with real shadows + cool rim
  scene.add(new THREE.HemisphereLight(0xffffff, 0x80869a, 1.1));
  const key = new THREE.DirectionalLight(0xffffff, 2.4);
  key.position.set(1.5, 9, 3);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  Object.assign(key.shadow.camera, { left: -5, right: 5, top: 5, bottom: -5, near: 1, far: 25 });
  key.shadow.radius = 6;
  scene.add(key);
  const rim = new THREE.DirectionalLight(ICE, 1.4);
  rim.position.set(-6, 2, -5);
  scene.add(rim);

  const floor = new THREE.Mesh(new THREE.PlaneGeometry(60, 60), new THREE.ShadowMaterial({ opacity: 0.07 }));
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -2.05;
  floor.receiveShadow = true;
  scene.add(floor);

  const root = new THREE.Group();
  scene.add(root);

  // floor rings (technical lines)
  for (const [r, o] of [[2.6, 0.35], [3.3, 0.2]]) {
    const pts = new THREE.EllipseCurve(0, 0, r, r).getPoints(160).map((p) => new THREE.Vector3(p.x, -2.03, p.y));
    const ring = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: INK, transparent: true, opacity: o }));
    root.add(ring);
  }

  // ---------- the ice vault
  const sculpture = new THREE.Group();
  root.add(sculpture);
  const crystalGeo = new THREE.IcosahedronGeometry(1.35, 0);
  crystalGeo.scale(1, 1.18, 1);
  const ice = new THREE.MeshPhysicalMaterial({
    color: 0xf4f8ff, metalness: 0, roughness: 0.14, transmission: 0.92, thickness: 1.8, ior: 1.31, specularIntensity: 1,
    attenuationColor: new THREE.Color(ICE), attenuationDistance: 3.2, iridescence: 0.5, iridescenceIOR: 1.25,
    iridescenceThicknessRange: [120, 420], clearcoat: 1, clearcoatRoughness: 0.08, envMapIntensity: 1.35,
    flatShading: true, transparent: true, opacity: 0,
  });
  const crystal = new THREE.Mesh(crystalGeo, ice);
  crystal.castShadow = true;
  sculpture.add(crystal);

  const wireMat = new THREE.LineBasicMaterial({ color: INK, transparent: true, opacity: 0 });
  const wire = new THREE.LineSegments(new THREE.EdgesGeometry(crystalGeo), wireMat);
  sculpture.add(wire);
  const cageGeo = new THREE.IcosahedronGeometry(1.95, 1);
  cageGeo.scale(1, 1.1, 1);
  const cageMat = new THREE.LineBasicMaterial({ color: INK, transparent: true, opacity: 0 });
  sculpture.add(new THREE.LineSegments(new THREE.EdgesGeometry(cageGeo), cageMat));

  // the shield at the core
  const sh = new THREE.Shape();
  sh.moveTo(0, 0.55);
  sh.quadraticCurveTo(0.36, 0.48, 0.5, 0.38);
  sh.lineTo(0.47, -0.02);
  sh.quadraticCurveTo(0.4, -0.4, 0, -0.62);
  sh.quadraticCurveTo(-0.4, -0.4, -0.47, -0.02);
  sh.lineTo(-0.5, 0.38);
  sh.quadraticCurveTo(-0.36, 0.48, 0, 0.55);
  const shieldGeo = new THREE.ExtrudeGeometry(sh, { depth: 0.12, bevelEnabled: true, bevelThickness: 0.04, bevelSize: 0.035, bevelSegments: 4, curveSegments: 28 });
  shieldGeo.center();
  const shieldMat = new THREE.MeshPhysicalMaterial({ color: 0xe9edf6, metalness: 0.75, roughness: 0.18, clearcoat: 1, envMapIntensity: 1.8,
    emissive: new THREE.Color(0x2a3047), emissiveIntensity: 0.25, transparent: true, opacity: 0 });
  const shield = new THREE.Mesh(shieldGeo, shieldMat);
  shield.scale.setScalar(1.15);
  shield.castShadow = true;
  sculpture.add(shield);

  // orbit rings (dashed)
  const orbits = [];
  for (const [r, tilt] of [[2.35, 0.35], [2.7, -0.55]]) {
    const pts = new THREE.EllipseCurve(0, 0, r, r * 0.92).getPoints(200).map((p) => new THREE.Vector3(p.x, 0, p.y));
    const line = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(pts),
      new THREE.LineDashedMaterial({ color: INK, dashSize: 0.08, gapSize: 0.06, transparent: true, opacity: 0 }));
    line.computeLineDistances();
    line.rotation.x = Math.PI / 2 + tilt;
    sculpture.add(line);
    orbits.push(line);
  }

  // ---------- particles that assemble into the crystal
  const N = 2200;
  const pos = crystalGeo.toNonIndexed().attributes.position;
  const tris = pos.count / 3;
  const target = new Float32Array(N * 3), start = new Float32Array(N * 3), delay = new Float32Array(N);
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
  for (let i = 0; i < N; i++) {
    const t = Math.floor(Math.random() * tris) * 3;
    a.fromBufferAttribute(pos, t); b.fromBufferAttribute(pos, t + 1); c.fromBufferAttribute(pos, t + 2);
    let u = Math.random(), v = Math.random();
    if (u + v > 1) { u = 1 - u; v = 1 - v; }
    const p = a.clone().add(b.clone().sub(a).multiplyScalar(u)).add(c.clone().sub(a).multiplyScalar(v)).multiplyScalar(1.02);
    target.set([p.x, p.y, p.z], i * 3);
    const dir = new THREE.Vector3().randomDirection().multiplyScalar(4 + Math.random() * 5);
    start.set([dir.x, dir.y, dir.z], i * 3);
    delay[i] = Math.random() * 0.5;
  }
  const pGeo = new THREE.BufferGeometry();
  pGeo.setAttribute("position", new THREE.BufferAttribute(start.slice(), 3));
  const pMat = new THREE.PointsMaterial({ color: INK, size: 0.026, transparent: true, opacity: 0.75, depthWrite: false });
  sculpture.add(new THREE.Points(pGeo, pMat));

  // ambient dust in the fog
  const D = 700, dust = new Float32Array(D * 3);
  for (let i = 0; i < D; i++) dust.set([(Math.random() - 0.5) * 26, Math.random() * 9 - 2, (Math.random() - 0.5) * 18], i * 3);
  const dustGeo = new THREE.BufferGeometry();
  dustGeo.setAttribute("position", new THREE.BufferAttribute(dust, 3));
  const dustPts = new THREE.Points(dustGeo, new THREE.PointsMaterial({ color: 0xffffff, size: 0.03, transparent: true, opacity: 0.55, depthWrite: false }));
  scene.add(dustPts);

  // ---------- chapter 2: frosted profile indicators
  const indMat = new THREE.MeshPhysicalMaterial({ color: 0xffffff, transmission: 0.9, roughness: 0.25, thickness: 0.5, ior: 1.3, envMapIntensity: 1.2, transparent: true, opacity: 0 });
  const indicators = [[-2.3, 1.1, 0.6], [2.4, 0.55, 0.9], [-1.6, -1.2, 1.4]].map((p) => {
    const m = new THREE.Mesh(new THREE.OctahedronGeometry(0.2, 0), indMat);
    m.position.set(...p);
    m.castShadow = true;
    sculpture.add(m);
    return m;
  });

  // ---------- chapter 3: rule paths converging on the core (the only colour: faint refraction)
  const paths = [];
  const cA = new THREE.Color(LAVENDER), cB = new THREE.Color(0x9fd6ff), cC = new THREE.Color(0xc2b4ff);
  for (let i = 0; i < 16; i++) {
    const ang = (i / 16) * Math.PI * 2 + 0.3;  // evenly spread, so rule labels never collide
    const from = new THREE.Vector3(Math.cos(ang) * 4.2, Math.sin(i * 1.7) * 1.3 + 0.5, Math.sin(ang) * 3.4);
    const mid = from.clone().multiplyScalar(0.5).add(new THREE.Vector3(0, 0.8 + Math.random(), 0));
    const pts = new THREE.QuadraticBezierCurve3(from, mid, new THREE.Vector3(0, 0, 0)).getPoints(80);
    const g = new THREE.BufferGeometry().setFromPoints(pts);
    const cols = new Float32Array(pts.length * 3);
    pts.forEach((_, k) => {
      const t = k / (pts.length - 1);
      const col = t < 0.5 ? cA.clone().lerp(cB, t * 2) : cB.clone().lerp(cC, (t - 0.5) * 2);
      cols.set([col.r, col.g, col.b], k * 3);
    });
    g.setAttribute("color", new THREE.BufferAttribute(cols, 3));
    g.setDrawRange(0, 0);
    const line = new THREE.Line(g, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.9 }));
    sculpture.add(line);
    paths.push({ line, n: pts.length, from });
  }

  // ---------- HTML labels pinned to 3D points
  const label = (html, anchor, chapters) => {
    const el = document.createElement("div");
    el.className = "label";
    el.innerHTML = html;
    labelsEl.appendChild(el);
    return { el, anchor: new THREE.Vector3(...anchor), chapters, html };
  };
  const emiLabel = label("", [1.2, -0.9, 0.6], [5]);
  const labels = [
    label("CORE <b>/ RULES ENGINE</b>", [1.05, 1.25, 0.3], [0, 1]),
    label("SHIELD <b>/ PII MASKED</b>", [0.45, 0, 0.7], [0, 1]),
    label("ORBIT <b>/ 4 LENDERS</b>", [2.4, -0.3, 0], [0]),
    label("LAT 28.61 · LON 77.21 <b>/ IN</b>", [-1.4, -1.85, 0.8], [0]),
    label("STATE <b>/ WIREFRAME → ICE</b>", [-1.9, 0.9, 0], [1]),
    label("INCOME <b>₹65,000 / MO</b>", indicators[0].position.toArray(), [2]),
    label("EXISTING EMI <b>₹8,500</b>", indicators[1].position.toArray(), [2]),
    label("TENURE <b>3 YRS</b>", indicators[2].position.toArray(), [2]),
    label("FOIR <b>≤ 50%</b>", paths[1].from.toArray(), [3]),
    label("CIBIL <b>≥ 700</b>", paths[5].from.toArray(), [3]),
    label("LTV <b>≤ 80%</b>", paths[9].from.toArray(), [3]),
    label("AGE <b>≤ 60 AT MATURITY</b>", paths[13].from.toArray(), [3]),
    label("VERDICT <b>/ FROM RULES, NOT AI</b>", [1.0, 1.3, 0.3], [4]),
    emiLabel,
  ];

  // ---------- interaction
  const mouse = new THREE.Vector2();
  if (!reduced) addEventListener("pointermove", (e) => mouse.set((e.clientX / innerWidth) * 2 - 1, (e.clientY / innerHeight) * 2 - 1), { passive: true });
  let needsRender = true;
  const wake = () => { needsRender = true; };
  addEventListener("scroll", wake, { passive: true });
  addEventListener("resize", () => {
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight, false);
    needsRender = true;
  });
  document.querySelectorAll("#cAmount, #cRate, #cTenure").forEach((el) => el.addEventListener("input", wake));

  const t0 = performance.now();
  const camTarget = new THREE.Vector3(), lookTarget = new THREE.Vector3(), tmp = new THREE.Vector3();
  let rotY = 0, gx = KEYS[0].gx, scaleNow = 1;

  function frame(now) {
    requestAnimationFrame(frame);
    if (document.hidden) return;
    const elapsed = (now - t0) / 1000;
    const p = progressFn();
    const pastStory = p > 5.6;
    canvas.style.visibility = pastStory ? "hidden" : "visible";
    labelsEl.style.visibility = pastStory ? "hidden" : "visible";
    const assembling = !reduced && elapsed < 3.2;
    if (pastStory || (reduced && !needsRender)) return;
    needsRender = false;

    // chapter weights
    const w = (ch) => clamp(1 - Math.abs(p - ch));
    const mobile = innerWidth < 960;

    // assembly (particles fly in), then materialise wireframe -> ice through chapter 1
    const build = reduced ? 1 : clamp(elapsed / 2.6);
    const arr = pGeo.attributes.position.array;
    for (let i = 0; i < N; i++) {
      const k = easeOut(clamp((build - delay[i]) / (1 - delay[i] * 0.9)));
      const j = i * 3;
      const shimmer = reduced ? 0 : Math.sin(elapsed * 1.3 + i) * 0.006;
      arr[j] = start[j] + (target[j] - start[j]) * k + shimmer;
      arr[j + 1] = start[j + 1] + (target[j + 1] - start[j + 1]) * k + shimmer;
      arr[j + 2] = start[j + 2] + (target[j + 2] - start[j + 2]) * k;
    }
    pGeo.attributes.position.needsUpdate = true;
    const solid = Math.max(0.6 * build, clamp(p)); // hero: frosted; chapter 1 completes the ice
    ice.opacity = solid;
    shieldMat.opacity = clamp(build * 1.2);
    wireMat.opacity = build * (0.55 - 0.35 * solid);
    cageMat.opacity = build * 0.07;
    pMat.opacity = 0.7 - 0.5 * solid;
    orbits.forEach((o) => { o.material.opacity = build * (0.45 * Math.max(w(0), w(1), w(4), w(5))); });

    // chapter 2 indicators, chapter 3 converging paths
    indMat.opacity = w(2);
    indicators.forEach((m, i) => {
      m.scale.setScalar(0.4 + 0.6 * w(2));
      m.rotation.y = elapsed * 0.6 + i;
      m.position.y += reduced ? 0 : Math.sin(elapsed * 1.1 + i * 2) * 0.0015;
    });
    const draw = clamp((p - 2.4) / 0.9);
    const fade = 1 - clamp((p - 3.6) / 0.6);
    paths.forEach(({ line, n }, i) => {
      line.geometry.setDrawRange(0, Math.floor(n * clamp(draw * 1.3 - i * 0.02)));
      line.material.opacity = 0.85 * fade;
    });

    // camera + sculpture choreography (smoothstep between chapter keyframes, damped)
    const i0 = clamp(Math.floor(p), 0, KEYS.length - 1), i1 = clamp(i0 + 1, 0, KEYS.length - 1);
    const f = smooth(clamp(p - i0));
    const A = KEYS[i0], B = KEYS[i1];
    camTarget.set(...A.cam).lerp(tmp.set(...B.cam), f);
    lookTarget.set(...A.look).lerp(tmp.set(...B.look), f);
    let gxT = A.gx + (B.gx - A.gx) * f;
    const sT = A.s + (B.s - A.s) * f;
    if (mobile) { gxT = 0; camTarget.z += 3; camTarget.y += 1.2; lookTarget.set(0, 0.6, 0); }
    const damp = reduced ? 1 : 0.06;
    camera.position.lerp(camTarget, damp);
    look.lerp(lookTarget, damp);
    camera.lookAt(look);
    gx += (gxT - gx) * damp;
    scaleNow += (sT - scaleNow) * damp;
    root.position.x = gx;
    sculpture.scale.setScalar(scaleNow * (1 + (window.__emiPlan ? Math.min(window.__emiPlan.amount / 1e7, 1) * 0.12 * w(5) : 0)));

    // cursor response + slow idle rotation
    rotY += reduced ? 0 : 0.0016;
    sculpture.rotation.y += (rotY + mouse.x * 0.45 - sculpture.rotation.y) * (reduced ? 1 : 0.05);
    sculpture.rotation.x += (mouse.y * 0.18 - sculpture.rotation.x) * (reduced ? 1 : 0.05);
    shield.rotation.y = -sculpture.rotation.y * 0.6 + (reduced ? 0 : Math.sin(elapsed * 0.7) * 0.25);
    orbits[0].rotation.z = reduced ? 0 : elapsed * 0.05;
    orbits[1].rotation.z = reduced ? 0 : -elapsed * 0.04;
    dustPts.rotation.y = reduced ? 0 : elapsed * 0.01;

    renderer.render(scene, camera);

    // labels follow their 3D anchors
    if (window.__emiPlan) emiLabel.el.innerHTML = `EMI <b>${fmtINR(window.__emiPlan.emi)} / MO</b>`;
    for (const L of labels) {
      const vis = Math.max(...L.chapters.map(w)) * (L.chapters.includes(0) ? Math.max(build, 0) : 1);
      tmp.copy(L.anchor);
      sculpture.localToWorld(tmp);
      tmp.project(camera);
      const x = (tmp.x * 0.5 + 0.5) * innerWidth, y = (-tmp.y * 0.5 + 0.5) * innerHeight;
      L.el.classList.toggle("flip", x > innerWidth - 240);
      L.el.style.left = `${x}px`;
      L.el.style.top = `${y}px`;
      L.el.style.opacity = String(vis > 0.35 && tmp.z < 1 ? Math.min(1, (vis - 0.35) * 2) : 0);
    }
    if (assembling || !reduced) needsRender = true;
  }
  requestAnimationFrame(frame);
}
