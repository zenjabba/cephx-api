# Ceph Management REST API - Dockerfile
# Multi-stage build for optimized production image

# Stage 1: Builder
FROM python:3.11-slim as builder

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        make \
        librados-dev \
        libcephfs-dev \
        librbd-dev \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /tmp/requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim

# Labels
LABEL maintainer="your-email@example.com" \
      description="Ceph Management REST API" \
      version="1.0.0"

# Install runtime dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ceph-common \
        librados2 \
        libcephfs2 \
        librbd1 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create application user
RUN groupadd -r ceph-api && \
    useradd -r -g ceph-api -s /sbin/nologin -c "Ceph API User" ceph-api

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Set environment variables
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/ceph-api

# Create application directories
RUN mkdir -p /opt/ceph-api/app \
             /opt/ceph-api/data \
             /opt/ceph-api/config \
             /var/log/ceph-api && \
    chown -R ceph-api:ceph-api /opt/ceph-api /var/log/ceph-api

# Set working directory
WORKDIR /opt/ceph-api

# Copy application code
COPY --chown=ceph-api:ceph-api app/ /opt/ceph-api/app/
COPY --chown=ceph-api:ceph-api config/ /opt/ceph-api/config/

# Copy additional files
COPY --chown=ceph-api:ceph-api VERSION /opt/ceph-api/ 2>/dev/null || true

# Health check script
COPY --chown=ceph-api:ceph-api docker/healthcheck.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/healthcheck.sh

# Switch to non-root user
USER ceph-api

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD ["/usr/local/bin/healthcheck.sh"]

# Volume for persistent data
VOLUME ["/opt/ceph-api/data", "/etc/ceph"]

# Run the application
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--workers", "4", \
     "--log-level", "info", \
     "--access-log", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
