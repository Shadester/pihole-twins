# ── Build stage ────────────────────────────────────────────────────
FROM python:3.14-slim AS builder

WORKDIR /build
COPY pyproject.toml .
COPY *.py ./

RUN pip install --no-cache-dir --prefix=/install \
    --ignore-installed \
    paramiko flask

# ── Runtime stage ──────────────────────────────────────────────────
FROM python:3.14-slim

LABEL maintainer="shades"
LABEL description="Pi-hole Twins - Multi-server Pi-hole log streamer"

RUN apt-get update && \
    apt-get install -y --no-install-recommends tini && \
    rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash appuser

WORKDIR /app
COPY --from=builder /install /usr/local
COPY *.py ./

# Create config and data directories
RUN mkdir -p /home/appuser/.config/piholetwins && \
    chown -R appuser:appuser /app /home/appuser

USER appuser

ENV PYTHONUNBUFFERED=1
EXPOSE 5000

ENTRYPOINT ["tini", "--"]
CMD ["python", "stream_pihole_logs.py", "stream"]
