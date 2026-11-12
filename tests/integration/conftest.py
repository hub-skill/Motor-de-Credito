"""Repositório falso e cliente HTTP compartilhados pelos testes de integração (sem banco)."""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import anyio
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.deps import CacheOrigem, get_cache_origem, get_repositorio
from app.core.exceptions import BancoIndisponivel
from app.main import app
from app.repositorios.base import OrigemDados, RegistroErro, RegistroPep, RegistroResposta, Sancao

ANO_FALSO = 2026


class RepositorioFalso:
    def __init__(self) -> None:
        self.sancoes: dict[str, list[Sancao]] = {}
        self.peps: dict[str, list[RegistroPep]] = {}
        self.falhar = False
        self.atraso = 0.0
        self.consultas_pep: list[str] = []
        self.erro_inesperado: Exception | None = None
        # Movimentação: o que chegou (na ordem; o número é a posição + 1) e a falha/lentidão da numeração.
        self.chegadas: list[tuple[str, str, str | None]] = []  # (método, rota, conteúdo)
        self.numeracao_falha = False
        self.numeracao_atraso = 0.0

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

    async def registrar_requisicao(self, metodo: str, rota: str, conteudo: str | None) -> tuple[int, int]:
        if self.numeracao_falha:
            raise BancoIndisponivel()
        await anyio.sleep(self.numeracao_atraso)
        self.chegadas.append((metodo, rota, conteudo))
        return ANO_FALSO, len(self.chegadas)

    async def registrar_respostas(self, registros: list[RegistroResposta]) -> None:
        return None

    async def fechar(self) -> None:
        return None


class GravadorFalso:
    """Guarda o que a API põe na fila de gravação (no lugar da fila que grava no banco)."""

    def __init__(self) -> None:
        self.registros: list[Any] = []

    def registrar(self, registro: Any) -> None:
        self.registros.append(registro)


@pytest.fixture
def repo() -> RepositorioFalso:
    return RepositorioFalso()


@pytest.fixture
def gravador() -> GravadorFalso:
    """Erros que iriam para a tabela log_erros."""
    return GravadorFalso()


@pytest.fixture
def gravador_respostas() -> GravadorFalso:
    """Respostas que iriam completar a movimentação."""
    return GravadorFalso()


@pytest_asyncio.fixture
async def cliente(
    repo: RepositorioFalso, gravador: GravadorFalso, gravador_respostas: GravadorFalso
) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_repositorio] = lambda: repo
    app.dependency_overrides[get_cache_origem] = lambda: CacheOrigem(ttl=0)
    app.state.repositorio = repo
    app.state.gravador_erros = gravador
    app.state.gravador_respostas = gravador_respostas
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    del app.state.gravador_erros
    del app.state.gravador_respostas
