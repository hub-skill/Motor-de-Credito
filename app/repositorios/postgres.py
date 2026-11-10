"""Repositório PostgreSQL (psycopg 3 async + pool). Schema credito, usuário da aplicação.

Windows: o psycopg async não funciona com o ProactorEventLoop. Rode o uvicorn com
--loop asyncio:SelectorEventLoop (ver README).
"""

import logging
from datetime import datetime

import psycopg
from psycopg import errors as pgerr
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from app.core.config import Settings
from app.core.exceptions import BancoExpirou, BancoIndisponivel
from app.repositorios.base import SQL_ORIGEM, SQL_PEPS, SQL_SANCOES, OrigemDados, RegistroPep, Sancao

logger = logging.getLogger(__name__)


class RepositorioPostgres:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    @classmethod
    async def criar(cls, s: Settings) -> "RepositorioPostgres":
        pool = AsyncConnectionPool(
            conninfo=(
                f"host={s.pg_host} port={s.pg_port} dbname={s.pg_database} user={s.pg_user}"
                f" sslmode={s.pg_sslmode} connect_timeout=5 application_name=motor-credito-api"
            ),
            kwargs={
                "password": s.pg_password.get_secret_value(),
                "options": f"-c statement_timeout={s.pg_statement_timeout_ms}"
                " -c default_transaction_read_only=on",  # a API só lê
            },
            min_size=s.pg_pool_min,
            max_size=s.pg_pool_max,
            open=False,
            check=AsyncConnectionPool.check_connection,
            timeout=5,  # espera máxima por uma conexão livre
        )
        await pool.open(wait=False)  # não derruba a subida se o banco estiver fora
        return cls(pool)

    async def _consultar(self, sql: str, params: tuple[object, ...]) -> list[tuple[object, ...]]:
        try:
            async with self._pool.connection() as conn:
                cur = await conn.execute(sql, params)
                return await cur.fetchall()
        except pgerr.QueryCanceled as exc:  # 57014: statement_timeout
            raise BancoExpirou() from exc
        except (PoolTimeout, psycopg.OperationalError) as exc:
            # Nunca logar exc.pgconn: contém a senha.
            logger.error("postgres indisponível", extra={"erro": type(exc).__name__})
            raise BancoIndisponivel() from exc

    async def buscar_sancoes(self, documento: str) -> list[Sancao]:
        linhas = await self._consultar(SQL_SANCOES.format(tabela="credito.sancoes", param="%s"), (documento,))
        return [Sancao(*linha) for linha in linhas]  # type: ignore[arg-type]

    async def buscar_peps_por_miolo(self, miolo: str) -> list[RegistroPep]:
        linhas = await self._consultar(SQL_PEPS.format(tabela="credito.peps", param="%s"), (miolo,))
        return [RegistroPep(*linha) for linha in linhas]  # type: ignore[arg-type]

    async def origem(self) -> OrigemDados:
        arquivos: list[str] = []
        ultima: datetime | None = None
        for tabela in ("credito.sancoes", "credito.peps"):
            for arquivo, carregado in await self._consultar(SQL_ORIGEM.format(tabela=tabela), ()):
                arquivos.append(str(arquivo))
                if isinstance(carregado, datetime) and (ultima is None or carregado > ultima):
                    ultima = carregado
        return OrigemDados("postgres", tuple(sorted(arquivos)), ultima)

    async def verificar(self) -> None:
        await self._consultar("select 1", ())

    async def fechar(self) -> None:
        await self._pool.close()
