"""Fila do log de erros: grava em lotes, nunca bloqueia a API e nunca deixa uma falha do banco subir."""

import asyncio
import logging

import pytest

from app.repositorios.base import RegistroErro
from app.services.log_erros import GravadorDeErros


def _registro(n: int) -> RegistroErro:
    return RegistroErro(
        f"req-{n}", "POST", "/api/v1/triagem", 422, "entrada_invalida", "Dados inválidos.", None, 3, "dev"
    )


class DestinoFalso:
    def __init__(self, falhar_vezes: int = 0) -> None:
        self.lotes: list[list[str]] = []
        self.falhar_vezes = falhar_vezes

    async def gravar_erros(self, registros: list[RegistroErro]) -> None:
        if self.falhar_vezes:
            self.falhar_vezes -= 1
            raise ConnectionError("banco fora")
        self.lotes.append([r.request_id for r in registros])


async def _esperar(condicao: object, prazo: float = 2.0) -> None:
    async with asyncio.timeout(prazo):
        while not condicao():  # type: ignore[operator]
            await asyncio.sleep(0.01)


async def test_grava_em_lotes_do_tamanho_configurado() -> None:
    destino = DestinoFalso()
    gravador = GravadorDeErros(destino, lote=2)
    for n in range(5):
        gravador.registrar(_registro(n))

    gravador.iniciar()
    await _esperar(lambda: sum(map(len, destino.lotes)) == 5)
    await gravador.parar()

    assert destino.lotes == [["req-0", "req-1"], ["req-2", "req-3"], ["req-4"]]


async def test_fila_cheia_descarta_sem_bloquear(caplog: pytest.LogCaptureFixture) -> None:
    gravador = GravadorDeErros(DestinoFalso(), capacidade=2)
    with caplog.at_level(logging.WARNING):
        for n in range(3):
            gravador.registrar(_registro(n))

    assert gravador.descartados == 1
    assert "fila do log de erros cheia" in caplog.text


async def test_falha_do_banco_perde_o_lote_e_continua(caplog: pytest.LogCaptureFixture) -> None:
    destino = DestinoFalso(falhar_vezes=1)
    gravador = GravadorDeErros(destino)
    gravador.iniciar()

    with caplog.at_level(logging.WARNING):
        gravador.registrar(_registro(1))
        await _esperar(lambda: gravador.perdidos == 1)
        gravador.registrar(_registro(2))
        await _esperar(lambda: destino.lotes == [["req-2"]])
    await gravador.parar()

    assert "falha ao gravar o log de erros" in caplog.text
    assert "banco fora" not in caplog.text  # só o tipo da exceção vai para o log


async def test_parar_grava_o_que_ficou_na_fila() -> None:
    destino = DestinoFalso()
    gravador = GravadorDeErros(destino, lote=2)
    for n in range(3):
        gravador.registrar(_registro(n))

    await gravador.parar()  # sem iniciar: tudo ainda na fila

    assert destino.lotes == [["req-0", "req-1"], ["req-2"]]
