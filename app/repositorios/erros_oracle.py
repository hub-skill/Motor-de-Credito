"""Oracle: tradução das falhas do python-oracledb para 503 (banco_indisponivel) ou 504 (banco_timeout).

Falha de banco nunca vira 500. Erro de programação (ORA-00942 etc.) continua sendo erro (500, bug).
Mesma lógica do módulo python-opcional/bancos da skill criar-api.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import oracledb

from app.core.exceptions import BancoExpirou, BancoIndisponivel

logger = logging.getLogger(__name__)

# DPY-4024: call_timeout estourado. ORA-01013: comando cancelado pelo tempo limite.
_ORA_EXPIROU = {"DPY-4024", "ORA-01013"}

# Login, instância, conexão perdida e listener. DPY-6xxx (rede) e ORA-125xx/126xx entram pelo prefixo.
_ORA_INDISPONIVEL = {
    "DPY-4005",  # conexão encerrada
    "DPY-4011",  # conexão caiu
    "ORA-01017",  # usuário/senha inválidos
    "ORA-01033",
    "ORA-01034",
    "ORA-01089",
    "ORA-03113",
    "ORA-03114",
    "ORA-03135",
    "ORA-12154",
    "ORA-12170",
    "ORA-12514",
    "ORA-12537",
    "ORA-12541",
    "ORA-12545",
    "ORA-28000",
}


def oracle_codigo_do_erro(exc: oracledb.Error) -> str:
    erro = exc.args[0] if exc.args else None
    return str(getattr(erro, "full_code", type(exc).__name__))


def oracle_indisponivel(codigo: str) -> bool:
    return codigo in _ORA_INDISPONIVEL or codigo.startswith(("DPY-6", "ORA-125", "ORA-126"))


@contextmanager
def traduzir_erros_oracle() -> Iterator[None]:
    try:
        yield
    except oracledb.Error as exc:
        codigo = oracle_codigo_do_erro(exc)
        # Só o código: a mensagem do driver pode trazer detalhes da conexão.
        logger.error("erro oracle", extra={"codigo_oracle": codigo})
        if codigo in _ORA_EXPIROU:
            raise BancoExpirou() from exc
        if oracle_indisponivel(codigo):
            raise BancoIndisponivel() from exc
        raise
