# =============================================================================
# Customer Support Service — Dockerfile
# =============================================================================
# Purpose
# --------
# Defines a reproducible, minimal, and secure container image for the Customer Support Service.
#
# Design Principles
# -----------------
# - Deterministic build: dependencies and base image are version pinned.
# - Separation of concerns: code and dependencies are isolated.
# - Security: runs as a non-root user and never embeds secrets.
#
# Usage
# -----
# Build the image:
#   docker build -t customer-support-service:latest .
#
# Run (Command-line interface):
#   docker run --rm -it \
#     --env-file ./.env \
#     customer-support-service:latest --cli
#
# Run (Web API interface):
#   docker run --rm -p 8000:8000 \
#     --env-file ./.env \
#     customer-support-service:latest
#
# Notes
# -----
# - Pass OPENAI_API_KEY via --env-file or -e. Do not bake secrets into the image.
# - The data/ and prompts/ are copied into the image. Mount them read-only when
#   iterating locally to avoid rebuilds.
# =============================================================================

# -----------------------------------------------------------------------------
# Base image
# -----------------------------------------------------------------------------
# Use a slim Python base to reduce attack surface and image size.
ARG PYTHON_VERSION=3.11-slim-bookworm
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
        libgomp1 \
        sqlite3 \
        libsqlite3-dev \
        build-essential \
    ; \
    rm -rf /var/lib/apt/lists/*; \
    groupadd -g "${APP_GID}" "${APP_USER}"; \
    useradd -m -u "${APP_UID}" -g "${APP_GID}" -s /bin/bash "${APP_USER}"

# -----------------------------------------------------------------------------
# Working directory and dependency installation
# -----------------------------------------------------------------------------
WORKDIR /customer-support-service

# Copy dependency manifest first to leverage Docker layer caching.
COPY requirements.txt ./requirements.txt

# Add the application root to PYTHONPATH for predictable imports.
ENV PYTHONPATH=/customer-support-service

# Enable static compilation of pysqlite3 with an embedded modern SQLite library for full compatibility.
ENV PSQLITE3_BUILD_WITH_BUNDLED_SQLITE=1

# Install Python dependencies with caching disabled to minimize image size.
# All versions are pinned in requirements.txt for deterministic builds.
RUN set -eux; \
    pip install --no-cache-dir --upgrade pip wheel; \
    pip install --no-cache-dir -r requirements.txt;

# -----------------------------------------------------------------------------
# Copy application source
# -----------------------------------------------------------------------------
# Copy all service files into the container.
# For local development, mount ./data and ./prompts as read-only volumes.
COPY . .

# Create writable directories for caches, tests, and persistent Chroma storage.
RUN mkdir -p /customer-support-service/.pytest_cache \
        /customer-support-service/chroma_store \
        /customer-support-service/.cache \
    && chown -R ${APP_UID}:${APP_GID} /customer-support-service/.pytest_cache \
        /customer-support-service/chroma_store \
        /customer-support-service/.cache

# -----------------------------------------------------------------------------
# Runtime configuration
# -----------------------------------------------------------------------------
# Default environment variables for logging, console formatting,
# and Chroma vector database persistence.
ENV LOG_LEVEL=INFO \
    ENABLE_COLOR=true \
    RAG_CHROMA_DIR=/customer-support-service/chroma_store \
    RAG_CHROMA_COLLECTION=customer_support_knowledge \
    HF_HUB_DISABLE_PROGRESS_BARS=1 \
    TQDM_DISABLE=1 \
    HF_HUB_ENABLE_TELEMETRY=0 \
    POSTHOG_DISABLED=1 \
    SENTENCE_TRANSFORMERS_HOME=/customer-support-service/.cache/sbert \
    TRANSFORMERS_VERBOSITY=error

# -----------------------------------------------------------------------------
# Network and runtime
# -----------------------------------------------------------------------------
# Expose the HTTP port used by the FastAPI service.
EXPOSE 8000

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

# Start the CLI service.
# Uncomment this line only when running the service in CLI mode and ensure the Web API command is commented out.
# CMD ["python", "app.py", "--cli"]

# Start the Web API service on port 8000 as the default behavior.
# Uncomment this line only when running the service in Web API mode and ensure the CLI command is commented out.
CMD ["python", "app.py"]
