"""Testes contra os bancos reais (dados da carga da CGU). Rode com: pytest -m bancos --no-cov

Leem as credenciais do .env da pasta do projeto. Só leitura, exceto a movimentação e o log de erros (só insert).
"""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import oracledb
import psycopg
import pytest
import pytest_asyncio
from dotenv import dotenv_values

from app.core.config import Settings
from app.movimentacao import ulid
from app.movimentacao.registros import RegistroErro, RegistroMovimentacao
from app.repositorios.base import RepositorioListas
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


def _utc(repo: RepositorioListas, coluna: str) -> str:
    """Expressão SQL que devolve o instante da coluna como texto em UTC (sem depender do fuso de quem lê)."""
    if isinstance(repo, RepositorioPostgres):
        return f"to_char({coluna} at time zone 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US')"
    return f"to_char(sys_extract_utc({coluna}), 'YYYY-MM-DD\"T\"HH24:MI:SS.FF6')"


def _instante(texto: str) -> datetime:
    return datetime.fromisoformat(texto).replace(tzinfo=UTC)


def _movimentacao(repo: RepositorioListas, requisicao_id: str) -> dict[str, Any]:
    (linha,) = _admin(
        repo,
        "select metodo, rota, requisicao_conteudo, situacao_requisicao, status_http, resposta_conteudo,"
        f" situacao_resposta, {_utc(repo, 'requisicao_em')}, {_utc(repo, 'resposta_em')}"
        " from {m} where requisicao_id = ?",
        requisicao_id,
    )
    nomes = (
        "metodo",
        "rota",
        "requisicao_conteudo",
        "situacao_requisicao",
        "status_http",
        "resposta_conteudo",
        "situacao_resposta",
        "requisicao_em",
        "resposta_em",
    )
    resultado = dict(zip(nomes, linha, strict=True))
    resultado["requisicao_em"] = _instante(resultado["requisicao_em"])
    resultado["resposta_em"] = _instante(resultado["resposta_em"])
    return resultado


def _registro(
    conteudo: str | None = "{}", status: int = 200, erro: RegistroErro | None = None, requisicao_id: str | None = None
) -> RegistroMovimentacao:
    chegada = datetime.now(UTC)
    situacao_requisicao = "ER" if 400 <= status < 500 else "OK"
    return RegistroMovimentacao(
        requisicao_id or ulid.novo(chegada),
        "POST",
        "/api/v1/triagem",
        conteudo,
        chegada,
        status,
        conteudo,
        chegada + timedelta(milliseconds=7),
        situacao_requisicao,
        "OK" if status < 400 else "ER",
        erro,
    )


@pytest.fixture
def limpeza(repo: RepositorioListas) -> Iterator[list[str]]:
    """ULID criados pelo teste: apagados no fim (log_erros primeiro, por causa da chave estrangeira)."""
    ids: list[str] = []
    yield ids
    for requisicao_id in ids:
        _admin(repo, "delete from {l} where requisicao_id = ?", requisicao_id)
        _admin(repo, "delete from {m} where requisicao_id = ?", requisicao_id)


async def test_lote_grava_a_movimentacao_com_os_instantes_e_o_erro_junto(
    repo: RepositorioListas, limpeza: list[str]
) -> None:
    erro = RegistroErro(
        "teste-bancos-1", "POST", "/api/v1/triagem", 422, "entrada_invalida", "Dados inválidos.", None, 5, "teste"
    )
    sucesso = _registro('{"documento": "***.982.247-**"}')
    recusada = _registro('{"documento": "x"}', status=422, erro=erro)
    limpeza.extend([sucesso.requisicao_id, recusada.requisicao_id])

    await repo.movimentacao.gravar([sucesso, recusada])

    linha = _movimentacao(repo, sucesso.requisicao_id)
    assert (linha["metodo"], linha["rota"], linha["status_http"]) == ("POST", "/api/v1/triagem", 200)
    assert linha["requisicao_conteudo"] == linha["resposta_conteudo"] == '{"documento": "***.982.247-**"}'
    assert (linha["situacao_requisicao"], linha["situacao_resposta"]) == ("OK", "OK")
    # Os instantes chegam ao banco como o mesmo momento (com fuso), não como hora local sem fuso.
    assert linha["requisicao_em"] == sucesso.requisicao_em
    assert linha["resposta_em"] == sucesso.resposta_em
    assert _admin(repo, "select count(*) from {l} where requisicao_id = ?", sucesso.requisicao_id) == [(0,)]

    assert _movimentacao(repo, recusada.requisicao_id)["situacao_requisicao"] == "ER"
    linhas = _admin(
        repo,
        "select request_id, status, codigo, titulo, tipo_excecao, duracao_ms, ambiente"
        " from {l} where requisicao_id = ?",
        recusada.requisicao_id,
    )
    assert [tuple(x) for x in linhas] == [
        ("teste-bancos-1", 422, "entrada_invalida", "Dados inválidos.", None, 5, "teste")
    ]


