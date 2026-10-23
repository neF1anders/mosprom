FROM node:22-bookworm-slim AS frontend
WORKDIR /web
COPY src/web/package*.json ./
RUN npm ci
COPY src/web/ ./
RUN npm run build

FROM python:3.11-slim-bookworm AS pythonbase
ENV PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
COPY requirements-runtime.txt ./
RUN pip install --no-cache-dir -r requirements-runtime.txt
RUN useradd --uid 10001 --create-home app && mkdir -p /data && chown app:app /data

FROM pythonbase AS browserbase
COPY requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt
COPY --from=frontend /usr/local/bin/node /usr/local/bin/node
COPY --from=frontend /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
COPY --from=frontend /web/node_modules /opt/web/node_modules
RUN /opt/web/node_modules/.bin/playwright install --with-deps chromium

FROM pythonbase AS runtime
COPY src/backend/ src/backend/
COPY src/mesh_analysis.py src/mesh_analysis.py
COPY migrations/ migrations/
COPY alembic.ini pyproject.toml ./
COPY knowledge/ knowledge/
COPY scripts/import_knowledge.py scripts/import_knowledge.py
COPY --from=frontend /web/dist src/web/dist
USER app
CMD ["uvicorn", "src.backend.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

FROM browserbase AS tests
COPY --from=runtime /app /app
COPY --from=frontend /web src/web
COPY scripts/ scripts/
COPY tests/ tests/
COPY pytest.ini .coveragerc requirements-dev.txt ./
CMD ["python", "scripts/run_tests.py"]
