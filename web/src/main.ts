/**
 * KickOff Agent frontend — wiring layer.
 *
 * One source of truth: the SSE stream of MongoDB Atlas change events from
 * the gateway. Every visual (3D corridors, cards, feed, alerts, ticker) is
 * a projection of database writes made by the agents.
 */
import "./style.css";
import {
  buildCorridorCards,
  updateCorridorCard,
  addDecision,
  upsertAlert,
  banner,
  updateTick,
  animateOdometer,
  recordMongoOp,
  primeCollections,
  setMongoLive,
} from "./panels";

let runId: string | null = null;
let corridorColors: Record<string, string> = {};
let fansTotal = 82500;
let kickoffShown = false;
let eventSource: EventSource | null = null;

// Scene implementation: photorealistic 3D Google Maps when a Maps API key
// is configured, Three.js stylized fallback otherwise. Same interface.
let sceneCorridorUpdate: ((doc: any) => void) | undefined;
let sceneSetDelivered: ((f: number) => void) | undefined;
let sceneKickoff: (() => void) | undefined;
let sceneReset: (() => void) | undefined;

async function initSceneImpl(cfg: any) {
  if (cfg.maps_api_key) {
    try {
      const m = await import("./scene3dmaps");
      await m.initScene(cfg.corridors, cfg.maps_api_key);
      (document.getElementById("scene") as HTMLCanvasElement).style.display = "none";
      ({ sceneCorridorUpdate, sceneSetDelivered, sceneKickoff, sceneReset } = m);
      return;
    } catch (e) {
      // The maps3d alpha channel changes under us — never let the scene
      // take the control panel down with it.
      console.error("3D Maps scene failed, using stylized fallback:", e);
      document.getElementById("map3d")!.replaceChildren();
    }
  }
  const m = await import("./scene");
  m.initScene(document.getElementById("scene") as HTMLCanvasElement, cfg.corridors);
  ({ sceneCorridorUpdate, sceneSetDelivered, sceneKickoff, sceneReset } = m);
}

async function boot() {
  // Wire the launch button before anything that can fail — the demo must
  // always be launchable even if the scene or state restore breaks.
  document.getElementById("launch-btn")!.addEventListener("click", launch);

  const cfg = await (await fetch("/api/config")).json();
  fansTotal = cfg.fans_total;
  document.getElementById("fans-total")!.textContent = fansTotal.toLocaleString("en-US");
  for (const c of cfg.corridors) corridorColors[c.corridor_id] = c.color;

  await initSceneImpl(cfg);
  buildCorridorCards(cfg.corridors);
  animateOdometer();

  // Collections that exist at boot are not "new" — only a mid-run creation
  // (surge_history) should trigger the schema-evolution banner.
  primeCollections(["runs", "transport_plans", "corridor_state", "ticks", "agent_decisions", "surge_alerts"]);

  // Resume an in-flight run on refresh.
  const state = await (await fetch("/api/state")).json();
  if (state.run && (state.run.status === "simulating" || state.run.status === "planning" || state.run.status === "plan_ready")) {
    runId = state.run.run_id;
    document.getElementById("launch-wrap")!.classList.add("hidden");
    state.corridors?.forEach((c: any) => {
      updateCorridorCard(c);
      sceneCorridorUpdate?.(c);
    });
    if (state.last_tick) updateTick(state.last_tick);
    state.decisions?.slice().reverse().forEach((d: any) => addDecision(d, corridorColors));
    connectStream();
  }
}

async function launch() {
  const btn = document.getElementById("launch-btn") as HTMLButtonElement;
  btn.disabled = true;
  (btn.querySelector(".btn-label") as HTMLElement).textContent = "PLANNING…";
  try {
    const res = await fetch("/api/launch", { method: "POST" });
    const body = await res.json();
    runId = body.run_id;
    sceneReset?.();
    kickoffShown = false;
    connectStream();
    setTimeout(() => {
      document.getElementById("launch-wrap")!.classList.add("hidden");
    }, 600);
    banner("PLANNER DESIGNING TRANSPORT PLAN", "success");
  } catch {
    btn.disabled = false;
    (btn.querySelector(".btn-label") as HTMLElement).textContent = "LAUNCH SIMULATION";
    banner("LAUNCH FAILED — IS THE GATEWAY UP?", "critical");
  }
}

function connectStream() {
  eventSource?.close();
  eventSource = new EventSource(`/api/stream${runId ? `?run_id=${runId}` : ""}`);
  eventSource.addEventListener("change", (e) => handleChange(JSON.parse((e as MessageEvent).data)));
  eventSource.onerror = () => setMongoLive(false);
  eventSource.onopen = () => setMongoLive(true);
}

function handleChange(event: any) {
  const isNewCollection = recordMongoOp(event);
  if (isNewCollection && event.collection === "surge_history") {
    banner("⬢ NEW COLLECTION CREATED LIVE: surge_history", "mongo");
  }

  const doc = event.doc ?? {};
  switch (event.collection) {
    case "corridor_state":
      updateCorridorCard(doc);
      sceneCorridorUpdate?.(doc);
      break;

    case "ticks":
      updateTick(doc);
      sceneSetDelivered?.((doc.delivered_total ?? 0) / fansTotal);
      if (doc.phase === "kickoff" && !kickoffShown) {
        kickoffShown = true;
        sceneKickoff?.();
        banner("⚽ KICKOFF — MATCH UNDERWAY", "success");
      }
      break;

    case "agent_decisions":
      if (event.operation === "insert") {
        addDecision(doc, corridorColors);
        if (doc.action === "incident") banner(doc.headline?.toUpperCase() ?? "INCIDENT", "critical");
      }
      break;

    case "surge_alerts":
      upsertAlert(doc);
      if (doc.status === "active" && doc.severity === "critical") {
        banner(`CRITICAL SURGE — ${doc.corridor_name?.toUpperCase()}`, "critical");
      }
      break;

    case "transport_plans":
      if (event.operation === "insert" && doc.narrative) {
        addDecision(
          {
            agent: "planner",
            tick: 0,
            action: "advise",
            headline: "Transport plan ready",
            reasoning: doc.narrative,
            corridor_id: "rail",
          },
          corridorColors
        );
        banner("TRANSPORT PLAN COMMITTED TO ATLAS", "mongo");
      }
      break;

    case "runs":
      if (doc.status === "complete") {
        const s = doc.summary ?? {};
        banner(
          `FULL TIME · ${(s.delivered ?? 0).toLocaleString("en-US")} FANS DELIVERED (${Math.round((s.delivery_rate ?? 0) * 100)}%)`,
          "success"
        );
        const wrap = document.getElementById("launch-wrap")!;
        const btn = document.getElementById("launch-btn") as HTMLButtonElement;
        setTimeout(() => {
          wrap.classList.remove("hidden");
          btn.disabled = false;
          (btn.querySelector(".btn-label") as HTMLElement).textContent = "RUN IT AGAIN";
        }, 6000);
      }
      if (doc.status === "failed") {
        banner("RUN FAILED — CHECK GATEWAY LOGS", "critical");
        const btn = document.getElementById("launch-btn") as HTMLButtonElement;
        btn.disabled = false;
        (btn.querySelector(".btn-label") as HTMLElement).textContent = "LAUNCH SIMULATION";
        document.getElementById("launch-wrap")!.classList.remove("hidden");
      }
      break;
  }
}

boot();
