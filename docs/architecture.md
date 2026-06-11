# KickOff Agent — Architecture

## Design principles

1. **MongoDB Atlas is the single source of truth and the event bus.** Agents
   never message the frontend; they write documents. The gateway converts
   one database-wide change stream into Server-Sent Events. If it's on
   screen, it's in Atlas.
2. **LLMs reason around the physics, never inside it.** The tick loop is
   deterministic Python (reproducible, free, fast); Gemini 3 agents are
   dispatched asynchronously at decision points and their effects apply on
   the next tick. The animation never stalls on a model call.
3. **One entry point for agent traffic.** `agents/common/dispatch.dispatch()`
   routes to in-process ADK runners (local) or Agent Engine streamQuery
   endpoints (cloud). Agent code is identical in both modes.

## Data flow on a run

```
click LAUNCH
  └─ gateway: insert runs{status: planning}            ──► change stream ──► UI
  └─ dispatch(coordinator, {action: launch})
       └─ coordinator ──call_agent (A2A)──► planner
            └─ planner: MCP find (baseline) → reason → MCP insert plan ──► UI banner
  └─ dispatch(simulator, {action: execute, plan})
       └─ engine: 100 ticks × ~1.2s
            ├─ per tick: update 4× corridor_state + insert ticks doc ──► UI bars/clock/particles
            ├─ scripted incidents (tick 28 rail, tick 55 tunnel)
            ├─ surge lifecycle → surge_alerts ──► UI alerts
            └─ fire-and-forget dispatch:
                 ├─ concierge round (every 12 ticks, staggered)
                 │    └─ concierge: MCP find → decide → MCP insert decision ──► UI feed
                 │         └─ return JSON → engine.queue_effect → applied next tick
                 ├─ coordinator on critical surge
                 │    └─ MCP find ×4 → create surge_history (first time) → directives
                 └─ post-match report
```

## The simulator's deterministic wrapper

`agents/simulator/agent.py` is an `LlmAgent` whose `before_model_callback`
returns canned responses: first a `run_matchday` function call, then a text
summary. The "model" is configured but never billed. This is the same trick
the Race Condition keynote repo uses for its race engine — an agent that is
100% reliable because the LLM cannot misroute it, while still being a
first-class ADK/Agent Engine citizen.

## Crowd model

- 82,500 fans, gaussian arrival curve (peak T−60, σ≈52 min) over 90 ticks.
- Corridor capacity/tick: rail 480, Shuttle A 200, Shuttle B 160, P&R 120
  (total 960 vs ~1,270 peak demand → queues at peak by construction).
- Surge: queue > 3× tick capacity. Critical: > 6×. Resolved: < 1.5×.
- Agent effects: `boost_capacity` (×1.05–1.5, cap 1.6 total), `divert`
  (move 2–20% of arrival share), `hold`/`advise` (no mechanical effect).
- Baseline (agents off): 87.9% delivered. With agent interventions: ~99.6%.

## MCP integration modes

| Mode | Transport | Used by |
|---|---|---|
| `local` | stdio — each agent spawns `npx mongodb-mcp-server` | local dev, self-contained Cloud Run demo |
| `http` | streamable HTTP — `kickoff-mcp` Cloud Run service | Agent Engine deployments (no Node runtime there) |

Tool whitelist (`agents/common/mcp.py`): find, aggregate, count,
insert-many, update-many, create-collection, create-index,
list-collections, collection-schema. Nothing destructive.

## Failure modes and what happens

| Failure | Behavior |
|---|---|
| Gemini quota / API error | dispatch retries ×3 with backoff; a missed concierge round skips (engine never blocks); `KICKOFF_AUTOPILOT=1` removes LLMs entirely |
| Atlas unreachable at boot | gateway serves UI, health shows `atlas: down`, change-stream watcher reconnects with backoff |
| Change stream drops mid-run | watcher reconnects (1s → 30s backoff); UI shows RECONNECTING; `/api/state` restores on refresh |
| Agent returns malformed JSON | `extract_json` salvages the first JSON object; otherwise the decision is logged-and-skipped |
| Concierge forgets its MCP write | dispatcher inserts the returned decision as fallback (marked `via: return_value`) |
