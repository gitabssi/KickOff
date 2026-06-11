"""Environment configuration shared by every KickOff component.

All settings come from the environment. Locally a .env file at the repo root
is loaded once on first import; on Cloud Run / Agent Engine the platform
injects the same variables and no .env exists.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_REPO_ROOT / ".env")


def required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def optional(name: str, default: str = "") -> str:
    return os.environ.get(name) or default


MONGODB_DB = optional("MONGODB_DB", "kickoff")
MODEL = optional("KICKOFF_MODEL", "gemini-3-flash-preview")
PLANNER_MODEL = optional("KICKOFF_PLANNER_MODEL", MODEL)

# local = in-process ADK runners | cloud = Vertex AI Agent Engine
AGENT_MODE = optional("KICKOFF_AGENT_MODE", "local")
# local = stdio npx mongodb-mcp-server | http = hosted MCP server
MCP_MODE = optional("KICKOFF_MCP_MODE", "local")

# autopilot = concierge/coordinator decisions are deterministic, zero LLM
# calls. Useful for UI development and as a rate-limit fallback.
AUTOPILOT = optional("KICKOFF_AUTOPILOT", "") in ("1", "true", "yes")
