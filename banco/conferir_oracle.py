"""Confere usuários, privilégios e objetos do motor de crédito no Oracle (como SYSTEM)."""

import os
import sys
from pathlib import Path

import oracledb
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

with oracledb.connect(user=os.environ["ORACLE_ADMIN_USER"], password=os.environ["ORACLE_ADMIN_PASSWORD"],
                      dsn=os.environ["ORACLE_DSN"]) as conn, conn.cursor() as cur:
    cur.execute("select username, authentication_type, account_status from dba_users"
                " where username in ('MOTOR_CREDITO', 'MOTOR_APP') order by 1")
    for u, auth, status in cur:
        print(f"usuário {u:14} autenticação={auth:9} status={status}")
    cur.execute("select privilege from dba_sys_privs where grantee = 'MOTOR_APP' order by 1")
    print("privilégios de sistema do MOTOR_APP:", [r[0] for r in cur])
    cur.execute("select table_name, listagg(privilege, ',') within group (order by privilege)"
                " from dba_tab_privs where grantee = 'MOTOR_APP' group by table_name order by 1")
    for t, p in cur:
        print(f"grants do MOTOR_APP em {t:8}: {p}")
    cur.execute("select synonym_name, table_owner || '.' || table_name from dba_synonyms"
                " where owner = 'MOTOR_APP' order by 1")
    for s, alvo in cur:
        print(f"sinônimo MOTOR_APP.{s:8} -> {alvo}")
    cur.execute("select object_type, object_name from dba_objects where owner = 'MOTOR_CREDITO'"
                " and object_type in ('TABLE', 'INDEX') order by 1, 2")
    print("objetos do MOTOR_CREDITO:", [f"{t.lower()} {n}" for t, n in cur])
    cur.execute("select count(*) from dba_col_comments where owner = 'MOTOR_CREDITO'"
                " and comments is not null")
    print("colunas com comentário:", cur.fetchone()[0])

# MOTOR_APP não deve conseguir criar tabela
with oracledb.connect(user=os.environ["ORACLE_USER"], password=os.environ["ORACLE_PASSWORD"],
                      dsn=os.environ["ORACLE_DSN"]) as app, app.cursor() as cur:
    try:
        cur.execute("create table teste_permissao (x number)")
        print("ATENÇÃO: MOTOR_APP conseguiu criar tabela")
        cur.execute("drop table teste_permissao")
    except oracledb.DatabaseError as exc:
        print("MOTOR_APP tentando criar tabela ->", exc.args[0].full_code, "(bloqueado, como esperado)")
