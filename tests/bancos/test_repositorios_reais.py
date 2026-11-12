"""Testes contra os bancos reais (dados da carga da CGU). Rode com: pytest -m bancos --no-cov

Leem as credenciais do .env da pasta do projeto. Só leitura, exceto o log de erros (só insert).
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from dotenv import dotenv_values

from app.core.config import Settings
from app.repositorios.base import RegistroErro, RepositorioListas
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
    return Settings.model_validate({**ENV, "api_key": os.environ["API_KEY"]})


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


async def test_grava_log_de_erros_mas_nao_le(repo: RepositorioListas) -> None:
    # A aplicação só tem INSERT em log_erros: gravar funciona, ler é negado (sessão de leitura comum).
    await repo.gravar_erros(
        [
            RegistroErro(
                "teste-bancos-1",
                "POST",
                "/api/v1/triagem",
                422,
                "entrada_invalida",
                "Dados inválidos.",
                None,
                5,
                "teste",
            ),
            RegistroErro(
                "teste-bancos-2",
                "GET",
                "/x",
                500,
                "erro_interno",
                "Erro interno.",
                "builtins.RuntimeError",
                None,
                "teste",
            ),
        ]
    )
    postgres = isinstance(repo, RepositorioPostgres)
    with pytest.raises(Exception):  # noqa: B017, PT011 - permissão negada, cada driver com sua exceção
        await repo._consultar(  # type: ignore[attr-defined]
            "select count(*) from credito.log_erros" if postgres else "select count(*) from log_erros",
            () if postgres else {},
        )
