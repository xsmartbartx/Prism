# syntax=docker/dockerfile:1.7
# Prism — production image: web UI + API in one non-root container.

# ---------- 1. Web UI ----------
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---------- 2. Python wheel ----------
FROM python:3.12-slim AS builder
WORKDIR /src
RUN pip install --no-cache-dir build
COPY pyproject.toml README.md LICENSE ./
COPY core/ core/
COPY data/ data/
COPY presentation/ presentation/
COPY catalog/ catalog/
COPY schemas/ schemas/
COPY security/ security/
COPY insight/ insight/
COPY server/ server/
RUN python -m build --wheel --outdir /wheels

# ---------- 3. Runtime ----------
FROM python:3.12-slim AS runtime
ARG PRISM_VERSION=1.0.0
LABEL org.opencontainers.image.title="Prism" \
      org.opencontainers.image.description="Self-hosted data platform: import, model, query and visualise data" \
      org.opencontainers.image.version="${PRISM_VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PRISM_ENV=production \
    PRISM_DATA_DIR=/var/lib/prism \
    PRISM_STATIC_DIR=/opt/prism/static \
    PRISM_HOST=0.0.0.0 \
    PRISM_PORT=8080

RUN useradd --system --uid 10001 --create-home --home-dir /home/prism prism \
 && mkdir -p /var/lib/prism /opt/prism \
 && chown prism:prism /var/lib/prism

COPY --from=builder /wheels /tmp/wheels
RUN pip install /tmp/wheels/*.whl "psycopg[binary]>=3.2" && rm -rf /tmp/wheels
COPY --from=web /web/dist /opt/prism/static

USER prism
WORKDIR /home/prism
VOLUME ["/var/lib/prism"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4).status == 200 else 1)"

ENTRYPOINT ["prism"]
CMD ["serve"]
