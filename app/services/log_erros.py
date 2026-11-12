"""Gravação assíncrona do log de erros na tabela log_erros (fila e lotes em app/services/gravacao.py)."""

from typing import Protocol

from app.repositorios.base import RegistroErro
from app.services.gravacao import CAPACIDADE_DA_FILA, TAMANHO_DO_LOTE, GravadorEmLotes


class DestinoDeErros(Protocol):
    async def gravar_erros(self, registros: list[RegistroErro]) -> None: ...


class GravadorDeErros(GravadorEmLotes[RegistroErro]):
    def __init__(
        self, destino: DestinoDeErros, capacidade: int = CAPACIDADE_DA_FILA, lote: int = TAMANHO_DO_LOTE
    ) -> None:
        super().__init__(destino.gravar_erros, "do log de erros", "o log de erros", capacidade, lote)
