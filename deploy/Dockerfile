# Prism — production container image
# Multi-stage build: dev deps for building, slim runtime for serving
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN pip install --no-cache-dir build

# Copy project
COPY pyproject.toml README.md ./
COPY core/ core/
COPY data/ data/
COPY presentation/ presentation/
COPY catalog/ catalog/
COPY schemas/ schemas/

# Build wheel
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /tmp/wheels .


FROM python:3.11-slim AS runtime

WORKDIR /app

# Security: run as non-root
RUN useradd --create-home prismuser

# Install runtime deps
COPY --from=builder /tmp/wheels /tmp/wheels
RUN pip install --no-cache-dir /tmp/wheels/*.whl

# Copy app source
COPY --from=builder /app/core /app/core
COPY --from=builder /app/data /app/data
COPY --from=builder /app/presentation /app/presentation
COPY --from=builder /app/catalog /app/catalog
COPY --from=builder /app/schemas /app/schemas

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "from presentation.render.svg_renderer import SvgRenderer; print('ok')"

USER prismuser

ENTRYPOINT ["python", "-c", "import sys; print('Prism core ready')"]