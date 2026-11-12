"""Cria as tabelas do motor de crédito no PostgreSQL e no Oracle, lendo o .env.

Uso (na pasta "Motor de credito"):
    uv run --no-project --with "psycopg[binary]" --with oracledb --with python-dotenv \
        python banco/criar_tabelas.py [postgres|oracle|todos]

- PostgreSQL: executa banco/postgres/02_tabelas_cgu.sql e 03_log_erros.sql como PG_ADMIN_USER no PG_DATABASE.
- Oracle: executa banco/oracle/01_usuarios.sql, 02_tabelas_cgu.sql e 03_log_erros.sql como ORACLE_ADMIN_USER.
- Depois confere o acesso com os usuários da aplicação (PG_USER e ORACLE_USER).
- Reexecutar é seguro: objetos que já existem são mantidos.
- Nunca imprime senhas nem o objeto de erro de conexão (que pode conter a senha).
"""

import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
PASTA = Path(__file__).resolve().parent
load_dotenv(PASTA.parent / ".env")


def exigir(*nomes: str) -> dict[str, str]:
    faltando = [n for n in nomes if not os.environ.get(n)]
    if faltando:
        raise SystemExit(f"Preencha no .env: {', '.join(faltando)}")
    return {n: os.environ[n] for n in nomes}


# --------------------------------------------------------------------- PostgreSQL
def postgres() -> None:
    import psycopg

    env = exigir("PG_HOST", "PG_PORT", "PG_DATABASE", "PG_ADMIN_USER", "PG_ADMIN_PASSWORD",
                 "PG_USER", "PG_PASSWORD")
    comum = {"host": env["PG_HOST"], "port": env["PG_PORT"], "dbname": env["PG_DATABASE"],
             "connect_timeout": 5, "application_name": "motor-credito-ddl"}
    print("\n=== PostgreSQL")
    try:
        with psycopg.connect(user=env["PG_ADMIN_USER"], password=env["PG_ADMIN_PASSWORD"],
                             autocommit=True, **comum) as conn:
            for arquivo in ("02_tabelas_cgu.sql", "03_log_erros.sql"):
                sql = (PASTA / "postgres" / arquivo).read_text(encoding="utf-8")
                conn.execute(sql)  # sem parâmetros: o psycopg aceita vários comandos de uma vez
                print(f"[ok] {arquivo} executado como", env["PG_ADMIN_USER"])
    except psycopg.Error as exc:
        print(f"[erro] {type(exc).__name__} sqlstate={exc.sqlstate}")
        raise SystemExit(1) from None

    with psycopg.connect(user=env["PG_USER"], password=env["PG_PASSWORD"], **comum) as conn:
        for tabela in ("sancoes", "peps"):
            linha = conn.execute(
                "select count(*), has_table_privilege(%s, 'SELECT'), has_table_privilege(%s, 'INSERT'),"
                " has_table_privilege(%s, 'DELETE')"
                f" from credito.{tabela}",
                (f"credito.{tabela}",) * 3,
            ).fetchone()
            cols = conn.execute(
                "select count(*) from information_schema.columns"
                " where table_schema = 'credito' and table_name = %s", (tabela,)
            ).fetchone()[0]
            print(f"[ok] {env['PG_USER']} acessa {tabela} sem prefixo: {cols} colunas, {linha[0]} linhas,"
                  f" select={linha[1]} insert={linha[2]} delete={linha[3]}")
        # Log de erros: a aplicação só insere (sem select, update ou delete).
        pode = conn.execute(
            "select has_table_privilege('credito.log_erros', 'INSERT'),"
            " has_table_privilege('credito.log_erros', 'SELECT'),"
            " has_table_privilege('credito.log_erros', 'UPDATE'),"
            " has_table_privilege('credito.log_erros', 'DELETE')"
        ).fetchone()
        esperado = (True, False, False, False)
        print(f"[{'ok' if pode == esperado else 'ERRO'}] {env['PG_USER']} em log_erros:"
              f" insert={pode[0]} select={pode[1]} update={pode[2]} delete={pode[3]} (esperado: só insert)")


