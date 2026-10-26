# ── Telecom AI Platform — Tool API Service ────────────────────────────────
#
# Build:
#   docker build -t telecom-tool-api .
#
# Run (standalone):
#   docker run -p 8000:8000 \
#     -e TOOL_API_KEY=your-key \
#     -e GOLD_PARQUET_PATH=/data/gold/features.parquet \
#     -v /local/data:/data \
#     telecom-tool-api

FROM python:3.11-slim AS base

# System dependencies required by spatial libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libgeos-dev \
        libgdal-dev \
        && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Dependency layer (cached unless requirements.txt changes) ─────────────
COPY requirements.txt ./
# Install only the packages needed by the API (skip heavy orchestration deps)
RUN pip install --no-cache-dir \
        fastapi>=0.110.0 \
        "uvicorn[standard]>=0.27.0" \
        httpx>=0.26.0 \
        PyYAML>=6.0.1 \
        pydantic>=2.5.0 \
        h3>=3.7.7 \
        pandas>=2.1.0 \
        pyarrow>=14.0.0 \
        scikit-learn>=1.4.0 \
        hdbscan>=0.8.33 \
        joblib>=1.3.0 \
        python-dotenv>=1.0.0 \
    && pip install --no-cache-dir umap-learn>=0.5.5 || true

# ── Application code ──────────────────────────────────────────────────────
COPY api/       ./api/
COPY ml/        ./ml/

# Generate OpenAPI schema at build time so the image ships with openapi.yaml
COPY export_openapi.py ./
RUN python export_openapi.py --out openapi.yaml || true

# ── Runtime configuration ─────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LOG_LEVEL=INFO \
    API_VERSION=1.0.0 \
    GOLD_PARQUET_PATH=/data/gold/features.parquet

EXPOSE 8000

# Non-root user for security
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
