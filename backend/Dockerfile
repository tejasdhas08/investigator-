FROM python:3.12-slim AS base
WORKDIR /srv/backend
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS worker-cpu
CMD ["celery", "-A", "app.pipeline.celery_app.celery", "worker", "-Q", "cpu", "-l", "info", "--concurrency", "2"]

FROM base AS worker-gpu
COPY requirements-cv.txt .
RUN pip install --no-cache-dir -r requirements-cv.txt
CMD ["celery", "-A", "app.pipeline.celery_app.celery", "worker", "-Q", "gpu", "-l", "info", "--concurrency", "1"]

FROM base AS beat
CMD ["celery", "-A", "app.pipeline.celery_app.celery", "beat", "-l", "info"]
