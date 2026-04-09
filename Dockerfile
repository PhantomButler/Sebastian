FROM python:3.12-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer cache)
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[memory]"

# Copy source
COPY sebastian/ ./sebastian/
COPY .env.example ./.env.example

# Create data dir
RUN mkdir -p /app/data /app/data/sessions/sebastian /app/data/sessions/subagents /app/knowledge

CMD ["uvicorn", "sebastian.gateway.app:app", "--host", "0.0.0.0", "--port", "8823"]
