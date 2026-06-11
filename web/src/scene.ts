/**
 * The 3D matchday map: MetLife Stadium, the Hudson, four glowing transport
 * corridors, and fan particles flowing along them in real time.
 *
 * Inputs are corridor state docs straight from MongoDB change events —
 * flow drives particle density/speed, queue size drives the origin beacon,
 * status drives color (corridor color → amber → red).
 */
import * as THREE from "three";

export interface CorridorSpec {
  corridor_id: string;
  name: string;
  color: string;
}

interface CorridorViz {
  spec: CorridorSpec;
  curve: THREE.CatmullRomCurve3;
  tube: THREE.Mesh;
  tubeMat: THREE.MeshBasicMaterial;
  points: THREE.Points;
  pointsMat: THREE.PointsMaterial;
  progress: Float32Array;
  speeds: Float32Array;
  activeCount: number;
  baseColor: THREE.Color;
  targetColor: THREE.Color;
  speedScale: number;
  queueBeacon: THREE.Mesh;
  queueBeam: THREE.Mesh;
  originGlow: THREE.Mesh;
  queueTarget: number;
}

const PARTICLES = 380;
const STADIUM_POS = new THREE.Vector3(13, 0, 0);

const ORIGINS: Record<string, THREE.Vector3> = {
  rail: new THREE.Vector3(-17, 0, -7),
  shuttle_a: new THREE.Vector3(-19, 0, 2),
  shuttle_b: new THREE.Vector3(-16, 0, 10),
  park_ride: new THREE.Vector3(-4, 0, -15),
};

const MIDPOINTS: Record<string, THREE.Vector3[]> = {
  rail: [new THREE.Vector3(-8, 0.6, -5.5), new THREE.Vector3(2, 0.8, -3)],
  shuttle_a: [new THREE.Vector3(-9, 0.6, 1.5), new THREE.Vector3(1, 0.8, 0.5)],
  shuttle_b: [new THREE.Vector3(-7, 0.6, 8), new THREE.Vector3(3, 0.8, 4)],
  park_ride: [new THREE.Vector3(1, 0.6, -9), new THREE.Vector3(7, 0.8, -4)],
};

const STATUS_COLORS: Record<string, string> = {
  surge: "#fb923c",
  critical: "#f43f5e",
};

let renderer: THREE.WebGLRenderer;
let scene: THREE.Scene;
let camera: THREE.PerspectiveCamera;
let corridors: Map<string, CorridorViz> = new Map();
let stadiumRing: THREE.Mesh;
let stadiumRingMat: THREE.MeshStandardMaterial;
let fillGauge: THREE.Mesh;
let confetti: THREE.Points | null = null;
let clock = new THREE.Clock();
let kickoffFired = false;

export function initScene(canvas: HTMLCanvasElement, specs: CorridorSpec[]) {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);

  scene = new THREE.Scene();
  scene.background = new THREE.Color("#06090f");
  scene.fog = new THREE.Fog("#06090f", 38, 80);

  camera = new THREE.PerspectiveCamera(42, window.innerWidth / window.innerHeight, 0.1, 200);
  camera.position.set(-1, 27, 26);
  camera.lookAt(0, 0, -1);

  scene.add(new THREE.AmbientLight(0x334466, 1.6));
  const key = new THREE.DirectionalLight(0x8fb8ff, 1.2);
  key.position.set(10, 30, 10);
  scene.add(key);

  buildGround();
  buildStadium();
  for (const spec of specs) buildCorridor(spec);

  window.addEventListener("resize", () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });

  renderer.setAnimationLoop(tickFrame);
}

function buildGround() {
  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(160, 120),
    new THREE.MeshStandardMaterial({ color: "#0a101c", roughness: 1 })
  );
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = -0.05;
  scene.add(ground);

  const grid = new THREE.GridHelper(160, 80, 0x16243c, 0x101a2c);
  (grid.material as THREE.Material).transparent = true;
  (grid.material as THREE.Material).opacity = 0.5;
  scene.add(grid);

  // The Hudson — a soft blue band between Manhattan and the Meadowlands.
  const river = new THREE.Mesh(
    new THREE.PlaneGeometry(5.5, 120),
    new THREE.MeshBasicMaterial({ color: "#0c1c30", transparent: true, opacity: 0.9 })
  );
  river.rotation.x = -Math.PI / 2;
  river.position.set(-11.5, 0.01, 0);
  scene.add(river);
}

