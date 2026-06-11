/**
 * DOM panels: corridor cards, agent decision feed, surge alerts, the
 * MongoDB ops ticker, clock and odometer. Pure render functions fed by
 * change events — no local simulation logic.
 */

const AGENT_LABELS: Record<string, string> = {
  concierge_rail: "CONCIERGE · RAIL",
  concierge_shuttle_a: "CONCIERGE · SHUTTLE A",
  concierge_shuttle_b: "CONCIERGE · SHUTTLE B",
  concierge_park_ride: "CONCIERGE · PARK & RIDE",
  coordinator: "COORDINATOR",
  planner: "PLANNER",
  simulator: "MATCHDAY CONTROL",
};

const ACTION_LABELS: Record<string, string> = {
  boost_capacity: "BOOST CAPACITY",
  divert: "DIVERT FLOW",
  hold: "HOLD",
  advise: "ADVISORY",
  incident: "INCIDENT",
};

const fmt = (n: number) => Math.round(n).toLocaleString("en-US");

// ---------------------------------------------------------------------------
// Corridor cards
// ---------------------------------------------------------------------------

const cards = new Map<string, HTMLElement>();

export function buildCorridorCards(specs: any[]) {
  const panel = document.getElementById("corridors-panel")!;
  panel.innerHTML = "";
  cards.clear();
  for (const s of specs) {
    const el = document.createElement("div");
    el.className = "corridor-card";
    el.style.setProperty("--c", s.color);
    el.innerHTML = `
      <div class="cc-head">
        <span class="cc-name">${s.name}</span>
        <span class="cc-status">READY</span>
      </div>
      <div class="cc-origin">from ${s.origin}</div>
      <div class="cc-bar"><div class="cc-bar-fill"></div></div>
      <div class="cc-stats">
        <span>flow <b class="s-flow">0</b>/tick</span>
        <span>queue <b class="s-queue">0</b></span>
        <span>arrived <b class="s-delivered">0</b></span>
      </div>
      <div class="cc-badges"></div>`;
    panel.appendChild(el);
    cards.set(s.corridor_id, el);
  }
}

export function updateCorridorCard(doc: any) {
  const el = cards.get(doc.corridor_id);
  if (!el) return;
  el.classList.toggle("surge", doc.status === "surge");
  el.classList.toggle("critical", doc.status === "critical");

  const status = el.querySelector(".cc-status")!;
  status.textContent = (doc.status ?? "ok").toUpperCase();
  status.className = `cc-status ${doc.status}`;

  const util = Math.min(((doc.flow ?? 0) / Math.max(doc.capacity_per_tick ?? 1, 1)) * 100, 100);
  (el.querySelector(".cc-bar-fill") as HTMLElement).style.width = `${util}%`;
  el.querySelector(".s-flow")!.textContent = fmt(doc.flow ?? 0);
  el.querySelector(".s-queue")!.textContent = fmt(doc.queued ?? 0);
  el.querySelector(".s-delivered")!.textContent = fmt(doc.delivered ?? 0);

  const badges = el.querySelector(".cc-badges")!;
  badges.innerHTML = "";
  if ((doc.boost ?? 1) > 1.01) {
    badges.insertAdjacentHTML("beforeend", `<span class="badge boost">⚡ +${Math.round((doc.boost - 1) * 100)}% SERVICE</span>`);
  }
  if (doc.incident) {
    badges.insertAdjacentHTML("beforeend", `<span class="badge incident">⚠ ${doc.incident}</span>`);
  }
}

// ---------------------------------------------------------------------------
// Decision feed
// ---------------------------------------------------------------------------

export function addDecision(doc: any, corridorColors: Record<string, string>) {
  const feed = document.getElementById("feed")!;
  const el = document.createElement("div");
  const isCoord = doc.agent === "coordinator";
  const isIncident = doc.action === "incident";
  el.className = `decision${isCoord ? " coordinator" : ""}${isIncident ? " incident" : ""}`;
  el.style.setProperty("--c", isCoord ? "#fbbf24" : corridorColors[doc.corridor_id] ?? "#9ab");

  const directives = (doc.directives ?? [])
    .map((d: any) => `<span class="d-action">${ACTION_LABELS[d.action] ?? d.action}${d.divert_to ? " → " + d.divert_to.toUpperCase() : ""}</span>`)
    .join(" ");

  el.innerHTML = `
    <div class="d-head">
      <span class="d-agent">${AGENT_LABELS[doc.agent] ?? doc.agent?.toUpperCase() ?? "AGENT"}</span>
      <span class="d-tick">tick ${doc.tick ?? "—"}</span>
    </div>
    <div class="d-headline">${doc.headline ?? ""}</div>
    <div class="d-reason">${doc.reasoning ?? ""}</div>
    <span class="d-action">${ACTION_LABELS[doc.action] ?? doc.action ?? ""}</span> ${directives}`;
  feed.prepend(el);
  while (feed.children.length > 40) feed.lastChild!.remove();
}

