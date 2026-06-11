"""Fan Concierge — one agent per transport corridor.

Each concierge owns the fan experience on its corridor. Every decision
round it reads its corridor's live state from MongoDB through MCP, makes
exactly one operational decision, records that decision back through MCP,
and returns it as JSON so the simulator can apply the effect.

The four corridors get distinct personas — same code, different stakes —
following the Race Condition pattern of agent variants over feature flags.
"""

from google.adk.agents import LlmAgent
from google.genai import types

from agents.common import config
from agents.common.contracts import ACTIONS_EXPLAINED, DECISION_SCHEMA, MONGO_RULES
from agents.common.corridors import CORRIDOR_BY_ID
from agents.common.mcp import mongo_toolset

PERSONAS = {
    "rail": "You run the NJ Transit rail corridor from Secaucus Junction — the workhorse "
    "carrying nearly half of all fans. When rail degrades, the whole matchday degrades. "
    "You think in trainsets and platform crowd density.",
    "shuttle_a": "You run Shuttle A, the express coach corridor from Port Authority. Your fleet "
    "is flexible — you can add departures fast — but the Lincoln Tunnel is your chokepoint.",
    "shuttle_b": "You run Shuttle B, the express coach corridor from Grand Central. Smaller fleet, "
    "longer crosstown haul. You protect your corridor by reacting early, not big.",
    "park_ride": "You run the Hackensack Park & Ride shuttle loop. Lowest capacity, most local "
    "control — your shuttles turn around quickly and you know every traffic light on the route.",
}

INSTRUCTION_TEMPLATE = """\
You are {agent_name}, the Fan Concierge for the "{corridor_name}" corridor
({corridor_id}) serving World Cup 2026 at MetLife Stadium. {persona}

Each message you receive is a live tick snapshot from the matchday simulator
(JSON with run_id, tick, and all four corridors' state).

Your decision round:
1. `find` your corridor's document in `corridor_state`
   (database "kickoff", filter {{"run_id": "<run_id>", "corridor_id": "{corridor_id}"}})
   to confirm the live numbers: queued, queue_ratio, capacity_per_tick,
   boost, incident, status.
2. Make ONE decision for THIS corridor using the action rules below. Judge
   against the other corridors' numbers in the snapshot — divert only when a
   target corridor has clear headroom (queue_ratio under 1.5).
3. `insert-many` your decision document into `agent_decisions` (database "kickoff").
4. Reply with ONLY the decision JSON (no markdown fences, no prose).

{actions}

Decision document schema:
{schema}

{mongo_rules}

Be decisive and specific — cite your queue numbers in the reasoning. A boost
you already applied is in the "boost" field; don't boost past 1.6 total.
"""


def get_agent(corridor_id: str) -> LlmAgent:
    spec = CORRIDOR_BY_ID[corridor_id]
    name = f"concierge_{corridor_id}"
    return LlmAgent(
        name=name,
        model=config.MODEL,
        description=f"Fan concierge for the {spec['name']} corridor: monitors live load and decides per-tick interventions.",
        instruction=INSTRUCTION_TEMPLATE.format(
            agent_name=name,
            corridor_name=spec["name"],
            corridor_id=corridor_id,
            persona=PERSONAS[corridor_id],
            actions=ACTIONS_EXPLAINED,
            schema=DECISION_SCHEMA,
            mongo_rules=MONGO_RULES,
        ),
        tools=[mongo_toolset()],
        generate_content_config=types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=1024,
        ),
    )
