# Imagem de produção do Motor de Crédito (FastAPI).
# Build:   docker build -t motor-credito-py:0.1.0 .
# Rodar:   ver DOCUMENTACAO.md, seção Operação (env file sem credenciais de administrador).
# Tags fixas (nunca latest). Atualize as versões de propósito e rode o trivy depois.

FROM python:3.12.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.10.8 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependências primeiro: a camada só é refeita quando pyproject.toml/uv.lock mudam.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.12.13-slim
# A imagem base fica semanas sem nova tag; as correções de segurança do Debian (trivy acusou 60 HIGH/CRITICAL
# corrigíveis em 11/11/2026) entram aqui. Reconstrua a imagem com frequência para pegá-las.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
# Usuário numérico: o Kubernetes só consegue conferir runAsNonRoot com UID numérico.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin api
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY app ./app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WEB_CONCURRENCY=1
USER 10001
EXPOSE 8080

# Um processo por container (WEB_CONCURRENCY=1): no Kubernetes quem escala é o cluster (réplicas/HPA).
# Fora do Kubernetes (VM, docker run), aumente WEB_CONCURRENCY (o gunicorn lê essa variável); cada
# processo abre o próprio pool (PG_POOL_MAX/ORACLE_POOL_MAX) e o próprio rate limit.
# Tempos em escada: banco (5 s) < REQUEST_TIMEOUT_SECONDS (10) < --timeout (15) < --graceful-timeout (20).
# No Linux o loop padrão do uvicorn já funciona com o psycopg async (o --loop do Windows não é preciso).
CMD ["gunicorn", "app.main:app", "-k", "uvicorn_worker.UvicornWorker", \
     "-b", "0.0.0.0:8080", "--timeout", "15", "--graceful-timeout", "20", "--keep-alive", "5", \
     "--worker-tmp-dir", "/dev/shm", "--access-logfile", "-"]
