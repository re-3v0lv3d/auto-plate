# --- etapa 1: compilar cfsolve (solver Turnstile libre, sin navegador) ---
FROM rust:1.99-slim AS cfsolve

RUN apt-get update \
    && apt-get install -y --no-install-recommends git cmake clang pkg-config libssl-dev build-essential perl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git clone --depth 1 https://github.com/chris124567/cfsolve.git .
# Usamos el toolchain de la imagen en vez del fijado por el repo.
RUN rm -f rust-toolchain.toml && cargo build --release --bin challenge

# --- etapa 2: aplicación ---
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/vehicles.db \
    CFSOLVE_BIN=/usr/local/bin/cfsolve \
    CFSOLVE_PROFILE=/app/profiles/safari-26-ios.json \
    CAPTCHA_PROVIDER=cfsolve

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=cfsolve /src/target/release/challenge /usr/local/bin/cfsolve
COPY --from=cfsolve /src/profiles /app/profiles

COPY plate_lookup ./plate_lookup
COPY web ./web
COPY seed ./seed

RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8000
CMD ["sh", "-c", "uvicorn plate_lookup.web:app --host 0.0.0.0 --port ${PORT:-8000}"]
