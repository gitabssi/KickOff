"""MongoDB Atlas MCP toolset for KickOff agents.

Every agent that reasons over matchday data gets its tools from the official
MongoDB MCP server (https://github.com/mongodb-js/mongodb-mcp-server), so
reads and writes happen through MCP tool calls — visible in agent traces and
in the UI's MongoDB ops ticker.

Two transports:
  local (default) — spawn `npx -y mongodb-mcp-server` over stdio.
  http            — connect to a hosted MCP server (Cloud Run) via
                    streamable HTTP; required on Agent Engine where no Node
                    runtime exists.
"""

import os

from google.adk.tools.mcp_tool import (
    McpToolset,
    StdioConnectionParams,
    StreamableHTTPConnectionParams,
)
from mcp import StdioServerParameters

from agents.common import config

# Whitelist: everything an agent needs to read state, write decisions, and
# evolve the schema mid-run — nothing destructive (no drops, no deletes).
ALLOWED_TOOLS = [
    "find",
    "aggregate",
    "count",
    "insert-many",
    "update-many",
    "create-collection",
    "create-index",
    "list-collections",
    "collection-schema",
]


def mongo_toolset(tool_filter: list[str] | None = None) -> McpToolset:
    """Build an MCP toolset connected to MongoDB Atlas.

    Each agent gets its own toolset instance (and its own MCP session).
    """
    tools = tool_filter or ALLOWED_TOOLS

    if config.MCP_MODE == "http":
        url = config.required("MCP_SERVER_URL")
        return McpToolset(
            connection_params=StreamableHTTPConnectionParams(url=url, timeout=30),
            tool_filter=tools,
        )

    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="npx",
                args=["-y", "mongodb-mcp-server", "--transport", "stdio"],
                env={
                    **os.environ,
                    "MDB_MCP_CONNECTION_STRING": config.required("MONGODB_URI"),
                    "MDB_MCP_TELEMETRY": "disabled",
                },
            ),
            timeout=60,
        ),
        tool_filter=tools,
    )
