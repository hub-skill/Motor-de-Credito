"""Comportamentos genéricos (mesmos do template da skill criar-api): formato dos erros, limites,
health, cabeçalhos, métricas e documentação. Sem banco: usam o repositório falso do conftest.
"""

import importlib
import os
from collections.abc import Iterator

import pytest
from httpx import ASGITransport, AsyncClient

import app.main as modulo_main
from app.core.config import get_settings
from app.core.limiter import limiter
from app.main import app
from tests.conftest import CPF_VALIDO
from tests.integration.conftest import RepositorioFalso

URL = "/api/v1/triagem"
CORPO_VALIDO = {"documento": CPF_VALIDO}
CABECALHOS = {"X-API-Key": os.environ["API_KEY"]}


async def test_erro_401_tem_formato_padrao_e_www_authenticate(cliente: AsyncClient) -> None:
    resposta = await cliente.post(URL, json=CORPO_VALIDO)
    assert resposta.status_code == 401
    assert resposta.headers["www-authenticate"] == "APIKey"
    erro = resposta.json()["error"]
    assert erro["code"] == "http_401" and erro["request_id"]


async def test_rota_inexistente_responde_404_no_formato_padrao(cliente: AsyncClient) -> None:
    resposta = await cliente.get("/nao-existe", headers=CABECALHOS)
    assert resposta.status_code == 404
    assert resposta.json()["error"]["code"] == "http_404"


async def test_json_invalido_responde_400_e_nao_500(cliente: AsyncClient) -> None:
    resposta = await cliente.post(
        URL, content=b"{nao e json", headers={**CABECALHOS, "Content-Type": "application/json"}
    )
    assert resposta.status_code == 400
    assert resposta.json()["error"]["code"] == "requisicao_invalida"


async def test_cabecalhos_de_seguranca(cliente: AsyncClient) -> None:
    resposta = await cliente.get("/health/live")
    assert resposta.headers["x-content-type-options"] == "nosniff"
    assert resposta.headers["x-frame-options"] == "DENY"
    assert resposta.headers["strict-transport-security"].startswith("max-age=")
    assert resposta.headers["cache-control"] == "no-store"
    assert resposta.headers["x-request-id"]


async def test_metricas_prometheus(cliente: AsyncClient) -> None:
    await cliente.post(URL, json=CORPO_VALIDO, headers=CABECALHOS)
    resposta = await cliente.get("/metrics")
    assert resposta.status_code == 200
    assert "http_request" in resposta.text
    assert CPF_VALIDO not in resposta.text  # métricas não carregam dados pessoais


@pytest.fixture
def limite_baixo(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # O slowapi lê o limite a cada requisição (lambda em routes.py): basta trocar a configuração.
    monkeypatch.setattr(get_settings(), "rate_limit", "2/minute")
    limiter.reset()
    yield
    limiter.reset()


@pytest.mark.usefixtures("limite_baixo")
async def test_rate_limit_responde_429_com_retry_after(cliente: AsyncClient) -> None:
    for _ in range(2):
        assert (await cliente.post(URL, json=CORPO_VALIDO, headers=CABECALHOS)).status_code == 200

    bloqueada = await cliente.post(URL, json=CORPO_VALIDO, headers=CABECALHOS)
    assert bloqueada.status_code == 429
    assert bloqueada.headers["retry-after"] == "60"
    assert bloqueada.json()["error"]["code"] == "limite_excedido"


async def test_erro_inesperado_responde_500_generico_sem_vazar_detalhes(
    cliente: AsyncClient, repo: RepositorioFalso
) -> None:
    repo.erro_inesperado = RuntimeError("detalhe interno: senha=abc")
    resposta = await cliente.post(URL, json=CORPO_VALIDO, headers=CABECALHOS)
    assert resposta.status_code == 500
    erro = resposta.json()["error"]
    assert erro["code"] == "erro_interno" and erro["request_id"]
    assert "detalhe interno" not in resposta.text
    assert "RuntimeError" not in resposta.text


async def test_ready_sem_repositorio_responde_503(cliente: AsyncClient) -> None:
    del app.state.repositorio  # como antes do lifespan terminar
    resposta = await cliente.get("/health/ready")
    assert resposta.status_code == 503 and resposta.json() == {"status": "starting"}


async def test_documentacao_desligada_por_padrao(cliente: AsyncClient) -> None:
    for rota in ("/docs", "/redoc", "/openapi.json"):
        assert (await cliente.get(rota)).status_code == 404


async def test_documentacao_ligada_e_publica(monkeypatch: pytest.MonkeyPatch) -> None:
    # A configuração é lida na importação: recarrega o módulo com ENABLE_DOCS=true e depois restaura.
    monkeypatch.setenv("ENABLE_DOCS", "true")
    get_settings.cache_clear()
    try:
        ligada = importlib.reload(modulo_main).app
        async with AsyncClient(transport=ASGITransport(app=ligada), base_url="http://test") as cliente:
            openapi = await cliente.get("/openapi.json")
            assert openapi.status_code == 200 and URL in openapi.text
            assert (await cliente.get("/docs")).status_code == 200
    finally:
        monkeypatch.setenv("ENABLE_DOCS", "false")
        get_settings.cache_clear()
        importlib.reload(modulo_main)
