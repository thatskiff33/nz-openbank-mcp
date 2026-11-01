# syntax=docker/dockerfile:1
# Stdio by default:  docker run -i --rm -e AKAHU_USER_TOKEN -e AKAHU_APP_TOKEN ghcr.io/thatskiff33/nz-openbank-mcp
# HTTP:              docker run ... ghcr.io/thatskiff33/nz-openbank-mcp nz-openbank-mcp-http

FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim@sha256:7cf77f594be8042dab6daa9fe326f90962252268b4f120a7f5dccce4d947e6c1 AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim-bookworm@sha256:516b51cb9db2ef061e465c803e50f64361b82cefd91e525b889b967b83e83527
LABEL org.opencontainers.image.source="https://github.com/thatskiff33/nz-openbank-mcp" \
      org.opencontainers.image.description="MCP server for New Zealand open banking via Akahu. Read-only by default." \
      org.opencontainers.image.licenses="Apache-2.0"
RUN useradd --system --uid 10001 --home-dir /var/lib/nz-openbank-mcp --create-home app
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    AKAHU_READ_ONLY=true \
    AKAHU_AUTOMATION_BYPASS=false \
    NZ_OPENBANK_MCP_STATE_DIR=/var/lib/nz-openbank-mcp \
    FASTMCP_HOME=/var/lib/nz-openbank-mcp/fastmcp
USER app
WORKDIR /var/lib/nz-openbank-mcp
VOLUME ["/var/lib/nz-openbank-mcp"]
EXPOSE 8091
CMD ["nz-openbank-mcp"]
