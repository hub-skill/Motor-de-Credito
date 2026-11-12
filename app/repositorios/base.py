"""Contrato dos repositórios: a regra de negócio não sabe qual banco está por trás."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


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


@dataclass(frozen=True)
class RegistroErro:
    """Uma resposta de erro da API, para a tabela log_erros. Só metadados: nunca documento, nome ou corpo.

    ``ano`` e ``requisicao`` apontam para a movimentação: sem eles o erro não é gravado (vai só para o log).
    """

    ano: int
    requisicao: int
    request_id: str
    metodo: str
    rota: str
    status: int
    codigo: str
    titulo: str
    tipo_excecao: str | None
    duracao_ms: int | None
    ambiente: str


@dataclass(frozen=True)
class RegistroResposta:
    """Resposta da API para completar a linha da movimentação (conteúdo já mascarado e limitado)."""

    ano: int
    requisicao: int
    status_http: int
    conteudo: str | None
    situacao_requisicao: str  # OK = aceita; ER = recusada (4xx)
    situacao_resposta: str  # OK = sucesso (2xx); ER = erro (4xx/5xx)


class RepositorioListas(Protocol):
    async def buscar_sancoes(self, documento: str) -> list[Sancao]: ...

    async def buscar_peps_por_miolo(self, miolo: str) -> list[RegistroPep]: ...

    async def origem(self) -> OrigemDados: ...

    async def verificar(self) -> None:
        """Lança exceção se o banco não responder (usado pelo /health/ready)."""
        ...

    async def gravar_erros(self, registros: list[RegistroErro]) -> None:
        """Grava um lote na tabela log_erros (a aplicação só tem INSERT nela)."""
        ...

    async def registrar_requisicao(self, metodo: str, rota: str, conteudo: str | None) -> tuple[int, int]:
        """Numera a requisição no ano e grava a chegada na movimentação. Devolve (ano, requisicao)."""
        ...

    async def registrar_respostas(self, registros: list[RegistroResposta]) -> None:
        """Completa as linhas da movimentação com as respostas (cada linha uma vez só)."""
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
SQL_LOG_ERROS = (
    "insert into {tabela} (ano, requisicao, request_id, metodo, rota, status, codigo, titulo, tipo_excecao,"
    " duracao_ms, ambiente)"
    " values ({params})"
)
SQL_ORIGEM = "select arquivo_origem, max(carregado_em) from {tabela} group by arquivo_origem"
