import secrets
import time
from typing import cast

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import Settings, get_settings
from app.repositorios.base import OrigemDados, RepositorioListas

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_ORIGEM_TTL_SEGUNDOS = 300


def verificar_api_key(
    chave_recebida: str | None = Security(_api_key_header),
    settings: Settings = Depends(get_settings),
) -> None:
    """Compara a chave em tempo constante, para evitar ataques de temporização."""
    esperada = settings.api_key.get_secret_value().encode("utf-8")
    if chave_recebida is None or not secrets.compare_digest(chave_recebida.encode("utf-8"), esperada):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não autorizado",
            headers={"WWW-Authenticate": "APIKey"},
        )


def get_repositorio(request: Request) -> RepositorioListas:
    """Repositório criado no lifespan. Nos testes, sobrescrito via dependency_overrides."""
    return cast(RepositorioListas, request.app.state.repositorio)


class CacheOrigem:
    """Guarda por alguns minutos de qual arquivo/carga vêm os dados (evita consulta por requisição)."""

    def __init__(self, ttl: float = _ORIGEM_TTL_SEGUNDOS) -> None:
        self._ttl = ttl
        self._valor: OrigemDados | None = None
        self._expira = 0.0

    async def obter(self, repo: RepositorioListas) -> OrigemDados:
        agora = time.monotonic()
        if self._valor is None or agora >= self._expira:
            self._valor = await repo.origem()
            self._expira = agora + self._ttl
        return self._valor


cache_origem = CacheOrigem()


def get_cache_origem() -> CacheOrigem:
    return cache_origem
