"""PostgreSQL: tradução das falhas do psycopg para 503 (banco_indisponivel) ou 504 (banco_timeout).

Falha de banco nunca vira 500. Erro de programação (tabela inexistente, SQL errado) continua sendo erro:
vira 500 e aparece no log como bug. Mesma lógica do módulo python-opcional/bancos da skill criar-api.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg import errors as pgerr
from psycopg_pool import PoolTimeout

from app.core.exceptions import BancoExpirou, BancoIndisponivel

logger = logging.getLogger(__name__)

# Classes de SQLSTATE de conexão (08), autenticação (28), recursos (53) e servidor desligando (57P).
_PG_PREFIXOS_INDISPONIVEL = ("08", "28", "53", "57P")


def pg_erro_de_conexao(sqlstate: str | None) -> bool:
    return sqlstate is not None and sqlstate.startswith(_PG_PREFIXOS_INDISPONIVEL)


@contextmanager
def traduzir_erros_postgres() -> Iterator[None]:
    try:
        yield
    except pgerr.QueryCanceled as exc:  # 57014: statement_timeout
        raise BancoExpirou() from exc
    except PoolTimeout as exc:  # nenhuma conexão livre (ou o banco não aceita conexões) no prazo do pool
        logger.error("postgres indisponível", extra={"erro": type(exc).__name__})
        raise BancoIndisponivel() from exc
    except psycopg.OperationalError as exc:
        # Na fase de conexão o sqlstate vem None (no Windows, porta fechada chega como ConnectionTimeout).
        # Depois de conectado, decide a classe do SQLSTATE; nunca o texto, que chega com acentuação quebrada.
        # Nunca logar exc.pgconn: contém a senha.
        if exc.sqlstate is None or pg_erro_de_conexao(exc.sqlstate):
            logger.error("postgres indisponível", extra={"erro": type(exc).__name__})
            raise BancoIndisponivel() from exc
        raise
    except psycopg.InterfaceError as exc:  # conexão fechada ou pool encerrado
        logger.error("postgres indisponível", extra={"erro": type(exc).__name__})
        raise BancoIndisponivel() from exc
