"""Testes contra os bancos reais (dados da carga da CGU). Rode com: pytest -m bancos --no-cov

Leem as credenciais do .env da pasta do projeto. Só leitura, exceto o log de erros (só insert).
"""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import oracledb
import psycopg
import pytest
import pytest_asyncio
from dotenv import dotenv_values

from app.core.config import Settings
from app.repositorios.base import RegistroErro, RegistroResposta, RepositorioListas
from app.repositorios.oracle import RepositorioOracle
from app.repositorios.postgres import RepositorioPostgres

pytestmark = pytest.mark.bancos
# Só as variáveis de banco (PG_* e ORACLE_*), sem as de administrador.
ENV = {
    k.lower(): v
    for k, v in dotenv_values(Path(__file__).resolve().parents[2] / ".env").items()
    if v and k.startswith(("PG_", "ORACLE_")) and "ADMIN" not in k
}
CNPJ_SANCIONADO = "19182685000162"  # Declaração de Inidoneidade (CEIS), publicado pela CGU


def _settings() -> Settings:
    return Settings.model_validate({**ENV, "api_key": os.environ["API_KEY"]})


@pytest_asyncio.fixture(params=["postgres", "oracle"])
async def repo(request: pytest.FixtureRequest) -> AsyncIterator[RepositorioListas]:
    s = _settings()
    r: RepositorioListas = (
        await RepositorioPostgres.criar(s) if request.param == "postgres" else await RepositorioOracle.criar(s)
    )
    yield r
    await r.fechar()


async def test_banco_responde(repo: RepositorioListas) -> None:
    await repo.verificar()


async def test_cnpj_sancionado(repo: RepositorioListas) -> None:
    sancoes = await repo.buscar_sancoes(CNPJ_SANCIONADO)
    assert len(sancoes) == 1
    assert sancoes[0].cadastro == "CEIS"
    assert sancoes[0].categoria == "Declaração de Inidoneidade sem prazo determinado"
    assert sancoes[0].data_fim is None


async def test_documento_sem_sancao(repo: RepositorioListas) -> None:
    assert await repo.buscar_sancoes("00000000000191") == []


async def test_peps_por_miolo_e_origem(repo: RepositorioListas) -> None:
    origem = await repo.origem()
    assert any(a.endswith("_PEP.csv") for a in origem.arquivos)
    assert origem.carregado_em is not None
    # O miolo "000000" deve ter poucos ou nenhum registro; só checa o formato do retorno.
    for p in await repo.buscar_peps_por_miolo("000000"):
        assert p.nome


ENV_ADMIN = {
    k: v
    for k, v in dotenv_values(Path(__file__).resolve().parents[2] / ".env").items()
    if v
    and k.startswith(("PG_", "ORACLE_"))
    and "ADMIN" in k
    or k in ("PG_HOST", "PG_PORT", "PG_DATABASE", "ORACLE_DSN")
}
ANO_ATUAL = datetime.now(timezone(timedelta(hours=-3))).year  # horário de Brasília (sem horário de verão)


def _oracle_clob_como_texto(cursor: oracledb.Cursor, metadata: oracledb.FetchInfo) -> object:
    if metadata.type_code is oracledb.DB_TYPE_CLOB:
        return cursor.var(oracledb.DB_TYPE_LONG, arraysize=cursor.arraysize)
    return None


def _admin(repo: RepositorioListas, sql: str, *params: object) -> list[tuple[Any, ...]]:
    """Executa como administrador (só para conferir e limpar; a aplicação não lê estas tabelas).

    ``sql`` usa {m} e {l} para movimentacao e log_erros, e ? para os parâmetros.
    """
    if isinstance(repo, RepositorioPostgres):
        texto = sql.format(m="credito.movimentacao", l="credito.log_erros").replace("?", "%s")
        with psycopg.connect(
            host=ENV_ADMIN["PG_HOST"],
            port=ENV_ADMIN["PG_PORT"],
            dbname=ENV_ADMIN["PG_DATABASE"],
            user=ENV_ADMIN["PG_ADMIN_USER"],
            password=ENV_ADMIN["PG_ADMIN_PASSWORD"],
            connect_timeout=5,
        ) as conexao:
            cursor = conexao.execute(texto, params)
            return cursor.fetchall() if cursor.description else []
    texto = sql.format(m="motor_credito.movimentacao", l="motor_credito.log_erros")
    for n in range(1, len(params) + 1):
        texto = texto.replace("?", f":{n}", 1)
    with oracledb.connect(
        user=ENV_ADMIN["ORACLE_ADMIN_USER"], password=ENV_ADMIN["ORACLE_ADMIN_PASSWORD"], dsn=ENV_ADMIN["ORACLE_DSN"]
    ) as conexao:
        conexao.outputtypehandler = _oracle_clob_como_texto
        with conexao.cursor() as cursor:
            cursor.execute(texto, list(params))
            linhas = cursor.fetchall() if cursor.description else []
        conexao.commit()
        return [tuple(linha) for linha in linhas]


