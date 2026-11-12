"""Movimentação: cada requisição (menos /health e /metrics) é numerada na chegada e completada com a resposta.

Sem banco: o repositório falso numera e guarda a chegada; a fila de respostas é a do GravadorFalso.
"""

import os

import pytest
from httpx import AsyncClient

from app.repositorios.base import RegistroResposta
from tests.conftest import CPF_VALIDO
from tests.integration.conftest import ANO_FALSO, GravadorFalso, RepositorioFalso

URL = "/api/v1/triagem"
CABECALHOS = {"X-API-Key": os.environ["API_KEY"]}
CABECALHOS_JSON = {**CABECALHOS, "Content-Type": "application/json"}


async def test_requisicao_com_sucesso_e_numerada_e_a_resposta_e_gravada(
    cliente: AsyncClient, repo: RepositorioFalso, gravador_respostas: GravadorFalso
) -> None:
    resposta = await cliente.post(
        URL, json={"documento": "529.982.247-25", "nome": "Fulano de Tal"}, headers=CABECALHOS
    )

    assert resposta.status_code == 200
    assert resposta.headers["x-requisicao"] == f"{ANO_FALSO}-000001"
    (metodo, rota, conteudo) = repo.chegadas[0]
    assert (metodo, rota) == ("POST", URL)
    assert conteudo is not None and "Fulano de Tal" in conteudo
    (gravada,) = gravador_respostas.registros
    assert isinstance(gravada, RegistroResposta)
    assert (gravada.ano, gravada.requisicao, gravada.status_http) == (ANO_FALSO, 1, 200)
    assert (gravada.situacao_requisicao, gravada.situacao_resposta) == ("OK", "OK")
    assert gravada.conteudo == resposta.text  # o conteúdo gravado é exatamente o que o cliente recebeu


async def test_cpf_e_mascarado_no_conteudo_da_requisicao_e_da_resposta(
    cliente: AsyncClient, repo: RepositorioFalso, gravador_respostas: GravadorFalso
) -> None:
    for formato in ("529.982.247-25", CPF_VALIDO):
        await cliente.post(URL, json={"documento": formato}, headers=CABECALHOS)

    for _, _, conteudo in repo.chegadas:
        assert conteudo is not None
        assert "***.982.247-**" in conteudo and "529" not in conteudo and "-25" not in conteudo
    for gravada in gravador_respostas.registros:
        assert gravada.conteudo is not None and "529.982.247-25" not in gravada.conteudo


async def test_conteudo_da_requisicao_aceita_qualquer_formato(cliente: AsyncClient, repo: RepositorioFalso) -> None:
    corpos = [b"{nao e json", b"texto solto \xff com byte invalido", b'["lista"]', b"<xml><a>1</a></xml>"]
    for corpo in corpos:
        await cliente.post(URL, content=corpo, headers=CABECALHOS_JSON)

    gravados = [c for _, _, c in repo.chegadas]
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
    gravador_respostas: GravadorFalso,
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

    assert resposta.status_code == status
    assert resposta.headers["x-requisicao"] == f"{ANO_FALSO}-000001"
    (gravada,) = gravador_respostas.registros
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
    gravador: GravadorFalso,
    gravador_respostas: GravadorFalso,
    metodo: str,
    rota: str,
    cabecalhos: dict[str, str],
) -> None:
    # Varreduras e chamadas sem chave recebem 401 e não gravam nada: nem movimentação, nem log de erros.
    resposta = await cliente.request(metodo, rota, json={"documento": CPF_VALIDO}, headers=cabecalhos)

    assert resposta.status_code == 401
    assert "x-requisicao" not in resposta.headers
    assert resposta.headers["x-request-id"]  # o 401 continua com request_id e headers de segurança
    assert repo.chegadas == [] and gravador_respostas.registros == [] and gravador.registros == []


async def test_corpo_grande_sem_chave_responde_413_e_nao_entra_na_movimentacao(
    cliente: AsyncClient, repo: RepositorioFalso
) -> None:
    corpo = b'{"documento": "' + b"1" * 5000 + b'"}'
    resposta = await cliente.post(URL, content=corpo, headers={"Content-Type": "application/json"})

    assert resposta.status_code == 413
    assert "x-requisicao" not in resposta.headers and repo.chegadas == []


async def test_erro_nao_tratado_tambem_entra_na_movimentacao_com_os_cabecalhos_da_api(
    cliente: AsyncClient, repo: RepositorioFalso, gravador_respostas: GravadorFalso
) -> None:
    repo.erro_inesperado = RuntimeError("detalhe interno: senha=abc")
    resposta = await cliente.post(URL, json={"documento": CPF_VALIDO}, headers=CABECALHOS)

    assert resposta.status_code == 500
    assert resposta.headers["x-requisicao"] and resposta.headers["x-request-id"]
    assert resposta.headers["x-content-type-options"] == "nosniff"
    (gravada,) = gravador_respostas.registros
    assert gravada.status_http == 500 and gravada.conteudo is not None and "senha" not in gravada.conteudo


async def test_health_e_metrics_nao_entram_na_movimentacao(
    cliente: AsyncClient, repo: RepositorioFalso, gravador_respostas: GravadorFalso
) -> None:
    for rota in ("/health/live", "/health/ready", "/metrics"):
        resposta = await cliente.get(rota)
        assert resposta.status_code == 200
        assert "x-requisicao" not in resposta.headers

    assert repo.chegadas == [] and gravador_respostas.registros == []


async def test_corpo_acima_do_limite_registra_so_o_tamanho(cliente: AsyncClient, repo: RepositorioFalso) -> None:
    corpo = b'{"documento": "' + b"1" * 5000 + b'"}'
    resposta = await cliente.post(URL, content=corpo, headers=CABECALHOS_JSON)

    assert resposta.status_code == 413
    (_, _, conteudo) = repo.chegadas[0]
    assert conteudo is not None and str(len(corpo)) in conteudo and "1111" not in conteudo


async def test_conteudo_muito_grande_e_cortado_em_32_kb(
    cliente: AsyncClient, repo: RepositorioFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.main.TAMANHO_MAXIMO_CORPO", 100_000)  # só para chegar ao limite de 32 KB
    await cliente.post(URL, content=b'{"x": "' + b"a" * 40_000 + b'"}', headers=CABECALHOS_JSON)

    (_, _, conteudo) = repo.chegadas[0]
    assert conteudo is not None and len(conteudo) == 32 * 1024 and conteudo.endswith("caracteres]")


async def test_sem_numero_a_requisicao_segue_normalmente_e_nada_e_gravado(
    cliente: AsyncClient, repo: RepositorioFalso, gravador_respostas: GravadorFalso
) -> None:
    repo.numeracao_falha = True
    resposta = await cliente.post(URL, json={"documento": CPF_VALIDO}, headers=CABECALHOS)

    assert resposta.status_code == 200
    assert "x-requisicao" not in resposta.headers
    assert gravador_respostas.registros == []


async def test_banco_lento_na_chegada_nao_segura_a_requisicao_alem_do_prazo(
    cliente: AsyncClient, repo: RepositorioFalso, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.main.PRAZO_PARA_NUMERAR_SEGUNDOS", 0.1)
    repo.numeracao_atraso = 5.0
    resposta = await cliente.post(URL, json={"documento": CPF_VALIDO}, headers=CABECALHOS)

    assert resposta.status_code == 200
    assert "x-requisicao" not in resposta.headers
    assert repo.chegadas == []  # a gravação lenta foi abandonada
