"""Repositório PostgreSQL (psycopg 3 async + pool). Schema credito, usuário da aplicação.

Windows: o psycopg async não funciona com o ProactorEventLoop. Rode o uvicorn com
--loop asyncio:SelectorEventLoop (ver README).
"""

from datetime import datetime

from psycopg_pool import AsyncConnectionPool

from app.core.config import Settings
from app.repositorios.base import (
    SQL_LOG_ERROS,
    SQL_ORIGEM,
    SQL_PEPS,
    SQL_SANCOES,
    OrigemDados,
    RegistroErro,
    RegistroPep,
    Sancao,
)
from app.repositorios.erros_postgres import traduzir_erros_postgres


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
        with traduzir_erros_postgres():
            async with self._pool.connection() as conn:
                cur = await conn.execute(sql, params)
                return await cur.fetchall()

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

    async def gravar_erros(self, registros: list[RegistroErro]) -> None:
        sql = SQL_LOG_ERROS.format(tabela="credito.log_erros", params=", ".join(["%s"] * 9))
        with traduzir_erros_postgres():
            async with self._pool.connection() as conn, conn.transaction():
                # A sessão é somente leitura (default_transaction_read_only); só esta transação, com SQL fixo,
                # escreve. A permissão do motor_app nesta tabela é apenas INSERT.
                await conn.execute("set transaction read write")
                async with conn.cursor() as cur:
                    await cur.executemany(sql, [_linha(r) for r in registros])

    async def fechar(self) -> None:
        await self._pool.close()


def _linha(r: RegistroErro) -> tuple[object, ...]:
    return (r.request_id, r.metodo, r.rota, r.status, r.codigo, r.titulo, r.tipo_excecao, r.duracao_ms, r.ambiente)
