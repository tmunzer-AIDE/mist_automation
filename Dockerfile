# Stage 1: Build Angular frontend
FROM node:22-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npx ng build --deploy-url static/

# Stage 2: Python runtime
FROM python:3.12-slim AS runtime
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# Copy backend and install from pyproject.toml
COPY backend/ .
RUN pip install --no-cache-dir -e "."

# Copy built frontend into the backend static directory
COPY --from=frontend-build /build/dist/frontend/browser/index.html app/frontend/index.html
COPY --from=frontend-build /build/dist/frontend/browser/ app/frontend/static/
RUN rm -f app/frontend/static/index.html

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
