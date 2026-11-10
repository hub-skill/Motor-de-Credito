"""Testes contra os bancos reais (dados da carga da CGU). Rode com: pytest -m bancos --no-cov

Leem as credenciais do .env da pasta do projeto. Só leitura.
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from dotenv import dotenv_values

from app.core.config import Settings
from app.repositorios.base import RepositorioListas
from app.repositorios.oracle import RepositorioOracle
from app.repositorios.postgres import RepositorioPostgres

pytestmark = pytest.mark.bancos
# Só as variáveis de banco (PG_* e ORACLE_*), sem as de administrador.
ENV = {
    k.lower(): v
    for k, v in dotenv_values(Path(__file__).resolve().parents[2] / ".env").items()
    if v and k.startswith(("PG_", "ORACLE_")) and "ADMIN" not in k
}
CNPJ_SANCIONADO = "19182685000162"  # Declaração de Inidoneidade (CEIS), publicado pela CGU


def _settings() -> Settings:
    return Settings(**{**ENV, "api_key": os.environ["API_KEY"]})


@pytest_asyncio.fixture(params=["postgres", "oracle"])
async def repo(request: pytest.FixtureRequest) -> AsyncIterator[RepositorioListas]:
    s = _settings()
    r: RepositorioListas = (
        await RepositorioPostgres.criar(s) if request.param == "postgres" else await RepositorioOracle.criar(s)
    )
    yield r
    await r.fechar()


async def test_banco_responde(repo: RepositorioListas) -> None:
    await repo.verificar()


async def test_cnpj_sancionado(repo: RepositorioListas) -> None:
    sancoes = await repo.buscar_sancoes(CNPJ_SANCIONADO)
    assert len(sancoes) == 1
    assert sancoes[0].cadastro == "CEIS"
    assert sancoes[0].categoria == "Declaração de Inidoneidade sem prazo determinado"
    assert sancoes[0].data_fim is None


async def test_documento_sem_sancao(repo: RepositorioListas) -> None:
    assert await repo.buscar_sancoes("00000000000191") == []


async def test_peps_por_miolo_e_origem(repo: RepositorioListas) -> None:
    origem = await repo.origem()
    assert any(a.endswith("_PEP.csv") for a in origem.arquivos)
    assert origem.carregado_em is not None
    # O miolo "000000" deve ter poucos ou nenhum registro; só checa o formato do retorno.
    for p in await repo.buscar_peps_por_miolo("000000"):
        assert p.nome
