# KickOff gateway image for Cloud Run.
#
# Ships both Python (gateway + in-process agents) and Node (stdio MongoDB
# MCP server), so a single Cloud Run service can run the complete demo in
# local agent mode — and flips to Agent Engine mode via KICKOFF_AGENT_MODE.

# ---- frontend build ----
FROM node:22-slim AS webbuild
WORKDIR /app/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npx vite build

# ---- runtime ----
FROM python:3.12-slim

# Node 22 for the stdio MongoDB MCP server (local agent mode).
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g mongodb-mcp-server@1.12.0 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
# Install the exact locked dependency set — a fresh resolve here once pulled
# in a google-adk whose MCP schema validation broke against the MongoDB MCP
# server's tool schemas.
RUN pip install --no-cache-dir uv \
    && uv export --frozen --no-dev --no-hashes --no-emit-project -o /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements.txt
COPY agents/ agents/
COPY gateway/ gateway/
RUN pip install --no-cache-dir --no-deps .

COPY --from=webbuild /app/gateway/static gateway/static

ENV PORT=8080
CMD ["sh", "-c", "uvicorn gateway.main:app --host 0.0.0.0 --port ${PORT}"]
