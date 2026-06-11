"""Agent dispatch — one entry point for all agent-to-agent traffic.

`await dispatch(agent_name, message)` is how the gateway and the simulator
reach other agents, mirroring the single-entry-point pattern from the Race
Condition reference architecture.

local mode  — agents run in-process on ADK InMemoryRunners. Zero deploy
              friction, identical agent code to cloud.
cloud mode  — agents are Vertex AI Agent Engine deployments; messages go
              through the Agent Engine streamQuery REST API. The mapping
              from agent name to engine resource is written by
              scripts/deploy_agents.py into .deploy/agent_engines.json.
"""

import asyncio
import json
import logging
import uuid
from pathlib import Path

from google.genai import types

from agents.common import config

logger = logging.getLogger(__name__)

_runners: dict = {}
_runner_lock = asyncio.Lock()

ENGINES_FILE = Path(__file__).resolve().parent.parent.parent / ".deploy" / "agent_engines.json"


def _build_agent(name: str):
    """Late import so each agent module only loads when first used."""
    if name == "planner":
        from agents.planner.agent import get_agent
        return get_agent()
    if name == "coordinator":
        from agents.coordinator.agent import get_agent
        return get_agent()
    if name == "simulator":
        from agents.simulator.agent import get_agent
        return get_agent()
    if name.startswith("concierge_"):
        from agents.concierge.agent import get_agent
        return get_agent(corridor_id=name.removeprefix("concierge_"))
    raise ValueError(f"Unknown agent: {name}")


async def _get_runner(name: str):
    from google.adk.runners import InMemoryRunner

    async with _runner_lock:
        if name not in _runners:
            _runners[name] = InMemoryRunner(agent=_build_agent(name), app_name=name)
        return _runners[name]


async def _dispatch_local(name: str, message: str) -> str:
    runner = await _get_runner(name)
    session_id = str(uuid.uuid4())
    await runner.session_service.create_session(app_name=name, user_id="kickoff", session_id=session_id)

    final_text = ""
    content = types.Content(role="user", parts=[types.Part(text=message)])
    async for event in runner.run_async(user_id="kickoff", session_id=session_id, new_message=content):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    final_text = part.text
    return final_text


def _load_engine_map() -> dict:
    """Agent name -> reasoningEngine resource. From AGENT_ENGINES_JSON env
    (set on deployed services) or .deploy/agent_engines.json (local file
    written by scripts/deploy_agents.py)."""
    env_map = config.optional("AGENT_ENGINES_JSON")
    if env_map:
        return json.loads(env_map)
    return json.loads(ENGINES_FILE.read_text())


async def _dispatch_cloud(name: str, message: str) -> str:
    """Query a deployed Agent Engine via the streamQuery REST API."""
    import httpx
    import google.auth
    import google.auth.transport.requests

    engines = _load_engine_map()
    resource = engines[name]  # projects/../locations/../reasoningEngines/..

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    location = config.optional("GOOGLE_CLOUD_LOCATION", "us-central1")
    url = f"https://{location}-aiplatform.googleapis.com/v1/{resource}:streamQuery?alt=sse"

    final_text = ""
    async with httpx.AsyncClient(timeout=600) as http:
        async with http.stream(
            "POST",
            url,
            headers={"Authorization": f"Bearer {creds.token}"},
            json={
                "class_method": "async_stream_query",
                "input": {"user_id": "kickoff", "message": message},
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line[len("data:"):].strip())
                except json.JSONDecodeError:
                    continue
                for part in event.get("content", {}).get("parts", []):
                    if part.get("text"):
                        final_text = part["text"]
    return final_text


async def dispatch(name: str, message: str, retries: int = 2) -> str:
    """Send a message to an agent and return its final text response."""
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            if config.AGENT_MODE == "cloud":
                return await _dispatch_cloud(name, message)
            return await _dispatch_local(name, message)
        except Exception as e:  # noqa: BLE001 — surface after retries
            last_error = e
            logger.warning("dispatch %s attempt %d failed: %s", name, attempt + 1, e)
            await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"dispatch to {name} failed after {retries + 1} attempts") from last_error


def extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of an LLM response (handles ``` fences)."""
    if not text:
        return None
    cleaned = text.strip()
    if "```" in cleaned:
        for chunk in cleaned.split("```"):
            chunk = chunk.strip().removeprefix("json").strip()
            if chunk.startswith("{"):
                cleaned = chunk
                break
    start = cleaned.find("{")
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(cleaned[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(cleaned[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None
