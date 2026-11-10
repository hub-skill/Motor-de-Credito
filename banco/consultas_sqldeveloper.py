"""Roda as mesmas consultas da conexão 'Motor_Credito' do SQL Developer (SYSTEM @ localhost:1521/XEPDB1)."""

import os
import sys
from pathlib import Path

import oracledb
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
e = os.environ

CONSULTAS = [
    "select sys_context('userenv','con_name') from dual",
    "select count(*) from motor_credito.peps",
    "select cadastro, count(*) from motor_credito.sancoes group by cadastro order by cadastro",
]

with oracledb.connect(user="SYSTEM", password=e["ORACLE_ADMIN_PASSWORD"], dsn="localhost:1521/XEPDB1") as c, \
     c.cursor() as cur:
    for sql in CONSULTAS:
        cur.execute(sql)
        print(f"{sql}\n   -> {cur.fetchall()}")