NOMES_MOVIMENTACAO = (
    "metodo",
    "rota",
    "requisicao_conteudo",
    "situacao_requisicao",
    "status_http",
    "resposta_conteudo",
    "resposta_em",
    "situacao_resposta",
    "requisicao_em",
)
SQL_MOVIMENTACAO = (
    "select metodo, rota, requisicao_conteudo, situacao_requisicao, status_http, resposta_conteudo,"
    " resposta_em, situacao_resposta, requisicao_em from {m} where ano = ? and requisicao = ?"
)


def _movimentacao(repo: RepositorioListas, ano: int, requisicao: int) -> dict[str, Any]:
    (linha,) = _admin(repo, SQL_MOVIMENTACAO, ano, requisicao)
    return dict(zip(NOMES_MOVIMENTACAO, linha, strict=True))


@pytest.fixture
def limpeza(repo: RepositorioListas) -> Iterator[list[tuple[int, int]]]:
    """Chaves (ano, requisicao) criadas pelo teste: apagadas no fim (log_erros primeiro, por causa da chave)."""
    chaves: list[tuple[int, int]] = []
    yield chaves
    for ano, requisicao in chaves:
        _admin(repo, "delete from {l} where ano = ? and requisicao = ?", ano, requisicao)
        _admin(repo, "delete from {m} where ano = ? and requisicao = ?", ano, requisicao)


async def test_requisicao_e_numerada_e_a_chegada_e_gravada(
    repo: RepositorioListas, limpeza: list[tuple[int, int]]
) -> None:
    ano, numero = await repo.registrar_requisicao("POST", "/api/v1/triagem", '{"documento": "***.982.247-**"}')
    limpeza.append((ano, numero))

    assert ano == ANO_ATUAL and numero >= 1
    linha = _movimentacao(repo, ano, numero)
    assert (linha["metodo"], linha["rota"]) == ("POST", "/api/v1/triagem")
    assert linha["requisicao_conteudo"] == '{"documento": "***.982.247-**"}'
    assert linha["requisicao_em"] is not None
    # Na chegada a resposta e as duas situações ainda não existem.
    assert linha["resposta_em"] is None and linha["status_http"] is None
    assert linha["situacao_requisicao"] is None and linha["situacao_resposta"] is None


async def test_resposta_completa_a_mesma_linha_uma_vez_so(
    repo: RepositorioListas, limpeza: list[tuple[int, int]]
) -> None:
    ano, numero = await repo.registrar_requisicao("POST", "/api/v1/triagem", "{}")
    limpeza.append((ano, numero))

    await repo.registrar_respostas([RegistroResposta(ano, numero, 422, '{"code": "entrada_invalida"}', "ER", "ER")])
    linha = _movimentacao(repo, ano, numero)
    assert (linha["status_http"], linha["situacao_requisicao"], linha["situacao_resposta"]) == (422, "ER", "ER")
    assert linha["resposta_conteudo"] == '{"code": "entrada_invalida"}'
    assert linha["resposta_em"] is not None and linha["resposta_em"] >= linha["requisicao_em"]

    # Uma segunda resposta para a mesma requisição não sobrescreve a primeira.
    await repo.registrar_respostas([RegistroResposta(ano, numero, 200, "outra", "OK", "OK")])
    assert _movimentacao(repo, ano, numero)["resposta_conteudo"] == '{"code": "entrada_invalida"}'


async def test_requisicoes_ao_mesmo_tempo_recebem_numeros_diferentes(
    repo: RepositorioListas, limpeza: list[tuple[int, int]]
) -> None:
    chaves = await asyncio.gather(*(repo.registrar_requisicao("GET", f"/x/{n}", None) for n in range(20)))
    limpeza.extend(chaves)

    assert len({chave for chave in chaves}) == 20
    assert {ano for ano, _ in chaves} == {ANO_ATUAL}


