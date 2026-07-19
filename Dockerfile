# ---- Phoenix Proxy Dockerfile ----
# Single container running: MTProto proxy + FastAPI panel + Telegram bot
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps needed to build cryptography/bcrypt wheels
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libffi-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Persistent data directory (mount a Volume here on Railway)
RUN mkdir -p /data/backups

# Proxy port + Panel port
EXPOSE 443 8080

# Panel health check (used by Railway)
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:${PANEL_PORT:-8080}/health || exit 1

# main.py orchestrates all three services in one process (asyncio)
CMD ["python", "main.py"]
