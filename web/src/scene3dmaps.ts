/**
 * Photorealistic 3D Google Maps scene — the real Meadowlands.
 *
 * Renders the actual MetLife Stadium and the four real transport corridors
 * on Google's photorealistic 3D tiles:
 *   - corridor routes as glowing 3D polylines (color shifts on surge)
 *   - flow "pulses" sliding along each route (speed/visibility ∝ flow)
 *   - extruded queue towers at each origin (height ∝ fans queued)
 *   - cinematic camera: idle orbit, fly-to on critical surge, 360° at kickoff
 *
 * Exposes the same interface as scene.ts (the Three.js fallback used when
 * no Maps API key is configured).
 */

export interface CorridorSpec {
  corridor_id: string;
  name: string;
  color: string;
}

const STADIUM = { lat: 40.8135, lng: -74.0745 };

// Real-world anchor points, lightly stylized between waypoints.
const ROUTES: Record<string, { lat: number; lng: number }[]> = {
  rail: [
    { lat: 40.7615, lng: -74.0757 }, // Secaucus Junction
    { lat: 40.7728, lng: -74.0823 },
    { lat: 40.7905, lng: -74.0856 },
    { lat: 40.8042, lng: -74.0812 },
    STADIUM,
  ],
  shuttle_a: [
    { lat: 40.757, lng: -73.9899 }, // Port Authority
    { lat: 40.7625, lng: -74.011 }, // Lincoln Tunnel
    { lat: 40.7705, lng: -74.0335 },
    { lat: 40.7898, lng: -74.052 }, // Route 3 west
    { lat: 40.805, lng: -74.063 },
    STADIUM,
  ],
  shuttle_b: [
    { lat: 40.7527, lng: -73.9772 }, // Grand Central
    { lat: 40.7565, lng: -73.999 },
    { lat: 40.7611, lng: -74.0125 }, // tunnel approach
    { lat: 40.7762, lng: -74.041 },
    { lat: 40.7962, lng: -74.0575 },
    STADIUM,
  ],
  park_ride: [
    { lat: 40.8859, lng: -74.0435 }, // Hackensack
    { lat: 40.8612, lng: -74.0532 },
    { lat: 40.8401, lng: -74.0588 }, // Route 17 south
    { lat: 40.825, lng: -74.069 },
    STADIUM,
  ],
};

const ORIGIN_LABELS: Record<string, string> = {
  rail: "Secaucus Junction",
  shuttle_a: "Port Authority",
  shuttle_b: "Grand Central",
  park_ride: "Hackensack P&R",
};

const SURGE_COLORS: Record<string, string> = {
  surge: "#fb923cee",
  critical: "#f43f5eee",
};

interface CorridorViz {
  spec: CorridorSpec;
  dense: { lat: number; lng: number }[];
  base: any; // Polyline3DElement
  pulses: any[];
  pulseOffsets: number[];
  speed: number; // route fractions per second
  flowOn: boolean;
  queuePoly: any; // extruded Polygon3DElement
  queueHeight: number;
  queueTarget: number;
  status: string;
}

let map: any;
let maps3d: any;
let corridors = new Map<string, CorridorViz>();
let kickoffFired = false;
let lastFly = 0;
let idleAnimation: number | null = null;

function densify(points: { lat: number; lng: number }[], per = 24) {
  const out: { lat: number; lng: number }[] = [];
  for (let i = 0; i < points.length - 1; i++) {
    for (let j = 0; j < per; j++) {
      const t = j / per;
      out.push({
        lat: points[i].lat + (points[i + 1].lat - points[i].lat) * t,
        lng: points[i].lng + (points[i + 1].lng - points[i].lng) * t,
      });
    }
  }
  out.push(points[points.length - 1]);
  return out;
}

function hexToRgba(hex: string, alpha: number) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function circleCoords(center: { lat: number; lng: number }, radiusM: number, altitude: number, n = 10) {
  const coords = [];
  for (let i = 0; i <= n; i++) {
    const a = (i / n) * Math.PI * 2;
    coords.push({
      lat: center.lat + (radiusM / 111320) * Math.cos(a),
      lng: center.lng + (radiusM / (111320 * Math.cos((center.lat * Math.PI) / 180))) * Math.sin(a),
      altitude,
    });
  }
  return coords;
}

