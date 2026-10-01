# syntax=docker/dockerfile:1
# Web build runs on the build platform only: dist/ is architecture independent.
FROM --platform=$BUILDPLATFORM node:24-slim AS web
RUN npm install -g pnpm@10
WORKDIR /web
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev
COPY tools ./tools
COPY --from=web /web/dist ./web/dist
ENV PATH="/app/.venv/bin:$PATH" WA_WEB_DIST=/app/web/dist WA_DATA_DIR=/data
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/health')"
CMD ["wheres-allie", "serve"]