function buildStadium() {
  stadiumRingMat = new THREE.MeshStandardMaterial({
    color: "#27354d",
    emissive: "#3b5a8c",
    emissiveIntensity: 0.5,
    roughness: 0.4,
  });
  stadiumRing = new THREE.Mesh(new THREE.TorusGeometry(4.6, 1.05, 24, 80), stadiumRingMat);
  stadiumRing.rotation.x = Math.PI / 2;
  stadiumRing.position.copy(STADIUM_POS).setY(0.9);
  scene.add(stadiumRing);

  const pitch = new THREE.Mesh(
    new THREE.CircleGeometry(3.6, 48),
    new THREE.MeshBasicMaterial({ color: "#0e3d23" })
  );
  pitch.rotation.x = -Math.PI / 2;
  pitch.position.copy(STADIUM_POS).setY(0.06);
  scene.add(pitch);

  // Fill gauge: a translucent green column rising as fans arrive.
  fillGauge = new THREE.Mesh(
    new THREE.CylinderGeometry(3.3, 3.3, 1, 48, 1, true),
    new THREE.MeshBasicMaterial({
      color: "#4ade80",
      transparent: true,
      opacity: 0.16,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    })
  );
  fillGauge.scale.y = 0.001;
  fillGauge.position.copy(STADIUM_POS).setY(0.01);
  scene.add(fillGauge);
}