async function loadMapsApi(apiKey: string) {
  (window as any).googleMapsBootstrap = ((g: any) => {
    let h: any, a: any, k: any;
    const p = "The Google Maps JavaScript API",
      c = "google",
      l = "importLibrary",
      q = "__ib__",
      m = document,
      w = window as any;
    let b = w[c] || (w[c] = {});
    const d = b.maps || (b.maps = {}),
      r = new Set(),
      e = new URLSearchParams(),
      u = () =>
        h ||
        (h = new Promise(async (f, n) => {
          a = m.createElement("script");
          e.set("libraries", [...r] + "");
          for (k in g)
            e.set(
              k.replace(/[A-Z]/g, (t: string) => "_" + t[0].toLowerCase()),
              g[k]
            );
          e.set("callback", c + ".maps." + q);
          a.src = `https://maps.${c}apis.com/maps/api/js?` + e;
          d[q] = f;
          a.onerror = () => (h = n(Error(p + " could not load.")));
          m.head.append(a);
        }));
    d[l]
      ? console.warn(p + " only loads once. Ignoring:", g)
      : (d[l] = (f: string, ...n: any[]) => r.add(f) && u().then(() => d[l](f, ...n)));
  })({ key: apiKey, v: "alpha" });

  const g = (window as any).google;
  maps3d = await g.maps.importLibrary("maps3d");
}

export async function initScene(specs: CorridorSpec[], apiKey: string) {
  await loadMapsApi(apiKey);
  const { Map3DElement, Polyline3DElement, Polygon3DElement, Marker3DElement, AltitudeMode } = maps3d;

  map = new Map3DElement({
    center: { lat: 40.793, lng: -74.027, altitude: 0 },
    range: 16500,
    tilt: 60,
    heading: -25,
    mode: "HYBRID",
  });
  map.style.cssText = "position:fixed;inset:0;width:100vw;height:100vh;";
  document.getElementById("map3d")!.appendChild(map);

  for (const spec of specs) {
    const dense = densify(ROUTES[spec.corridor_id] ?? [STADIUM, STADIUM]);

    const base = new Polyline3DElement({
      coordinates: dense.map((p) => ({ ...p, altitude: 70 })),
      strokeColor: hexToRgba(spec.color, 0.55),
      strokeWidth: 10,
      altitudeMode: AltitudeMode.RELATIVE_TO_GROUND,
      drawsOccludedSegments: true,
    });
    map.append(base);

    const pulses: any[] = [];
    const pulseOffsets = [0, 0.5];
    for (const off of pulseOffsets) {
      const pulse = new Polyline3DElement({
        coordinates: [],
        strokeColor: hexToRgba(spec.color, 0.0),
        strokeWidth: 16,
        altitudeMode: AltitudeMode.RELATIVE_TO_GROUND,
        drawsOccludedSegments: true,
      });
      map.append(pulse);
      pulses.push(pulse);
    }

    const origin = dense[0];
    const queuePoly = new Polygon3DElement({
      outerCoordinates: circleCoords(origin, 130, 1),
      extruded: true,
      fillColor: hexToRgba(spec.color, 0.45),
      strokeColor: hexToRgba(spec.color, 0.9),
      strokeWidth: 2,
      altitudeMode: AltitudeMode.RELATIVE_TO_GROUND,
      drawsOccludedSegments: false,
    });
    map.append(queuePoly);

    const label = new Marker3DElement({
      position: { ...origin, altitude: 120 },
      altitudeMode: AltitudeMode.RELATIVE_TO_GROUND,
      extruded: true,
      label: ORIGIN_LABELS[spec.corridor_id] ?? spec.name,
    });
    map.append(label);

    corridors.set(spec.corridor_id, {
      spec,
      dense,
      base,
      pulses,
      pulseOffsets,
      speed: 0.05,
      flowOn: false,
      queuePoly,
      queueHeight: 1,
      queueTarget: 1,
      status: "ok",
    });
  }

  const stadiumMarker = new Marker3DElement({
    position: { ...STADIUM, altitude: 90 },
    altitudeMode: AltitudeMode.RELATIVE_TO_GROUND,
    extruded: true,
    label: "MetLife Stadium",
  });
  map.append(stadiumMarker);

  startFrameLoop();
  startIdleOrbit();
}

