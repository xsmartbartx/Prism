# syntax=docker/dockerfile:1.7
# Prism — production image: web UI + API in one non-root container.

# ---------- 1. Web UI ----------
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---------- 2. Runtime ----------
FROM python:3.12-slim AS runtime
ARG PRISM_VERSION=1.0.0
LABEL org.opencontainers.image.title="Prism" \
      org.opencontainers.image.description="Self-hosted data platform: import, model, query and visualise data" \
      org.opencontainers.image.version="${PRISM_VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/opt/prism/app \
    PRISM_ENV=production \
    PRISM_DATA_DIR=/var/lib/prism \
    PRISM_STATIC_DIR=/opt/prism/static \
    PRISM_HOST=0.0.0.0 \
    PRISM_PORT=8080

RUN useradd --system --uid 10001 --create-home --home-dir /home/prism prism \
 && mkdir -p /var/lib/prism /opt/prism/app \
 && chown prism:prism /var/lib/prism

# Third-party dependencies: pinned, hash-verified, prebuilt wheels only.
COPY requirements/runtime.txt /tmp/runtime.txt
RUN pip install --only-binary :all: --require-hashes -r /tmp/runtime.txt && rm /tmp/runtime.txt

# Application code (pure Python, no build step) and the built web UI.
COPY core/ /opt/prism/app/core/
COPY data/ /opt/prism/app/data/
COPY presentation/ /opt/prism/app/presentation/
COPY catalog/ /opt/prism/app/catalog/
COPY schemas/ /opt/prism/app/schemas/
COPY server/ /opt/prism/app/server/
COPY --from=web /web/dist /opt/prism/static
RUN printf '#!/bin/sh\nexec python -m server.cli "$@"\n' > /usr/local/bin/prism \
 && chmod 0755 /usr/local/bin/prism \
 && python -m compileall -q /opt/prism/app

USER prism
WORKDIR /home/prism
VOLUME ["/var/lib/prism"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4).status == 200 else 1)"

ENTRYPOINT ["prism"]
CMD ["serve"]
