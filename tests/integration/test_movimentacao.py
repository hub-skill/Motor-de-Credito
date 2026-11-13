"""Movimentação: cada requisição com chave válida (menos /health e /metrics) ganha um ULID na chegada e é gravada,
com a resposta, uma só vez e em segundo plano.

Sem banco: o repositório falso (``repo.movimentacao``) guarda o que seria gravado. Para ver a gravação, os testes
chamam ``movimentacao.parar()``, que grava o que ainda está na fila.
"""

import asyncio
import os
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from app.movimentacao import ulid
from app.movimentacao.http import Movimentacao
from tests.conftest import CPF_VALIDO
from tests.integration.conftest import RepositorioFalso, id_do_header

URL = "/api/v1/triagem"
CABECALHOS = {"X-API-Key": os.environ["API_KEY"]}
CABECALHOS_JSON = {**CABECALHOS, "Content-Type": "application/json"}


async def test_requisicao_com_sucesso_ganha_ulid_e_e_gravada_com_a_resposta(
    cliente: AsyncClient, repo: RepositorioFalso, movimentacao: Movimentacao
) -> None:
    resposta = await cliente.post(
        URL, json={"documento": "529.982.247-25", "nome": "Fulano de Tal"}, headers=CABECALHOS
    )
    await movimentacao.parar()

    assert resposta.status_code == 200
    gravada = repo.movimentacao.por_id(id_do_header(resposta))
    assert (gravada.metodo, gravada.rota, gravada.status_http) == ("POST", URL, 200)
    assert gravada.requisicao_conteudo is not None and "Fulano de Tal" in gravada.requisicao_conteudo
    assert (gravada.situacao_requisicao, gravada.situacao_resposta) == ("OK", "OK")
    assert gravada.resposta_conteudo == resposta.text  # o conteúdo gravado é exatamente o que o cliente recebeu
    assert gravada.erro is None and gravada.resposta_em >= gravada.requisicao_em
    # A hora de chegada é a que está no próprio ULID (milissegundo).
    assert abs((gravada.requisicao_em - ulid.momento(gravada.requisicao_id)).total_seconds()) < 0.002


async def test_cpf_e_mascarado_no_conteudo_da_requisicao_e_da_resposta(
    cliente: AsyncClient, repo: RepositorioFalso, movimentacao: Movimentacao
) -> None:
    ids = [
        id_do_header(await cliente.post(URL, json={"documento": formato}, headers=CABECALHOS))
        for formato in ("529.982.247-25", CPF_VALIDO)
    ]
    await movimentacao.parar()

    for identificador in ids:
        gravada = repo.movimentacao.por_id(identificador)
        assert gravada.requisicao_conteudo is not None
        assert "***.982.247-**" in gravada.requisicao_conteudo
        assert "529" not in gravada.requisicao_conteudo and "-25" not in gravada.requisicao_conteudo
        assert gravada.resposta_conteudo is not None and "529.982.247-25" not in gravada.resposta_conteudo


async def test_conteudo_da_requisicao_aceita_qualquer_formato(
    cliente: AsyncClient, repo: RepositorioFalso, movimentacao: Movimentacao
) -> None:
    corpos = [b"{nao e json", b"texto solto \xff com byte invalido", b'["lista"]', b"<xml><a>1</a></xml>"]
    ids = [id_do_header(await cliente.post(URL, content=corpo, headers=CABECALHOS_JSON)) for corpo in corpos]
    await movimentacao.parar()

    gravados = [repo.movimentacao.por_id(i).requisicao_conteudo for i in ids]
    assert gravados[0] == "{nao e json"
    assert gravados[1] is not None and gravados[1].startswith("texto solto ") and "�" in gravados[1]
    assert gravados[2:] == ['["lista"]', "<xml><a>1</a></xml>"]


