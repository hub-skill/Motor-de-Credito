import logging
import time
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

from app.api.deps import chave_valida
from app.api.v1.routes import router as router_v1
from app.core.config import Settings, get_settings
from app.core.exceptions import ErroDeDominio
from app.core.limiter import limiter
from app.core.logging import configurar_logs
from app.core.profundidade_json import corpo_json_ilegivel
from app.movimentacao.http import Movimentacao, registrar_erro
from app.movimentacao.regras import conteudo_da_requisicao, movimentar
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
    app.state.movimentacao = Movimentacao(app.state.repositorio.movimentacao, settings.app_env)
    app.state.movimentacao.iniciar()
    logger.info("api iniciada", extra={"banco": settings.motor_banco, "ambiente": settings.app_env})
    try:
        yield
    finally:
        # Grava o que ainda estiver na fila antes de fechar o pool.
        await app.state.movimentacao.parar()
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
    tipo_excecao: str | None = None,
) -> JSONResponse:
    """Formato único de erro: RFC 9457 (Problem Details), o mesmo do Motor .NET.

    Corpo sempre com exatamente `title`, `status`, `code` e `request_id` (sem `type`: ausente = about:blank).
    """
    registrar_erro(request, status_code, codigo, mensagem, tipo_excecao)  # grava junto com a movimentação
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
    request.state.inicio = time.perf_counter()

    tamanho = request.headers.get("content-length")
    grande = tamanho is not None and tamanho.isdigit() and int(tamanho) > TAMANHO_MAXIMO_CORPO
    # Só quem tem chave de API válida entra na movimentação (e tem o corpo lido aqui): varreduras e chamadas sem
    # chave recebem 401 e não gravam nada no banco.
    chave_ok = chave_valida(request.headers.get("X-API-Key"), get_settings())
    corpo = b"" if grande or not chave_ok else await request.body()  # fica em cache para a rota

    # Movimentação: o ULID nasce aqui, na API (sem banco), inclusive para os erros 4xx; menos /health e /metrics.
    movimentacao = Movimentacao.da(request) if chave_ok and movimentar(request.url.path) else None
    if movimentacao:
        movimentacao.abrir(request, conteudo_da_requisicao(corpo, tamanho, grande))

    if grande:
        response: Response = _resposta_erro(request, 413, "corpo_muito_grande", "Corpo da requisição excede o limite.")
    elif (
        # JSON que o Motor .NET recusa na leitura (mais de 64 níveis, NaN/Infinity): 400, igual a ele. Só com
        # chave válida (sem ela a resposta é 401).
        chave_ok
        and request.method == "POST"
        and "json" in request.headers.get("content-type", "")
        and corpo_json_ilegivel(corpo)
    ):
        response = _resposta_erro(request, 400, "requisicao_invalida", "Requisição inválida.")
    else:
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 - erro não tratado: o 500 sai daqui para entrar na movimentação
            response = await tratar_erro_inesperado(request, exc)

    if movimentacao:
        response = await movimentacao.completar(request, response)
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
    # Rota inexistente ou método errado SEM chave válida: 401, como no Motor .NET (não revela quais rotas existem).
    if exc.status_code in (404, 405) and not chave_valida(request.headers.get("X-API-Key"), get_settings()):
        return _resposta_erro(request, 401, "http_401", _TITULOS_HTTP[401], headers={"WWW-Authenticate": "APIKey"})
    # Corpo que o FastAPI não consegue ler (ex.: UTF-8 inválido): mesmo erro do JSON malformado, como no Motor .NET,
    # em vez de 400 http_400 com o texto do framework em inglês ("There was an error parsing the body").
    if exc.status_code == 400:
        return _resposta_erro(request, 400, "requisicao_invalida", "Requisição inválida.")
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
    return _resposta_erro(
        request,
        500,
        "erro_interno",
        "Erro interno. Informe o request_id ao suporte.",
        tipo_excecao=f"{type(exc).__module__}.{type(exc).__qualname__}",
    )


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
