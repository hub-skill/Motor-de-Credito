"""Toda resposta de erro (4xx e 5xx) vai para o log de erros, só com metadados (nunca documento ou nome).

Cada erro leva a chave (ano, requisicao) da sua movimentação; sem ela (rota sem movimentação ou banco fora na
chegada) o erro não é gravado: a log_erros nunca tem linha sem a chave.
"""

import os

from httpx import AsyncClient

from app.core.config import get_settings
from tests.conftest import CPF_VALIDO
from tests.integration.conftest import ANO_FALSO, GravadorFalso, RepositorioFalso

URL = "/api/v1/triagem"
CABECALHOS = {"X-API-Key": os.environ["API_KEY"]}


async def test_entrada_invalida_registra_metadados_sem_dados_pessoais(
    cliente: AsyncClient, gravador: GravadorFalso
) -> None:
    cpf_errado = "529.982.247-24"
    resposta = await cliente.post(URL, json={"documento": cpf_errado, "nome": "Fulano de Tal"}, headers=CABECALHOS)

    assert resposta.status_code == 422
    (registro,) = gravador.registros
    assert registro.request_id == resposta.json()["request_id"] == resposta.headers["x-request-id"]
    assert (registro.metodo, registro.rota, registro.status) == ("POST", URL, 422)
    assert (registro.codigo, registro.titulo) == ("entrada_invalida", resposta.json()["title"])
    assert registro.tipo_excecao is None
    assert registro.duracao_ms is not None and registro.duracao_ms >= 0
    assert registro.ambiente == get_settings().app_env
    assert "982" not in repr(registro) and "Fulano" not in repr(registro)


async def test_cada_erro_leva_a_chave_da_sua_movimentacao(cliente: AsyncClient, gravador: GravadorFalso) -> None:
    primeira = await cliente.post(URL, json={"documento": "529.982.247-24"}, headers=CABECALHOS)
    segunda = await cliente.get("/nao-existe", headers=CABECALHOS)

    assert [(r.ano, r.requisicao) for r in gravador.registros] == [(ANO_FALSO, 1), (ANO_FALSO, 2)]
    assert primeira.headers["x-requisicao"] == f"{ANO_FALSO}-000001"
    assert segunda.headers["x-requisicao"] == f"{ANO_FALSO}-000002"


async def test_sucesso_e_health_nao_registram(cliente: AsyncClient, gravador: GravadorFalso) -> None:
    assert (await cliente.post(URL, json={"documento": CPF_VALIDO}, headers=CABECALHOS)).status_code == 200
    assert (await cliente.get("/health/live")).status_code == 200
    assert (await cliente.get("/health/ready")).status_code == 200
    assert gravador.registros == []


async def test_erros_do_framework_e_do_middleware_registram(cliente: AsyncClient, gravador: GravadorFalso) -> None:
    await cliente.post(URL, json={"documento": CPF_VALIDO})  # 401 sem chave: não entra (sem movimentação)
    await cliente.get("/nao-existe", headers=CABECALHOS)  # 404
    await cliente.get(URL, headers=CABECALHOS)  # 405
    await cliente.post(URL, content=b"{nao e json", headers={**CABECALHOS, "Content-Type": "application/json"})
    await cliente.post(  # 413, respondido pelo middleware
        URL, content=b"{" + b" " * 5000 + b"}", headers={**CABECALHOS, "Content-Type": "application/json"}
    )

    assert [(r.status, r.codigo, r.rota) for r in gravador.registros] == [
        (404, "http_404", "/nao-existe"),
        (405, "http_405", URL),
        (400, "requisicao_invalida", URL),
        (413, "corpo_muito_grande", URL),
    ]


async def test_erro_interno_registra_o_tipo_da_excecao(
    cliente: AsyncClient, repo: RepositorioFalso, gravador: GravadorFalso
) -> None:
    repo.erro_inesperado = RuntimeError("detalhe interno: senha=abc")
    resposta = await cliente.post(URL, json={"documento": CPF_VALIDO}, headers=CABECALHOS)

    assert resposta.status_code == 500
    (registro,) = gravador.registros
    assert (registro.codigo, registro.tipo_excecao) == ("erro_interno", "builtins.RuntimeError")
    assert "senha" not in repr(registro)


async def test_banco_fora_registra_503(cliente: AsyncClient, repo: RepositorioFalso, gravador: GravadorFalso) -> None:
    repo.falhar = True
    await cliente.post(URL, json={"documento": CPF_VALIDO}, headers=CABECALHOS)

    assert [(r.status, r.codigo) for r in gravador.registros] == [(503, "banco_indisponivel")]


async def test_rota_muito_longa_e_truncada(cliente: AsyncClient, gravador: GravadorFalso) -> None:
    await cliente.get("/" + "a" * 500, headers=CABECALHOS)

    (registro,) = gravador.registros
    assert registro.status == 404 and len(registro.rota) == 200


async def test_sem_numero_de_requisicao_o_erro_nao_e_gravado(
    cliente: AsyncClient, repo: RepositorioFalso, gravador: GravadorFalso
) -> None:
    # Banco fora na chegada: a API segue (a resposta de erro sai normal), mas a log_erros não recebe linha sem chave.
    repo.numeracao_falha = True
    resposta = await cliente.post(URL, json={"documento": "529.982.247-24"}, headers=CABECALHOS)

    assert resposta.status_code == 422
    assert "x-requisicao" not in resposta.headers
    assert gravador.registros == []
