# Multi-stage build with slim final image
FROM node:22-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

RUN printf '#!/bin/bash\nuv run python agent.py start &\nuv run uvicorn server:app --host 0.0.0.0 --port 7860\n' > start.sh \
    && chmod +x start.sh

EXPOSE 7860

# LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, SARVAM_API_KEY, etc.
# are provided via HF Space secrets at runtime.

CMD ["./start.sh"]