# --------------------------------------------------------------------- Oracle
IGNORAR_ORA = {
    1920: "usuário já existe",
    955: "objeto já existe",
    1408: "índice já existe",
    2261: "chave única já existe",
}


def comandos_oracle(arquivo: Path) -> list[str]:
    """Separa o script em comandos pelas linhas que contêm só '/' (formato SQL*Plus)."""
    texto = arquivo.read_text(encoding="utf-8")
    blocos, atual = [], []
    for linha in texto.splitlines():
        if linha.strip() == "/":
            sql = "\n".join(l for l in atual if not l.strip().startswith("--")).strip()
            if sql:
                blocos.append(sql)
            atual = []
        else:
            atual.append(linha)
    return blocos


def oracle() -> None:
    import oracledb

    env = exigir("ORACLE_DSN", "ORACLE_ADMIN_USER", "ORACLE_ADMIN_PASSWORD", "ORACLE_USER",
                 "ORACLE_PASSWORD")
    senha_app = env["ORACLE_PASSWORD"]
    if '"' in senha_app:
        raise SystemExit("ORACLE_PASSWORD não pode conter aspas duplas.")
    print("\n=== Oracle")
    try:
        conn = oracledb.connect(user=env["ORACLE_ADMIN_USER"], password=env["ORACLE_ADMIN_PASSWORD"],
                                dsn=env["ORACLE_DSN"])
    except oracledb.Error as exc:
        (err,) = exc.args
        print(f"[erro] conexão do administrador: {getattr(err, 'full_code', type(exc).__name__)}")
        raise SystemExit(1) from None

    with conn:
        print(f"[ok] conectado como {env['ORACLE_ADMIN_USER']} em {env['ORACLE_DSN']}")
        with conn.cursor() as cur:
            for arquivo in ("01_usuarios.sql", "02_tabelas_cgu.sql", "03_log_erros.sql"):
                criados = ignorados = 0
                for sql in comandos_oracle(PASTA / "oracle" / arquivo):
                    resumo = re.sub(r'IDENTIFIED BY "[^"]*"', 'IDENTIFIED BY "***"',
                                    sql.splitlines()[0])[:70]
                    try:
                        cur.execute(sql.replace("&senha_motor_app", senha_app))
                        criados += 1
                    except oracledb.DatabaseError as exc:
                        (err,) = exc.args
                        if err.code in IGNORAR_ORA:
                            ignorados += 1
                            print(f"   - {IGNORAR_ORA[err.code]}: {resumo}")
                        else:
                            print(f"[erro] {err.full_code} em: {resumo}")
                            raise SystemExit(1) from None
                print(f"[ok] {arquivo}: {criados} comandos executados, {ignorados} já existiam")

    with oracledb.connect(user=env["ORACLE_USER"], password=senha_app, dsn=env["ORACLE_DSN"]) as app:
        with app.cursor() as cur:
            for tabela in ("sancoes", "peps"):
                cur.execute(f"select count(*) from {tabela}")  # via sinônimo, sem o schema
                linhas = cur.fetchone()[0]
                cur.execute("select count(*) from all_tab_columns where owner = 'MOTOR_CREDITO'"
                            " and table_name = :t", t=tabela.upper())
                cols = cur.fetchone()[0]
                print(f"[ok] {env['ORACLE_USER']} acessa {tabela} pelo sinônimo: {cols} colunas, {linhas} linhas")
            # Log de erros: a aplicação só insere (sem select, update ou delete).
            cur.execute("select listagg(privilege, ',') within group (order by privilege) from all_tab_privs"
                        " where table_schema = 'MOTOR_CREDITO' and table_name = 'LOG_ERROS' and grantee = :u",
                        u=env["ORACLE_USER"].upper())
            privilegios = cur.fetchone()[0]
            print(f"[{'ok' if privilegios == 'INSERT' else 'ERRO'}] {env['ORACLE_USER']} em log_erros:"
                  f" {privilegios} (esperado: só INSERT)")


if __name__ == "__main__":
    alvo = sys.argv[1] if len(sys.argv) > 1 else "todos"
    if alvo in ("postgres", "todos"):
        postgres()
    if alvo in ("oracle", "todos"):
        oracle()
