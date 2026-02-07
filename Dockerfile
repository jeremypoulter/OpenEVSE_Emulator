# OpenEVSE Emulator Dockerfile
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

# Copy application code
COPY src/ ./src/
COPY config.json .
COPY openapi.yaml .

# Expose ports
# 8080 - Web UI and API
# 8023 - TCP serial port (when in TCP mode)
EXPOSE 8080 8023

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the emulator
CMD ["python", "src/main.py"]
