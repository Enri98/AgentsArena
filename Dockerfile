# Multi-stage build for AgentsArena WebSocket server.
# Stage 1: Build dependencies in a temporary image.
FROM python:3.11-slim AS builder

WORKDIR /app

# Copy only what setuptools needs to install dependencies.
COPY pyproject.toml .
COPY src/ src/

# Install build dependencies and the package with server extras.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --upgrade pip \
    && pip install --target=/app/site-packages \
    --upgrade \
    ".[server]"


# Stage 2: Runtime image with only what we need.
FROM python:3.11-slim

WORKDIR /app

# Create non-root user (UID 1000, group 1000).
RUN groupadd -g 1000 arena && useradd -u 1000 -g 1000 -d /app arena

# Install curl for healthcheck and clean up apt.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder.
COPY --from=builder /app/site-packages /usr/local/lib/python3.11/site-packages

# Copy source code.
COPY src/arena/ /app/arena/

# Set Python path and switch to non-root user.
ENV PYTHONPATH=/app:/usr/local/lib/python3.11/site-packages
USER arena

# Expose the server port.
EXPOSE 8080

# Health check: verify the server is responding on /games endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/games || exit 1

# Run the server.
CMD ["python", "-m", "arena.server", "--host", "0.0.0.0", "--port", "8080"]
