"""Testa se cada credencial do .env conecta (PostgreSQL e Oracle). Nunca imprime senhas.

Uso (na pasta "Motor de credito"):
    uv run --no-project --with "psycopg[binary]" --with oracledb --with python-dotenv python banco/testar_env.py
"""

import os
import sys
from pathlib import Path

import oracledb
import psycopg
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
E = os.environ.get


def pg(rotulo: str, usuario_var: str, senha_var: str) -> None:
    if not E(senha_var):
        print(f"[--]   {rotulo:34} {senha_var} vazia no .env")
        return
    try:
        with psycopg.connect(host=E("PG_HOST"), port=E("PG_PORT"), dbname=E("PG_DATABASE"),
                             user=E(usuario_var), password=E(senha_var), connect_timeout=5) as c:
            u, db, v = c.execute("select current_user, current_database(),"
                                 " split_part(version(), ' ', 2)").fetchone()
            print(f"[ok]   {rotulo:34} {u} @ {db} (PostgreSQL {v})")
    except psycopg.Error as exc:
        senha = bool(exc.pgconn is not None and exc.pgconn.used_password)
        motivo = "usuário/senha recusados" if senha else f"sem conexão ({type(exc).__name__})"
        print(f"[ERRO] {rotulo:34} {E(usuario_var)}: {motivo}")


def ora(rotulo: str, usuario_var: str, senha_var: str, aviso_inexistente: str = "") -> None:
    if not E(senha_var):
        print(f"[--]   {rotulo:34} {senha_var} vazia no .env")
        return
    try:
        with oracledb.connect(user=E(usuario_var), password=E(senha_var), dsn=E("ORACLE_DSN")) as c:
            with c.cursor() as cur:
                cur.execute("select user, sys_context('userenv','con_name'), version_full"
                            " from product_component_version where rownum = 1")
                u, con, v = cur.fetchone()
                print(f"[ok]   {rotulo:34} {u} @ {con} (Oracle {v})")
    except oracledb.Error as exc:
        (err,) = exc.args
        codigo = getattr(err, "full_code", type(exc).__name__)
        extra = f" -> {aviso_inexistente}" if codigo == "ORA-01017" and aviso_inexistente else ""
        print(f"[ERRO] {rotulo:34} {E(usuario_var)}: {codigo}{extra}")


print(f"PostgreSQL: {E('PG_HOST')}:{E('PG_PORT')}/{E('PG_DATABASE')}   Oracle: {E('ORACLE_DSN')}\n")
pg("PostgreSQL administrador", "PG_ADMIN_USER", "PG_ADMIN_PASSWORD")
pg("PostgreSQL aplicação", "PG_USER", "PG_PASSWORD")
ora("Oracle administrador", "ORACLE_ADMIN_USER", "ORACLE_ADMIN_PASSWORD")
ora("Oracle aplicação", "ORACLE_USER", "ORACLE_PASSWORD",
    "esperado antes de rodar criar_tabelas.py: o usuário ainda não existe")
