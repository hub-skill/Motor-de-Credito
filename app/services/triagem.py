"""Triagem de compliance: sanções (CEIS/CNEP) e PEP. Funções puras, sem banco e sem I/O.

Política PROVISÓRIA – validar com a área de risco/compliance:
  - Sanção vigente (CEIS ou CNEP)            -> bloquear  (S01)
  - Só sanções encerradas                    -> sem efeito na decisão (S02, informativo)
  - PEP em exercício ou dentro da carência   -> revisar   (P01) – diligência reforçada, não bloqueio
  - PEP com a carência encerrada             -> sem efeito na decisão (P02, informativo)
  - CPF sem nome informado                   -> PEP não verificado (P03, informativo)
"""

import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from app.repositorios.base import RegistroPep, Sancao

Resultado = Literal["liberar", "revisar", "bloquear"]
_GRAVIDADE: dict[Resultado, int] = {"liberar": 0, "revisar": 1, "bloquear": 2}


@dataclass(frozen=True)
class Motivo:
    codigo: str
    texto: str


@dataclass
class ResultadoTriagem:
    resultado: Resultado = "liberar"
    motivos: list[Motivo] = field(default_factory=list)
    sancoes_vigentes: list[Sancao] = field(default_factory=list)
    sancoes_encerradas: list[Sancao] = field(default_factory=list)
    pep_verificado: bool = False
    pep_ativo: bool = False
    peps: list[RegistroPep] = field(default_factory=list)

    def agravar(self, novo: Resultado) -> None:
        if _GRAVIDADE[novo] > _GRAVIDADE[self.resultado]:
            self.resultado = novo


def normalizar_nome(nome: str) -> str:
    """Maiúsculas, sem acentos e com espaços simples: 'José  da Silva' -> 'JOSE DA SILVA'."""
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    return " ".join(sem_acento.upper().split())


def sancao_vigente(s: Sancao, hoje: date) -> bool:
    """Vigente: já começou (ou sem data de início) e não terminou (sem data final = sem prazo)."""
    comecou = s.data_inicio is None or s.data_inicio <= hoje
    nao_terminou = s.data_fim is None or s.data_fim >= hoje
    return comecou and nao_terminou


def pep_ativo(p: RegistroPep, hoje: date) -> bool:
    """PEP enquanto exerce a função e até o fim da carência. Datas não informadas contam como ativas."""
    if p.data_fim_carencia is not None:
        return p.data_fim_carencia >= hoje
    return p.data_fim_exercicio is None or p.data_fim_exercicio >= hoje


def triar(
    tipo: Literal["CPF", "CNPJ"],
    nome: str | None,
    sancoes: list[Sancao],
    candidatos_pep: list[RegistroPep],
    hoje: date,
) -> ResultadoTriagem:
    r = ResultadoTriagem()

    r.sancoes_vigentes = [s for s in sancoes if sancao_vigente(s, hoje)]
    r.sancoes_encerradas = [s for s in sancoes if not sancao_vigente(s, hoje)]
    if r.sancoes_vigentes:
        cadastros = sorted({s.cadastro for s in r.sancoes_vigentes})
        r.agravar("bloquear")
        r.motivos.append(
            Motivo("S01", f"Sanção vigente em {', '.join(cadastros)} ({len(r.sancoes_vigentes)} registro(s)).")
        )
    elif r.sancoes_encerradas:
        r.motivos.append(Motivo("S02", "Possui apenas sanções já encerradas (informativo)."))

    if tipo == "CPF":
        if not nome:
            r.motivos.append(Motivo("P03", "PEP não verificado: informe o nome (a CGU publica o CPF mascarado)."))
        else:
            r.pep_verificado = True
            alvo = normalizar_nome(nome)
            r.peps = [p for p in candidatos_pep if normalizar_nome(p.nome) == alvo]
            ativos = [p for p in r.peps if pep_ativo(p, hoje)]
            if ativos:
                r.pep_ativo = True
                r.agravar("revisar")
                r.motivos.append(
                    Motivo(
                        "P01", f"Pessoa exposta politicamente ({ativos[0].descricao_funcao or 'função não informada'})."
                    )
                )
            elif r.peps:
                r.motivos.append(Motivo("P02", "Foi PEP; carência encerrada (informativo)."))

    if not r.motivos:
        r.motivos.append(Motivo("OK", "Nenhuma restrição nas listas consultadas."))
    return r
