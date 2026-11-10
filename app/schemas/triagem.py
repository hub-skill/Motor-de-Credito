import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.services.documentos import normalizar_documento

_CONTROLE = re.compile(r"[\x00-\x1f\x7f]")


class EntradaTriagem(BaseModel):
    documento: str = Field(
        ...,
        min_length=11,
        max_length=20,
        description="CPF ou CNPJ, com ou sem pontuação",
        examples=["529.982.247-25"],
    )
    nome: str | None = Field(
        None,
        max_length=200,
        description="Nome da pessoa (necessário para verificar PEP em CPF)",
        examples=["MARIA DA SILVA"],
    )

    @field_validator("documento")
    @classmethod
    def validar_documento(cls, valor: str) -> str:
        normalizar_documento(valor.strip())  # lança ValueError se inválido
        return valor.strip()

    @field_validator("nome")
    @classmethod
    def validar_nome(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        valor = valor.strip()
        if _CONTROLE.search(valor):
            raise ValueError("nome contém caracteres de controle")
        return valor or None


class MotivoSaida(BaseModel):
    codigo: str
    texto: str


class SancaoSaida(BaseModel):
    cadastro: str
    categoria: str | None
    orgao_sancionador: str | None
    uf_orgao: str | None
    data_inicio: date | None
    data_fim: date | None
    numero_processo: str | None
    vigente: bool


class PepSaida(BaseModel):
    verificado: bool
    ativo: bool
    funcoes: list[str]


class FonteSaida(BaseModel):
    banco: str
    arquivos: list[str]
    carregado_em: datetime | None


class SaidaTriagem(BaseModel):
    documento: str = Field(..., description="Documento mascarado (CPF) ou formatado (CNPJ)")
    tipo: Literal["CPF", "CNPJ"]
    resultado: Literal["liberar", "revisar", "bloquear"]
    motivos: list[MotivoSaida]
    sancoes: list[SancaoSaida]
    pep: PepSaida
    consultado_em: date
    fonte: FonteSaida
