"""Mostra, pelo catálogo de cada banco, onde as tabelas estão, quem é o dono e quantas linhas têm."""

import os
import sys
from pathlib import Path

import oracledb
import psycopg
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
e = os.environ

print("=== PostgreSQL (como administrador)")
with psycopg.connect(host=e["PG_HOST"], port=e["PG_PORT"], dbname=e["PG_DATABASE"],
                     user=e["PG_ADMIN_USER"], password=e["PG_ADMIN_PASSWORD"]) as c:
    print("servidor:", c.execute("select inet_server_addr() || ':' || inet_server_port()").fetchone()[0],
          "| banco:", c.execute("select current_database()").fetchone()[0])
    for schema, tabela, dono in c.execute(
        "select schemaname, tablename, tableowner from pg_tables"
        " where schemaname = 'credito' order by tablename"
    ).fetchall():
        linhas = c.execute(f"select count(*) from {schema}.{tabela}").fetchone()[0]
        print(f"  {schema}.{tabela:10} dono={dono:9} linhas={linhas}")

print("\n=== Oracle (como administrador)")
with oracledb.connect(user=e["ORACLE_ADMIN_USER"], password=e["ORACLE_ADMIN_PASSWORD"],
                      dsn=e["ORACLE_DSN"]) as c, c.cursor() as cur:
    cur.execute("select sys_context('userenv','con_name'), sys_context('userenv','server_host') from dual")
    con, host = cur.fetchone()
    print("contêiner:", con, "| host:", host, "| DSN:", e["ORACLE_DSN"])
    cur.execute("select owner, object_name, to_char(created, 'DD/MM/YYYY HH24:MI:SS')"
                " from dba_objects where owner = 'MOTOR_CREDITO' and object_type = 'TABLE' order by 2")
    for dono, tabela, criada in cur.fetchall():
        cur.execute(f"select count(*) from {dono}.{tabela}")
        print(f"  {dono}.{tabela:8} criada em {criada}  linhas={cur.fetchone()[0]}")
