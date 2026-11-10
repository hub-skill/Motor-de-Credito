"""Carga das listas da CGU (CEIS, CNEP e PEP) no PostgreSQL e no Oracle.

Uso (na pasta "Motor de credito"):
    uv run --no-project --with "psycopg[binary]" --with oracledb --with python-dotenv \
        python banco/carregar_cgu.py [--banco postgres|oracle|todos] [--pasta <dir com os CSVs>]

Sem --pasta, baixa os arquivos mais recentes do Portal da Transparência para dados_cgu/:
  CEIS e CNEP são diários e PEP é mensal; o Portal só mantém o arquivo mais recente
  (os anteriores respondem 403), por isso o script recua alguns dias/meses até achar.

Cada tabela é substituída de forma atômica: apaga e insere na mesma transação.
Se algo falhar (valor maior que a coluna, erro de banco), nada é gravado e os
dados anteriores continuam intactos. Usa os usuários da aplicação (PG_USER / ORACLE_USER).
"""

import argparse
import csv
import io
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")
URL = "https://portaldatransparencia.gov.br/download-de-dados/{tipo}/{periodo}"

# ----------------------------------------------------------------------------- conversões
def texto(v: str) -> str | None:
    v = v.strip()
    return v or None


def data_br(v: str) -> date | None:
    v = v.strip()
    if not v or v.lower().startswith("não informad"):
        return None
    return datetime.strptime(v, "%d/%m/%Y").date()


