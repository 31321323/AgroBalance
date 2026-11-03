FROM node:22-bookworm-slim AS frontend
WORKDIR /build
RUN npm install -g pnpm@11.25.0
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.lock.txt /app/backend/requirements.lock.txt
RUN pip install --no-cache-dir -r backend/requirements.lock.txt && useradd --create-home agro
COPY backend/ /app/backend/
COPY --from=frontend /build/dist /app/frontend/dist/
USER agro
EXPOSE 8000
CMD ["sh", "-c", "python -m alembic -c backend/alembic.ini upgrade head && python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000"]
