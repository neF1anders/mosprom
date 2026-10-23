FROM node:22-bookworm-slim AS frontend
WORKDIR /web
COPY src/web/package*.json ./
RUN npm ci
COPY src/web/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.11.26@sha256:3d868e555f8f1dbc324afa005066cd11e1053fc4743b9808ca8025283e65efa5 AS uv

FROM python:3.11-slim-bookworm AS pythonbase
ENV PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
    UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN --mount=from=uv,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project --python /usr/local/bin/python3
RUN useradd --uid 10001 --create-home app && mkdir -p /data && chown app:app /data

FROM scratch AS appfiles
COPY src/backend/ /src/backend/
COPY src/mesh_analysis.py /src/mesh_analysis.py
COPY migrations/ /migrations/
COPY alembic.ini /alembic.ini
COPY knowledge/ /knowledge/
COPY scripts/import_knowledge.py /scripts/import_knowledge.py
COPY --from=frontend /web/dist /src/web/dist

FROM pythonbase AS browserbase
RUN --mount=from=uv,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --python /usr/local/bin/python3
COPY --from=frontend /usr/local/bin/node /usr/local/bin/node
COPY --from=frontend /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
COPY --from=frontend /web/node_modules /opt/web/node_modules
RUN /opt/web/node_modules/.bin/playwright install --with-deps chromium

FROM pythonbase AS runtime
COPY --from=appfiles / /app/
USER app
CMD ["uvicorn", "src.backend.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

FROM browserbase AS tests
COPY --from=appfiles / /app/
COPY --from=frontend /web src/web
COPY scripts/ scripts/
COPY tests/ tests/
COPY pytest.ini .coveragerc ./
CMD ["python", "scripts/run_tests.py"]