@pytest.mark.parametrize(
    ("chamada", "status", "situacao_requisicao", "situacao_resposta"),
    [
        ("entrada_invalida", 422, "ER", "ER"),
        ("rota_inexistente", 404, "ER", "ER"),
        ("json_malformado", 400, "ER", "ER"),
        ("banco_fora", 503, "OK", "ER"),
        ("erro_inesperado", 500, "OK", "ER"),
        ("sucesso", 200, "OK", "OK"),
    ],
)
async def test_situacoes_da_requisicao_e_da_resposta(
    cliente: AsyncClient,
    repo: RepositorioFalso,
    movimentacao: Movimentacao,
    chamada: str,
    status: int,
    situacao_requisicao: str,
    situacao_resposta: str,
) -> None:
    bom = {"documento": CPF_VALIDO}
    if chamada == "entrada_invalida":
        resposta = await cliente.post(URL, json={"documento": "529.982.247-24"}, headers=CABECALHOS)
    elif chamada == "rota_inexistente":
        resposta = await cliente.get("/nao-existe", headers=CABECALHOS)
    elif chamada == "json_malformado":
        resposta = await cliente.post(URL, content=b"{nao e json", headers=CABECALHOS_JSON)
    elif chamada == "banco_fora":
        repo.falhar = True
        resposta = await cliente.post(URL, json=bom, headers=CABECALHOS)
    elif chamada == "erro_inesperado":
        repo.erro_inesperado = RuntimeError("falha")
        resposta = await cliente.post(URL, json=bom, headers=CABECALHOS)
    else:
        resposta = await cliente.post(URL, json=bom, headers=CABECALHOS)
    await movimentacao.parar()

    assert resposta.status_code == status
    gravada = repo.movimentacao.por_id(id_do_header(resposta))
    assert (gravada.status_http, gravada.situacao_requisicao, gravada.situacao_resposta) == (
        status,
        situacao_requisicao,
        situacao_resposta,
    )


@pytest.mark.parametrize(
    ("metodo", "rota", "cabecalhos"),
    [
        ("POST", URL, {}),  # sem chave
        ("POST", URL, {"X-API-Key": "chave-errada"}),
        ("GET", "/nao-existe", {}),  # sem chave: 401, não revela se a rota existe
        ("GET", URL, {}),
    ],
    ids=["sem_chave", "chave_errada", "rota_inexistente_sem_chave", "metodo_errado_sem_chave"],
)
async def test_sem_chave_valida_nao_entra_na_movimentacao(
    cliente: AsyncClient,
    repo: RepositorioFalso,
    movimentacao: Movimentacao,
    metodo: str,
    rota: str,
    cabecalhos: dict[str, str],
) -> None:
    # Varreduras e chamadas sem chave recebem 401 e não gravam nada: nem movimentação, nem log de erros.
    resposta = await cliente.request(metodo, rota, json={"documento": CPF_VALIDO}, headers=cabecalhos)
    await movimentacao.parar()

    assert resposta.status_code == 401
    assert "x-requisicao" not in resposta.headers
    assert resposta.headers["x-request-id"]  # o 401 continua com request_id e headers de segurança
    assert repo.movimentacao.registros == []


async def test_corpo_grande_sem_chave_responde_413_e_nao_entra_na_movimentacao(
    cliente: AsyncClient, repo: RepositorioFalso, movimentacao: Movimentacao
) -> None:
    corpo = b'{"documento": "' + b"1" * 5000 + b'"}'
    resposta = await cliente.post(URL, content=corpo, headers={"Content-Type": "application/json"})
    await movimentacao.parar()

    assert resposta.status_code == 413
    assert "x-requisicao" not in resposta.headers and repo.movimentacao.registros == []


async def test_erro_nao_tratado_entra_na_movimentacao_com_os_cabecalhos_da_api(
    cliente: AsyncClient, repo: RepositorioFalso, movimentacao: Movimentacao
) -> None:
    repo.erro_inesperado = RuntimeError("detalhe interno: senha=abc")
    resposta = await cliente.post(URL, json={"documento": CPF_VALIDO}, headers=CABECALHOS)
    await movimentacao.parar()

    assert resposta.status_code == 500
    assert resposta.headers["x-request-id"] and resposta.headers["x-content-type-options"] == "nosniff"
    gravada = repo.movimentacao.por_id(id_do_header(resposta))
    assert gravada.status_http == 500 and gravada.resposta_conteudo is not None
    assert "senha" not in gravada.resposta_conteudo


