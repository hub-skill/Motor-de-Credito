import os
from collections.abc import AsyncIterator
from datetime import date, datetime

import anyio
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.deps import CacheOrigem, get_cache_origem, get_repositorio
from app.core.exceptions import BancoIndisponivel
from app.main import app
from app.repositorios.base import OrigemDados, RegistroPep, Sancao
from tests.conftest import CNPJ_VALIDO, CPF_VALIDO

URL = "/api/v1/triagem"
CABECALHOS = {"X-API-Key": os.environ["API_KEY"]}


class RepositorioFalso:
    def __init__(self) -> None:
        self.sancoes: dict[str, list[Sancao]] = {}
        self.peps: dict[str, list[RegistroPep]] = {}
        self.falhar = False
        self.atraso = 0.0
        self.consultas_pep: list[str] = []

    async def buscar_sancoes(self, documento: str) -> list[Sancao]:
        if self.falhar:
            raise BancoIndisponivel()
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
async def cliente(repo: RepositorioFalso) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_repositorio] = lambda: repo
    app.dependency_overrides[get_cache_origem] = lambda: CacheOrigem(ttl=0)
    app.state.repositorio = repo
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_cpf_sem_restricao_libera(cliente: AsyncClient) -> None:
    r = await cliente.post(URL, json={"documento": "529.982.247-25", "nome": "Fulano"}, headers=CABECALHOS)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["resultado"] == "liberar"
    assert corpo["documento"] == "***.982.247-**"  # CPF nunca volta completo
    assert corpo["pep"] == {"verificado": True, "ativo": False, "funcoes": []}
    assert corpo["fonte"]["banco"] == "falso"
    assert r.headers["cache-control"] == "no-store"


async def test_cnpj_com_sancao_vigente_bloqueia(cliente: AsyncClient, repo: RepositorioFalso) -> None:
    repo.sancoes[CNPJ_VALIDO] = [
        Sancao("CEIS", 79854, "Inidoneidade", "Prefeitura X", "SC", date(2016, 6, 28), None, "104/2014")
    ]
    r = await cliente.post(URL, json={"documento": "00.000.000/0001-91"}, headers=CABECALHOS)
    corpo = r.json()
    assert r.status_code == 200 and corpo["resultado"] == "bloquear"
    assert corpo["sancoes"][0]["vigente"] is True
    assert corpo["motivos"][0]["codigo"] == "S01"
    assert repo.consultas_pep == []  # CNPJ não consulta PEP


async def test_pep_ativo_vai_para_revisao(cliente: AsyncClient, repo: RepositorioFalso) -> None:
    repo.peps["982247"] = [RegistroPep("MARIA DA SILVA", "PREFEITO", "PREFEITURA", date(2025, 1, 1), None, None)]
    r = await cliente.post(URL, json={"documento": CPF_VALIDO, "nome": "maria da silva"}, headers=CABECALHOS)
    corpo = r.json()
    assert corpo["resultado"] == "revisar"
    assert corpo["pep"] == {"verificado": True, "ativo": True, "funcoes": ["PREFEITO"]}
    assert repo.consultas_pep == ["982247"]


async def test_cpf_sem_nome_nao_consulta_pep(cliente: AsyncClient, repo: RepositorioFalso) -> None:
    r = await cliente.post(URL, json={"documento": CPF_VALIDO}, headers=CABECALHOS)
    assert r.json()["pep"]["verificado"] is False and repo.consultas_pep == []


@pytest.mark.parametrize("cabecalhos", [{}, {"X-API-Key": "errada"}])
async def test_sem_chave_ou_chave_errada(cliente: AsyncClient, cabecalhos: dict[str, str]) -> None:
    r = await cliente.post(URL, json={"documento": CPF_VALIDO}, headers=cabecalhos)
    assert r.status_code == 401 and r.json()["error"]["code"] == "http_401"


@pytest.mark.parametrize(
    "corpo",
    [
        {"documento": "52998224724"},  # dígito errado
        {"documento": ""},
        {},
        {"documento": "' OR 1=1 --"},  # injeção
        {"documento": CPF_VALIDO, "nome": "Maria\x00Silva"},  # byte nulo
        {"documento": CPF_VALIDO, "nome": "x" * 201},  # nome grande demais
        {"documento": "1" * 21},
    ],
)
async def test_entradas_invalidas(cliente: AsyncClient, corpo: dict[str, str]) -> None:
    r = await cliente.post(URL, json=corpo, headers=CABECALHOS)
    assert r.status_code == 422
    erro = r.json()["error"]
    assert erro["code"] == "entrada_invalida" and erro["request_id"]
    assert "52998224724" not in r.text  # não ecoa a entrada


async def test_corpo_grande_demais(cliente: AsyncClient) -> None:
    r = await cliente.post(
        URL,
        content=b'{"documento": "' + b"1" * 5000 + b'"}',
        headers={**CABECALHOS, "Content-Type": "application/json"},
    )
    assert r.status_code == 413


async def test_banco_fora_do_ar(cliente: AsyncClient, repo: RepositorioFalso) -> None:
    repo.falhar = True
    r = await cliente.post(URL, json={"documento": CPF_VALIDO}, headers=CABECALHOS)
    assert r.status_code == 503 and r.json()["error"]["code"] == "banco_indisponivel"
    pronto = await cliente.get("/health/ready")
    assert pronto.status_code == 503


async def test_timeout(cliente: AsyncClient, repo: RepositorioFalso) -> None:
    repo.atraso = 3  # REQUEST_TIMEOUT_SECONDS=2 no conftest
    r = await cliente.post(URL, json={"documento": CPF_VALIDO}, headers=CABECALHOS)
    assert r.status_code == 504 and r.json()["error"]["code"] == "timeout"


async def test_health(cliente: AsyncClient) -> None:
    assert (await cliente.get("/health/live")).json() == {"status": "ok"}
    assert (await cliente.get("/health/ready")).status_code == 200
