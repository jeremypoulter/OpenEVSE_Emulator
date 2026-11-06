# OpenEVSE Emulator Dockerfile
#
# Two stages: the first builds the real OpenEVSE safety firmware natively (for
# engine mode), the second is the emulator, which carries the resulting
# binaries. The Python EVSE stays the default; engine mode is opt-in with
# ENGINE_ENABLED=true (and ENGINE_BOARD=oev6|nxt).

# ---- firmware source -------------------------------------------------------
# Fetched from git by default. To build a local checkout instead, hand BuildKit
# a clean export of it as this stage (see DOCKER.md):
#   docker buildx build --build-context firmware-src=/path/to/open_evse .
#
# FIRMWARE_REPO is a GitHub owner/repo. FIRMWARE_REF is a branch, tag or commit;
# CI passes the exact commit it resolved. A branch name would let Docker reuse
# a cached layer after the branch has moved, so the image could carry older
# firmware than the one the tests ran against -- a commit changes the build
# argument and so the layer.
FROM alpine/git AS firmware-fetch
ARG FIRMWARE_REPO=jeremypoulter/open_evse
ARG FIRMWARE_REF=feat/native-target
RUN git init -q /src \
    && cd /src \
    && git remote add origin "https://github.com/${FIRMWARE_REPO}.git" \
    && git fetch -q --depth 1 origin "${FIRMWARE_REF}" \
    && git checkout -q FETCH_HEAD \
    && git rev-parse HEAD > /src/.firmware-commit

FROM scratch AS firmware-src
COPY --from=firmware-fetch /src /

# ---- firmware build --------------------------------------------------------
FROM python:3.13-slim AS firmware-build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    git \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir platformio
COPY --from=firmware-src / /src
WORKDIR /src
RUN pio run -e native_oev6 -e native_nxt \
    && mkdir -p /out \
    && cp .pio/build/native_oev6/program /out/native_oev6 \
    && cp .pio/build/native_nxt/program /out/native_nxt \
    && (cp .firmware-commit /out/FIRMWARE_COMMIT 2>/dev/null || echo "local build" > /out/FIRMWARE_COMMIT)

# ---- emulator --------------------------------------------------------------
FROM python:3.14-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Natively-built firmware for engine mode, one binary per board
COPY --from=firmware-build /out/ /opt/openevse/

# Copy application code
COPY src/ ./src/
COPY config.json .
COPY openapi.yaml .

# Expose ports
# 8080 - Web UI and API
# 8023 - TCP serial port (when in TCP mode)
EXPOSE 8080 8023

# Set environment variables
# OPENEVSE_NATIVE_DIR is where engine mode looks for the firmware
ENV PYTHONUNBUFFERED=1 \
    OPENEVSE_NATIVE_DIR=/opt/openevse

# Run the emulator
CMD ["python", "src/main.py"]
