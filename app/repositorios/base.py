"""Contrato dos repositórios: a regra de negócio não sabe qual banco está por trás."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from app.movimentacao.registros import RepositorioDeMovimentacao


@dataclass(frozen=True)
class Sancao:
    cadastro: str
    codigo_sancao: int
    categoria: str | None
    orgao_sancionador: str | None
    uf_orgao: str | None
    data_inicio: date | None
    data_fim: date | None
    numero_processo: str | None


@dataclass(frozen=True)
class RegistroPep:
    nome: str
    descricao_funcao: str | None
    nome_orgao: str | None
    data_inicio_exercicio: date | None
    data_fim_exercicio: date | None
    data_fim_carencia: date | None


@dataclass(frozen=True)
class OrigemDados:
    banco: str
    arquivos: tuple[str, ...]
    carregado_em: datetime | None


class RepositorioListas(Protocol):
    async def buscar_sancoes(self, documento: str) -> list[Sancao]: ...

    async def buscar_peps_por_miolo(self, miolo: str) -> list[RegistroPep]: ...

    async def origem(self) -> OrigemDados: ...

    async def verificar(self) -> None:
        """Lança exceção se o banco não responder (usado pelo /health/ready)."""
        ...

    @property
    def movimentacao(self) -> RepositorioDeMovimentacao:
        """Onde a movimentação e o log de erros são gravados (a aplicação só tem INSERT nas duas tabelas)."""
        ...

    async def fechar(self) -> None: ...


# Consultas compartilhadas: só colunas pequenas (sem os CLOBs/text longos).
SQL_SANCOES = (
    "select cadastro, codigo_sancao, categoria, orgao_sancionador, uf_orgao,"
    " data_inicio, data_fim, numero_processo"
    " from {tabela} where documento = {param} order by data_inicio desc"
)
SQL_PEPS = (
    "select nome, descricao_funcao, nome_orgao, data_inicio_exercicio,"
    " data_fim_exercicio, data_fim_carencia"
    " from {tabela} where cpf_miolo = {param}"
)
SQL_ORIGEM = "select arquivo_origem, max(carregado_em) from {tabela} group by arquivo_origem"
