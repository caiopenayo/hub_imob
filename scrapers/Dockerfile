FROM python:3.11-slim
WORKDIR /src

COPY backend/requirements.txt /src/backend-requirements.txt
COPY scrapers/requirements.txt /src/scrapers-requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && pip install --no-cache-dir -r /src/backend-requirements.txt -r /src/scrapers-requirements.txt \
    && apt-get remove -y build-essential \
    && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY backend /src/backend
COPY scrapers /src/scrapers

ENV PYTHONUNBUFFERED=1

# Default: dedicated scheduler process. Use --run-due-once for external cron.
CMD ["python", "-m", "scrapers.scheduler"]