// ---------------------------------------------------------------------------
// Surge alerts
// ---------------------------------------------------------------------------

const alertEls = new Map<string, HTMLElement>();

export function upsertAlert(doc: any) {
  const wrap = document.getElementById("alerts")!;
  let el = alertEls.get(doc.surge_id);
  if (!el) {
    el = document.createElement("div");
    alertEls.set(doc.surge_id, el);
    wrap.prepend(el);
  }
  const resolved = doc.status === "resolved";
  el.className = `alert${resolved ? " resolved" : ""}`;
  el.innerHTML = `
    <div class="alert-head"><span class="alert-dot"></span>
      ${resolved ? "SURGE RESOLVED" : doc.severity === "critical" ? "CRITICAL SURGE" : "SURGE ALERT"}
    </div>
    <div class="alert-msg">${doc.message ?? ""}</div>`;
  if (resolved) {
    setTimeout(() => {
      el!.remove();
      alertEls.delete(doc.surge_id);
    }, 8000);
  }
  while (wrap.children.length > 3) wrap.lastChild!.remove();
}

// ---------------------------------------------------------------------------
// Banners (center-stage drama)
// ---------------------------------------------------------------------------

export function banner(text: string, kind: "warn" | "critical" | "success" | "mongo" = "warn") {
  const wrap = document.getElementById("banner")!;
  const el = document.createElement("div");
  el.className = `banner-item ${kind}`;
  el.textContent = text;
  wrap.appendChild(el);
  setTimeout(() => el.remove(), 6200);
}

// ---------------------------------------------------------------------------
// Clock / odometer / phase
// ---------------------------------------------------------------------------

const PHASE_LABELS: Record<string, string> = {
  early_arrivals: "GATES OPEN",
  building: "CROWDS BUILDING",
  peak_crush: "PEAK CRUSH",
  final_approach: "FINAL APPROACH",
  kickoff: "KICKOFF",
};

let displayedFans = 0;
let fansTarget = 0;

export function updateTick(doc: any) {
  const tMin = doc.t_minus_minutes ?? 0;
  const clock = document.getElementById("clock")!;
  clock.textContent = tMin >= 0 ? `T−${String(tMin).padStart(3, "0")}:00` : `+${-tMin}:00`;
  const phase = document.getElementById("phase-chip")!;
  phase.textContent = PHASE_LABELS[doc.phase] ?? doc.phase ?? "";
  phase.className = `clock-label${doc.phase === "peak_crush" || doc.phase === "final_approach" ? " hot" : ""}`;
  fansTarget = doc.delivered_total ?? 0;
}

export function animateOdometer() {
  if (Math.abs(displayedFans - fansTarget) > 1) {
    displayedFans += (fansTarget - displayedFans) * 0.12;
    document.getElementById("fans-delivered")!.textContent = fmt(displayedFans);
  }
  requestAnimationFrame(animateOdometer);
}

// ---------------------------------------------------------------------------
// MongoDB ops ticker + counters
// ---------------------------------------------------------------------------

const opCounts = new Map<string, number>();
const knownCollections = new Set<string>();
let totalOps = 0;

export function recordMongoOp(event: any): boolean {
  totalOps++;
  const coll = event.collection;
  opCounts.set(coll, (opCounts.get(coll) ?? 0) + 1);

  const ticker = document.getElementById("mongo-ticker")!;
  const op = document.createElement("span");
  op.className = "op";
  const verb = event.operation === "insert" ? "insert" : event.operation === "update" ? "update" : event.operation;
  op.innerHTML = `✓ ${verb} <span class="op-coll">${coll}</span>${event.doc?.corridor_id ? " · " + event.doc.corridor_id : ""}`;
  ticker.prepend(op);
  while (ticker.children.length > 6) ticker.lastChild!.remove();

  renderCounters();

  const isNew = !knownCollections.has(coll);
  knownCollections.add(coll);
  return isNew;
}

export function primeCollections(colls: string[]) {
  colls.forEach((c) => knownCollections.add(c));
}

function renderCounters() {
  const el = document.getElementById("mongo-counters")!;
  const parts = [...opCounts.entries()].map(([c, n]) => `<span>${c} <b>${n}</b></span>`);
  parts.push(`<span>total ops <b>${totalOps}</b></span>`);
  el.innerHTML = parts.join("");
}

export function setMongoLive(up: boolean) {
  const el = document.getElementById("mongo-live")!;
  el.textContent = up ? "● LIVE" : "● RECONNECTING";
  el.className = `mongo-live${up ? "" : " down"}`;
}