function buildCorridor(spec: CorridorSpec) {
  const origin = ORIGINS[spec.corridor_id] ?? new THREE.Vector3(-15, 0, 0);
  const end = STADIUM_POS.clone().setY(0.4);
  const dir = end.clone().sub(origin).normalize();
  const edge = end.clone().sub(dir.multiplyScalar(5.4)); // stop at stadium edge
  const pts = [origin.clone().setY(0.4), ...(MIDPOINTS[spec.corridor_id] ?? []), edge];
  const curve = new THREE.CatmullRomCurve3(pts, false, "catmullrom", 0.6);
  const baseColor = new THREE.Color(spec.color);

  const tubeMat = new THREE.MeshBasicMaterial({
    color: baseColor.clone(),
    transparent: true,
    opacity: 0.32,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, 80, 0.16, 10, false), tubeMat);
  scene.add(tube);

  // Fan particles
  const positions = new Float32Array(PARTICLES * 3);
  const progress = new Float32Array(PARTICLES);
  const speeds = new Float32Array(PARTICLES);
  for (let i = 0; i < PARTICLES; i++) {
    progress[i] = Math.random();
    speeds[i] = 0.045 + Math.random() * 0.035;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  const pointsMat = new THREE.PointsMaterial({
    color: baseColor.clone().lerp(new THREE.Color("#ffffff"), 0.35),
    size: 0.34,
    transparent: true,
    opacity: 0.95,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const points = new THREE.Points(geo, pointsMat);
  scene.add(points);

  // Origin: station glow + queue beacon (beam grows with queue size)
  const originGlow = new THREE.Mesh(
    new THREE.CircleGeometry(1.1, 32),
    new THREE.MeshBasicMaterial({
      color: baseColor.clone(),
      transparent: true,
      opacity: 0.5,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    })
  );
  originGlow.rotation.x = -Math.PI / 2;
  originGlow.position.copy(origin).setY(0.03);
  scene.add(originGlow);

  const queueBeacon = new THREE.Mesh(
    new THREE.RingGeometry(1.2, 1.45, 40),
    new THREE.MeshBasicMaterial({
      color: baseColor.clone(),
      transparent: true,
      opacity: 0.0,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    })
  );
  queueBeacon.rotation.x = -Math.PI / 2;
  queueBeacon.position.copy(origin).setY(0.05);
  scene.add(queueBeacon);

  const queueBeam = new THREE.Mesh(
    new THREE.CylinderGeometry(0.22, 0.34, 1, 12, 1, true),
    new THREE.MeshBasicMaterial({
      color: baseColor.clone(),
      transparent: true,
      opacity: 0.4,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      side: THREE.DoubleSide,
    })
  );
  queueBeam.scale.y = 0.001;
  queueBeam.position.copy(origin).setY(0.01);
  scene.add(queueBeam);

  corridors.set(spec.corridor_id, {
    spec,
    curve,
    tube,
    tubeMat,
    points,
    pointsMat,
    progress,
    speeds,
    activeCount: 30,
    baseColor,
    targetColor: baseColor.clone(),
    speedScale: 0.4,
    queueBeacon,
    queueBeam,
    originGlow,
    queueTarget: 0,
  });
}

/** Feed a corridor_state document from MongoDB into the scene. */
export function sceneCorridorUpdate(doc: any) {
  const c = corridors.get(doc.corridor_id);
  if (!c) return;
  const cap = Math.max(doc.capacity_per_tick ?? 1, 1);
  const flowRatio = Math.min((doc.flow ?? 0) / cap, 1);
  c.activeCount = Math.round(12 + flowRatio * (PARTICLES - 12) * Math.min((doc.in_transit ?? 0) / 2200, 1) + Math.min((doc.in_transit ?? 0) / 12, 80));
  c.activeCount = Math.min(c.activeCount, PARTICLES);
  c.speedScale = 0.35 + flowRatio * 0.95;
  c.queueTarget = Math.min((doc.queued ?? 0) / 2800, 2.2);

  const statusColor = STATUS_COLORS[doc.status];
  c.targetColor = statusColor ? new THREE.Color(statusColor) : c.baseColor.clone();
}

/** delivered fraction 0..1 — raises the stadium fill gauge. */
export function sceneSetDelivered(fraction: number) {
  const target = Math.max(0.001, fraction * 6);
  fillGauge.scale.y += (target - fillGauge.scale.y) * 0.2;
  fillGauge.position.y = (fillGauge.scale.y * 1) / 2;
}

export function sceneKickoff() {
  if (kickoffFired) return;
  kickoffFired = true;
  const N = 900;
  const pos = new Float32Array(N * 3);
  const vel: number[] = [];
  for (let i = 0; i < N; i++) {
    pos[i * 3] = STADIUM_POS.x;
    pos[i * 3 + 1] = 1.5;
    pos[i * 3 + 2] = STADIUM_POS.z;
    vel.push((Math.random() - 0.5) * 0.4, 0.25 + Math.random() * 0.4, (Math.random() - 0.5) * 0.4);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  confetti = new THREE.Points(
    geo,
    new THREE.PointsMaterial({
      color: "#ffe066",
      size: 0.3,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    })
  );
  (confetti as any).userData = { vel, age: 0 };
  scene.add(confetti);
}

export function sceneReset() {
  kickoffFired = false;
  if (confetti) {
    scene.remove(confetti);
    confetti = null;
  }
  for (const c of corridors.values()) {
    c.activeCount = 30;
    c.queueTarget = 0;
    c.targetColor = c.baseColor.clone();
  }
  fillGauge.scale.y = 0.001;
}

function tickFrame() {
  const dt = Math.min(clock.getDelta(), 0.05);
  const t = clock.elapsedTime;

  // gentle camera drift
  camera.position.x = -1 + Math.sin(t * 0.08) * 1.6;
  camera.position.y = 27 + Math.sin(t * 0.05) * 0.8;
  camera.lookAt(0, 0, -1);

  for (const c of corridors.values()) {
    // colors ease toward target
    c.tubeMat.color.lerp(c.targetColor, 0.06);
    c.pointsMat.color.lerp(c.targetColor.clone().lerp(new THREE.Color("#ffffff"), 0.35), 0.06);
    (c.originGlow.material as THREE.MeshBasicMaterial).color.lerp(c.targetColor, 0.06);
    (c.queueBeam.material as THREE.MeshBasicMaterial).color.lerp(c.targetColor, 0.06);
    (c.queueBeacon.material as THREE.MeshBasicMaterial).color.lerp(c.targetColor, 0.06);

    // queue beacon pulse + beam height
    const beaconMat = c.queueBeacon.material as THREE.MeshBasicMaterial;
    if (c.queueTarget > 0.05) {
      const pulse = 0.5 + 0.5 * Math.sin(t * 4);
      beaconMat.opacity = 0.25 + 0.45 * pulse * Math.min(c.queueTarget, 1);
      const s = 1 + c.queueTarget * 0.9 * pulse * 0.3 + c.queueTarget * 0.4;
      c.queueBeacon.scale.set(s, s, s);
    } else {
      beaconMat.opacity += (0 - beaconMat.opacity) * 0.1;
    }
    const beamTarget = Math.max(0.001, c.queueTarget * 4.2);
    c.queueBeam.scale.y += (beamTarget - c.queueBeam.scale.y) * 0.1;
    c.queueBeam.position.y = c.queueBeam.scale.y / 2;

    // particles
    const posAttr = c.points.geometry.getAttribute("position") as THREE.BufferAttribute;
    const arr = posAttr.array as Float32Array;
    const v = new THREE.Vector3();
    for (let i = 0; i < PARTICLES; i++) {
      if (i >= c.activeCount) {
        arr[i * 3 + 1] = -10; // park unused particles below ground
        continue;
      }
      c.progress[i] += c.speeds[i] * c.speedScale * dt;
      if (c.progress[i] > 1) c.progress[i] -= 1;
      c.curve.getPointAt(c.progress[i], v);
      const wob = Math.sin(t * 2 + i * 1.7) * 0.12;
      arr[i * 3] = v.x + wob;
      arr[i * 3 + 1] = v.y + 0.25 + Math.sin(t * 3 + i) * 0.06;
      arr[i * 3 + 2] = v.z + Math.cos(t * 2 + i * 2.3) * 0.12;
    }
    posAttr.needsUpdate = true;
  }

  // stadium ring shimmer
  stadiumRingMat.emissiveIntensity = 0.45 + Math.sin(t * 1.2) * 0.12;

  // confetti
  if (confetti) {
    const ud = (confetti as any).userData;
    ud.age += dt;
    const posAttr = confetti.geometry.getAttribute("position") as THREE.BufferAttribute;
    const arr = posAttr.array as Float32Array;
    for (let i = 0; i < arr.length / 3; i++) {
      arr[i * 3] += ud.vel[i * 3] * dt * 8;
      arr[i * 3 + 1] += ud.vel[i * 3 + 1] * dt * 8 - ud.age * dt * 2;
      arr[i * 3 + 2] += ud.vel[i * 3 + 2] * dt * 8;
    }
    posAttr.needsUpdate = true;
    (confetti.material as THREE.PointsMaterial).opacity = Math.max(0, 1 - ud.age / 6);
    if (ud.age > 6.5) {
      scene.remove(confetti);
      confetti = null;
    }
  }

  renderer.render(scene, camera);
}
