# Motor de Crédito – Triagem (sanções e PEP)

API interna (FastAPI) que recebe um CPF ou CNPJ e consulta as listas da CGU gravadas no banco:
**CEIS e CNEP** (sanções) e **PEP** (pessoas expostas politicamente). Devolve `liberar`, `revisar`
ou `bloquear`, sempre com os motivos.

As tabelas existem no **PostgreSQL** (`motor_credito`, schema `credito`) e no **Oracle**
(`XEPDB1`, schema `MOTOR_CREDITO`). A API usa um dos dois, escolhido em `MOTOR_BANCO`.

## Política de triagem (PROVISÓRIA – validar com risco/compliance)

| Situação | Resultado | Código |
|---|---|---|
| Sanção vigente no CEIS ou CNEP | `bloquear` | S01 |
| Só sanções encerradas | sem efeito (informativo) | S02 |
| PEP em exercício ou dentro da carência | `revisar` (diligência reforçada) | P01 |
| Foi PEP, carência encerrada | sem efeito (informativo) | P02 |
| CPF sem nome informado | PEP não verificado | P03 |

**Por que o PEP precisa do nome:** a CGU publica o CPF mascarado (`***.123.456-**`). A busca usa os
6 dígitos visíveis **e** o nome (sem acentos, maiúsculas). Só os dígitos dariam falso positivo para
cerca de 13% dos CPFs. Mesmo com o nome, homônimos com os mesmos 6 dígitos ainda são possíveis:
por isso PEP manda para revisão humana, não bloqueia.

## Configuração

Tudo no `.env` desta pasta (modelo em `.env.example`). Principais variáveis:

| Variável | Uso |
|---|---|
| `API_KEY` | Chave que os clientes enviam no header `X-API-Key` |
| `MOTOR_BANCO` | `postgres` ou `oracle` |
| `PG_*` | Conexão PostgreSQL com o usuário da aplicação (`motor_app`) |
| `ORACLE_*` | Conexão Oracle com o usuário da aplicação (`MOTOR_APP`) |
| `PG_ADMIN_*`, `ORACLE_ADMIN_*` | Só para os scripts de `banco/` (criar tabelas). A API não usa |

A API só lê: no PostgreSQL a sessão abre como `read only`.

## Rodar

```powershell
uv sync
# Windows: o --loop é obrigatório (psycopg async não funciona com o loop padrão do Windows)
uv run uvicorn app.main:app --port 8000 --loop asyncio:SelectorEventLoop
```

Com `ENABLE_DOCS=true`, a documentação fica em http://localhost:8000/docs.

```powershell
curl.exe -X POST http://localhost:8000/api/v1/triagem `
  -H "X-API-Key: <API_KEY do .env>" -H "Content-Type: application/json" `
  -d '{\"documento\": \"19.182.685/0001-62\"}'
```

Resposta (resumida):
```json
{
  "documento": "19.182.685/0001-62", "tipo": "CNPJ", "resultado": "bloquear",
  "motivos": [{"codigo": "S01", "texto": "Sanção vigente em CEIS (1 registro(s))."}],
  "sancoes": [{"cadastro": "CEIS", "categoria": "Declaração de Inidoneidade sem prazo determinado",
               "data_inicio": "2016-06-28", "data_fim": null, "vigente": true, "...": "..."}],
  "pep": {"verificado": false, "ativo": false, "funcoes": []},
  "fonte": {"banco": "postgres", "arquivos": ["202609_PEP.csv", "20261110_CEIS.csv", "20261110_CNEP.csv"]}
}
```

CPF nunca volta completo na resposta (`***.982.247-**`). CNPJ é dado público e volta formatado.
Aceita também o **CNPJ alfanumérico** da Receita (ex.: `12.ABC.345/01DE-35`).

## Atualizar os dados

```powershell
uv run python banco/carregar_cgu.py          # baixa CEIS/CNEP (diários) e PEP (mensal) e carrega nos 2 bancos
uv run python banco/conferir_carga.py        # compara PostgreSQL x Oracle
```

## Testes e verificações

```powershell
uv run ruff check . ; uv run ruff format --check app tests
uv run mypy app
uv run pytest                                              # sem banco: repositório falso + falhas com porta fechada
uv run pytest -m "bancos or not bancos" --cov-fail-under=95  # inclui PostgreSQL e Oracle reais
uv run bandit -r app ; uv run pip-audit
```

## Erros

Formato único: `{"error": {"code", "message", "request_id"}}`.

| Status | Código | Quando |
|---|---|---|
| 400 | `requisicao_invalida` | JSON malformado |
| 401 | `http_401` | `X-API-Key` ausente ou inválida |
| 413 | `corpo_muito_grande` | Corpo maior que 4 KB |
| 422 | `entrada_invalida` | CPF/CNPJ inválido ou nome com caracteres de controle |
| 429 | `limite_excedido` | Rate limit |
| 500 | `erro_interno` | Erro inesperado (detalhes só no log, pelo `request_id`) |
| 503 | `banco_indisponivel` | Banco fora do ar, senha errada ou pool esgotado |
| 504 | `timeout` / `banco_timeout` | Tempo limite excedido |

Documentação completa de uso: [DOCUMENTACAO.md](DOCUMENTACAO.md). Métricas Prometheus em `/metrics`
(exponha só na rede interna).

## Estrutura

```
app/
  api/v1/routes.py         POST /api/v1/triagem
  services/documentos.py   validação CPF/CNPJ (inclusive alfanumérico)
  services/triagem.py      regra de decisão (função pura)
  repositorios/            postgres.py e oracle.py (mesma interface, base.py)
                           erros_postgres.py / erros_oracle.py: falha de banco = 503/504, nunca 500
banco/                     scripts: criar tabelas, carga da CGU, conferências
tests/unit, tests/integration (sem banco), tests/falhas (drivers reais, porta fechada),
tests/bancos (bancos reais, -m bancos)
```
