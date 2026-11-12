# Motor de Crédito – Triagem – Documentação de uso

Versão 0.1.0 · 11/11/2026

## Sumário

1. [Para que serve](#1-para-que-serve)
2. [Como funciona](#2-como-funciona)
3. [Começando em 5 minutos](#3-começando-em-5-minutos)
4. [Referência da API](#4-referência-da-api)
5. [Regras de negócio](#5-regras-de-negócio)
6. [Erros](#6-erros)
7. [Exemplos de integração](#7-exemplos-de-integração)
8. [Operação](#8-operação)
9. [Configuração](#9-configuração)
10. [Segurança e LGPD](#10-segurança-e-lgpd)
11. [Limitações](#11-limitações)
12. [Solução de problemas](#12-solução-de-problemas)

---

## 1. Para que serve

API interna que recebe um **CPF ou CNPJ** (e, para CPF, o nome) e verifica se ele aparece nas listas públicas da
CGU de **sanções (CEIS e CNEP)** e de **pessoas expostas politicamente (PEP)**. Devolve uma decisão de triagem
com os motivos, para o sistema de venda parcelada decidir se segue, revisa ou recusa antes da análise de crédito.

| Resultado | Significado | O que fazer |
|---|---|---|
| `liberar` | Nenhuma restrição nas listas consultadas | Seguir para a análise de crédito |
| `revisar` | PEP em exercício ou dentro da carência | Diligência reforçada: análise humana antes de aprovar |
| `bloquear` | Sanção vigente no CEIS ou no CNEP | Não seguir; registrar o motivo |

`liberar` significa só "nada nestas listas". Não é aprovação de crédito.

### Utilidades

- **Triagem antes da venda parcelada**: barra empresas inidôneas ou punidas (CEIS/CNEP) antes de gastar consulta
  de bureau.
- **Prevenção à lavagem de dinheiro (PLD)**: identifica PEP para aplicar diligência reforçada.
- **Cadastro de fornecedores e parceiros**: a mesma consulta vale para CNPJ de fornecedor.
- **Base local rápida**: as listas ficam gravadas no banco, então a consulta não depende da API da CGU no ar e
  responde em poucos milissegundos.

### Fontes de dados

| Lista | O que é | Atualização na CGU | Tabela |
|---|---|---|---|
| CEIS | Cadastro de Empresas Inidôneas e Suspensas | diária | `sancoes` (`cadastro = 'CEIS'`) |
| CNEP | Cadastro Nacional de Empresas Punidas (Lei Anticorrupção) | diária | `sancoes` (`cadastro = 'CNEP'`) |
| PEP | Pessoas Expostas Politicamente | mensal | `peps` |

Os arquivos são baixados do Portal da Transparência e carregados pelo script `banco/carregar_cgu.py` (ver
[Operação](#8-operação)). Toda resposta informa de qual arquivo e de qual carga vieram os dados (`fonte`).

---

## 2. Como funciona

```
sistema de vendas ──POST /api/v1/triagem──▶ API (FastAPI)
                                             │ 1. valida chave e CPF/CNPJ
                                             │ 2. consulta sanções (e PEP, se CPF com nome)
                                             ▼
                              PostgreSQL (schema credito)  ou  Oracle (schema MOTOR_CREDITO)
                                             │ 3. aplica a regra de triagem (função pura)
                                             ▼
                              resposta: resultado + motivos + sanções + PEP + fonte
```

1. A API confere a chave (`X-API-Key`) e valida os dígitos verificadores do documento. Documento inválido nem chega
   ao banco.
2. Consulta as sanções pelo documento. Se for CPF **com nome**, consulta também o PEP (ver
   [Regras](#5-regras-de-negócio)).
3. A regra de triagem decide o resultado. O banco usado (PostgreSQL ou Oracle) é escolhido em `MOTOR_BANCO`; as
   tabelas e as respostas são as mesmas nos dois.

Tempo medido (máquina local, 20 chamadas por caso, banco aquecido):

| Caso | PostgreSQL (mediana / p95) | Oracle (mediana / p95) |
|---|---|---|
| CNPJ com sanção | 5,2 / 30,5 ms | 8,7 / 23,3 ms |
| CPF com nome (sanções + PEP) | 7,7 / 13,3 ms | 8,1 / 12,2 ms |
| Documento inválido (não vai ao banco) | 4,0 / 5,2 ms | 6,3 / 8,1 ms |

---

## 3. Começando em 5 minutos

Pré-requisitos: [uv](https://docs.astral.sh/uv/), Python 3.12+, PostgreSQL ou Oracle com as tabelas carregadas e o
arquivo `.env` preenchido (ver [Configuração](#9-configuração)).

```powershell
cd "C:\Felipe\Programacao\Python\APIs\Motor de credito"
uv sync
# Windows: o --loop é obrigatório (o psycopg async não funciona com o loop padrão do Windows)
uv run uvicorn app.main:app --port 8000 --loop asyncio:SelectorEventLoop
```

Primeira chamada (PowerShell), lendo a chave do `.env`:

```powershell
$chave = ((Get-Content .env | Where-Object { $_ -like 'API_KEY=*' }) -replace '^API_KEY=','')
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/triagem `
  -Headers @{ 'X-API-Key' = $chave } -ContentType 'application/json' `
  -Body '{"documento": "19.182.685/0001-62"}'
```

Resultado esperado: `resultado = bloquear`, motivo `S01` (CNPJ com declaração de inidoneidade no CEIS).

---

## 4. Referência da API

### Autenticação

A rota de triagem exige o header `X-API-Key: <valor de API_KEY>`. A chave é comparada em tempo constante.
Sem chave ou com chave errada: **401** (com `WWW-Authenticate: APIKey`). Sem chave, até rotas inexistentes e métodos
errados respondem 401, como no Motor .NET: a API não revela quais rotas existem.

### `POST /api/v1/triagem`

Verifica um CPF ou CNPJ nas listas de sanções e de PEP. É POST, e não GET, para o documento não aparecer em URL,
logs de proxy e histórico do navegador.

**Requisição** (`Content-Type: application/json`, corpo de até 4 KB):

| Campo | Tipo | Obrigatório | Regras |
|---|---|---|---|
| `documento` | texto | sim | CPF ou CNPJ, com ou sem pontuação (`.`, `-`, `/`); 11 a 20 caracteres; dígitos verificadores corretos. Aceita o **CNPJ alfanumérico** da Receita (ex.: `12.ABC.345/01DE-35`) |
| `nome` | texto | não | Até 200 caracteres, sem caracteres de controle. **Necessário para verificar PEP** em CPF; ignorado em CNPJ |

```json
{ "documento": "529.982.247-25", "nome": "Fulano de Tal" }
```

**Resposta 200:**

| Campo | Descrição |
|---|---|
| `documento` | CPF **mascarado** (`***.982.247-**`) ou CNPJ formatado (dado público) |
| `tipo` | `CPF` ou `CNPJ` |
| `resultado` | `liberar`, `revisar` ou `bloquear` |
| `motivos[]` | `codigo` e `texto` de cada regra que se aplicou (ver [Regras](#5-regras-de-negócio)) |
| `sancoes[]` | Cada sanção encontrada: `cadastro` (CEIS/CNEP), `categoria`, `orgao_sancionador`, `uf_orgao`, `data_inicio`, `data_fim` (`null` = sem prazo), `numero_processo`, `vigente` |
| `pep` | `verificado` (houve consulta), `ativo` (PEP em exercício ou carência) e `funcoes` |
| `consultado_em` | Data da consulta |
| `fonte` | `banco` usado, `arquivos` da CGU carregados e `carregado_em` (data e hora da carga) |

Exemplo real (CNPJ com sanção vigente):

```json
{
  "documento": "19.182.685/0001-62",
  "tipo": "CNPJ",
  "resultado": "bloquear",
  "motivos": [{ "codigo": "S01", "texto": "Sanção vigente em CEIS (1 registro(s))." }],
  "sancoes": [
    {
      "cadastro": "CEIS",
      "categoria": "Declaração de Inidoneidade sem prazo determinado",
      "orgao_sancionador": "Prefeitura Municipal de Riqueza (SC)",
      "uf_orgao": "SC",
      "data_inicio": "2016-06-28",
      "data_fim": null,
      "numero_processo": "104/2014",
      "vigente": true
    }
  ],
  "pep": { "verificado": false, "ativo": false, "funcoes": [] },
  "consultado_em": "2026-11-11",
  "fonte": {
    "banco": "postgres",
    "arquivos": ["202609_PEP.csv", "20261110_CEIS.csv", "20261110_CNEP.csv"],
    "carregado_em": "2026-11-10T17:07:11.766945-03:00"
  }
}
```

Exemplo real (CPF com nome, sem restrição):

```json
{
  "documento": "***.982.247-**",
  "tipo": "CPF",
  "resultado": "liberar",
  "motivos": [{ "codigo": "OK", "texto": "Nenhuma restrição nas listas consultadas." }],
  "sancoes": [],
  "pep": { "verificado": true, "ativo": false, "funcoes": [] },
  "consultado_em": "2026-11-11",
  "fonte": { "banco": "postgres", "arquivos": ["202609_PEP.csv", "20261110_CEIS.csv", "20261110_CNEP.csv"],
             "carregado_em": "2026-11-10T17:07:11.766945-03:00" }
}
```

O mesmo CPF **sem nome** volta `liberar` com o motivo `P03` e `pep.verificado = false`.

### Outros endpoints

| Endpoint | Autenticação | Uso |
|---|---|---|
| `GET /health/live` | não | A aplicação está no ar: `{"status":"ok"}` (não consulta o banco) |
| `GET /health/ready` | não | O banco responde: `{"status":"ok","banco":"postgres"}`; `503` com `banco_indisponivel` ou `starting` |
| `GET /metrics` | não | Métricas Prometheus (requisições, latência, erros). **Exponha só na rede interna** |
| `GET /docs`, `/redoc`, `/openapi.json` | não | Documentação interativa e contrato. Só com `ENABLE_DOCS=true` |

### Limites

| Limite | Valor padrão | Configuração |
|---|---|---|
| Requisições por IP | 60 por minuto | `RATE_LIMIT` |
| Tempo total da requisição | 10 s | `REQUEST_TIMEOUT_SECONDS` (de 0 a 60) |
| Tempo de cada consulta no banco | 5 s | `PG_STATEMENT_TIMEOUT_MS` / `ORACLE_CALL_TIMEOUT_MS` |
| Espera por conexão livre no pool | 5 s | fixo nos repositórios |
| Tamanho do corpo | 4 KB | fixo (`TAMANHO_MAXIMO_CORPO` em `app/main.py`) |

Mantenha `REQUEST_TIMEOUT_SECONDS` **maior** que a espera do pool (5 s): com o banco fora do ar, a API leva até
5 s para concluir que não há conexão. Com um tempo de requisição menor, o cliente recebe `504 timeout` em vez de
`503 banco_indisponivel`.

### Headers de resposta

| Header | Valor |
|---|---|
| `X-Request-ID` | Identificador da requisição. **Informe ao suporte** em caso de erro |
| `Cache-Control: no-store` | A resposta tem dados pessoais: não guarde em cache |
| `X-Content-Type-Options` / `X-Frame-Options` / `Strict-Transport-Security` | Proteções do navegador |
| `Retry-After` | Nas respostas 429: segundos até poder tentar de novo |

---

## 5. Regras de negócio

**Política PROVISÓRIA**: precisa ser validada pelas áreas de risco e compliance antes de uso em produção.

| Código | Situação | Efeito |
|---|---|---|
| `S01` | Sanção **vigente** no CEIS ou no CNEP | `bloquear` |
| `S02` | Só sanções encerradas | Informativo (não muda o resultado) |
| `P01` | PEP em exercício ou dentro da carência | `revisar` |
| `P02` | Foi PEP, carência encerrada | Informativo |
| `P03` | CPF sem nome: PEP não verificado | Informativo |
| `OK` | Nenhuma restrição | `liberar` |

- **Sanção vigente**: já começou (ou sem data de início) e não terminou (sem data final = sem prazo).
- **PEP ativo**: até o fim da carência, se informado; senão, até o fim do exercício. Datas não informadas contam
  como ativas.
- **Prioridade**: `bloquear` prevalece sobre `revisar`, que prevalece sobre `liberar`.
- **Por que o PEP precisa do nome**: a CGU publica o CPF mascarado (`***.123.456-**`). A busca usa os 6 dígitos
  visíveis **e** o nome normalizado (maiúsculas, sem acentos, espaços simples). Só os dígitos dariam falso positivo
  para cerca de 13% dos CPFs. Homônimos com os mesmos 6 dígitos continuam possíveis: por isso PEP manda para
  revisão humana, nunca bloqueia.

---

## 6. Erros

Formato único, **o mesmo do Motor .NET**: RFC 9457 (Problem Details), com `Content-Type: application/problem+json` e
exatamente quatro campos: `title` (texto para pessoas), `status` (o mesmo código HTTP), `code` (para o seu programa
decidir o que fazer) e `request_id`:

```json
{
  "title": "Dados de entrada inválidos.",
  "status": 422,
  "code": "entrada_invalida",
  "request_id": "b6f3799f-e6d9-4a3e-a898-3cce7d4863eb"
}
```

Decida sempre pelo `code` (ou pelo `status`), nunca pelo texto do `title`, que pode ser reescrito.

| HTTP | `code` | Quando | O cliente deve |
|---|---|---|---|
| 400 | `requisicao_invalida` | JSON malformado | Corrigir o corpo |
| 401 | `http_401` | Sem `X-API-Key` ou chave errada | Conferir a chave |
| 404 | `http_404` | Rota inexistente (com chave válida) | Conferir a URL |
| 405 | `http_405` | Método não permitido (a triagem é só `POST`) | Usar `POST` |
| 413 | `corpo_muito_grande` | Corpo acima de 4 KB | Reduzir o corpo |
| 422 | `entrada_invalida` | CPF/CNPJ inválido, campo ausente ou nome com caracteres de controle | Corrigir; **não repetir** |
| 429 | `limite_excedido` | Limite de requisições | Esperar `Retry-After` |
| 500 | `erro_interno` | Erro inesperado | Informar o `request_id` |
| 503 | `banco_indisponivel` | Banco fora do ar, senha do banco errada ou pool esgotado | Tentar de novo depois |
| 504 | `banco_timeout` | Consulta passou do tempo no banco | Tentar de novo depois |
| 504 | `timeout` | A requisição inteira passou de `REQUEST_TIMEOUT_SECONDS` | Tentar de novo depois |

As mensagens de erro nunca repetem a entrada (CPF, nome) nem detalhes internos. Repita só 429, 503 e 504, com
espera crescente; nunca repita erros de entrada (400, 413, 422). **Na dúvida (503/504), não aprove a venda sem
triagem**: trate como pendente.

### Log de erros no banco

Toda resposta de erro (4xx e 5xx) é gravada na tabela `log_erros`, no mesmo banco que a API estiver usando:

| Banco | Tabela |
|---|---|
| PostgreSQL | `credito.log_erros` |
| Oracle | `motor_credito.log_erros` |

Colunas: `ocorrido_em`, `request_id` (o mesmo devolvido ao cliente), `metodo`, `rota`, `status`, `codigo`, `titulo`,
`tipo_excecao` (só no 500), `duracao_ms` e `ambiente` (`APP_ENV`). **Nunca** grava CPF, CNPJ, nome ou o corpo da
requisição. As tabelas são criadas por `banco/criar_tabelas.py` (script `03_log_erros.sql`).

- A resposta não espera o banco: o erro entra numa fila em memória (até 1000) e é gravado em lotes de até 100.
  Com o banco fora ou lento, a fila enche e os registros a mais são descartados (aviso no log da aplicação);
  a API continua respondendo normalmente. Ao desligar, a API grava o que ainda estiver na fila (até 5 s).
- O usuário da aplicação (`motor_app / MOTOR_APP`) só tem **INSERT** nessa tabela: não lê, não altera e não apaga. Consultas e
  limpeza são feitas por um administrador.
- Para achar o erro que um cliente relatou: `select * from credito.log_erros where request_id = '<request_id>'`.
- Limpeza (o volume cresce com varreduras e clientes integrando errado). Exemplo, manter 90 dias:
  `delete from credito.log_erros where ocorrido_em < now() - interval '90 days'` (PostgreSQL) ou
  `DELETE FROM motor_credito.log_erros WHERE ocorrido_em < SYSTIMESTAMP - INTERVAL '90' DAY` (Oracle).

---

## 7. Exemplos de integração

### curl

```bash
curl -X POST http://127.0.0.1:8000/api/v1/triagem \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"documento": "529.982.247-25", "nome": "Fulano de Tal"}'
```

### Python

```python
import os

import httpx

resposta = httpx.post(
    "http://127.0.0.1:8000/api/v1/triagem",
    headers={"X-API-Key": os.environ["API_KEY"]},
    json={"documento": "529.982.247-25", "nome": "Fulano de Tal"},
    timeout=15,
)
resposta.raise_for_status()
triagem = resposta.json()
match triagem["resultado"]:
    case "bloquear":
        ...  # recusar a venda e registrar triagem["motivos"]
    case "revisar":
        ...  # mandar para a fila de análise humana
    case _:
        ...  # seguir para a análise de crédito
```

No fluxo da venda parcelada: chame a triagem **antes** do bureau de crédito, sempre envie o nome junto com o CPF e
guarde `motivos`, `fonte` e o `X-Request-ID` com a proposta, para auditoria.

---

## 8. Operação

### Atualizar as listas da CGU

```powershell
uv run python banco/carregar_cgu.py      # baixa CEIS/CNEP (diários) e PEP (mensal) e carrega nos 2 bancos
uv run python banco/conferir_carga.py    # compara PostgreSQL x Oracle
```

Agende o `carregar_cgu.py` uma vez por dia (CEIS e CNEP mudam diariamente). A API guarda a `fonte` em cache por
5 minutos; depois de uma carga, as respostas passam a mostrar os arquivos novos em até 5 minutos.

### Rodar em container (Docker)

Validado em 11/11/2026 com Docker Desktop 29.9.3 no Windows, com PostgreSQL e Oracle rodando no próprio
Windows. Imagem final: 355 MB, usuário não root (UID 10001) e zero vulnerabilidades HIGH/CRITICAL corrigíveis
(trivy 0.58.1).

```powershell
cd "C:\Felipe\Programacao\Python\APIs\Motor de credito"

# 1) Construir a imagem (o .dockerignore deixa .env, .venv, tests e dados fora)
docker build -t motor-credito-py:0.1.0 .

# 2) Arquivo de variáveis do container: o .env sem os administradores e com o banco em host.docker.internal
#    (dentro do container, "localhost" é o próprio container). O .env.docker está no .gitignore.
$l = Get-Content .env -Encoding utf8 | Where-Object { $_.Trim() -and $_ -notmatch '^\s*#' -and $_ -notmatch '^PG_ADMIN_|^ORACLE_ADMIN_' } |
  ForEach-Object { $_ -replace '^PG_HOST=.*','PG_HOST=host.docker.internal' -replace '^(ORACLE_DSN=)(localhost|127\.0\.0\.1)','${1}host.docker.internal' }
[IO.File]::WriteAllLines("$PWD\.env.docker", [string[]]$l)   # UTF-8 sem BOM (o Set-Content do PowerShell 5.1 grava BOM)

# 3) Subir (porta 8081 do Windows -> 8080 do container)
docker run -d --name motor-py -p 8081:8080 --env-file .env.docker motor-credito-py:0.1.0
#    Para consultar o Oracle: acrescente  -e MOTOR_BANCO=oracle

# 4) Conferir
curl.exe http://localhost:8081/health/ready      # {"status":"ok","banco":"postgres"}
docker logs motor-py --tail 20

# Parar / remover
docker rm -f motor-py
```

Observações:

- No Linux o loop padrão já funciona com o psycopg async; o `--loop asyncio:SelectorEventLoop` só é exigido no
  Windows.
- `WEB_CONCURRENCY=1` (um processo por container): no Kubernetes quem escala são as réplicas. Fora dele, aumente
  com `-e WEB_CONCURRENCY=2`; cada processo abre o próprio pool e o próprio rate limit.
- Escala de tempos: banco (5 s) < requisição (`REQUEST_TIMEOUT_SECONDS=10`) < gunicorn `--timeout` (15 s) <
  `--graceful-timeout` (20 s) < proxy.
- Com o banco inacessível, `/health/live` continua 200, `/health/ready` dá 503 e a triagem responde
  `503 banco_indisponivel` em cerca de 5 s (espera do pool).
- O `Dockerfile` aplica as atualizações de segurança do Debian: reconstrua a imagem periodicamente.
- Não foi preciso mexer no `pg_hba.conf` nem no listener do Oracle nesta máquina. Se der `no pg_hba.conf entry
  for host "x.x.x.x"`, libere a faixa do Docker (192.168.65.0/24) para o usuário da aplicação.

### Rodar no Kubernetes

Validado em 11/11/2026 no Kubernetes v1.36.1 do Docker Desktop (modo kind), com os bancos no Windows. Os
manifestos ficam em `k8s/` (Kustomize: `base/` e `overlays/local`, `overlays/producao`). Precisa da imagem do
passo anterior e do `.env.docker`.

```powershell
# 1) Gerar k8s/ (config.env e segredos.env saem do .env.docker; segredos.env está no .gitignore)
& "$HOME\.claude\skills\kubernetes\scripts\preparar-k8s.ps1" -Projeto . -Nome motor-credito-py -Linguagem python

# 2) Modo kind (nó "desktop-control-plane"): levar a imagem ao nó. Rode no bash (o pipe do PowerShell 5.1 corrompe o tar)
docker save motor-credito-py:0.1.0 | docker exec -i desktop-control-plane ctr -n k8s.io images import --all-platforms -

# 3) Publicar e conferir
kubectl apply -f k8s/overlays/local/namespace.yaml
kubectl apply -k k8s/overlays/local
kubectl -n motor-credito-py rollout status deploy/motor-credito-py --timeout=180s
kubectl -n motor-credito-py get pods                      # 1/1 Running, RESTARTS 0

# 4) Acessar (http://localhost:9081)
kubectl -n motor-credito-py port-forward svc/motor-credito-py 9081:80

# Remover
kubectl delete -k k8s/overlays/local
```

Resultados da validação: triagem real igual à do container; `rollout restart` com tráfego contínuo pelo Service,
622 chamadas e 0 falhas; versão com o banco inacessível nunca fica pronta e o pod antigo segue atendendo, sem
reinícios.

- Cada mudança de código pede **tag nova** (`0.1.1`): importe a imagem e troque o `newTag` em
  `k8s/overlays/local/kustomization.yaml` (ou passe `-Tag` ao script).
- O rate limit (`RATE_LIMIT`) é **por pod** e em memória: com N réplicas o limite real é N vezes maior. No Python,
  só a rota `/api/v1/triagem` tem limite; `/health/*` não.
- Com o banco fora, o `/health/ready` demora cerca de 5 s (espera do pool) e a readiness tem prazo de 3 s: o
  kubelet registra `context deadline exceeded` em vez de 503. O efeito é o mesmo: o pod sai do Service.
- Conexões no banco = réplicas × `PG_POOL_MAX`. No overlay `local` há 1 réplica; o HPA (2 a 6) só existe na `base`
  e no `producao`. O Docker Desktop não traz metrics-server nem aplica NetworkPolicy.

### Monitoramento

- `/health/ready` no balanceador/orquestrador (tira a instância de rotação se o banco cair).
- `/metrics` no Prometheus: acompanhe taxa de 503/504 e latência.
- Tabela `log_erros` (seção 6): histórico dos erros por `request_id`, rota e código. Avisos `fila do log de erros
  cheia` ou `falha ao gravar o log de erros` no log da aplicação indicam que o banco não está recebendo os registros.
- Logs em JSON com `request_id`; falhas de banco aparecem como `postgres indisponível` ou `erro oracle` com o
  código (`codigo_oracle`), nunca com a senha.

---

## 9. Configuração

Arquivo `.env` na raiz da API (**nunca versionado**; modelo em `.env.example`). Variáveis de ambiente já
definidas têm prioridade.

| Variável | Padrão | Descrição |
|---|---|---|
| `API_KEY` | – (obrigatória) | Chave dos clientes, mínimo 32 caracteres. A API não sobe sem ela |
| `MOTOR_BANCO` | `postgres` | Banco consultado: `postgres` ou `oracle` |
| `APP_ENV` | `dev` | `dev`, `staging` ou `prod` |
| `ALLOWED_HOSTS` | `["localhost","127.0.0.1"]` | Hosts aceitos (JSON) |
| `ALLOWED_ORIGINS` | `[]` | Origens liberadas para CORS (JSON) |
| `ENABLE_DOCS` | `false` | Liga `/docs`, `/redoc` e `/openapi.json`. **Desligue em produção** |
| `REQUEST_TIMEOUT_SECONDS` | `10` | Tempo máximo da requisição (maior que 5 s; ver [Limites](#limites)) |
| `RATE_LIMIT` | `60/minute` | Requisições por IP. Com várias instâncias, use Redis (`app/core/limiter.py`) |
| `PG_HOST`, `PG_PORT`, `PG_DATABASE` | `127.0.0.1`, `5432`, `motor_credito` | PostgreSQL |
| `PG_USER`, `PG_PASSWORD` | `motor_app`, – | Usuário da aplicação (só leitura no schema `credito`) |
| `PG_SSLMODE` | `prefer` | Use `require` ou `verify-full` fora da máquina local |
| `PG_POOL_MIN`, `PG_POOL_MAX` | `1`, `5` | Tamanho do pool |
| `PG_STATEMENT_TIMEOUT_MS` | `5000` | Tempo máximo de cada consulta |
| `ORACLE_DSN` | `localhost:1521/XEPDB1` | Banco plugável (nunca o CDB `XE`) |
| `ORACLE_USER`, `ORACLE_PASSWORD` | `MOTOR_APP`, – | Usuário da aplicação (lê `MOTOR_CREDITO` por sinônimos) |
| `ORACLE_POOL_MIN`, `ORACLE_POOL_MAX` | `1`, `5` | Tamanho do pool |
| `ORACLE_CALL_TIMEOUT_MS` | `5000` | Tempo máximo de cada chamada |
| `PG_ADMIN_*`, `ORACLE_ADMIN_*` | – | Só para os scripts de `banco/`. A API não usa |

---

## 10. Segurança e LGPD

- O documento vai no corpo (POST), nunca na URL.
- **O CPF nunca volta completo** (`***.982.247-**`) e não é registrado em log; o CNPJ é dado público.
- Logs em JSON, sem dados pessoais e sem segredos; o objeto de conexão do psycopg (`pgconn`), que contém a senha,
  nunca é registrado.
- A API só lê: no PostgreSQL a sessão abre como `read only`; no Oracle o usuário `MOTOR_APP` só tem `SELECT` pelos
  sinônimos.
- Consultas sempre parametrizadas (sem concatenar valores no SQL).
- Segredos só no `.env` ou em variáveis de ambiente (`SecretStr` na configuração).
- As listas são dados públicos da CGU, mas cruzá-las com CPF de clientes é tratamento de dado pessoal: registre a
  finalidade (prevenção à fraude e PLD). Decisões automatizadas dão ao titular o direito de pedir revisão (LGPD,
  art. 20): por isso a resposta sempre traz os motivos e a fonte.

---

## 11. Limitações

- **Não é análise de crédito**: verifica só sanções e PEP. Score, renda e restrições de bureau ficam fora.
- **PEP depende do nome**: sem o nome, o CPF não é verificado (`P03`). Homônimos com os mesmos 6 dígitos podem
  gerar `revisar` indevido.
- **Atraso dos dados**: a API responde com a última carga (`fonte.carregado_em`). CEIS e CNEP mudam todo dia; o
  PEP, todo mês.
- `fonte.carregado_em` vem com fuso horário no PostgreSQL (`-03:00`) e sem fuso no Oracle (horário local do
  servidor).
- Política de triagem provisória (ver [Regras](#5-regras-de-negócio)).
- Rate limit em memória: com várias instâncias, cada uma conta separado até configurar Redis.

---

## 12. Solução de problemas

| Sintoma | Causa provável | Solução |
|---|---|---|
| A API não sobe: `ValidationError` em `Settings` | `API_KEY` vazia ou com menos de 32 caracteres | Preencher no `.env` |
| `401` em todas as chamadas | Chave errada ou header ausente | Header `X-API-Key` com o valor de `API_KEY` |
| `400 Invalid host header` | Host fora de `ALLOWED_HOSTS` | Incluir o host dos clientes |
| `503 banco_indisponivel` e `/health/ready` 503 | Banco fora, senha errada (`28P01` / `ORA-01017`) ou pool esgotado | Ver o log (`erro`/`codigo_oracle`); conferir `PG_*`/`ORACLE_*` |
| `504 timeout` com o banco fora | `REQUEST_TIMEOUT_SECONDS` menor que a espera do pool (5 s) | Usar 10 s (padrão) |
| No Windows, erro `ProactorEventLoop` ao consultar o PostgreSQL | uvicorn sem o loop compatível | `--loop asyncio:SelectorEventLoop` |
| `ORA-12514` / `DPY-6001` | DSN apontando para o CDB ou serviço errado | `ORACLE_DSN=localhost:1521/XEPDB1` |
| `PEP não verificado` em CPF | Nome não enviado | Enviar `nome` |
| `pip-audit` aponta vulnerabilidade | Dependência com falha conhecida | Atualizar no `pyproject.toml` e rodar `uv lock` |

Ao abrir chamado, informe o **`request_id`** (ou o header `X-Request-ID`), a data e a hora.
