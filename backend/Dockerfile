FROM python:3.13-slim
# poppler-utils: pdftotext, used by the parser when available (same as the prototype)
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.7.19 /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev
ENV SBCX_VAR_DIR=/data/var SBCX_DATA_DIR=/app/data
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "sbcx.main:app", "--host", "0.0.0.0", "--port", "8000"]
