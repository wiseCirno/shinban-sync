FROM node:22-bookworm-slim AS web

WORKDIR /web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web ./
RUN pnpm generate

FROM python:3.13-slim

WORKDIR /shinban-sync

RUN apt-get update && apt-get install -y --no-install-recommends \
        cron \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1 \
    ACG_RIP_MIN_INTERVAL_SECONDS=2.0 \
    ACG_RIP_RETRY_AFTER_SECONDS=30.0 \
    ACG_RIP_MAX_ATTEMPTS=3

RUN pip install --no-cache-dir "poetry==2.5.1"

COPY pyproject.toml poetry.lock README.md ./
COPY src ./src
RUN poetry install --only main --no-interaction \
    && pip uninstall -y poetry \
    && rm -rf /root/.cache

COPY --from=web /web/.output/public /shinban-sync/web-dist
ENV SHINBAN_WEB_DIST=/shinban-sync/web-dist

VOLUME /app
EXPOSE 3325

ENTRYPOINT ["shinban-sync"]
CMD ["run", "--modules", "sync", "-c", "/app/config.yml"]
