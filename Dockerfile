FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/vehicles.db

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY plate_lookup ./plate_lookup
COPY web ./web
COPY seed ./seed

RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8000
CMD ["sh", "-c", "uvicorn plate_lookup.web:app --host 0.0.0.0 --port ${PORT:-8000}"]