async def test_health_e_metrics_nao_entram_na_movimentacao(
    cliente: AsyncClient, repo: RepositorioFalso, movimentacao: Movimentacao
) -> None:
    for rota in ("/health/live", "/health/ready", "/metrics"):
        resposta = await cliente.get(rota)
        assert resposta.status_code == 200
        assert "x-requisicao" not in resposta.headers
    await movimentacao.parar()

    assert repo.movimentacao.registros == []


async def test_corpo_acima_do_limite_registra_so_o_tamanho(
    cliente: AsyncClient, repo: RepositorioFalso, movimentacao: Movimentacao
) -> None:
    corpo = b'{"documento": "' + b"1" * 5000 + b'"}'
    resposta = await cliente.post(URL, content=corpo, headers=CABECALHOS_JSON)
    await movimentacao.parar()

    assert resposta.status_code == 413
    gravada = repo.movimentacao.por_id(id_do_header(resposta))
    assert gravada.requisicao_conteudo is not None and str(len(corpo)) in gravada.requisicao_conteudo
    assert "1111" not in gravada.requisicao_conteudo


async def test_conteudo_muito_grande_e_cortado_em_32_kb(
    cliente: AsyncClient, repo: RepositorioFalso, movimentacao: Movimentacao, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.main.TAMANHO_MAXIMO_CORPO", 100_000)  # só para chegar ao limite de 32 KB
    resposta = await cliente.post(URL, content=b'{"x": "' + b"a" * 40_000 + b'"}', headers=CABECALHOS_JSON)
    await movimentacao.parar()

    conteudo = repo.movimentacao.por_id(id_do_header(resposta)).requisicao_conteudo
    assert conteudo is not None and len(conteudo) == 32 * 1024 and conteudo.endswith("caracteres]")


async def test_banco_lento_ou_fora_na_gravacao_nao_afeta_a_resposta(
    cliente: AsyncClient, repo: RepositorioFalso, movimentacao: Movimentacao
) -> None:
    # Banco lento: a gravação fica presa num portão (sem cronômetro: não depende da velocidade da máquina).
    repo.movimentacao.portao = asyncio.Event()
    movimentacao.iniciar()
    resposta = await cliente.post(URL, json={"documento": CPF_VALIDO}, headers=CABECALHOS)

    assert resposta.status_code == 200  # a resposta saiu com a gravação ainda presa
    identificador = id_do_header(resposta)  # o número nasce na API: sempre existe
    assert repo.movimentacao.registros == []
    repo.movimentacao.portao.set()
    async with asyncio.timeout(2):
        while not repo.movimentacao.registros:
            await asyncio.sleep(0.01)
    assert repo.movimentacao.por_id(identificador).status_http == 200

    # Banco fora: o lote é perdido (o aviso vai para o log) e a resposta sai normalmente.
    repo.movimentacao.falha = True
    sem_banco = await cliente.post(URL, json={"documento": CPF_VALIDO}, headers=CABECALHOS)
    await movimentacao.parar()
    assert sem_banco.status_code == 200 and ulid.valido(sem_banco.headers["x-requisicao"])
    assert movimentacao.gravador.perdidos >= 1


async def test_cada_requisicao_tem_um_ulid_proprio(cliente: AsyncClient, movimentacao: Movimentacao) -> None:
    ids = [id_do_header(await cliente.post(URL, json={"documento": CPF_VALIDO}, headers=CABECALHOS)) for _ in range(30)]
    await movimentacao.parar()

    assert len(set(ids)) == 30
    agora = datetime.now(UTC)
    assert all(0 <= (agora - ulid.momento(i)).total_seconds() < 30 for i in ids)


async def test_iniciar_grava_em_segundo_plano_e_parar_encerra(
    cliente: AsyncClient, repo: RepositorioFalso, movimentacao: Movimentacao
) -> None:
    movimentacao.iniciar()
    resposta = await cliente.post(URL, json={"documento": "529.982.247-24"}, headers=CABECALHOS)

    async with asyncio.timeout(2):
        while not repo.movimentacao.registros:  # sem parar(): a tarefa de fundo grava sozinha
            await asyncio.sleep(0.01)
    await movimentacao.parar()

    gravada = repo.movimentacao.por_id(id_do_header(resposta))
    assert gravada.status_http == 422 and gravada.erro is not None and gravada.erro.codigo == "entrada_invalida"
