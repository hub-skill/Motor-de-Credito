import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.routes import router as router_v1
from app.core.config import Settings, get_settings
from app.core.exceptions import ErroDeDominio
from app.core.limiter import limiter
from app.core.logging import configurar_logs
from app.repositorios.base import RepositorioListas

configurar_logs()
logger = logging.getLogger(__name__)
settings = get_settings()

TAMANHO_MAXIMO_CORPO = 4 * 1024  # bytes; a entrada é um documento e um nome. O proxy deve limitar também.


async def criar_repositorio(s: Settings) -> RepositorioListas:
    # Import tardio: só carrega o driver do banco escolhido.
    if s.motor_banco == "oracle":
        from app.repositorios.oracle import RepositorioOracle

        return await RepositorioOracle.criar(s)
    from app.repositorios.postgres import RepositorioPostgres

    return await RepositorioPostgres.criar(s)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.repositorio = await criar_repositorio(settings)
    logger.info("api iniciada", extra={"banco": settings.motor_banco, "ambiente": settings.app_env})
    try:
        yield
    finally:
        await app.state.repositorio.fechar()


app = FastAPI(
    title="Motor de Crédito - Triagem",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.enable_docs else None,
    redoc_url="/redoc" if settings.enable_docs else None,
    openapi_url="/openapi.json" if settings.enable_docs else None,
)
app.state.limiter = limiter

app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)


# Textos dos erros genéricos do framework (401, 404, 405), em português e iguais aos do Motor .NET.
_TITULOS_HTTP = {
    401: "Chave de API ausente ou inválida.",
    404: "Recurso não encontrado.",
    405: "Método não permitido.",
}


def _resposta_erro(
    request: Request,
    status_code: int,
    codigo: str,
    mensagem: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Formato único de erro: RFC 9457 (Problem Details), o mesmo do Motor .NET.

    Corpo sempre com exatamente `title`, `status`, `code` e `request_id` (sem `type`: ausente = about:blank).
    """
    return JSONResponse(
        status_code=status_code,
        content={
            "title": mensagem,
            "status": status_code,
            "code": codigo,
            "request_id": getattr(request.state, "request_id", None),
        },
        headers=headers,
        media_type="application/problem+json",
    )


@app.middleware("http")
async def contexto_da_requisicao(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    request.state.request_id = str(uuid.uuid4())

    tamanho = request.headers.get("content-length")
    if tamanho is not None and tamanho.isdigit() and int(tamanho) > TAMANHO_MAXIMO_CORPO:
        return _resposta_erro(request, 413, "corpo_muito_grande", "Corpo da requisição excede o limite.")

    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Cache-Control"] = "no-store"  # resposta contém dados pessoais
    return response


@app.exception_handler(ErroDeDominio)
async def tratar_erro_de_dominio(request: Request, exc: ErroDeDominio) -> JSONResponse:
    return _resposta_erro(request, exc.status_code, exc.codigo, exc.mensagem)


@app.exception_handler(RequestValidationError)
async def tratar_erro_de_validacao(request: Request, exc: RequestValidationError) -> JSONResponse:
    # JSON malformado é erro de requisição (400), não de conteúdo (422).
    if any(erro.get("type") == "json_invalid" for erro in exc.errors()):
        return _resposta_erro(request, 400, "requisicao_invalida", "Requisição inválida.")
    # Mensagem genérica: os detalhes do Pydantic ecoariam a entrada (CPF, nome).
    return _resposta_erro(request, 422, "entrada_invalida", "Dados de entrada inválidos.")


@app.exception_handler(RateLimitExceeded)
async def tratar_rate_limit(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return _resposta_erro(
        request,
        429,
        "limite_excedido",
        "Muitas requisições. Tente mais tarde.",
        headers={"Retry-After": "60"},
    )


@app.exception_handler(StarletteHTTPException)
async def tratar_erro_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return _resposta_erro(
        request,
        exc.status_code,
        f"http_{exc.status_code}",
        _TITULOS_HTTP.get(exc.status_code, str(exc.detail)),
        headers=dict(exc.headers) if exc.headers else None,
    )


@app.exception_handler(Exception)
async def tratar_erro_inesperado(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("erro não tratado", extra={"request_id": getattr(request.state, "request_id", None)})
    return _resposta_erro(request, 500, "erro_interno", "Erro interno. Informe o request_id ao suporte.")


@app.get("/health/live", include_in_schema=False)
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
async def ready(request: Request) -> JSONResponse:
    repo: RepositorioListas | None = getattr(request.app.state, "repositorio", None)
    if repo is None:
        return JSONResponse(status_code=503, content={"status": "starting"})
    try:
        await repo.verificar()
    except Exception:  # noqa: BLE001 - qualquer falha do banco = não pronto
        return JSONResponse(status_code=503, content={"status": "banco_indisponivel"})
    return JSONResponse(status_code=200, content={"status": "ok", "banco": settings.motor_banco})


# Métricas Prometheus (latência, requisições, erros). Exponha /metrics só na rede interna.
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

app.include_router(router_v1)
