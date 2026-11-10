"""Teste de login real no PostgreSQL com o usuário da aplicação.

Uso (na pasta "Motor de credito"):
    uv run --no-project --with "psycopg[binary]" --with python-dotenv python banco/testar_login.py

Lê as variáveis PG_* do arquivo .env desta pasta. Nunca imprime a senha nem o objeto
de erro do psycopg (exc.pgconn), que contém a senha em texto puro.
"""

import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
PASTA = Path(__file__).resolve().parent.parent
load_dotenv(PASTA / ".env")

obrigatorias = ["PG_HOST", "PG_PORT", "PG_DATABASE", "PG_USER", "PG_PASSWORD"]
faltando = [v for v in obrigatorias if not os.environ.get(v)]
if faltando:
    print("Preencha no .env:", ", ".join(faltando))
    sys.exit(1)

try:
    conn = psycopg.connect(
        host=os.environ["PG_HOST"],
        port=os.environ["PG_PORT"],
        dbname=os.environ["PG_DATABASE"],
        user=os.environ["PG_USER"],
        password=os.environ["PG_PASSWORD"],
        sslmode=os.environ.get("PG_SSLMODE", "prefer"),
        connect_timeout=5,
        application_name="motor-credito-teste-login",
    )
except psycopg.Error as exc:
    usou_senha = bool(exc.pgconn is not None and exc.pgconn.used_password)
    if usou_senha:
        print("[erro] servidor recusou usuário/senha (ou o banco não existe). Confira o .env.")
    else:
        print(f"[erro] não conectou: {type(exc).__name__}. Servidor, porta ou pg_hba.conf.")
    sys.exit(2)

with conn:
    info = conn.execute(
        """
        select current_user, current_database(), current_setting('search_path'),
               current_schema(), split_part(version(), ' on ', 1),
               has_schema_privilege('credito', 'USAGE'),
               has_schema_privilege('credito', 'CREATE'),
               has_schema_privilege('public', 'CREATE'),
               (select count(*) from information_schema.tables where table_schema = 'credito')
        """
    ).fetchone()

rotulos = ["usuário", "banco", "search_path", "schema atual", "versão",
           "usa schema credito", "cria no schema credito", "cria no schema public",
           "tabelas em credito"]
print("[ok] login realizado\n")
for rotulo, valor in zip(rotulos, info, strict=True):
    print(f"  {rotulo:24} {valor}")
