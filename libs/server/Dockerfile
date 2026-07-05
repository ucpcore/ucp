# syntax=docker/dockerfile:1

# --- build stage: build the wheel, keep build tooling out of the image -------
FROM python:3.12-slim AS build

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir build && python -m build --wheel --outdir /dist

# --- runtime stage ------------------------------------------------------------
FROM python:3.12-slim

LABEL org.opencontainers.image.title="ucp-server" \
      org.opencontainers.image.description="Self-hosted UCP generation service: REST + MCP (Streamable HTTP)" \
      org.opencontainers.image.url="https://ucpcore.org" \
      org.opencontainers.image.source="https://github.com/ucpcore/ucp" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.vendor="UCP contributors"

RUN useradd --create-home --uid 1000 ucp

COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

# 0.0.0.0 is deliberate inside the container: the container boundary is the
# isolation; publish the port consciously (see README, Security).
ENV UCP_SERVER_HOST=0.0.0.0 \
    UCP_SERVER_PORT=8080 \
    UCP_CACHE_DIR=/home/ucp/.cache/ucp-server

USER ucp
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4)"]

ENTRYPOINT ["ucp-server"]