function startIdleOrbit() {
  // gentle continuous orbit; restarted after any flyCameraTo
  const orbit = () => {
    try {
      map.flyCameraAround({
        camera: { center: { ...STADIUM, altitude: 0 }, range: 12000, tilt: 58 },
        durationMillis: 120000,
        rounds: 1,
      });
    } catch {
      /* camera busy */
    }
  };
  orbit();
  idleAnimation = window.setInterval(orbit, 121000) as unknown as number;
}

function startFrameLoop() {
  let last = performance.now();
  const frame = (now: number) => {
    const dt = Math.min((now - last) / 1000, 0.1);
    last = now;
    for (const c of corridors.values()) {
      // sliding pulse windows
      if (c.flowOn) {
        const W = 0.14; // window length as route fraction
        c.pulses.forEach((pulse, i) => {
          c.pulseOffsets[i] = (c.pulseOffsets[i] + c.speed * dt) % 1;
          const start = c.pulseOffsets[i];
          const n = c.dense.length;
          const i0 = Math.floor(start * n);
          const i1 = Math.min(Math.floor((start + W) * n), n - 1);
          if (i1 > i0 + 1) {
            pulse.coordinates = c.dense.slice(i0, i1).map((p) => ({ ...p, altitude: 78 }));
            pulse.strokeColor = hexToRgba("#ffffff", 0.85);
          }
        });
      } else {
        c.pulses.forEach((p) => (p.strokeColor = "rgba(255,255,255,0)"));
      }
      // queue tower easing
      if (Math.abs(c.queueHeight - c.queueTarget) > 1) {
        c.queueHeight += (c.queueTarget - c.queueHeight) * Math.min(dt * 3, 0.3);
        c.queuePoly.outerCoordinates = circleCoords(c.dense[0], 130, Math.max(c.queueHeight, 1));
      }
    }
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

/** Feed a corridor_state document from MongoDB into the scene. */
export function sceneCorridorUpdate(doc: any) {
  const c = corridors.get(doc.corridor_id);
  if (!c) return;
  const cap = Math.max(doc.capacity_per_tick ?? 1, 1);
  const flowRatio = Math.min((doc.flow ?? 0) / cap, 1);
  c.flowOn = (doc.flow ?? 0) > 5;
  c.speed = 0.04 + flowRatio * 0.1;
  // 1m per ~12 queued fans, capped at 900m towers
  c.queueTarget = Math.min(Math.max((doc.queued ?? 0) / 12, 1), 900);

  const statusColor = SURGE_COLORS[doc.status];
  c.base.strokeColor = statusColor ?? hexToRgba(c.spec.color, 0.55);
  c.base.strokeWidth = doc.status === "critical" ? 16 : doc.status === "surge" ? 13 : 10;
  c.queuePoly.fillColor = statusColor ? hexToRgba(statusColor.slice(0, 7), 0.5) : hexToRgba(c.spec.color, 0.45);

  // Cinematic: fly to a corridor going critical (rate-limited).
  if (doc.status === "critical" && Date.now() - lastFly > 25000) {
    lastFly = Date.now();
    const origin = c.dense[0];
    try {
      map.flyCameraTo({
        endCamera: { center: { ...origin, altitude: 0 }, range: 3800, tilt: 62, heading: 0 },
        durationMillis: 2600,
      });
      setTimeout(() => {
        try {
          map.flyCameraTo({
            endCamera: { center: { ...STADIUM, altitude: 0 }, range: 12000, tilt: 58, heading: -25 },
            durationMillis: 3200,
          });
        } catch {}
      }, 7000);
    } catch {}
  }
}

export function sceneSetDelivered(_fraction: number) {
  // Stadium fill is communicated via the odometer in maps mode.
}

export function sceneKickoff() {
  if (kickoffFired) return;
  kickoffFired = true;
  try {
    map.flyCameraTo({
      endCamera: { center: { ...STADIUM, altitude: 0 }, range: 2600, tilt: 66, heading: 0 },
      durationMillis: 3000,
    });
    setTimeout(() => {
      try {
        map.flyCameraAround({
          camera: { center: { ...STADIUM, altitude: 0 }, range: 2600, tilt: 66 },
          durationMillis: 18000,
          rounds: 1,
        });
      } catch {}
    }, 3200);
  } catch {}
}

export function sceneReset() {
  kickoffFired = false;
  for (const c of corridors.values()) {
    c.queueTarget = 1;
    c.flowOn = false;
    c.base.strokeColor = hexToRgba(c.spec.color, 0.55);
  }
}
