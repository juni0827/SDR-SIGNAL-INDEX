FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl libsndfile1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY apps apps
COPY packages packages
COPY workers workers
COPY infra infra
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app/apps/api:/app/packages/source_adapters:/app/packages/signal_processing:/app/workers/audio_processor
USER 65532:65532
