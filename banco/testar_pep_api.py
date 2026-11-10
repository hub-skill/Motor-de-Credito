"""Prova o caminho PEP de ponta a ponta na API, sem exibir o nome da pessoa.

Pega um PEP ativo real do PostgreSQL, monta um CPF válido com os mesmos 6 dígitos visíveis
(a CGU mascara o resto) e chama a API com o nome. Também chama com outro nome, que não deve casar.
Uso: uv run python banco/testar_pep_api.py [porta]
"""

import json
import sys
import urllib.request
from pathlib import Path

import psycopg
from dotenv import dotenv_values

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ENV = dotenv_values(Path(__file__).resolve().parent.parent / ".env")
PORTA = sys.argv[1] if len(sys.argv) > 1 else "8010"


def cpf_com_miolo(miolo: str) -> str:
    """Monta um CPF válido 'XXX' + miolo + dígitos verificadores (prefixo 123)."""
    base = [int(c) for c in "123" + miolo]
    for pos in (9, 10):
        soma = sum(base[i] * (pos + 1 - i) for i in range(pos))
        base.append((soma * 10) % 11 % 10)
    return "".join(map(str, base))


with psycopg.connect(host=ENV["PG_HOST"], port=ENV["PG_PORT"], dbname=ENV["PG_DATABASE"],
                     user=ENV["PG_USER"], password=ENV["PG_PASSWORD"]) as c:
    miolo, nome, funcao = c.execute(
        "select cpf_miolo, nome, descricao_funcao from peps"
        " where data_fim_exercicio >= current_date and descricao_funcao = 'PREFEITO' limit 1"
    ).fetchone()

cpf = cpf_com_miolo(miolo)
print(f"PEP real escolhido: função={funcao}, CPF montado ***.{cpf[3:6]}.{cpf[6:9]}-** (nome omitido)")

for rotulo, nome_enviado in (("nome do PEP (minúsculo)", nome.lower()), ("outro nome", "Nome Que Nao Existe")):
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORTA}/api/v1/triagem", method="POST",
        data=json.dumps({"documento": cpf, "nome": nome_enviado}).encode(),
        headers={"Content-Type": "application/json", "X-API-Key": ENV["API_KEY"] or ""},
    )
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 - localhost
        corpo = json.loads(r.read())
    print(f"\n[{rotulo}] HTTP 200 -> resultado={corpo['resultado']}  pep={corpo['pep']}")
    print("   motivos:", [f"{m['codigo']}: {m['texto']}" for m in corpo["motivos"]])
