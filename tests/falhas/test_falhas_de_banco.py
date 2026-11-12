"""Falhas de banco viram 503/504, nunca 500. Não precisa de banco no ar: roda no CI.

Usa os repositórios REAIS (psycopg async e python-oracledb) apontando para uma porta sem servidor, e
exceções dos drivers para os casos que exigiriam um banco lento ou quebrado.
"""

import os
from types import SimpleNamespace

import oracledb
import psycopg
import pytest
from httpx import ASGITransport, AsyncClient
from psycopg import errors as pgerr
from psycopg_pool import PoolTimeout

import app.main as modulo_main
from app.core.config import Settings, get_settings
from app.core.exceptions import BancoExpirou, BancoIndisponivel
from app.repositorios.base import RegistroErro, RegistroResposta
from app.repositorios.erros_oracle import oracle_codigo_do_erro, oracle_indisponivel, traduzir_erros_oracle
from app.repositorios.erros_postgres import pg_erro_de_conexao, traduzir_erros_postgres
from app.repositorios.oracle import RepositorioOracle
from app.repositorios.postgres import RepositorioPostgres
from tests.contrato import afirmar_problema

PORTA_SEM_SERVIDOR = 1


def _settings() -> Settings:
    # Senhas falsas: nada aqui conecta de verdade.
    return Settings(
        pg_host="127.0.0.1",
        pg_port=PORTA_SEM_SERVIDOR,
        pg_password="x",  # noqa: S106
        oracle_dsn=f"127.0.0.1:{PORTA_SEM_SERVIDOR}/XEPDB1",
        oracle_password="x",  # noqa: S106
    )


async def test_repositorio_postgres_fora_do_ar_vira_banco_indisponivel() -> None:
    repo = await RepositorioPostgres.criar(_settings())  # sobe mesmo com o banco fora
    try:
        with pytest.raises(BancoIndisponivel):
            await repo.buscar_sancoes("00000000000191")
    finally:
        await repo.fechar()


async def test_repositorio_oracle_fora_do_ar_vira_banco_indisponivel() -> None:
    repo = await RepositorioOracle.criar(_settings())
    try:
        with pytest.raises(BancoIndisponivel):
            await repo.verificar()
    finally:
        await repo.fechar()


_REGISTRO = RegistroErro(
    2026, 1, "r1", "POST", "/api/v1/triagem", 503, "banco_indisponivel", "Banco fora.", None, 1, "dev"
)
_RESPOSTA = RegistroResposta(2026, 1, 503, "{}", "OK", "ER")


async def test_log_de_erros_com_banco_fora_vira_banco_indisponivel() -> None:
    # O GravadorDeErros captura a exceção; aqui só se confere que o driver não vaza o erro cru.
    for repo in (await RepositorioPostgres.criar(_settings()), await RepositorioOracle.criar(_settings())):
        try:
            with pytest.raises(BancoIndisponivel):
                await repo.gravar_erros([_REGISTRO])
        finally:
            await repo.fechar()


async def test_movimentacao_com_banco_fora_vira_banco_indisponivel() -> None:
    # Numerar a chegada e gravar a resposta com o banco fora: exceção traduzida, nunca o erro cru do driver.
    for repo in (await RepositorioPostgres.criar(_settings()), await RepositorioOracle.criar(_settings())):
        try:
            with pytest.raises(BancoIndisponivel):
                await repo.registrar_requisicao("POST", "/api/v1/triagem", "{}")
            with pytest.raises(BancoIndisponivel):
                await repo.registrar_respostas([_RESPOSTA])
        finally:
            await repo.fechar()


# --- PostgreSQL: exceções do driver ---


@pytest.mark.parametrize(
    "erro",
    [
        PoolTimeout("couldn't get a connection after 5.00 sec"),
        psycopg.OperationalError("connection failed"),  # fase de conexão: sqlstate None
        pgerr.AdminShutdown("terminating connection due to administrator command"),  # 57P01
        pgerr.TooManyConnections("too many connections"),  # 53300
        psycopg.InterfaceError("the connection is closed"),
    ],
)
def test_postgres_indisponivel(erro: Exception) -> None:
    with pytest.raises(BancoIndisponivel), traduzir_erros_postgres():
        raise erro


