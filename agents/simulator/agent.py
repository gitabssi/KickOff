"""Simulator agent — runs matchday ticks as an ADK agent.

The root LlmAgent exposes one tool, `run_matchday`, which executes the
deterministic engine (engine.py) with the agent dispatcher attached. A
before_model_callback drives the tool deterministically — the pattern the
Race Condition keynote repo uses for its tick loop — so simulating costs
zero model tokens and cannot be derailed by an LLM misrouting.

The interesting LLM reasoning happens in the agents the engine fires
*during* the run (concierges, coordinator), not in this wrapper.
"""

import json
import logging

from google.adk.agents import LlmAgent
from google.adk.models import LlmResponse
from google.genai import types

from agents.common import config
from agents.simulator.dispatcher import AgentDispatcher
from agents.simulator.engine import MatchdayEngine

logger = logging.getLogger(__name__)


async def run_matchday(message: str) -> dict:
    """Run the full matchday simulation tick loop.

    Args:
        message: JSON string with run_id and the transport plan:
            {"run_id": "...", "plan": {"corridors": [...]}}.

    Returns:
        Summary statistics once the matchday completes (~2 minutes).
    """
    payload = json.loads(message)
    run_id = payload["run_id"]
    engine = MatchdayEngine(run_id, plan=payload.get("plan") or {})
    engine.dispatcher = AgentDispatcher(engine)
    summary = await engine.run()
    return {"status": "complete", **summary}


def _deterministic_router(callback_context, llm_request) -> LlmResponse | None:
    """Drive the root agent without a model: first turn calls run_matchday
    with the raw user message; once the tool result is back, emit a short
    text summary and end the invocation."""
    for content in reversed(llm_request.contents or []):
        for part in content.parts or []:
            if part.function_response is not None:
                result = part.function_response.response or {}
                return LlmResponse(
                    content=types.Content(
                        role="model",
                        parts=[types.Part(text=json.dumps(result, default=str))],
                    )
                )

    user_text = ""
    for content in llm_request.contents or []:
        if content.role == "user":
            for part in content.parts or []:
                if part.text:
                    user_text = part.text
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part(function_call=types.FunctionCall(name="run_matchday", args={"message": user_text}))],
        )
    )


def get_agent(name: str = "simulator") -> LlmAgent:
    return LlmAgent(
        name=name,
        # Model is configured but never invoked — the deterministic router
        # intercepts every model call.
        model=config.MODEL,
        description="Runs the matchday tick loop: fan flow physics, surge detection, agent dispatch.",
        instruction="Call run_matchday with the incoming message, then summarize the result.",
        tools=[run_matchday],
        before_model_callback=_deterministic_router,
    )


root_agent = get_agent()
