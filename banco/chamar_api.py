"""Chama a API do motor rodando localmente (como um cliente real). Lê a API_KEY do .env sem exibi-la.

Uso: uv run python banco/chamar_api.py [porta]
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import dotenv_values

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
PORTA = sys.argv[1] if len(sys.argv) > 1 else "8010"
BASE = f"http://127.0.0.1:{PORTA}"
CHAVE = dotenv_values(Path(__file__).resolve().parent.parent / ".env")["API_KEY"] or ""


def chamar(metodo: str, caminho: str, corpo: dict[str, str] | None = None, chave: str | None = CHAVE) -> None:
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(BASE + caminho, data=dados, method=metodo)
    req.add_header("Content-Type", "application/json")
    if chave:
        req.add_header("X-API-Key", chave)
    inicio = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 - localhost
            status, texto = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        status, texto = e.code, e.read().decode()
    ms = (time.perf_counter() - inicio) * 1000
    print(f"\n### {metodo} {caminho} {json.dumps(corpo, ensure_ascii=False) if corpo else ''}")
    print(f"HTTP {status} em {ms:.0f} ms")
    print(json.dumps(json.loads(texto), ensure_ascii=False, indent=2))


for _ in range(30):  # espera a API subir
    try:
        urllib.request.urlopen(BASE + "/health/live", timeout=1)  # noqa: S310
        break
    except OSError:
        time.sleep(0.5)

chamar("GET", "/health/ready")
chamar("POST", "/api/v1/triagem", {"documento": "19.182.685/0001-62"})        # CNPJ sancionado (CEIS)
chamar("POST", "/api/v1/triagem", {"documento": "00.000.000/0001-91"})        # CNPJ sem sanção
chamar("POST", "/api/v1/triagem", {"documento": "529.982.247-25", "nome": "Fulano de Tal"})  # CPF sem restrição
chamar("POST", "/api/v1/triagem", {"documento": "529.982.247-24"})            # CPF inválido
chamar("POST", "/api/v1/triagem", {"documento": "00000000000191"}, chave=None)  # sem chave
