# Synapse — minimal Dockerfile for the Python SDK + gateway.
# For multi-service local dev (Redis + Postgres + gateway), use docker-compose.yml.

FROM python:3.12-slim

WORKDIR /app

# System deps (psycopg2 needs libpq; curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install the SDK
COPY sdk-python/ /app/sdk-python/
RUN pip install --no-cache-dir -e /app/sdk-python

# Default: launch the gateway. Override with `docker run … synapse watch` etc.
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "runtime.gateway.server:app", "--host", "0.0.0.0", "--port", "8000"]
