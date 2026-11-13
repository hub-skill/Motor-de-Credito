"""Toda resposta de erro (4xx e 5xx) vai para o log de erros, só com metadados (nunca documento ou nome).

O erro é gravado junto com a sua movimentação (mesma transação, ligado pelo ULID): sem movimentação (rota sem
movimentação, ou sem chave de API válida) não há erro gravado.
"""

import os

from httpx import AsyncClient

from app.core.config import get_settings
from app.movimentacao.http import Movimentacao
from app.movimentacao.registros import RegistroErro
from tests.conftest import CPF_VALIDO
from tests.integration.conftest import RepositorioFalso, id_do_header

URL = "/api/v1/triagem"
CABECALHOS = {"X-API-Key": os.environ["API_KEY"]}


def _erros(repo: RepositorioFalso) -> list[RegistroErro]:
    return [r.erro for r in repo.movimentacao.registros if r.erro is not None]


async def test_entrada_invalida_registra_metadados_sem_dados_pessoais(
    cliente: AsyncClient, repo: RepositorioFalso, movimentacao: Movimentacao
) -> None:
    cpf_errado = "529.982.247-24"
    resposta = await cliente.post(URL, json={"documento": cpf_errado, "nome": "Fulano de Tal"}, headers=CABECALHOS)
    await movimentacao.parar()

    assert resposta.status_code == 422
    (erro,) = _erros(repo)
    assert erro.request_id == resposta.json()["request_id"] == resposta.headers["x-request-id"]
    assert (erro.metodo, erro.rota, erro.status) == ("POST", URL, 422)
    assert (erro.codigo, erro.titulo) == ("entrada_invalida", resposta.json()["title"])
    assert erro.tipo_excecao is None
    assert erro.duracao_ms is not None and erro.duracao_ms >= 0
    assert erro.ambiente == get_settings().app_env
    assert "982" not in repr(erro) and "Fulano" not in repr(erro)


async def test_cada_erro_e_gravado_junto_com_a_sua_movimentacao(
    cliente: AsyncClient, repo: RepositorioFalso, movimentacao: Movimentacao
) -> None:
    primeira = await cliente.post(URL, json={"documento": "529.982.247-24"}, headers=CABECALHOS)
    segunda = await cliente.get("/nao-existe", headers=CABECALHOS)
    await movimentacao.parar()

    for resposta, codigo in ((primeira, "entrada_invalida"), (segunda, "http_404")):
        gravada = repo.movimentacao.por_id(id_do_header(resposta))
        assert gravada.erro is not None and gravada.erro.codigo == codigo
        assert gravada.erro.status == gravada.status_http == resposta.status_code


async def test_sucesso_e_health_nao_geram_erro(
    cliente: AsyncClient, repo: RepositorioFalso, movimentacao: Movimentacao
) -> None:
    assert (await cliente.post(URL, json={"documento": CPF_VALIDO}, headers=CABECALHOS)).status_code == 200
    assert (await cliente.get("/health/live")).status_code == 200
    assert (await cliente.get("/health/ready")).status_code == 200
    await movimentacao.parar()

    assert len(repo.movimentacao.registros) == 1 and _erros(repo) == []


async def test_erros_do_framework_e_do_middleware_registram(
    cliente: AsyncClient, repo: RepositorioFalso, movimentacao: Movimentacao
) -> None:
    await cliente.post(URL, json={"documento": CPF_VALIDO})  # 401 sem chave: não entra (sem movimentação)
    await cliente.get("/nao-existe", headers=CABECALHOS)  # 404
    await cliente.get(URL, headers=CABECALHOS)  # 405
    await cliente.post(URL, content=b"{nao e json", headers={**CABECALHOS, "Content-Type": "application/json"})
    await cliente.post(  # 413, respondido pelo middleware
        URL, content=b"{" + b" " * 5000 + b"}", headers={**CABECALHOS, "Content-Type": "application/json"}
    )
    await movimentacao.parar()

    assert [(e.status, e.codigo, e.rota) for e in _erros(repo)] == [
        (404, "http_404", "/nao-existe"),
        (405, "http_405", URL),
        (400, "requisicao_invalida", URL),
        (413, "corpo_muito_grande", URL),
    ]


async def test_erro_interno_registra_o_tipo_da_excecao(
    cliente: AsyncClient, repo: RepositorioFalso, movimentacao: Movimentacao
) -> None:
    repo.erro_inesperado = RuntimeError("detalhe interno: senha=abc")
    resposta = await cliente.post(URL, json={"documento": CPF_VALIDO}, headers=CABECALHOS)
    await movimentacao.parar()

    assert resposta.status_code == 500
    (erro,) = _erros(repo)
    assert (erro.codigo, erro.tipo_excecao) == ("erro_interno", "builtins.RuntimeError")
    assert "senha" not in repr(erro)


async def test_banco_fora_registra_503(
    cliente: AsyncClient, repo: RepositorioFalso, movimentacao: Movimentacao
) -> None:
    repo.falhar = True
    await cliente.post(URL, json={"documento": CPF_VALIDO}, headers=CABECALHOS)
    await movimentacao.parar()

    assert [(e.status, e.codigo) for e in _erros(repo)] == [(503, "banco_indisponivel")]


async def test_rota_muito_longa_e_truncada(
    cliente: AsyncClient, repo: RepositorioFalso, movimentacao: Movimentacao
) -> None:
    await cliente.get("/" + "a" * 500, headers=CABECALHOS)
    await movimentacao.parar()

    (gravada,) = repo.movimentacao.registros
    assert gravada.status_http == 404 and len(gravada.rota) == 200
    assert gravada.erro is not None and len(gravada.erro.rota) == 200