def decimal_br(v: str) -> Decimal | None:
    v = v.strip()
    if not v:
        return None
    try:
        return Decimal(v.replace(".", "").replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError(f"valor decimal inválido: {v!r}") from exc


def inteiro(v: str) -> int:
    return int(v.strip())


def miolo_cpf(v: str) -> str:
    return re.sub(r"\D", "", v)  # ***.123.456-** -> 123456


# ----------------------------------------------------------------------------- layouts
# (coluna na tabela, coluna no CSV, conversão, tamanho máximo ou None, é CLOB no Oracle)
SANCOES: list[tuple[str, str, Callable, int | None, bool]] = [
    ("cadastro", "CADASTRO", texto, 10, False),
    ("codigo_sancao", "CÓDIGO DA SANÇÃO", inteiro, None, False),
    ("tipo_pessoa", "TIPO DE PESSOA", texto, 1, False),
    ("documento", "CPF OU CNPJ DO SANCIONADO", texto, 20, False),
    ("nome_sancionado", "NOME DO SANCIONADO", texto, 200, False),
    ("nome_informado_orgao", "NOME INFORMADO PELO ÓRGÃO SANCIONADOR", texto, 200, False),
    ("razao_social", "RAZÃO SOCIAL - CADASTRO RECEITA", texto, 200, False),
    ("nome_fantasia", "NOME FANTASIA - CADASTRO RECEITA", texto, 100, False),
    ("numero_processo", "NÚMERO DO PROCESSO", texto, 80, False),
    ("categoria", "CATEGORIA DA SANÇÃO", texto, 120, False),
    ("valor_multa", "VALOR DA MULTA", decimal_br, None, False),
    ("data_inicio", "DATA INÍCIO SANÇÃO", data_br, None, False),
    ("data_fim", "DATA FINAL SANÇÃO", data_br, None, False),
    ("data_publicacao", "DATA PUBLICAÇÃO", data_br, None, False),
    ("publicacao", "PUBLICAÇÃO", texto, 150, False),
    ("detalhamento_publicacao", "DETALHAMENTO DO MEIO DE PUBLICAÇÃO", texto, None, True),
    ("data_transito_julgado", "DATA DO TRÂNSITO EM JULGADO", data_br, None, False),
    ("abrangencia", "ABRAGÊNCIA DA SANÇÃO", texto, 100, False),
    ("orgao_sancionador", "ÓRGÃO SANCIONADOR", texto, 300, False),
    ("uf_orgao", "UF ÓRGÃO SANCIONADOR", texto, 2, False),
    ("esfera_orgao", "ESFERA ÓRGÃO SANCIONADOR", texto, 20, False),
    ("fundamentacao_legal", "FUNDAMENTAÇÃO LEGAL", texto, None, True),
    ("data_origem", "DATA ORIGEM INFORMAÇÃO", data_br, None, False),
    ("origem_informacao", "ORIGEM INFORMAÇÕES", texto, 150, False),
    ("observacoes", "OBSERVAÇÕES", texto, None, True),
]
PEPS: list[tuple[str, str, Callable, int | None, bool]] = [
    ("cpf_mascarado", "CPF", texto, 20, False),
    ("cpf_miolo", "CPF", miolo_cpf, 20, False),
    ("nome", "Nome_PEP", texto, 100, False),
    ("sigla_funcao", "Sigla_Função", texto, 10, False),
    ("descricao_funcao", "Descrição_Função", texto, 100, False),
    ("nivel_funcao", "Nível_Função", texto, 10, False),
    ("nome_orgao", "Nome_Órgão", texto, 100, False),
    ("data_inicio_exercicio", "Data_Início_Exercício", data_br, None, False),
    ("data_fim_exercicio", "Data_Fim_Exercício", data_br, None, False),
    ("data_fim_carencia", "Data_Fim_Carência", data_br, None, False),
]


COLUNAS_OPCIONAIS = {"VALOR DA MULTA"}


# ----------------------------------------------------------------------------- arquivos
def baixar(tipo: str, destino: Path) -> Path:
    """Baixa o arquivo mais recente disponível e devolve o caminho do CSV extraído."""
    hoje = date.today()
    if tipo == "pep":
        periodos = [(hoje.replace(day=1) - timedelta(days=30 * i)).strftime("%Y%m") for i in range(4)]
    else:
        periodos = [(hoje - timedelta(days=i)).strftime("%Y%m%d") for i in range(8)]
    for periodo in periodos:
        try:
            req = urllib.request.Request(URL.format(tipo=tipo, periodo=periodo),
                                         headers={"User-Agent": "motor-credito-carga/1.0"})
            with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 - URL fixa do gov.br
                conteudo = resp.read()
        except urllib.error.HTTPError:
            continue
        with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
            nome = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            destino.mkdir(parents=True, exist_ok=True)
            caminho = destino / Path(nome).name
            caminho.write_bytes(z.read(nome))
            print(f"[download] {tipo.upper():4} {periodo} -> {caminho.name}")
            return caminho
    raise SystemExit(f"Nenhum arquivo {tipo.upper()} disponível nos períodos {periodos}")


def localizar(pasta: Path, tipo: str) -> Path:
    achados = sorted(pasta.rglob(f"*_{tipo.upper()}.csv"))
    if not achados:
        raise SystemExit(f"Nenhum *_{tipo.upper()}.csv em {pasta}")
    return achados[-1]


def ler(caminho: Path, layout, extras: dict[str, str] | None = None) -> tuple[list[str], list[tuple]]:
    """Lê o CSV (latin-1, ';'), converte e valida tamanhos. Devolve colunas e linhas."""
    with caminho.open(encoding="latin-1", newline="") as f:
        leitor = csv.DictReader(f, delimiter=";")
        # "VALOR DA MULTA" só existe no CNEP: no CEIS a coluna fica nula.
        faltando = {c for _, c, *_ in layout} - set(leitor.fieldnames or []) - COLUNAS_OPCIONAIS
        if faltando:
            raise SystemExit(f"{caminho.name}: colunas ausentes no CSV (layout mudou?): {sorted(faltando)}")
        linhas, erros = [], []
        for n, reg in enumerate(leitor, start=2):
            valores = []
            for col, csv_col, conv, tam, _ in layout:
                try:
                    v = conv(reg.get(csv_col) or "")
                except ValueError as exc:
                    erros.append(f"linha {n}, {col}: {exc}")
                    v = None
                if tam and isinstance(v, str) and len(v) > tam:
                    erros.append(f"linha {n}, {col}: {len(v)} caracteres (máximo {tam})")
                valores.append(v)
            valores += list((extras or {}).values())
            linhas.append(tuple(valores))
    if erros:
        print(f"[erro] {caminho.name}: {len(erros)} problema(s); nada será gravado. Primeiros:")
        for e in erros[:10]:
            print("   ", e)
        raise SystemExit(1)
    colunas = [c for c, *_ in layout] + list((extras or {}).keys())
    return colunas, linhas


# ----------------------------------------------------------------------------- bancos
def carregar_postgres(cargas: list[tuple[str, str | None, list[str], list[tuple]]]) -> None:
    import psycopg

    e = os.environ
    with psycopg.connect(host=e["PG_HOST"], port=e["PG_PORT"], dbname=e["PG_DATABASE"],
                         user=e["PG_USER"], password=e["PG_PASSWORD"], connect_timeout=5,
                         application_name="motor-credito-carga-cgu") as conn:
        with conn.transaction():  # tudo ou nada
            for tabela, filtro, colunas, linhas in cargas:
                inicio = time.perf_counter()
                if filtro:
                    conn.execute(f"delete from credito.{tabela} where cadastro = %s", (filtro,))
                else:
                    conn.execute(f"delete from credito.{tabela}")
                with conn.cursor().copy(
                    f"copy credito.{tabela} ({', '.join(colunas)}) from stdin"
                ) as cp:
                    for linha in linhas:
                        cp.write_row(linha)
                rotulo = f"{tabela}" + (f" ({filtro})" if filtro else "")
                print(f"[postgres] {rotulo:16} {len(linhas):>7} linhas em {time.perf_counter() - inicio:5.1f}s")


def carregar_oracle(cargas: list[tuple[str, str | None, list[str], list[tuple]]],
                    clobs: dict[str, set[str]]) -> None:
    import oracledb

    e = os.environ
    with oracledb.connect(user=e["ORACLE_USER"], password=e["ORACLE_PASSWORD"], dsn=e["ORACLE_DSN"]) as conn:
        with conn.cursor() as cur:
            for tabela, filtro, colunas, linhas in cargas:
                inicio = time.perf_counter()
                if filtro:
                    cur.execute(f"delete from {tabela} where cadastro = :c", c=filtro)
                else:
                    cur.execute(f"delete from {tabela}")
                binds = ", ".join(f":{i + 1}" for i in range(len(colunas)))
                sql = f"insert into {tabela} ({', '.join(colunas)}) values ({binds})"
                # Textos que podem passar de 4.000 bytes precisam ser declarados como CLOB.
                tipos = [oracledb.DB_TYPE_CLOB if c in clobs.get(tabela, set()) else None for c in colunas]
                for i in range(0, len(linhas), 5000):
                    cur.setinputsizes(*tipos)
                    cur.executemany(sql, linhas[i:i + 5000])
                rotulo = f"{tabela}" + (f" ({filtro})" if filtro else "")
                print(f"[oracle]   {rotulo:16} {len(linhas):>7} linhas em {time.perf_counter() - inicio:5.1f}s")
        conn.commit()  # só confirma depois de todas as tabelas


# ----------------------------------------------------------------------------- principal
def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--banco", choices=["postgres", "oracle", "todos"], default="todos")
    p.add_argument("--pasta", type=Path, help="usar CSVs já baixados nesta pasta")
    args = p.parse_args()

    if args.pasta:
        arquivos = {t: localizar(args.pasta, t) for t in ("ceis", "cnep", "pep")}
    else:
        destino = RAIZ / "dados_cgu"
        arquivos = {t: baixar(t, destino) for t in ("ceis", "cnep", "pep")}

    cargas = []
    for tipo in ("ceis", "cnep"):
        colunas, linhas = ler(arquivos[tipo], SANCOES, {"arquivo_origem": arquivos[tipo].name})
        cargas.append(("sancoes", tipo.upper(), colunas, linhas))
        print(f"[leitura]  {arquivos[tipo].name:22} {len(linhas):>7} linhas válidas")
    colunas, linhas = ler(arquivos["pep"], PEPS, {"arquivo_origem": arquivos["pep"].name})
    cargas.append(("peps", None, colunas, linhas))
    print(f"[leitura]  {arquivos['pep'].name:22} {len(linhas):>7} linhas válidas")

    clobs = {"sancoes": {c for c, *_, eh_clob in SANCOES if eh_clob}}
    if args.banco in ("postgres", "todos"):
        carregar_postgres(cargas)
    if args.banco in ("oracle", "todos"):
        carregar_oracle(cargas, clobs)
    print("[ok] carga concluída")


if __name__ == "__main__":
    main()
