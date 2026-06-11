# ruff: noqa
"""agent-starter-pack entry point.

The starter pack convention expects `agents/agent.py` to expose a root
agent and an App. KickOff's root agent is the Matchday Coordinator — the
operations chief that orchestrates the planner over A2A and rebalances
corridors during surges. The full agent fleet (planner, simulator, four
concierges) lives in the sibling packages and deploys via
scripts/deploy_agents.py.
"""

import os

import google.auth
from google.adk.apps import App

# Gemini 3 preview models are served from the global endpoint.
try:
    _, _project_id = google.auth.default()
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", _project_id or "")
except google.auth.exceptions.DefaultCredentialsError:
    pass  # local tooling without ADC; agents.common.config loads .env
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

from agents.coordinator.agent import get_agent

root_agent = get_agent()

app = App(
    root_agent=root_agent,
    name="agents",
)
