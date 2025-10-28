# =============================================================================
# UI Service — Dockerfile
# =============================================================================
# Purpose
# --------
# Defines a reproducible, minimal, and secure container image for the UI Service.
#
# Design Principles
# -----------------
# - Deterministic build: base image and dependencies are version pinned.
# - Separation of concerns: UI-only image, no backend or model packages.
# - Security: runs as a non-root user and never embeds secrets.
#
# Usage
# -----
# Build the image:
#   docker build -t ui-service:latest .
#
# Run the UI on port 8501:
#   docker run --rm -p 8501:8501 \
#     -e BACKEND_BASE_URL="http://localhost:8000" \
#     ui-service:latest
#
# Environment
# -----------
# - BACKEND_BASE_URL: Base URL of the backend API (default: http://localhost:8000)
# =============================================================================

# -----------------------------------------------------------------------------
# Base image
# -----------------------------------------------------------------------------
# Use a slim Python base to reduce attack surface and image size.
ARG PYTHON_VERSION=3.11-slim
FROM python:${PYTHON_VERSION} AS runtime

# -----------------------------------------------------------------------------
# Environment hardening and Python ergonomics
# -----------------------------------------------------------------------------
# - Prevent Python from writing .pyc files to disk.
# - Enable unbuffered output for immediate log flushing.
# - Disable pip cache to save space and ensure deterministic builds.
# - Suppress root-user warnings from pip during Docker builds.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore

# Define non-root runtime user and group for better security posture.
ARG APP_USER=appuser
ARG APP_UID=10001
ARG APP_GID=10001

# Install minimal OS packages and create the secure runtime user.
RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        tini \
    ; \
    rm -rf /var/lib/apt/lists/*; \
    groupadd -g "${APP_GID}" "${APP_USER}"; \
    useradd  -m -u "${APP_UID}" -g "${APP_GID}" -s /bin/bash "${APP_USER}"

# -----------------------------------------------------------------------------
# Working directory and dependency installation
# -----------------------------------------------------------------------------
WORKDIR /ui-service

# Copy dependency manifest first to leverage Docker layer caching.
COPY requirements.txt ./requirements.txt

# Install Python dependencies with caching disabled to minimize image size.
# All versions are pinned in requirements.txt for deterministic builds.
RUN pip install --no-cache-dir -r requirements.txt

# -----------------------------------------------------------------------------
# Copy application source
# -----------------------------------------------------------------------------
# Copy all service files into the container.
COPY . .

# -----------------------------------------------------------------------------
# Runtime configuration
# -----------------------------------------------------------------------------
# Streamlit settings to reduce telemetry and ensure clean logs.
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_HEADLESS=true

# Default backend base URL used by the UI (can be overridden at runtime).
ENV BACKEND_BASE_URL=http://localhost:8000

# -----------------------------------------------------------------------------
# Network and runtime
# -----------------------------------------------------------------------------
# Streamlit listens on 8501 by default.
EXPOSE 8501

# -----------------------------------------------------------------------------
# Runtime security
# -----------------------------------------------------------------------------
# Enforce execution as a non-root user to reduce privilege risks.
USER ${APP_USER}:${APP_USER}

# -----------------------------------------------------------------------------
# Entrypoint and execution command
# -----------------------------------------------------------------------------
# Use tini as the container init process to handle signal forwarding and zombies.
ENTRYPOINT ["/usr/bin/tini", "--"]

# Start the Streamlit web UI on 0.0.0.0:8501 as the default behavior.
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
