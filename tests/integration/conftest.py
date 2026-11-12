"""Repositório falso e cliente HTTP compartilhados pelos testes de integração (sem banco)."""

from collections.abc import AsyncIterator
from datetime import datetime

import anyio
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.deps import CacheOrigem, get_cache_origem, get_repositorio
from app.core.exceptions import BancoIndisponivel
from app.main import app
from app.repositorios.base import OrigemDados, RegistroErro, RegistroPep, Sancao


class RepositorioFalso:
    def __init__(self) -> None:
        self.sancoes: dict[str, list[Sancao]] = {}
        self.peps: dict[str, list[RegistroPep]] = {}
        self.falhar = False
        self.atraso = 0.0
        self.consultas_pep: list[str] = []
        self.erro_inesperado: Exception | None = None

    async def buscar_sancoes(self, documento: str) -> list[Sancao]:
        if self.falhar:
            raise BancoIndisponivel()
        if self.erro_inesperado is not None:
            raise self.erro_inesperado
        await anyio.sleep(self.atraso)
        return self.sancoes.get(documento, [])

    async def buscar_peps_por_miolo(self, miolo: str) -> list[RegistroPep]:
        self.consultas_pep.append(miolo)
        return self.peps.get(miolo, [])

    async def origem(self) -> OrigemDados:
        return OrigemDados("falso", ("20261110_CEIS.csv",), datetime(2026, 11, 10, 7, 0))

    async def verificar(self) -> None:
        if self.falhar:
            raise BancoIndisponivel()

    async def gravar_erros(self, registros: list[RegistroErro]) -> None:
        return None

    async def fechar(self) -> None:
        return None


class GravadorFalso:
    """Guarda os erros registrados pela API (no lugar da fila que grava na tabela log_erros)."""

    def __init__(self) -> None:
        self.registros: list[RegistroErro] = []

    def registrar(self, registro: RegistroErro) -> None:
        self.registros.append(registro)


@pytest.fixture
def repo() -> RepositorioFalso:
    return RepositorioFalso()


@pytest.fixture
def gravador() -> GravadorFalso:
    return GravadorFalso()


@pytest_asyncio.fixture
async def cliente(repo: RepositorioFalso, gravador: GravadorFalso) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_repositorio] = lambda: repo
    app.dependency_overrides[get_cache_origem] = lambda: CacheOrigem(ttl=0)
    app.state.repositorio = repo
    app.state.gravador_erros = gravador
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    del app.state.gravador_erros
