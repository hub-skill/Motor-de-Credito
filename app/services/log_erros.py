"""Gravação assíncrona do log de erros na tabela log_erros.

A resposta ao cliente nunca espera o banco: o erro entra numa fila em memória e uma tarefa de fundo grava
em lotes. Se a fila encher (banco lento ou fora do ar), o registro é descartado e contado; se o banco
falhar, o lote é perdido e a falha vai para o log da aplicação. O log de erros nunca derruba a API.
"""

import asyncio
import contextlib
import logging
from typing import Protocol

from app.repositorios.base import RegistroErro

logger = logging.getLogger(__name__)

CAPACIDADE_DA_FILA = 1000
TAMANHO_DO_LOTE = 100


class DestinoDeErros(Protocol):
    async def gravar_erros(self, registros: list[RegistroErro]) -> None: ...


class GravadorDeErros:
    def __init__(
        self, destino: DestinoDeErros, capacidade: int = CAPACIDADE_DA_FILA, lote: int = TAMANHO_DO_LOTE
    ) -> None:
        self._destino = destino
        self._fila: asyncio.Queue[RegistroErro] = asyncio.Queue(maxsize=capacidade)
        self._lote = lote
        self._tarefa: asyncio.Task[None] | None = None
        self.descartados = 0  # fila cheia
        self.perdidos = 0  # lote que o banco recusou

    def registrar(self, registro: RegistroErro) -> None:
        """Não bloqueia: com a fila cheia, descarta (o cliente já recebeu a resposta de erro)."""
        try:
            self._fila.put_nowait(registro)
        except asyncio.QueueFull:
            self.descartados += 1
            if self.descartados == 1 or self.descartados % 100 == 0:
                logger.warning("fila do log de erros cheia: registros descartados", extra={"total": self.descartados})

    def iniciar(self) -> None:
        self._tarefa = asyncio.create_task(self._consumir(), name="gravador-log-erros")

    async def parar(self, prazo_segundos: float = 5.0) -> None:
        """Para a tarefa de fundo e tenta gravar o que ainda está na fila."""
        if self._tarefa is not None:
            self._tarefa.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._tarefa
            self._tarefa = None
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(prazo_segundos):
                while not self._fila.empty():
                    await self._gravar(self._retirar_lote([]))

    async def _consumir(self) -> None:
        while True:
            primeiro = await self._fila.get()
            await self._gravar(self._retirar_lote([primeiro]))

    def _retirar_lote(self, lote: list[RegistroErro]) -> list[RegistroErro]:
        while len(lote) < self._lote and not self._fila.empty():
            lote.append(self._fila.get_nowait())
        return lote

    async def _gravar(self, lote: list[RegistroErro]) -> None:
        try:
            await self._destino.gravar_erros(lote)
        except Exception as exc:  # noqa: BLE001 - o log de erros nunca pode derrubar a API
            self.perdidos += len(lote)
            # Só o tipo: o objeto de erro do driver pode conter dados da conexão (ex.: pgconn com a senha).
            logger.warning(
                "falha ao gravar o log de erros no banco", extra={"erro": type(exc).__name__, "registros": len(lote)}
            )
