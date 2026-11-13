"""Repositório falso e cliente HTTP compartilhados pelos testes de integração (sem banco)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime

import anyio
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Response

from app.api.deps import CacheOrigem, get_cache_origem, get_repositorio
from app.core.config import get_settings
from app.core.exceptions import BancoIndisponivel
from app.main import app
from app.movimentacao import ulid
from app.movimentacao.http import Movimentacao
from app.movimentacao.registros import RegistroMovimentacao
from app.repositorios.base import OrigemDados, RegistroPep, Sancao


class MovimentacaoFalsa:
    """Guarda o que iria para as tabelas movimentacao e log_erros (no lugar do banco)."""

    def __init__(self) -> None:
        self.registros: list[RegistroMovimentacao] = []
        self.falha = False
        self.portao: asyncio.Event | None = None  # enquanto fechado, a gravação espera (banco lento)

    async def gravar(self, registros: list[RegistroMovimentacao]) -> None:
        if self.falha:
            raise ConnectionError("banco fora")
        if self.portao is not None:
            await self.portao.wait()
        self.registros.extend(registros)

    def por_id(self, requisicao_id: str) -> RegistroMovimentacao:
        return next(r for r in self.registros if r.requisicao_id == requisicao_id)


def id_do_header(resposta: Response) -> str:
    """O ULID que a API devolveu em X-Requisicao (confere que é um ULID válido)."""
    identificador = resposta.headers["x-requisicao"]
    assert ulid.valido(identificador), identificador
    return identificador


class RepositorioFalso:
    def __init__(self) -> None:
        self.sancoes: dict[str, list[Sancao]] = {}
        self.peps: dict[str, list[RegistroPep]] = {}
        self.falhar = False
        self.atraso = 0.0
        self.consultas_pep: list[str] = []
        self.erro_inesperado: Exception | None = None
        self.movimentacao = MovimentacaoFalsa()

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

    async def fechar(self) -> None:
        return None


@pytest.fixture
def repo() -> RepositorioFalso:
    return RepositorioFalso()


@pytest_asyncio.fixture
async def movimentacao(repo: RepositorioFalso) -> AsyncIterator[Movimentacao]:
    """A movimentação ligada à API, gravando no repositório falso. ``await movimentacao.parar()`` grava a fila."""
    app.state.movimentacao = Movimentacao(repo.movimentacao, ambiente=get_settings().app_env)
    yield app.state.movimentacao
    del app.state.movimentacao


@pytest_asyncio.fixture
async def cliente(repo: RepositorioFalso, movimentacao: Movimentacao) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_repositorio] = lambda: repo
    app.dependency_overrides[get_cache_origem] = lambda: CacheOrigem(ttl=0)
    app.state.repositorio = repo
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
