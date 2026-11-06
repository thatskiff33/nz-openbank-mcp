# syntax=docker/dockerfile:1@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e
# Stdio by default:  docker run -i --rm -e AKAHU_USER_TOKEN -e AKAHU_APP_TOKEN ghcr.io/thatskiff33/nz-openbank-mcp
# HTTP:              docker run ... ghcr.io/thatskiff33/nz-openbank-mcp nz-openbank-mcp-http
#
# The image installs a wheel built beforehand with the hash-pinned build
# backend, so no build backend runs inside the image build. Releases install
# the wheel the release publishes to PyPI. To build locally:
#   uv build --wheel --build-constraints .github/build-constraints/requirements.txt --require-hashes
#   docker build .

FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim@sha256:7cf77f594be8042dab6daa9fe326f90962252268b4f120a7f5dccce4d947e6c1 AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
# Locked, hash-checked dependencies only; --no-build refuses source builds.
RUN uv sync --frozen --no-dev --no-install-project --no-build
# The wheel named for this pyproject version, installed with no network access.
# --no-build makes uv refuse anything but a wheel.
RUN --network=none --mount=type=bind,source=.,target=/ctx \
    set -eu; \
    uv --version; \
    version=$(python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])'); \
    wheel="/ctx/dist/nz_openbank_mcp-${version}-py3-none-any.whl"; \
    if [ ! -f "$wheel" ]; then \
      echo "dist/ has no nz_openbank_mcp ${version} wheel; build it first (see the top of this file)" >&2; \
      exit 1; \
    fi; \
    uv pip install --offline --python /app/.venv/bin/python --no-deps --no-build "$wheel"; \
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
