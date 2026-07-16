FROM python:3.11-slim
WORKDIR /src

# Install runtime dependencies
COPY backend/requirements.txt /src/requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && pip install --no-cache-dir -r /src/requirements.txt \
    && apt-get remove -y build-essential \
    && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Copy application
COPY backend /src/backend

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
