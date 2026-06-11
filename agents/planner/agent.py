"""Planner — designs the matchday transport plan for MetLife Stadium.

Reads the baseline plan template from MongoDB through the MCP server,
adapts corridor shares and capacities for the scenario it is given, writes
the run-specific plan back to `transport_plans` through MCP, and returns
the plan as JSON for the coordinator.
"""

from google.adk.agents import LlmAgent
from google.genai import types

from agents.common import config
from agents.common.mcp import mongo_toolset

INSTRUCTION = """\
You are the Transport Planner for FIFA World Cup 2026 matchdays at MetLife
Stadium, East Rutherford NJ. 82,500 fans, no fan parking — everyone arrives
through 4 managed corridors: NJ Transit Rail from Secaucus (rail), Shuttle A
from Port Authority (shuttle_a), Shuttle B from Grand Central (shuttle_b),
and the Hackensack Park & Ride (park_ride).

You will receive a launch message with a run_id and scenario notes.

Work through these steps:
1. `find` the baseline template in the `transport_plans` collection
   (database "kickoff", filter {"plan_id": "baseline"}). It contains the
   corridor specs: capacity_per_tick, preference_share, transit_ticks.
2. Decide your matchday plan: per-corridor preference_share (must sum to
   1.0) and capacity_per_tick. You may shift shares a few points or
   pre-boost a corridor's capacity up to +15% based on the scenario notes
   (weather, expected transit pressure). Anchor on the baseline numbers —
   do not invent corridors or wild values.
3. Write your plan: `insert-many` into `transport_plans` (database
   "kickoff") one document:
   {"plan_id": "<run_id>", "kind": "matchday", "run_id": "<run_id>",
    "corridors": [{"corridor_id", "preference_share", "capacity_per_tick"} x4],
    "narrative": "<3-4 sentence plan summary for the operations room>",
    "risks": ["<top 2-3 risks you anticipate>"]}
4. Reply with ONLY that same JSON document (no markdown fences, no prose).

Numbers discipline: preference_share values must sum to 1.0 (±0.01).
capacity_per_tick must stay within 85%-115% of baseline values.
"""


def get_agent(name: str = "planner") -> LlmAgent:
    return LlmAgent(
        name=name,
        model=config.PLANNER_MODEL,
        description=(
            "Designs World Cup matchday transport plans for MetLife Stadium: "
            "corridor demand shares, capacities, and risk narrative, persisted to MongoDB."
        ),
        instruction=INSTRUCTION,
        tools=[mongo_toolset()],
        generate_content_config=types.GenerateContentConfig(
            temperature=0.4,
            max_output_tokens=2048,
        ),
    )


root_agent = get_agent()
