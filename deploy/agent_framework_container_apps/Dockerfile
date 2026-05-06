# Multi-stage build for Azure Twilio Agent Connect deployment
FROM python:3.13-slim AS builder

# Set working directory
WORKDIR /app

# Copy requirements file
COPY agent_framework_container_apps/requirements.txt /app/requirements.txt

# Install dependencies (twilio-agent-connect-microsoft from PyPI, pulls in twilio-agent-connect transitively)
RUN pip install --no-cache-dir -r requirements.txt

# Final stage
FROM python:3.13-slim

# Install runtime dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY agent_framework_container_apps/server.py ./

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Run as non-root user
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Run the application
CMD ["python", "server.py"]
