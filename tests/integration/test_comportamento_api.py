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
from app.core.exceptions import BancoExpirou
from app.core.limiter import limiter
from app.main import app
from tests.conftest import CPF_VALIDO
from tests.contrato import afirmar_problema
from tests.integration.conftest import RepositorioFalso

URL = "/api/v1/triagem"
CORPO_VALIDO = {"documento": CPF_VALIDO}
CABECALHOS = {"X-API-Key": os.environ["API_KEY"]}


async def test_erro_401_tem_formato_padrao_e_www_authenticate(cliente: AsyncClient) -> None:
    resposta = await cliente.post(URL, json=CORPO_VALIDO)
    afirmar_problema(resposta, 401, "http_401")
    assert resposta.headers["www-authenticate"] == "APIKey"


async def test_rota_inexistente_responde_404_no_formato_padrao(cliente: AsyncClient) -> None:
    afirmar_problema(await cliente.get("/nao-existe", headers=CABECALHOS), 404, "http_404")


@pytest.mark.parametrize(("metodo", "rota"), [("GET", "/nao-existe"), ("GET", URL)])
async def test_sem_chave_rota_inexistente_ou_metodo_errado_responde_401(
    cliente: AsyncClient, metodo: str, rota: str
) -> None:
    # Igual ao Motor .NET: sem chave, a API não revela quais rotas existem.
    resposta = await cliente.request(metodo, rota)
    afirmar_problema(resposta, 401, "http_401")
    assert resposta.headers["www-authenticate"] == "APIKey"


async def test_metodo_errado_responde_405_no_formato_padrao(cliente: AsyncClient) -> None:
    resposta = await cliente.get(URL, headers=CABECALHOS)
    afirmar_problema(resposta, 405, "http_405")
    assert "POST" in resposta.headers["allow"]


async def test_json_invalido_responde_400_e_nao_500(cliente: AsyncClient) -> None:
    resposta = await cliente.post(
        URL, content=b"{nao e json", headers={**CABECALHOS, "Content-Type": "application/json"}
    )
    afirmar_problema(resposta, 400, "requisicao_invalida")


CABECALHOS_JSON = {**CABECALHOS, "Content-Type": "application/json"}


def _aninhado(niveis: int) -> bytes:
    """Corpo válido com um campo extra aninhado até ``niveis`` no total (o objeto da raiz conta como 1)."""
    return f'{{"documento": "{CPF_VALIDO}", "extra": '.encode() + b"[" * (niveis - 1) + b"]" * (niveis - 1) + b"}"


async def test_json_ate_64_niveis_passa_e_acima_responde_400(cliente: AsyncClient) -> None:
    # Mesmo limite do Motor .NET (MaxDepth 64 do System.Text.Json). Chaves dentro de textos não contam.
    assert (await cliente.post(URL, content=_aninhado(64), headers=CABECALHOS_JSON)).status_code == 200
    texto_com_chaves = f'{{"documento": "{CPF_VALIDO}", "nome": "{"[" * 100}"}}'.encode()
    assert (await cliente.post(URL, content=texto_com_chaves, headers=CABECALHOS_JSON)).status_code == 200
    afirmar_problema(
        await cliente.post(URL, content=_aninhado(65), headers=CABECALHOS_JSON), 400, "requisicao_invalida"
    )


@pytest.mark.parametrize("valor", [b"NaN", b"Infinity", b"-Infinity"])
async def test_nan_e_infinity_respondem_400_como_json_malformado(cliente: AsyncClient, valor: bytes) -> None:
    # Não existem em JSON (RFC 8259); o json do Python aceitaria, o .NET recusa na leitura. Igualado em 400.
    corpo = b'{"documento": "' + CPF_VALIDO.encode() + b'", "nome": ' + valor + b"}"
    afirmar_problema(await cliente.post(URL, content=corpo, headers=CABECALHOS_JSON), 400, "requisicao_invalida")


async def test_utf8_invalido_responde_400_e_nao_http_400_em_ingles(cliente: AsyncClient) -> None:
    corpo = b'{"documento": "' + CPF_VALIDO.encode() + b'", "nome": "Jos' + bytes([0xFF]) + b'"}'  # 0xFF: nunca é UTF-8
    afirmar_problema(await cliente.post(URL, content=corpo, headers=CABECALHOS_JSON), 400, "requisicao_invalida")


async def test_json_fundo_sem_chave_responde_401(cliente: AsyncClient) -> None:
    resposta = await cliente.post(URL, content=_aninhado(65), headers={"Content-Type": "application/json"})
    afirmar_problema(resposta, 401, "http_401")


@pytest.mark.parametrize(
    "corpo",
    [
        b'{"documento": 52998224725}',
        b'{"documento": ["529.982.247-25"]}',
        b'{"documento": "529.982.247-25", "nome": {"a": 1}}',
        b'[{"documento": "529.982.247-25"}]',
        b'"529.982.247-25"',
        b"null",
        b"",
    ],
    ids=[
        "documento_numero",
        "documento_lista",
        "nome_objeto",
        "lista_no_topo",
        "texto_no_topo",
        "null_no_topo",
        "vazio",
    ],
)
async def test_json_valido_com_forma_errada_responde_422(cliente: AsyncClient, corpo: bytes) -> None:
    # Igual ao Motor .NET: só o corpo ilegível é 400; JSON válido com forma errada é 422.
    afirmar_problema(await cliente.post(URL, content=corpo, headers=CABECALHOS_JSON), 422, "entrada_invalida")


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
    afirmar_problema(bloqueada, 429, "limite_excedido")
    assert bloqueada.headers["retry-after"] == "60"


async def test_erro_inesperado_responde_500_generico_sem_vazar_detalhes(
    cliente: AsyncClient, repo: RepositorioFalso
) -> None:
    repo.erro_inesperado = RuntimeError("detalhe interno: senha=abc")
    resposta = await cliente.post(URL, json=CORPO_VALIDO, headers=CABECALHOS)
    afirmar_problema(resposta, 500, "erro_interno")
    assert "detalhe interno" not in resposta.text
    assert "RuntimeError" not in resposta.text


async def test_banco_expirou_responde_504_banco_timeout(cliente: AsyncClient, repo: RepositorioFalso) -> None:
    repo.erro_inesperado = BancoExpirou()
    afirmar_problema(await cliente.post(URL, json=CORPO_VALIDO, headers=CABECALHOS), 504, "banco_timeout")


async def test_ready_sem_repositorio_responde_503(cliente: AsyncClient) -> None:
    del app.state.repositorio  # como antes do lifespan terminar
    resposta = await cliente.get("/health/ready")
    assert resposta.status_code == 503 and resposta.json() == {"status": "starting"}


async def test_documentacao_desligada_por_padrao(cliente: AsyncClient) -> None:
    for rota in ("/docs", "/redoc", "/openapi.json"):
        assert (await cliente.get(rota, headers=CABECALHOS)).status_code == 404
        assert (await cliente.get(rota)).status_code == 401  # sem chave não revela que a rota não existe


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
