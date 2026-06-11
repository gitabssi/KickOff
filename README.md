# ⚽ KickOff Agent

**A multi-agent World Cup 2026 fan-logistics simulation for MetLife Stadium — live on MongoDB Atlas, reasoning on Gemini 3, orchestrated with Google ADK.**

MetLife Stadium hosts the World Cup 2026 final: **82,500 fans, no fan parking**. Everyone arrives through four managed transport corridors. One button launches a full matchday: fans flood the network, a signal failure cripples the rail line at the worst moment, AI agents read the live database, reason, disagree, escalate, and rebalance the flow — every decision persisted to MongoDB Atlas and streamed to a 3D operations view in real time.

```
┌─────────────┐   SSE (Atlas change events)   ┌──────────────────────────────┐
│  Frontend    │ ◄──────────────────────────── │  Gateway (FastAPI, Cloud Run) │
│  Three.js    │   POST /api/launch ─────────► │  thin: agents own all state   │
└─────────────┘                               └──────────┬───────────────────┘
                                                          │ dispatch (A2A)
                  ┌───────────────────────────────────────┼─────────────────┐
                  ▼                   ▼                   ▼                 ▼
            ┌──────────┐       ┌───────────┐       ┌────────────┐   ┌──────────────┐
            │ Planner   │      │ Coordinator│       │ Simulator  │   │ 4× Concierge │
            │ (Gemini 3)│◄─A2A─│ (Gemini 3) │       │ tick engine│──►│  (Gemini 3)  │
            └─────┬─────┘      └─────┬──────┘       └─────┬──────┘   └──────┬───────┘
                  │                  │                    │                 │
                  ▼                  ▼                    ▼                 ▼
            ╔══════════════════════════════════════════════════════════════════╗
            ║                MongoDB Atlas  (via MongoDB MCP server)            ║
            ║  transport_plans · corridor_state · ticks · agent_decisions       ║
            ║  surge_alerts · surge_history (created LIVE mid-run by an agent)  ║
            ╚══════════════════════════════════════════════════════════════════╝
```

## Why MongoDB is the spine, not a sidecar

1. **Agents read and write through the MongoDB MCP server.** Every concierge decision starts with an MCP `find` on live corridor state and ends with an MCP `insert-many` into `agent_decisions`. No hardcoded state anywhere.
2. **Atlas change streams ARE the UI.** The gateway holds one change stream over the database and forwards every event to the browser. When a decision card appears on screen, you are watching the actual insert hit Atlas — the bottom bar counts every op.
3. **Schema evolution, live, mid-simulation.** The first time a surge goes critical, the Coordinator agent creates a brand-new `surge_history` collection (`create-collection` + `create-index` over MCP) while the simulation is running. The UI celebrates it the moment the change stream sees the first write. No migration, no downtime — that's the document model.

## The cast

| Agent | Model | Role |
|---|---|---|
| **Planner** | Gemini 3 | Reads the baseline plan from Atlas, designs the matchday corridor split, commits the plan |
| **Coordinator** | Gemini 3 | Orchestrates: calls the planner over A2A at launch; during critical surges reads the whole network and issues cross-corridor rebalance directives; creates `surge_history`; writes the match report |
| **Simulator** | deterministic ADK agent | Runs 100 matchday ticks (1 tick = 2 sim-minutes): demand curve, queues, transit, surge detection. Zero LLM tokens — driven by a `before_model_callback`, the keynote-proven pattern |
| **4× Fan Concierge** | Gemini 3 | One per corridor (rail / Shuttle A / Shuttle B / Park & Ride), distinct personas; each decision round: MCP read → one decision → MCP write |

Agent-to-agent traffic flows through a single `dispatch()` entry point: in-process ADK runners locally, Vertex AI Agent Engine endpoints in the cloud.

## The matchday arc (what you'll watch)

