"""Compara a carga da CGU entre PostgreSQL e Oracle (mesmas consultas nos dois bancos)."""

import os
import sys
from pathlib import Path

import oracledb
import psycopg
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
e = os.environ

# (descrição, SQL PostgreSQL, SQL Oracle)
CONSULTAS = [
    ("sanções CEIS", "select count(*) from sancoes where cadastro = 'CEIS'",
     "select count(*) from sancoes where cadastro = 'CEIS'"),
    ("sanções CNEP", "select count(*) from sancoes where cadastro = 'CNEP'",
     "select count(*) from sancoes where cadastro = 'CNEP'"),
    ("PEPs", "select count(*) from peps", "select count(*) from peps"),
    ("soma das multas CNEP", "select sum(valor_multa) from sancoes",
     "select sum(valor_multa) from sancoes"),
    ("sanções vigentes em 10/11/2026",
     "select count(*) from sancoes where data_inicio <= date '2026-11-10'"
     " and (data_fim is null or data_fim >= date '2026-11-10')",
     "select count(*) from sancoes where data_inicio <= date '2026-11-10'"
     " and (data_fim is null or data_fim >= date '2026-11-10')"),
    ("sanções sem data final", "select count(*) from sancoes where data_fim is null",
     "select count(*) from sancoes where data_fim is null"),
    ("maior fundamentação legal (caracteres)", "select max(length(fundamentacao_legal)) from sancoes",
     "select max(dbms_lob.getlength(fundamentacao_legal)) from sancoes"),
    ("maior detalhamento publicação", "select max(length(detalhamento_publicacao)) from sancoes",
     "select max(dbms_lob.getlength(detalhamento_publicacao)) from sancoes"),
    ("PEP com fim de exercício nulo", "select count(*) from peps where data_fim_exercicio is null",
     "select count(*) from peps where data_fim_exercicio is null"),
    ("PEP com cpf_miolo de 6 dígitos", "select count(*) from peps where length(cpf_miolo) = 6",
     "select count(*) from peps where length(cpf_miolo) = 6"),
    ("busca CNPJ 19182685000162",
     "select count(*) || ' | ' || min(categoria) || ' | ' || min(to_char(data_inicio, 'DD/MM/YYYY'))"
     " from sancoes where documento = '19182685000162'",
     "select count(*) || ' | ' || min(categoria) || ' | ' || min(to_char(data_inicio, 'DD/MM/YYYY'))"
     " from sancoes where documento = '19182685000162'"),
]

with psycopg.connect(host=e["PG_HOST"], port=e["PG_PORT"], dbname=e["PG_DATABASE"],
                     user=e["PG_USER"], password=e["PG_PASSWORD"]) as pg, \
     oracledb.connect(user=e["ORACLE_USER"], password=e["ORACLE_PASSWORD"], dsn=e["ORACLE_DSN"]) as ora:
    cur_ora = ora.cursor()
    divergencias = 0
    print(f"{'verificação':42} {'PostgreSQL':>24} {'Oracle':>24}")
    for descricao, sql_pg, sql_ora in CONSULTAS:
        v_pg = pg.execute(sql_pg).fetchone()[0]
        cur_ora.execute(sql_ora)
        v_ora = cur_ora.fetchone()[0]
        igual = str(v_pg) == str(v_ora)
        divergencias += not igual
        print(f"{descricao:42} {str(v_pg):>24} {str(v_ora):>24}  {'ok' if igual else 'DIFERENTE'}")
    print(f"\n{divergencias} divergência(s)")
