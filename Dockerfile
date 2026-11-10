FROM python:3.12.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.10.8 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM python:3.12.13-slim
RUN useradd --create-home --uid 10001 api
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY app ./app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER api
EXPOSE 8000
# Timeouts: banco (5 s) < aplicação (REQUEST_TIMEOUT_SECONDS=10) < gunicorn (15) < proxy.
# Em Linux o loop padrão do uvicorn já é compatível com o psycopg async.
CMD ["gunicorn", "app.main:app", "-k", "uvicorn_worker.UvicornWorker", \
     "-w", "2", "-b", "0.0.0.0:8000", "--timeout", "15", "--graceful-timeout", "15", \
     "--keep-alive", "5"]