- **T−180:00** — Launch. Planner commits the transport plan to Atlas.
- **T−124:00** — Scripted incident: *signal failure at Secaucus Junction*, rail capacity cut to 45%.
- **~T−120** — Rail queue explodes past 3× capacity: **SURGE**. The rail concierge boosts service.
- **~T−115** — Queue passes 6×: **CRITICAL**. Coordinator wakes, creates `surge_history` live, diverts 10% of arrivals and boosts healthy corridors.
- **T−80 → T−40** — Peak crush. Concierges keep deciding every round; a second incident hits the Lincoln Tunnel.
- **T−0** — Kickoff. Confetti. Without agents the network strands ~10,000 fans (87.9% delivered); with agents it delivers ~99.6%.

## Quickstart (local)

Prereqs: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 20+, a free [MongoDB Atlas](https://cloud.mongodb.com) M0 cluster, a GCP project with Vertex AI enabled.

```bash
cp .env.example .env       # fill in MONGODB_URI + GOOGLE_CLOUD_PROJECT
make init                  # uv sync + npm install
make seed                  # collections, indexes, baseline plan
make build                 # frontend -> gateway/static
make dev                   # http://localhost:8080 — press the button
```

`gcloud auth application-default login` is required for Gemini calls in local mode.

**No LLM access / no quota?** `KICKOFF_AUTOPILOT=1 make dev` runs the identical simulation with deterministic agent policies — same decision feed, same Mongo writes, zero model calls (the Race Condition `runner_autopilot` pattern).

## Deploy (Google Cloud)

```bash
make deploy-mcp        # MongoDB MCP server -> Cloud Run
make deploy-agents     # agents -> Vertex AI Agent Engine (planner, simulator, 4 concierges, then coordinator)
make deploy-gateway    # frontend+gateway -> Cloud Run
```

Hosted modes: the gateway image bundles Node, so it can also run the full demo self-contained (`AGENT_MODE=local`, default) — flip to `cloud` to route every agent call through Agent Engine:

```bash
bash scripts/deploy_gateway.sh PROJECT_ID us-central1 cloud
```

## Repo map

```
agents/
  common/        config, corridor model, MCP toolset factory, dispatch (A2A), contracts
  planner/       plan design agent
  concierge/     per-corridor fan concierge (4 personas)
  coordinator/   orchestrator + surge rebalancing + schema evolution
  simulator/     engine.py (tick physics) · dispatcher.py (engine->agents) · agent.py (ADK wrapper)
gateway/         FastAPI: /api/launch, SSE stream of Atlas change events, static frontend
web/             Vite + TypeScript + Three.js operations view
scripts/         seed_db.py, deploy_mcp.sh, deploy_agents.py, deploy_gateway.sh
docs/            demo-script.md, architecture.md
```

## MongoDB schema

| Collection | Writer | Shape |
|---|---|---|
| `transport_plans` | Planner (MCP) | one plan doc per run + baseline template |
| `corridor_state` | Simulator engine | 4 live docs per run, updated every tick (the UI bars) |
| `ticks` | Simulator engine | per-tick snapshot: clock, phase, totals |
| `agent_decisions` | Concierges + Coordinator (MCP) | append-only decision log with reasoning |
| `surge_alerts` | Simulator engine | surge lifecycle: active → critical → resolved |
| `surge_history` | **Coordinator (MCP), created mid-run** | permanent surge record + per-tick readings |

## Honest design notes

- The tick physics is deterministic code, not LLM output — by design. LLMs reason *around* the physics (what to do about a surge), never inside it, so the animation never stalls on a model call and runs are reproducible. This mirrors the Race Condition keynote architecture.
- Engine telemetry (per-tick state) goes through the driver; *agent reasoning* goes through MCP. High-frequency telemetry through an LLM tool-call loop would add latency and nothing else.
- The hosted MCP server is deployed `--allow-unauthenticated` for demo simplicity (the connection string stays server-side). Lock it with Cloud Run IAM for anything real.

## License

Apache 2.0 — see [LICENSE](LICENSE).
