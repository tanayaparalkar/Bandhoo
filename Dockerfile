# ==============================================================================
# Bandhoo FastAPI Backend - Production Dockerfile
# Optimized for Kubernetes (Minikube), Azure Container Apps (ACA), and AWS ECS/EKS
# Base Image: Python 3.11 Slim
# ==============================================================================

FROM python:3.11-slim AS runtime

LABEL maintainer="Bandhoo Team" \
      version="1.0.0" \
      description="Bandhoo Criminal Law Decision Support & Complaint Structuring Backend"

# Prevents Python from writing pyc files and buffers stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BANDHOO_HOST=0.0.0.0 \
    BANDHOO_PORT=8001 \
    BANDHOO_STORAGE_DIR=/app/private_storage \
    BANDHOO_SKIP_DOTENV=1 \
    REQUIRE_METRICS=1 \
    ENABLE_METRICS=true

WORKDIR /app

# Install system dependencies required for compilation, database connectors, and healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements lock/spec first to leverage Docker layer caching
COPY requirements.txt .

# Upgrade pip and install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Create an unprivileged non-root user (security best practice for K8s & Azure Container Apps)
RUN useradd -m -u 10001 -s /bin/bash appuser && \
    mkdir -p /app/private_storage && \
    chown -R appuser:appuser /app

# Copy application modules and datasets with proper ownership
COPY --chown=appuser:appuser datasets/ ./datasets/
COPY --chown=appuser:appuser legal_engine/ ./legal_engine/
COPY --chown=appuser:appuser complaint_engine/ ./complaint_engine/
COPY --chown=appuser:appuser db/ ./db/
COPY --chown=appuser:appuser migrations/ ./migrations/
COPY --chown=appuser:appuser alembic.ini .
COPY --chown=appuser:appuser main.py .

# Switch to non-root execution
USER appuser

# Expose FastAPI application port
EXPOSE 8001

# Container healthcheck for Kubernetes / Docker / Azure App Service
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://127.0.0.1:8001/health || exit 1

# Start Uvicorn ASGI server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]