def test_postgres_statement_timeout_vira_banco_expirou() -> None:
    with pytest.raises(BancoExpirou), traduzir_erros_postgres():
        raise pgerr.QueryCanceled("canceling statement due to statement timeout")


@pytest.mark.parametrize(
    "erro",
    [
        pgerr.UndefinedTable("relation does not exist"),  # bug: deve virar 500, não 503
        pgerr.DeadlockDetected("deadlock detected"),  # OperationalError com o banco no ar
    ],
)
def test_postgres_erro_de_programacao_continua_sendo_erro(erro: Exception) -> None:
    with pytest.raises(type(erro)), traduzir_erros_postgres():
        raise erro


@pytest.mark.parametrize(
    ("sqlstate", "indisponivel"),
    [("08006", True), ("28P01", True), ("53300", True), ("57P01", True), ("42P01", False), (None, False)],
)
def test_postgres_classifica_sqlstate(sqlstate: str | None, indisponivel: bool) -> None:
    assert pg_erro_de_conexao(sqlstate) is indisponivel


# --- Oracle: exceções do driver ---


def _erro_oracle(codigo: str) -> oracledb.DatabaseError:
    # O python-oracledb guarda em args[0] um objeto com full_code (ex.: "DPY-4024").
    return oracledb.DatabaseError(SimpleNamespace(full_code=codigo))


@pytest.mark.parametrize("codigo", ["DPY-4024", "ORA-01013"])
def test_oracle_timeout_vira_banco_expirou(codigo: str) -> None:
    with pytest.raises(BancoExpirou), traduzir_erros_oracle():
        raise _erro_oracle(codigo)


def test_oracle_senha_errada_vira_banco_indisponivel() -> None:
    with pytest.raises(BancoIndisponivel), traduzir_erros_oracle():
        raise _erro_oracle("ORA-01017")


def test_oracle_erro_de_programacao_continua_sendo_erro() -> None:
    with pytest.raises(oracledb.DatabaseError), traduzir_erros_oracle():
        raise _erro_oracle("ORA-00942")


def test_oracle_erro_sem_codigo_usa_o_nome_da_classe() -> None:
    assert oracle_codigo_do_erro(oracledb.InterfaceError()) == "InterfaceError"


@pytest.mark.parametrize(
    ("codigo", "indisponivel"),
    [
        ("DPY-6005", True),
        ("DPY-6001", True),
        ("ORA-12541", True),
        ("ORA-12600", True),
        ("ORA-28000", True),
        ("ORA-00942", False),
        ("ORA-00001", False),
    ],
)
def test_oracle_classifica_codigos(codigo: str, indisponivel: bool) -> None:
    assert oracle_indisponivel(codigo) is indisponivel


# --- API de ponta a ponta, com o repositório real e o banco fora do ar ---


@pytest.mark.parametrize("banco", ["postgres", "oracle"])
async def test_api_sobe_com_banco_fora_e_ready_responde_503(banco: str, monkeypatch: pytest.MonkeyPatch) -> None:
    s = _settings().model_copy(update={"motor_banco": banco})
    monkeypatch.setattr(modulo_main, "settings", s)
    app = modulo_main.app
    async with modulo_main.lifespan(app):  # não pode derrubar a subida
        assert type(app.state.repositorio).__name__.lower().endswith(banco)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as cliente:
            pronto = await cliente.get("/health/ready")
    assert pronto.status_code == 503 and pronto.json() == {"status": "banco_indisponivel"}


@pytest.mark.parametrize("banco", ["postgres", "oracle"])
async def test_triagem_com_banco_fora_responde_503(banco: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # Com o banco fora, o pool espera até 5 s por uma conexão. O tempo da requisição precisa ser maior
    # que essa espera (padrão: 10 s); senão o cliente recebe 504 em vez de 503.
    monkeypatch.setattr(get_settings(), "request_timeout_seconds", 10.0)
    monkeypatch.setattr(modulo_main, "settings", _settings().model_copy(update={"motor_banco": banco}))
    app = modulo_main.app
    async with modulo_main.lifespan(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as cliente:
            resposta = await cliente.post(
                "/api/v1/triagem", json={"documento": "00000000000191"}, headers={"X-API-Key": os.environ["API_KEY"]}
            )
    afirmar_problema(resposta, 503, "banco_indisponivel")
