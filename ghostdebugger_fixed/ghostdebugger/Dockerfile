# ─────────────────────────────────────────────────────────────
# GhostDebugger — Production Dockerfile
# AMD AI Developer Hackathon Act II
# ─────────────────────────────────────────────────────────────

FROM python:3.11-slim AS base

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY agents/   ./agents/
COPY core/     ./core/
COPY api/      ./api/
COPY frontend/ ./frontend/

# Create __init__.py files
RUN touch agents/__init__.py core/__init__.py api/__init__.py frontend/__init__.py

# ─────────────────────────────────────────────────────────────
# Runtime stage
# ─────────────────────────────────────────────────────────────
FROM base AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    APP_ENV=production \
    LOG_LEVEL=INFO \
    SANDBOX_TIMEOUT=10 \
    SANDBOX_MEMORY_MB=256 \
    MAX_CODE_LENGTH=10000

# Health check — FastAPI must respond before container is "healthy"
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start script runs both FastAPI + Streamlit
COPY start.sh .
RUN chmod +x start.sh

# Non-root user — the sandbox executes arbitrary/LLM-generated code,
# so it must never run as root even inside the container.
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000 8501

CMD ["./start.sh"]
