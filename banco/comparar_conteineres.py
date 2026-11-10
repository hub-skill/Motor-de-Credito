"""Mostra a diferença entre conectar no CDB (XE) e no PDB (XEPDB1) ao consultar motor_credito.peps."""

import os
import sys
from pathlib import Path

import oracledb
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
e = os.environ

for dsn in ("localhost:1521/XE", "localhost:1521/XEPDB1"):
    with oracledb.connect(user=e["ORACLE_ADMIN_USER"], password=e["ORACLE_ADMIN_PASSWORD"], dsn=dsn) as c, \
         c.cursor() as cur:
        cur.execute("select sys_context('userenv', 'con_name') from dual")
        conteiner = cur.fetchone()[0]
        try:
            cur.execute("select count(*) from motor_credito.peps")
            resultado = f"{cur.fetchone()[0]} linhas"
        except oracledb.DatabaseError as exc:
            resultado = exc.args[0].full_code
        print(f"{dsn:24} contêiner={conteiner:9} select count(*) from motor_credito.peps -> {resultado}")
