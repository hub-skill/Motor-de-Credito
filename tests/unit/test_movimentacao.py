"""Regras da movimentação sem banco: máscara de CPF, limite do conteúdo, situações e fila de respostas."""

import asyncio

import pytest

from app.repositorios.base import RegistroResposta
from app.services.movimentacao import (
    LIMITE_DO_CONTEUDO,
    GravadorDeRespostas,
    conteudo_para_gravar,
    mascarar_cpfs,
    movimentar,
    numero_formatado,
    situacoes,
)


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("529.982.247-25", "***.982.247-**"),
        ("52998224725", "***.982.247-**"),
        ("529982.247-25", "***.982.247-**"),
        ('{"documento": "529.982.247-25", "nome": "Ana"}', '{"documento": "***.982.247-**", "nome": "Ana"}'),
        ("a 52998224725 e 11144477735 juntos", "a ***.982.247-** e ***.444.777-** juntos"),
        ("19.182.685/0001-62", "19.182.685/0001-62"),  # CNPJ formatado não é CPF
        ("19182685000162", "19182685000162"),  # CNPJ só dígitos (14) não é CPF
        ("123456789012", "123456789012"),  # 12 dígitos: não casa
        ("sem numero nenhum", "sem numero nenhum"),
    ],
)
def test_mascara_todo_cpf_em_qualquer_formato(entrada: str, esperado: str) -> None:
    assert mascarar_cpfs(entrada) == esperado


def test_conteudo_vazio_vira_nulo_e_qualquer_formato_vira_texto() -> None:
    assert conteudo_para_gravar(b"") is None
    assert conteudo_para_gravar(b"<a>1</a>") == "<a>1</a>"
    assert conteudo_para_gravar(b"ol\xff") == "ol�"  # byte inválido não derruba a gravação
    assert conteudo_para_gravar("José Conceição".encode()) == "José Conceição"


def test_conteudo_acima_do_limite_e_cortado_com_aviso() -> None:
    texto = conteudo_para_gravar(b"a" * (LIMITE_DO_CONTEUDO + 500))
    assert texto is not None and len(texto) == LIMITE_DO_CONTEUDO
    assert texto.endswith("[cortado em 32768 caracteres]")
    assert conteudo_para_gravar(b"a" * LIMITE_DO_CONTEUDO) == "a" * LIMITE_DO_CONTEUDO  # no limite: inteiro


@pytest.mark.parametrize(
    ("status", "esperado"),
    [
        (200, ("OK", "OK")),
        (301, ("OK", "OK")),
        (400, ("ER", "ER")),
        (401, ("ER", "ER")),
        (422, ("ER", "ER")),
        (429, ("ER", "ER")),
        (500, ("OK", "ER")),
        (503, ("OK", "ER")),
        (504, ("OK", "ER")),
    ],
)
def test_situacoes_da_requisicao_e_da_resposta(status: int, esperado: tuple[str, str]) -> None:
    assert situacoes(status) == esperado


def test_numero_formatado_e_rotas_sem_movimentacao() -> None:
    assert numero_formatado(2026, 123) == "2026-000123"
    assert numero_formatado(2027, 1_234_567) == "2027-1234567"
    assert not movimentar("/health/live") and not movimentar("/health/ready") and not movimentar("/metrics")
    assert movimentar("/api/v1/triagem") and movimentar("/nao-existe") and movimentar("/")


class DestinoFalso:
    def __init__(self) -> None:
        self.lotes: list[list[tuple[int, int]]] = []

    async def registrar_respostas(self, registros: list[RegistroResposta]) -> None:
        self.lotes.append([(r.ano, r.requisicao) for r in registros])


async def test_respostas_sao_gravadas_em_lotes_em_segundo_plano() -> None:
    destino = DestinoFalso()
    gravador = GravadorDeRespostas(destino, lote=2)
    for n in range(1, 6):
        gravador.registrar(RegistroResposta(2026, n, 200, "{}", "OK", "OK"))

    gravador.iniciar()
    async with asyncio.timeout(2):
        while sum(map(len, destino.lotes)) < 5:
            await asyncio.sleep(0.01)
    await gravador.parar()

    assert destino.lotes == [[(2026, 1), (2026, 2)], [(2026, 3), (2026, 4)], [(2026, 5)]]
