# MongoDB MCP server on Cloud Run — streamable HTTP transport.
# Agents on Vertex AI Agent Engine connect here for all reasoning
# reads/writes against Atlas.
FROM node:22-slim

RUN npm install -g mongodb-mcp-server@1.12.0

ENV MDB_MCP_TELEMETRY=disabled

# MDB_MCP_CONNECTION_STRING is injected at deploy time (Cloud Run env/secret).
CMD ["sh", "-c", "mongodb-mcp-server --transport http --httpHost 0.0.0.0 --httpPort ${PORT:-8080}"]
