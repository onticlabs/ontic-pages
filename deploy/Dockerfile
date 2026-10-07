# The ontic-pages gateway image. The build context is the repo root:
#
#   podman build -t localhost/ontic-pages:latest \
#     --ignorefile deploy/Dockerfile.dockerignore -f deploy/Dockerfile .
#
# deploy/pages.sh runs this on the box.
FROM python:3.12-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /usr/local/bin/uv
WORKDIR /src
COPY pyproject.toml uv.lock README.md /src/
COPY src /src/src
ENV UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
RUN uv sync --locked --no-dev --no-editable

FROM python:3.12-slim-bookworm
ARG REVISION=unknown
LABEL org.opencontainers.image.title="ontic-pages gateway" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.source="https://github.com/onticlabs/ontic-pages"
# uid 10003, the same as the old gateway (10001 is atlas, 10002 is olympus on the box).
RUN useradd --system --uid 10003 --user-group --no-create-home \
      --shell /usr/sbin/nologin ontic-pages
COPY --from=build /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH HOME=/tmp PYTHONUNBUFFERED=1
USER 10003:10003
WORKDIR /tmp
EXPOSE 8790
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8790/_health', timeout=4)"]
ENTRYPOINT ["ontic-pages"]
CMD ["gateway", "--help"]
