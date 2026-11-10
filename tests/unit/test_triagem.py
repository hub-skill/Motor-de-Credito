from datetime import date

from app.repositorios.base import RegistroPep, Sancao
from app.services.triagem import normalizar_nome, pep_ativo, sancao_vigente, triar

HOJE = date(2026, 11, 10)


def sancao(inicio: date | None = date(2025, 1, 1), fim: date | None = None, cadastro: str = "CEIS") -> Sancao:
    return Sancao(cadastro, 1, "Suspensão", "Órgão X", "SP", inicio, fim, "123/2025")


def pep(
    nome: str = "MARIA DA SILVA", fim_exercicio: date | None = None, fim_carencia: date | None = None
) -> RegistroPep:
    return RegistroPep(nome, "VEREADOR", "CAMARA", date(2021, 1, 1), fim_exercicio, fim_carencia)


def test_sancao_vigente_regras() -> None:
    assert sancao_vigente(sancao(fim=None), HOJE)  # sem prazo
    assert sancao_vigente(sancao(fim=HOJE), HOJE)  # termina hoje: ainda vale
    assert not sancao_vigente(sancao(fim=date(2026, 11, 9)), HOJE)  # terminou ontem
    assert not sancao_vigente(sancao(inicio=date(2026, 12, 1)), HOJE)  # ainda não começou
    assert sancao_vigente(sancao(inicio=None), HOJE)  # sem início informado


def test_pep_ativo_regras() -> None:
    assert pep_ativo(pep(), HOJE)  # em exercício
    assert pep_ativo(pep(fim_exercicio=date(2025, 1, 1), fim_carencia=date(2030, 1, 1)), HOJE)
    assert not pep_ativo(pep(fim_exercicio=date(2020, 1, 1), fim_carencia=date(2025, 1, 1)), HOJE)


def test_normalizar_nome() -> None:
    assert normalizar_nome("  José   da  Conceição ") == "JOSE DA CONCEICAO"


def test_sem_restricoes_libera() -> None:
    r = triar("CPF", "Fulano", [], [], HOJE)
    assert r.resultado == "liberar" and [m.codigo for m in r.motivos] == ["OK"]
    assert r.pep_verificado and not r.pep_ativo


def test_sancao_vigente_bloqueia() -> None:
    r = triar("CNPJ", None, [sancao(), sancao(cadastro="CNEP")], [], HOJE)
    assert r.resultado == "bloquear"
    assert r.motivos[0].codigo == "S01" and "CEIS, CNEP" in r.motivos[0].texto


def test_sancao_encerrada_so_informa() -> None:
    r = triar("CNPJ", None, [sancao(fim=date(2024, 1, 1))], [], HOJE)
    assert r.resultado == "liberar" and r.motivos[0].codigo == "S02"


def test_pep_ativo_manda_para_revisao_com_nome_sem_acento() -> None:
    r = triar("CPF", "Maria da Sílva", [], [pep("MARIA DA SILVA")], HOJE)
    assert r.resultado == "revisar" and r.pep_ativo
    assert r.motivos[0].codigo == "P01" and "VEREADOR" in r.motivos[0].texto


def test_mesmo_miolo_com_outro_nome_nao_e_pep() -> None:
    r = triar("CPF", "João Souza", [], [pep("MARIA DA SILVA")], HOJE)
    assert r.resultado == "liberar" and r.peps == []


def test_pep_com_carencia_encerrada_so_informa() -> None:
    antigo = pep(fim_exercicio=date(2020, 1, 1), fim_carencia=date(2021, 1, 1))
    r = triar("CPF", "Maria da Silva", [], [antigo], HOJE)
    assert r.resultado == "liberar" and r.motivos[0].codigo == "P02"


def test_cpf_sem_nome_nao_verifica_pep() -> None:
    r = triar("CPF", None, [], [], HOJE)
    assert not r.pep_verificado and r.motivos[0].codigo == "P03"


def test_bloqueio_prevalece_sobre_revisao() -> None:
    r = triar("CPF", "Maria da Silva", [sancao()], [pep()], HOJE)
    assert r.resultado == "bloquear"
    assert {m.codigo for m in r.motivos} == {"S01", "P01"}
