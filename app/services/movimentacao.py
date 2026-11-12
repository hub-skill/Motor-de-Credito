"""Movimentação: o que chegou à API e o que ela respondeu, na tabela movimentacao.

- Na chegada, a API espera o banco devolver o número (ano, requisicao), com prazo curto: sem número no prazo,
  a requisição segue normalmente, sem movimentação (e sem linha na log_erros).
- A resposta completa a linha em segundo plano (fila e lotes de app/services/gravacao.py).
- O conteúdo é gravado como texto, em qualquer formato, até ``LIMITE_DO_CONTEUDO`` caracteres e com todo CPF
  mascarado (***.999.999-**). A chave de API nunca é gravada (vai num header, não no corpo).
"""

import re
from typing import Protocol

from app.repositorios.base import RegistroResposta
from app.services.gravacao import CAPACIDADE_DA_FILA, TAMANHO_DO_LOTE, GravadorEmLotes

LIMITE_DO_CONTEUDO = 32 * 1024  # caracteres
PRAZO_PARA_NUMERAR_SEGUNDOS = 1.0
ROTAS_SEM_MOVIMENTACAO = ("/health/", "/metrics")  # probes e scraping: chamadas a cada poucos segundos

# CPF com ou sem pontuação, sem dígito colado antes ou depois (um CNPJ de 14 dígitos não casa).
_CPF = re.compile(r"(?<!\d)\d{3}\.?(\d{3})\.?(\d{3})-?\d{2}(?!\d)")
_AVISO_CORTE = "...[cortado em {limite} caracteres]"


def mascarar_cpfs(texto: str) -> str:
    """Troca todo CPF do texto pela máscara da CGU: 529.982.247-25 -> ***.982.247-**."""
    return _CPF.sub(lambda m: f"***.{m.group(1)}.{m.group(2)}-**", texto)


def conteudo_para_gravar(corpo: bytes) -> str | None:
    """Corpo como texto para a movimentação: UTF-8 (bytes inválidos viram �), CPF mascarado e limitado."""
    if not corpo:
        return None
    texto = mascarar_cpfs(corpo.decode("utf-8", errors="replace"))
    if len(texto) > LIMITE_DO_CONTEUDO:
        aviso = _AVISO_CORTE.format(limite=LIMITE_DO_CONTEUDO)
        texto = texto[: LIMITE_DO_CONTEUDO - len(aviso)] + aviso
    return texto


def situacoes(status_http: int) -> tuple[str, str]:
    """(situação da requisição, situação da resposta): 4xx = requisição recusada; 2xx = resposta de sucesso."""
    requisicao = "ER" if 400 <= status_http < 500 else "OK"
    resposta = "OK" if status_http < 400 else "ER"
    return requisicao, resposta


def movimentar(rota: str) -> bool:
    return not rota.startswith(ROTAS_SEM_MOVIMENTACAO)


def numero_formatado(ano: int, requisicao: int) -> str:
    """Valor do header X-Requisicao: 2026-000123."""
    return f"{ano}-{requisicao:06d}"


class DestinoDeRespostas(Protocol):
    async def registrar_respostas(self, registros: list[RegistroResposta]) -> None: ...


class GravadorDeRespostas(GravadorEmLotes[RegistroResposta]):
    def __init__(
        self, destino: DestinoDeRespostas, capacidade: int = CAPACIDADE_DA_FILA, lote: int = TAMANHO_DO_LOTE
    ) -> None:
        super().__init__(destino.registrar_respostas, "da movimentação", "a resposta na movimentação", capacidade, lote)