async def test_conteudo_aceita_qualquer_formato_e_tamanho_e_pode_ser_nulo(
    repo: RepositorioListas, limpeza: list[tuple[int, int]]
) -> None:
    grande = "ação é ç " * 3500  # ~32 mil caracteres: passa de 32767 bytes (limite de texto comum do Oracle)
    xml = '<?xml version="1.0"?><a b="1">ç</a>'
    for conteudo in (grande, xml, None):
        ano, numero = await repo.registrar_requisicao("POST", "/x", conteudo)
        limpeza.append((ano, numero))
        await repo.registrar_respostas([RegistroResposta(ano, numero, 200, conteudo, "OK", "OK")])

        linha = _movimentacao(repo, ano, numero)
        assert linha["requisicao_conteudo"] == conteudo
        assert linha["resposta_conteudo"] == conteudo


# Acessos que o usuário da aplicação NÃO pode ter: ela só executa as funções/procedures da movimentação.
ACESSOS_NEGADOS_POSTGRES = (
    "select count(*) from credito.movimentacao",
    "select count(*) from credito.contador_requisicao",
    "update credito.contador_requisicao set ultimo = 1",
    "delete from credito.movimentacao",
)
ACESSOS_NEGADOS_ORACLE = (
    "select count(*) from movimentacao",
    "select count(*) from contador_requisicao",
    "update contador_requisicao set ultimo = 1",
    "delete from movimentacao",
)


async def test_aplicacao_nao_le_nem_altera_a_movimentacao(repo: RepositorioListas) -> None:
    if isinstance(repo, RepositorioPostgres):
        # Sessão de escrita com o usuário da aplicação: a negação vem da permissão (InsufficientPrivilege), não
        # do modo somente leitura que a API usa, que barraria o update e o delete antes.
        s = _settings()
        with psycopg.connect(
            host=s.pg_host,
            port=s.pg_port,
            dbname=s.pg_database,
            user=s.pg_user,
            password=s.pg_password.get_secret_value(),
            connect_timeout=5,
        ) as conexao:
            for sql in ACESSOS_NEGADOS_POSTGRES:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    conexao.execute(sql)
                conexao.rollback()
        return
    for sql in ACESSOS_NEGADOS_ORACLE:
        with pytest.raises(oracledb.DatabaseError):  # ORA-00942: sem privilégio nem sinônimo
            await repo._consultar(sql, {})  # type: ignore[attr-defined]


async def test_grava_log_de_erros_com_a_chave_da_movimentacao_mas_nao_le(
    repo: RepositorioListas, limpeza: list[tuple[int, int]]
) -> None:
    # A aplicação só tem INSERT em log_erros: gravar funciona, ler é negado (sessão de leitura comum).
    ano, numero = await repo.registrar_requisicao("POST", "/api/v1/triagem", "{}")
    limpeza.append((ano, numero))
    await repo.gravar_erros(
        [
            RegistroErro(
                ano,
                numero,
                "teste-bancos-1",
                "POST",
                "/api/v1/triagem",
                422,
                "entrada_invalida",
                "Dados inválidos.",
                None,
                5,
                "teste",
            ),
            RegistroErro(
                ano,
                numero,
                "teste-bancos-2",
                "GET",
                "/x",
                500,
                "erro_interno",
                "Erro interno.",
                "builtins.RuntimeError",
                None,
                "teste",
            ),
        ]
    )

    linhas = _admin(
        repo, "select ano, requisicao, codigo from {l} where ano = ? and requisicao = ? order by id", ano, numero
    )
    assert [(a, r, c) for a, r, c in linhas] == [(ano, numero, "entrada_invalida"), (ano, numero, "erro_interno")]

    postgres = isinstance(repo, RepositorioPostgres)
    with pytest.raises(Exception):  # noqa: B017, PT011 - permissão negada, cada driver com sua exceção
        await repo._consultar(  # type: ignore[attr-defined]
            "select count(*) from credito.log_erros" if postgres else "select count(*) from log_erros",
            () if postgres else {},
        )


async def test_log_de_erros_recusa_erro_sem_movimentacao(repo: RepositorioListas) -> None:
    # Chave que não existe na movimentação: o banco recusa (chave estrangeira); nunca grava linha solta.
    inexistente = RegistroErro(
        ANO_ATUAL, 999_999_999, "teste-bancos-x", "GET", "/x", 500, "erro_interno", "Erro interno.", None, None, "teste"
    )
    with pytest.raises(Exception):  # noqa: B017, PT011 - violação de chave estrangeira, cada driver com a sua
        await repo.gravar_erros([inexistente])
    assert _admin(repo, "select count(*) from {l} where request_id = ?", "teste-bancos-x") == [(0,)]
