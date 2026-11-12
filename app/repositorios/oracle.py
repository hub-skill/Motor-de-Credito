"""Repositório Oracle (python-oracledb thin, async + pool). MOTOR_APP lê pelos sinônimos."""

from dataclasses import asdict
from datetime import datetime

import oracledb

from app.core.config import Settings
from app.repositorios.base import (
    SQL_LOG_ERROS,
    SQL_ORIGEM,
    SQL_PEPS,
    SQL_SANCOES,
    OrigemDados,
    RegistroErro,
    RegistroPep,
    RegistroResposta,
    Sancao,
)
from app.repositorios.erros_oracle import traduzir_erros_oracle


def _para_date(valor: object) -> object:
    """O Oracle devolve DATE como datetime; o contrato usa date."""
    return valor.date() if isinstance(valor, datetime) else valor


class RepositorioOracle:
    def __init__(self, pool: oracledb.AsyncConnectionPool, call_timeout_ms: int) -> None:
        self._pool = pool
        self._timeout = call_timeout_ms

    @classmethod
    async def criar(cls, s: Settings) -> "RepositorioOracle":
        pool = oracledb.create_pool_async(
            user=s.oracle_user,
            password=s.oracle_password.get_secret_value(),
            dsn=s.oracle_dsn,
            min=s.oracle_pool_min,
            max=s.oracle_pool_max,
            increment=1,
            ping_interval=60,
            wait_timeout=5000,  # ms esperando conexão livre
            getmode=oracledb.POOL_GETMODE_TIMEDWAIT,
        )
        return cls(pool, s.oracle_call_timeout_ms)

    async def _consultar(self, sql: str, params: dict[str, object]) -> list[tuple[object, ...]]:
        with traduzir_erros_oracle():
            async with self._pool.acquire() as conn:
                conn.call_timeout = self._timeout
                with conn.cursor() as cur:
                    await cur.execute(sql, params)
                    linhas: list[tuple[object, ...]] = await cur.fetchall()
                    return linhas

    async def buscar_sancoes(self, documento: str) -> list[Sancao]:
        linhas = await self._consultar(
            SQL_SANCOES.format(tabela="sancoes", param=":documento"), {"documento": documento}
        )
        return [
            Sancao(c, cod, cat, org, uf, _para_date(ini), _para_date(fim), proc)  # type: ignore[arg-type]
            for c, cod, cat, org, uf, ini, fim, proc in linhas
        ]

    async def buscar_peps_por_miolo(self, miolo: str) -> list[RegistroPep]:
        linhas = await self._consultar(SQL_PEPS.format(tabela="peps", param=":miolo"), {"miolo": miolo})
        return [
            RegistroPep(nome, funcao, orgao, _para_date(ini), _para_date(fim), _para_date(car))  # type: ignore[arg-type]
            for nome, funcao, orgao, ini, fim, car in linhas
        ]

    async def origem(self) -> OrigemDados:
        arquivos: list[str] = []
        ultima: datetime | None = None
        for tabela in ("sancoes", "peps"):
            for arquivo, carregado in await self._consultar(SQL_ORIGEM.format(tabela=tabela), {}):
                arquivos.append(str(arquivo))
                if isinstance(carregado, datetime) and (ultima is None or carregado > ultima):
                    ultima = carregado
        return OrigemDados("oracle", tuple(sorted(arquivos)), ultima)

    async def verificar(self) -> None:
        await self._consultar("select 1 from dual", {})

    async def gravar_erros(self, registros: list[RegistroErro]) -> None:
        sql = SQL_LOG_ERROS.format(
            tabela="log_erros",  # sinônimo do MOTOR_APP para MOTOR_CREDITO.LOG_ERROS
            params=(
                ":ano, :requisicao, :request_id, :metodo, :rota, :status, :codigo, :titulo, :tipo_excecao,"
                " :duracao_ms, :ambiente"
            ),
        )
        with traduzir_erros_oracle():
            async with self._pool.acquire() as conn:
                conn.call_timeout = self._timeout
                with conn.cursor() as cur:
                    await cur.executemany(sql, [asdict(r) for r in registros])
                await conn.commit()

    async def registrar_requisicao(self, metodo: str, rota: str, conteudo: str | None) -> tuple[int, int]:
        # Procedure do dono (MOTOR_CREDITO) pelo sinônimo: o MOTOR_APP só tem EXECUTE nela.
        with traduzir_erros_oracle():
            async with self._pool.acquire() as conn:
                conn.call_timeout = self._timeout
                with conn.cursor() as cur:
                    ano = cur.var(int)
                    numero = cur.var(int)
                    await cur.callproc("registrar_requisicao", [metodo, rota, await _clob(conn, conteudo), ano, numero])
                await conn.commit()
        return int(ano.getvalue()), int(numero.getvalue())

    async def registrar_respostas(self, registros: list[RegistroResposta]) -> None:
        with traduzir_erros_oracle():
            async with self._pool.acquire() as conn:
                conn.call_timeout = self._timeout
                with conn.cursor() as cur:
                    for r in registros:
                        parametros: list[object] = [r.ano, r.requisicao, r.status_http, await _clob(conn, r.conteudo)]
                        parametros += [r.situacao_requisicao, r.situacao_resposta]
                        await cur.callproc("registrar_resposta", parametros)
                await conn.commit()

    async def fechar(self) -> None:
        await self._pool.close(force=True)


async def _clob(conn: oracledb.AsyncConnection, texto: str | None) -> oracledb.AsyncLOB | None:
    """Texto como CLOB temporário: sem isto, um texto acima de 32767 bytes não passa como parâmetro de procedure."""
    if texto is None:
        return None
    lob: oracledb.AsyncLOB = await conn.createlob(oracledb.DB_TYPE_CLOB, texto)
    return lob