async def test_conteudo_aceita_qualquer_formato_e_tamanho_e_pode_ser_nulo(
    repo: RepositorioListas, limpeza: list[str]
) -> None:
    grande = "ação é ç " * 3500  # ~32 mil caracteres: passa de 32767 bytes (limite de texto comum do Oracle)
    xml = '<?xml version="1.0"?><a b="1">ç</a>'
    registros = [_registro(conteudo) for conteudo in (grande, xml, None)]
    limpeza.extend(r.requisicao_id for r in registros)

    await repo.movimentacao.gravar(registros)

    for registro in registros:
        linha = _movimentacao(repo, registro.requisicao_id)
        assert linha["requisicao_conteudo"] == registro.requisicao_conteudo
        assert linha["resposta_conteudo"] == registro.resposta_conteudo


async def test_ulid_repetido_recusa_o_lote_inteiro(repo: RepositorioListas, limpeza: list[str]) -> None:
    primeiro = _registro()
    limpeza.append(primeiro.requisicao_id)
    await repo.movimentacao.gravar([primeiro])

    novo = _registro()
    limpeza.append(novo.requisicao_id)
    with pytest.raises(Exception):  # noqa: B017, PT011 - chave primária repetida, cada driver com a sua exceção
        await repo.movimentacao.gravar([novo, _registro(requisicao_id=primeiro.requisicao_id)])

    # Uma transação só: o registro novo do mesmo lote também não ficou.
    assert _admin(repo, "select count(*) from {m} where requisicao_id = ?", novo.requisicao_id) == [(0,)]


async def test_lotes_ao_mesmo_tempo_gravam_tudo(repo: RepositorioListas, limpeza: list[str]) -> None:
    lotes = [[_registro() for _ in range(5)] for _ in range(6)]
    limpeza.extend(r.requisicao_id for lote in lotes for r in lote)

    await asyncio.gather(*(repo.movimentacao.gravar(lote) for lote in lotes))

    ids = [r.requisicao_id for lote in lotes for r in lote]
    assert _admin(repo, "select count(*) from {m} where requisicao_id in (" + ", ".join("?" * 30) + ")", *ids) == [
        (30,)
    ]


# O usuário da aplicação só insere: sem select, update ou delete nas duas tabelas.
ACESSOS_NEGADOS = (
    "select count(*) from {t}",
    "update {t} set rota = 'x'",
    "delete from {t}",
)


async def test_aplicacao_so_insere_na_movimentacao_e_no_log_de_erros(repo: RepositorioListas) -> None:
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
            for tabela in ("credito.movimentacao", "credito.log_erros"):
                for sql in ACESSOS_NEGADOS:
                    with pytest.raises(psycopg.errors.InsufficientPrivilege):
                        conexao.execute(sql.format(t=tabela))
                    conexao.rollback()
        return
    for tabela in ("movimentacao", "log_erros"):
        for sql in ACESSOS_NEGADOS:
            with pytest.raises(oracledb.DatabaseError):  # ORA-01031: sem privilégio
                await repo._consultar(sql.format(t=tabela), {})  # type: ignore[attr-defined]


async def test_log_de_erros_recusa_linha_sem_movimentacao(repo: RepositorioListas) -> None:
    # Chave que não existe na movimentação: o banco recusa (chave estrangeira); nunca fica linha solta.
    inexistente = ulid.novo()
    colunas = "(requisicao_id, request_id, metodo, rota, status, codigo, titulo, ambiente)"
    valores = "'teste-bancos-x', 'GET', '/x', 500, 'erro_interno', 'Erro interno.', 'teste'"
    if isinstance(repo, RepositorioPostgres):
        s = _settings()
        with (
            psycopg.connect(
                host=s.pg_host,
                port=s.pg_port,
                dbname=s.pg_database,
                user=s.pg_user,
                password=s.pg_password.get_secret_value(),
                connect_timeout=5,
            ) as conexao,
            pytest.raises(psycopg.errors.ForeignKeyViolation),
        ):
            conexao.execute(
                f"insert into credito.log_erros {colunas} values (%s, {valores})",
                (inexistente,),
            )
    else:
        with pytest.raises(oracledb.DatabaseError):  # ORA-02291: chave pai não encontrada
            async with repo._pool.acquire() as conexao:  # type: ignore[attr-defined]
                with conexao.cursor() as cursor:
                    await cursor.execute(
                        f"insert into log_erros {colunas} values (:1, {valores})",
                        [inexistente],
                    )
    assert _admin(repo, "select count(*) from {l} where request_id = ?", "teste-bancos-x") == [(0,)]
