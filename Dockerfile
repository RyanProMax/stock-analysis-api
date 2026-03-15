# -------------------------------------------------------------
# Stage 1: Build dependencies with uv
# -------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libc-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Copy dependency files
COPY pyproject.toml uv.lock* README.md ./

# Install dependencies
RUN uv venv /app/.venv
RUN uv pip install --system -e .

# Copy application code
COPY . .

# OPTIONAL: remove build tools for smaller builder layer
RUN apt-get purge -y gcc libc-dev curl && apt-get autoremove -y


# -------------------------------------------------------------
# Stage 2: Minimal runtime image
# -------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Shanghai

WORKDIR /app

# Install curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Minimal timezone
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Copy virtual environment and source
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

# Use venv
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8080

# Default: HTTP service
# Use: docker run ... stock-analysis-api http   (HTTP API)
# Use: docker run ... stock-analysis-api mcp    (MCP Server)
CMD ["sh", "-c", "if [ \"$1\" = \"mcp\" ]; then exec python -m src.mcp_server.server; else exec uvicorn src.main:app --host 0.0.0.0 --port 8080; fi"]
