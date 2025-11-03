# Multi-stage build for optimal size and security
FROM python:3.11-slim-bullseye as builder

# Build-time environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    python3-dev \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and build wheels
COPY requirements.txt .
# Build wheels for requirements AND their dependencies so the final stage can
# install from the wheel directory offline. Removing `--no-deps` ensures
# transitive dependencies are collected into /app/wheels.
RUN pip wheel --no-cache-dir --wheel-dir /app/wheels -r requirements.txt

# ==============================================================================
# Final stage - minimal runtime image
# ==============================================================================
FROM python:3.11-slim-bullseye

# Runtime environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    # Privacy: Disable telemetry
    TRANSFORMERS_OFFLINE=0 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    # Performance
    MALLOC_TRIM_THRESHOLD_=100000

WORKDIR /app

# Install runtime dependencies (PIL/Pillow needs these)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libjpeg62-turbo \
    zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user with specific UID/GID for security
RUN groupadd -r -g 1000 appuser && \
    useradd -r -u 1000 -g appuser -m -s /sbin/nologin appuser

# Copy wheels and install
COPY --from=builder /app/requirements.txt .
# Install Python dependencies directly from PyPI in the final image. This
# trades a slightly longer build time for reliability (ensures packages are
# installed into the final environment correctly).
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY --chown=appuser:appuser app.py .
COPY --chown=appuser:appuser static/ ./static/

# Create directory for potential .env file (not copied, mounted at runtime)
RUN mkdir -p /app/config && chown appuser:appuser /app/config

# Security: Remove any unnecessary files and set proper permissions
RUN find /app -type d -exec chmod 755 {} + && \
    find /app -type f -exec chmod 644 {} + && \
    chmod 644 /app/app.py

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Enhanced healthcheck with better parameters
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Security: Add labels for documentation
LABEL maintainer="your-email@example.com" \
      description="FLUX Image Generator API with Privacy Protection" \
      version="1.0" \
      security.no-root="true" \
      privacy.token-caching="disabled"

# Start application with optimized settings
CMD ["uvicorn", "app:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--log-level", "info", \
     "--no-access-log", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]