# syntax=docker/dockerfile:1@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e
# Stdio by default:  docker run -i --rm -e AKAHU_USER_TOKEN -e AKAHU_APP_TOKEN ghcr.io/thatskiff33/nz-openbank-mcp
# HTTP:              docker run ... ghcr.io/thatskiff33/nz-openbank-mcp nz-openbank-mcp-http
#
# The image installs a wheel built beforehand with the hash-pinned build
# backend, so no build backend runs inside the image build. Releases install
# the wheel published to PyPI. To build locally:
#   uv build --wheel --build-constraints .github/build-constraints/requirements.txt --require-hashes
#   docker build .

FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim@sha256:7cf77f594be8042dab6daa9fe326f90962252268b4f120a7f5dccce4d947e6c1 AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
# Locked, hash-checked dependencies only. --no-build refuses any source build.
RUN uv sync --frozen --no-dev --no-install-project --no-build
COPY dist/ /tmp/dist/
RUN set -eu; \
    set -- /tmp/dist/nz_openbank_mcp-*-py3-none-any.whl; \
    if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then \
      echo "dist/ must hold exactly one nz_openbank_mcp wheel; build it first (see the top of this file)" >&2; \
      exit 1; \
    fi; \
    uv pip install --python /app/.venv/bin/python --no-deps --no-build "$1"; \
    uv pip check --python /app/.venv/bin/python

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
