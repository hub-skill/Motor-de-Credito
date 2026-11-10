"""Gera o PDF de base de conhecimento do Motor de Crédito."""

import sys
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

DESTINO = sys.argv[1]

pdfmetrics.registerFont(TTFont("Arial", r"C:\Windows\Fonts\arial.ttf"))
pdfmetrics.registerFont(TTFont("Arial-Bold", r"C:\Windows\Fonts\arialbd.ttf"))
pdfmetrics.registerFont(TTFont("Arial-Italic", r"C:\Windows\Fonts\ariali.ttf"))
pdfmetrics.registerFont(TTFont("Consolas", r"C:\Windows\Fonts\consola.ttf"))
pdfmetrics.registerFontFamily(
    "Arial", normal="Arial", bold="Arial-Bold", italic="Arial-Italic", boldItalic="Arial-Bold"
)

AZUL = colors.HexColor("#1F3A5F")
AZUL_CLARO = colors.HexColor("#E8EEF5")
CINZA = colors.HexColor("#555555")
AMARELO = colors.HexColor("#FFF6DA")

base = getSampleStyleSheet()
S = {
    "titulo": ParagraphStyle("t", parent=base["Title"], fontName="Arial-Bold", fontSize=22,
                             textColor=AZUL, spaceAfter=6, alignment=TA_LEFT, leading=27),
    "sub": ParagraphStyle("s", fontName="Arial", fontSize=11, textColor=CINZA, spaceAfter=14,
                          leading=15),
    "h1": ParagraphStyle("h1", fontName="Arial-Bold", fontSize=15, textColor=AZUL,
                         spaceBefore=14, spaceAfter=8, leading=19),
    "h2": ParagraphStyle("h2", fontName="Arial-Bold", fontSize=12, textColor=AZUL,
                         spaceBefore=10, spaceAfter=5, leading=15, keepWithNext=1),
    "p": ParagraphStyle("p", fontName="Arial", fontSize=9.5, leading=13.5, spaceAfter=5),
    "li": ParagraphStyle("li", fontName="Arial", fontSize=9.5, leading=13.5, leftIndent=14,
                         bulletIndent=4, spaceAfter=2),
    "cel": ParagraphStyle("c", fontName="Arial", fontSize=8.5, leading=11),
    "celb": ParagraphStyle("cb", fontName="Arial-Bold", fontSize=8.5, leading=11,
                           textColor=colors.white),
    "code": ParagraphStyle("code", fontName="Consolas", fontSize=8, leading=10.5,
                           backColor=colors.HexColor("#F4F4F4"), borderPadding=6,
                           spaceBefore=4, spaceAfter=8),
    "nota": ParagraphStyle("n", fontName="Arial", fontSize=9, leading=12.5,
                           backColor=AMARELO, borderPadding=6, spaceBefore=4, spaceAfter=8),
    "link": ParagraphStyle("l", fontName="Arial", fontSize=8.5, leading=12, leftIndent=14,
                           bulletIndent=4, spaceAfter=2),
}

story: list = []


def p(texto: str, estilo: str = "p") -> None:
    story.append(Paragraph(texto, S[estilo]))


def h1(t: str) -> None:
    story.append(Paragraph(escape(t), S["h1"]))


def h2(t: str) -> None:
    story.append(Paragraph(escape(t), S["h2"]))


def itens(lista: list[str]) -> None:
    for t in lista:
        story.append(Paragraph(t, S["li"], bulletText="•"))


def codigo(t: str, titulo: str | None = None) -> None:
    partes = [Paragraph(escape(titulo), S["h2"])] if titulo else []
    story.append(KeepTogether(partes + [Preformatted(t, S["code"])]))


def nota(t: str) -> None:
    story.append(Paragraph(t, S["nota"]))


def tabela(cab: list[str], linhas: list[list[str]], larguras: list[float]) -> None:
    dados = [[Paragraph(escape(c), S["celb"]) for c in cab]]
    for linha in linhas:
        dados.append([Paragraph(c, S["cel"]) for c in linha])
    t = Table(dados, colWidths=[w * cm for w in larguras], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B8C4D2")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, AZUL_CLARO]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))


def link(texto: str, url: str) -> None:
    story.append(Paragraph(f'{escape(texto)}: <link href="{url}" color="#1F3A5F">'
                           f'{escape(url)}</link>', S["link"], bulletText="•"))


# ---------------------------------------------------------------- Capa / resumo
p("Motor de Crédito – Base de Conhecimento", "titulo")
p("Pesquisa, decisões e plano para a API Serasa e para o motor de crédito de venda parcelada. "
  "Compilado em 10/11/2026.", "sub")

h1("Resumo")
itens([
    "<b>API Serasa (projeto existente):</b> código pronto e testado (37 testes, 95% de cobertura), "
    "mas nunca chamou a Serasa real. Falta o arquivo <b>.env</b> com as credenciais, e o formato "
    "do token e da consulta precisa ser ajustado ao padrão oficial da Serasa (seção 1).",
    "<b>Participação societária</b> não é uma API separada na Serasa: é uma feature opcional "
    "(<i>optionalFeatures</i>) dos relatórios de pessoa física.",
    "<b>Fontes para estudar de graça:</b> BrasilAPI e Minha Receita (CNPJ e quadro societário, sem "
    "cadastro) e Serpro Consulta CPF (só a demonstração é grátis).",
    "<b>Motor de crédito:</b> produto definido = <b>venda parcelada</b>. Arquitetura e recursos "
    "definidos com base em 5 fornecedores de mercado (seções 4 e 5).",
    "<b>Limite deste material:</b> a parte técnica está pronta para decisão profissional; a "
    "política de crédito (cortes, limites, taxas) depende de dados da operação e de validação por "
    "um profissional de risco (seção 6).",
])

h2("Decisões pendentes do usuário")
tabela(["Pergunta", "Por que importa"], [
    ["Vende para consumidor final (PF) ou para empresas (PJ)?",
     "Muda as fontes de dados (CPF x CNPJ), as regras e o cálculo de limite."],
    ["Quem assume o risco: crediário próprio, financeira parceira ou BNPL?",
     "Define o enquadramento legal e se é preciso autorização do Banco Central."],
    ["É estudo ou operação real?",
     "Define se a política pode usar valores provisórios ou precisa de validação formal."],
], [7, 10])

# ---------------------------------------------------------------- 1. Serasa
h1("1. API Serasa – situação e ajustes necessários")
h2("Estado do projeto (c:\\Felipe\\Programacao\\Python\\APIs\\API SERASA)")
itens([
    "FastAPI com endpoint <b>POST /api/v1/quadro-societario</b> (CPF no corpo, API key no header "
    "X-API-Key), rate limit, timeout, logs sem CPF, CPF mascarado na resposta.",
    "Cliente Serasa em <b>app/services/serasa.py</b>, com token OAuth2 em cache e uma nova "
    "tentativa em caso de 401.",
    "Script <b>scripts/testar_conexao.py</b> testa token e consulta e salva a resposta em "
    "saida_teste/resposta.json.",
    "<b>Não existe .env</b>: a API não sobe sem ele. Copiar .env.example e preencher.",
    "VS Code configurado para usar o Python do .venv (.vscode/settings.json). Copilot desativado "
    "a pedido do usuário.",
])

h2("O que a documentação oficial da Serasa diz (Developer Portal)")
p("Fonte: developer.serasaexperian.com.br, página do Relatório Avançado PJ. O relatório PF segue o "
  "mesmo padrão, mas a URL exata dele não está na página pública.")
tabela(["Item", "Nosso código hoje", "Padrão Serasa"], [
    ["URL do token (homologação)", "Variável SERASA_AUTH_URL",
     "https://uat-api.serasaexperian.com.br/security/iam/v1/client-identities/login"],
    ["URL do token (produção)", "—",
     "https://api.serasaexperian.com.br/security/iam/v1/client-identities/login"],
    ["Envio do token", "Form + HTTP Basic com client_id/secret",
     "POST JSON, header Authorization: Basic &lt;valor fornecido pela Serasa&gt;"],
    ["Resposta do token", "access_token, expires_in",
     "accessToken, tokenType, expiresIn (string), scope. Validade de 1 hora"],
    ["Documento consultado", "No caminho ou na query string",
     "No header <b>X-Document-Id</b>"],
    ["Relatório e features", "—",
     "Query: reportName=&lt;relatório&gt;&amp;optionalFeatures=&lt;features separadas por vírgula&gt;"],
    ["Header de distribuidor", "—",
     "X-Retailer-Document-Id (CNPJ do cliente consultante); X-Cost-Center opcional"],
    ["Erros", "412 tratado como indisponível (502)",
     "412 = documento não encontrado/inválido, feature inexistente ou USER-NOT-AUTHORIZED"],
], [3.6, 4.4, 9])
p("Exemplo de consulta PJ (homologação):")
codigo("GET https://uat-api.serasaexperian.com.br/credit-services/business-information-report/v1/reports\n"
       "    ?reportName=<relatorio>&optionalFeatures=<features>\n"
       "Headers: Authorization: Bearer <token>\n"
       "         X-Document-Id: <documento consultado>\n"
       "         X-Retailer-Document-Id: <CNPJ do cliente consultante>")
p("Relatórios PJ citados: RELATORIO_AVANCADO_PJ, RELATORIO_AVANCADO_TOP_SCORE_PJ, "
  "RELATORIO_AVANCADO_PLUS_PJ, RELATORIO_AVANCADO_PJ_PME (e versões _ANALITICO). Nos relatórios PF, "
  "a tabela pública mostra a feature PARTICIPACAO SOCIETARIA (grafia exata na URL a confirmar).")

h2("O que só a Serasa fornece")
itens([
    "Contrato de homologação com o relatório PF que inclui participação societária.",
    "O valor do header Authorization: Basic para gerar o token.",
    "URL e reportName exatos do relatório PF e o nome exato da feature.",
    "Massa de testes (CPFs cadastrados na homologação).",
    "Troca da senha inicial do logon de homologação em serasaexperian.com.br/homologa.",
    "Contato: representante comercial ou Central Serasa (11) 3003-7372. A Serasa só libera "
    "documentação completa para quem tem contrato ativo.",
])
nota("<b>Ajuste de código pendente</b> (oferecido, ainda não feito): token em JSON com accessToken, CPF "
     "no header X-Document-Id, reportName e optionalFeatures configuráveis no .env, tratamento do "
     "erro 412 e atualização dos testes.")

# ---------------------------------------------------------------- 2. Fontes de dados
h1("2. Fontes de dados para testes e estudo")
p("Limites, preços e planos gratuitos mudam: confirmar no site antes de depender deles.")
tabela(["Serviço", "Custo", "O que oferece", "Observação"], [
    ["<b>BrasilAPI</b><br/>brasilapi.com.br", "Grátis, sem cadastro",
     "CNPJ com quadro societário (qsa), CEP, DDD, bancos, feriados, FIPE, IBGE, NCM, ISBN, PIX, "
     "CVM, câmbio, B3, IBPT",
     "Testada em 10/11/2026: funcionou. Beta, sem garantia. Proibido loop/varredura. "
     "Só busca por CNPJ"],
    ["<b>Minha Receita</b><br/>minhareceita.org", "Grátis, sem chave",
     "CNPJ com quadro societário", "Código aberto; segundo o site, sem limite de uso"],
    ["<b>OpenCNPJ</b><br/>opencnpj.org / opencnpj.com", "Grátis, sem cadastro",
     "Dados de CNPJ", "São dois projetos diferentes com o mesmo nome"],
    ["<b>CNPJ.ws</b>", "Faixa gratuita + planos", "Dados de CNPJ", "—"],
    ["<b>Serpro Consulta CPF</b>", "Demonstração grátis; produção paga",
     "CPF, nome, situação cadastral, nascimento, inscrição, nome social",
     "v3 exige CPF + data de nascimento (DDMMAAAA). Sem homologação separada: fora da demo, "
     "tudo é cobrado (exceto erros 400, 401, 403, 500, 504). OAuth2, token de 1 hora"],
    ["<b>Serpro Consulta CNPJ</b>", "Pago/restrito", "3 níveis de consulta", "Catálogo gov.br/conecta"],
    ["<b>Direct Data</b>", "Pago", "Vínculos societários por CPF ou CNPJ",
     "Mesmo tipo de produto que se queria da Serasa"],
    ["<b>BigDataCorp</b>", "Pago", "Datasets de pessoas e empresas", "Documentação pública grande"],
    ["<b>Infosimples</b>", "Pago por consulta", "Receita, tribunais, Detran etc.", "Não conferido"],
    ["<b>CPFHub.io</b>", "Plano gratuito (~50 consultas)", "Consulta CPF", "Segundo o próprio blog"],
    ["<b>Equifax BoaVista / Quod</b>", "Contrato", "Birôs de crédito", "Mesmo modelo da Serasa"],
], [3.3, 2.7, 5.2, 5.8])
nota("<b>LGPD:</b> nos testes, usar CPFs fictícios das demonstrações ou o próprio CPF. Não consultar "
     "CPF de terceiros sem base legal. Nas bases públicas de CNPJ, o CPF dos sócios vem mascarado.")
p("A Apify (conector instalado) serve para busca e leitura de páginas públicas e para scraping. "
  "Ela não substitui credenciais de birô.")

# ---------------------------------------------------------------- 3. Conceito
story.append(PageBreak())
h1("3. Motor de crédito – conceito e regras legais")
p("Um motor de crédito recebe um pedido (quem pede, quanto, em quantas parcelas) e devolve uma "
  "<b>decisão</b> (aprovado, reprovado, análise manual ou contraproposta), um <b>limite</b>, uma "
  "<b>taxa</b> e os <b>motivos</b>, aplicando a política de crédito da empresa sobre dados de "
  "várias fontes.")
h2("Fluxo (pipeline)")
codigo("Pedido -> 1. Validação -> 2. Regras eliminatórias -> 3. Busca de dados\n"
       "       -> 4. Score -> 5. Decisão (+ limite, taxa, contraproposta) -> 6. Registro")
itens([
    "<b>1. Validação:</b> CPF/CNPJ válido, idade, valor e prazo dentro do produto.",
    "<b>2. Regras eliminatórias (knock-outs):</b> CPF irregular, menor de idade, cliente já em "
    "atraso. Rodam antes das consultas pagas.",
    "<b>3. Busca de dados, da mais barata para a mais cara:</b> dados internos; Receita (Serpro, "
    "BrasilAPI para PJ); birôs (score, negativações, participação societária); Open Finance.",
    "<b>4. Score:</b> probabilidade de não pagar. Começar com scorecard (regressão logística com "
    "WoE, biblioteca optbinning), que explica cada ponto. Sem histórico próprio, usar o score do birô.",
    "<b>5. Decisão:</b> cruza o score com a política (faixas, limite por renda, tabela de taxa).",
    "<b>6. Registro imutável:</b> dados usados, versão da política e do modelo, motivos "
    "(reason codes).",
])
p("Latências típicas citadas no mercado: birôs 150–400 ms; SCR 0,5–1 s; Receita 200–600 ms; "
  "Open Finance 0,3–1,2 s; antifraude &lt; 50 ms.")

h2("Regras legais")
itens([
    "<b>LGPD, art. 20:</b> o titular pode pedir revisão de decisões tomadas unicamente por "
    "tratamento automatizado, incluindo as de perfil de crédito. O controlador deve informar, "
    "quando solicitado, os critérios e procedimentos da decisão (respeitado o segredo comercial). "
    "Consequência: motivos registrados e caminho de revisão humana.",
    "<b>Conceder crédito com recursos próprios</b> exige autorização do Banco Central (ex.: "
    "Sociedade de Crédito Direto) ou operação via parceiro autorizado (BaaS).",
    "<b>SCR e Open Finance:</b> acesso direto só para instituições autorizadas pelo Banco Central.",
    "<b>Cadastro Positivo (Lei 12.414/2011):</b> regula o uso do histórico de pagamentos.",
    "<b>Segurança cibernética:</b> Resolução CMN 4.893/2021 (instituições financeiras) e "
    "Resolução BCB 85/2021 (instituições de pagamento).",
    "<b>Venda parcelada / crediário próprio:</b> cobrar juros pode exigir estrutura específica. "
    "Validar o enquadramento com advogado ou consultor regulatório.",
    "Para <b>estudo</b>, nada disso impede construir e testar o motor com dados fictícios ou públicos.",
])

h2("Datasets públicos para treinar um score de estudo")
itens(["<i>Give Me Some Credit</i> (Kaggle)", "<i>Home Credit Default Risk</i> (Kaggle)",
       "<i>German Credit</i> (UCI)"])
p("Servem para aprender. Um modelo treinado neles <b>não vale</b> para o público real da operação.")

h2("Monitoramento do modelo")
itens([
    "<b>KS e Gini:</b> se o modelo separa bem quem paga de quem não paga.",
    "<b>PSI:</b> se o perfil dos clientes mudou em relação ao treino.",
    "<b>Inadimplência por safra:</b> acompanhar cada mês de concessão.",
    "<b>Champion/challenger:</b> política nova em parte dos pedidos antes de trocar de vez.",
])

# ---------------------------------------------------------------- 4. Mercado
story.append(PageBreak())
h1("4. O que os motores de mercado oferecem")
p("Fornecedores lidos: B2E Group, Teros, Celcoin (Brasil); Taktile, Provenir (internacionais). "
  "É material de marketing: aproveitar as funcionalidades, não os números de desempenho.")
tabela(["#", "Recurso", "Quem oferece", "O que é"], [
    ["1", "<b>Consultas em ordem de custo</b>", "B2E, Celcoin",
     "Fontes grátis/baratas primeiro; pagas só se o pedido não foi barrado"],
    ["2", "<b>Política editável sem programar</b>", "B2E, Teros, Taktile, Provenir",
     "Área de risco muda faixas e limites sem deploy, com versionamento"],
    ["3", "<b>Modelos de política prontos</b>", "B2E", "Biblioteca de regras padrão para começar"],
    ["4", "<b>Análise em lote</b>", "B2E, Taktile",
     "Planilha de clientes analisada de uma vez (ex.: revisar limites da carteira)"],
    ["5", "<b>Contraproposta</b>", "B2E",
     "Em vez de reprovar, oferecer valor menor ou mais parcelas"],
    ["6", "<b>Preço junto com a decisão</b>", "Teros",
     "Taxa calculada no mesmo fluxo e com os mesmos dados do risco"],
    ["7", "<b>Simulação no histórico (backtest)</b>", "Taktile, Provenir",
     "Rodar política nova sobre pedidos antigos antes de publicar"],
    ["8", "<b>Teste A/B (champion/challenger)</b>", "Taktile",
     "Política nova decide parte dos pedidos; comparar resultados"],
    ["9", "<b>Fila de análise manual</b>", "Provenir, Taktile",
     "Casos duvidosos vão a um analista, que vê dados e lógica usados"],
    ["10", "<b>Explicação da decisão</b>", "Provenir, Celcoin",
     "Motivos em linguagem simples; atende LGPD art. 20"],
    ["11", "<b>Governança</b>", "Taktile, Provenir",
     "Perfis de acesso, aprovação de mudanças, registro de quem mudou o quê"],
    ["12", "<b>Ambientes separados</b>", "Provenir", "Promover política de teste -> homologação -> produção"],
    ["13", "<b>Catálogo de fontes</b>", "Provenir (225+), Taktile (200+)",
     "Fontes já integradas, ligadas por configuração"],
    ["14", "<b>IA para documentos</b>", "Provenir",
     "Ler extratos e balanços, gerar parecer. Avançado: fica para depois"],
], [0.7, 4.5, 4, 7.8])
p("Critérios que especialistas usam para avaliar um motor (Taktile): histórico no caso de uso; "
  "edição de regras por não programadores; suporte de regras simples a modelos estatísticos; "
  "testes antes de publicar; integrações com birôs e Open Finance; governança e colaboração; "
  "implantação rápida; certificações de segurança (ISO 27001, SOC 2); SLA e suporte; preço "
  "compatível com o estágio da empresa.")

# ---------------------------------------------------------------- 5. Desenho
h1("5. Desenho da nossa API do motor")
h2("Endpoints propostos")
codigo("POST /v1/decisoes                   decide um pedido (resposta em segundos)\n"
       "POST /v1/decisoes/lote              planilha processada em segundo plano      (#4)\n"
       "GET  /v1/decisoes/{id}              decisão com tudo que foi usado            (#10)\n"
       "POST /v1/decisoes/{id}/revisao      revisão humana exigida pela LGPD          (#9)\n"
       "GET  /v1/fila-manual                casos aguardando analista                 (#9)\n"
       "POST /v1/politicas                  cria versão nova da política              (#2, #11)\n"
       "POST /v1/politicas/{versao}/simular backtest sobre o histórico                (#7)\n"
       "POST /v1/politicas/{versao}/publicar publica, com aprovação de outra pessoa   (#11, #12)")
codigo(titulo="Exemplo de resposta de /v1/decisoes", t='{\n'
       '  "id": "dec_123",\n'
       '  "decisao": "aprovado_com_contraproposta",\n'
       '  "solicitado": {"valor": 10000, "parcelas": 12},\n'
       '  "oferta":     {"valor": 7000,  "parcelas": 18, "taxa_mensal": 0.029},\n'
       '  "score": 642, "faixa_risco": "C",\n'
       '  "motivos": [\n'
       '    {"codigo": "R07",\n'
       '     "texto": "Comprometimento de renda acima de 30% no valor pedido"}\n'
       '  ],\n'
       '  "versao_politica": "2026.11.3", "versao_modelo": "scorecard-v1",\n'
       '  "fontes_consultadas": [\n'
       '    {"fonte": "interna", "custo": 0},\n'
       '    {"fonte": "serasa",  "custo": 1.20}\n'
       '  ]\n'
       '}')
h2("Arquitetura")
itens([
    "<b>Conectores (#13):</b> cada fonte implementa a mesma interface (nome, custo, consultar(), "
    "cache). O cliente Serasa existente vira o primeiro conector; Serpro e BrasilAPI seguem o molde.",
    "<b>Política em YAML versionado (#2, #3):</b> ordem das etapas (#1), regras, faixas de score, "
    "tabela de preço (#6) e regras de contraproposta (#5). Mudança sem deploy; cada decisão "
    "registra a versão que a tomou.",
    "<b>Toda decisão gravada</b> com entrada, dados, versões e motivos: alimenta backtest (#7), "
    "A/B (#8) e auditoria (#10).",
    "Mesmo padrão do projeto Serasa: FastAPI, API key, rate limit, timeouts, logs sem dado pessoal, "
    "testes automatizados.",
    "Sugestão: motor como projeto próprio nesta pasta, com a API Serasa como uma de suas fontes.",
])
h2("Prioridade")
tabela(["Fase", "Recursos", "Custo"], [
    ["1 – Base", "1, 2, 5, 6, 10 + gravar todas as decisões. Scorecard de estudo em dataset público",
     "Grátis"],
    ["2 – Operação / dados de teste", "9 (fila e revisão LGPD), 4 (lote), 3 (modelos prontos). "
     "Conectores Serpro (demo), BrasilAPI e Serasa (homologação)", "Grátis ou homologação"],
    ["3 – Maturidade / produção", "7 (backtest), 8 (A/B), 11 e 12 (governança e ambientes). "
     "Licença ou parceiro BC, contratos com birôs, monitoramento", "Pago"],
    ["Depois", "14 (IA para documentos)", "—"],
], [4, 10, 3])

# ---------------------------------------------------------------- 6. Limites
story.append(PageBreak())
h1("6. O que dá para decidir e o que depende de dados")
h2("Pode ser decidido no nível profissional (padrão de mercado)")
p("Arquitetura, código e conformidade técnica: fluxo em etapas com consultas em ordem de custo, "
  "conectores, política versionada, motivos, auditoria, fila de revisão humana, lote, "
  "contraproposta, backtest, A/B, segurança, testes e deploy.")
h2("Não deve ser decidido sem dados da operação")
tabela(["Decisão", "Por que", "O que é preciso"], [
    ["Pontos de corte do score", "Dependem da inadimplência real dos clientes",
     "Histórico de vendas parceladas: quem pagou e quem atrasou"],
    ["Limite por cliente", "Depende de renda, ticket médio e margem", "Números do negócio"],
    ["Inadimplência aceitável", "Decisão comercial: aprovar mais e perder mais, ou o contrário",
     "Margem e custo do dinheiro"],
    ["Taxa de juros (se houver)", "Depende do custo de capital e da concorrência", "Área financeira"],
    ["Score próprio", "Modelo de Kaggle/outro país não vale para o público real",
     "Alguns milhares de vendas com resultado de pagamento; antes disso, score do birô"],
    ["Enquadramento legal", "Muda se financia a loja, uma financeira ou um BNPL",
     "Advogado ou consultor regulatório"],
], [4, 6.5, 6.5])
nota("<b>Prática de mercado:</b> sem histórico, começar com política conservadora baseada no score do "
     "birô e em regras simples, calibrar conforme a carteira gera dados, e ter a política validada "
     "por um profissional de risco antes da produção. No motor, os valores iniciais ficam marcados "
     "como <b># PROVISÓRIO – validar com risco</b> e são ajustados no YAML, com backtest antes de "
     "publicar.")

# ---------------------------------------------------------------- 7. Próximos passos
h1("7. Próximos passos")
itens([
    "Responder as três perguntas pendentes (PF/PJ, quem assume o risco, estudo ou operação).",
    "Criar o projeto do motor nesta pasta (fase 1).",
    "Adaptar o cliente Serasa ao formato oficial (token JSON, X-Document-Id, reportName, 412).",
    "Obter com a Serasa: contrato de homologação, Authorization Basic, URL do relatório PF, nome "
    "da feature, massa de testes.",
    "Para treinar o fluxo OAuth2 de graça: cliente para a demonstração do Serpro Consulta CPF "
    "(abrir a página no navegador para pegar endereço e token de teste).",
])

# ---------------------------------------------------------------- Fontes
h1("Fontes")
link("Serasa – Developer Portal (Relatório Avançado PJ)",
     "https://developer.serasaexperian.com.br/api/relatorio-avancado-pj")
link("Serasa – Portal Integração", "https://www.serasaexperian.com.br/portal-integracao/")
link("Serpro – aviso Consulta CPF v3",
     "https://centraldeajuda.serpro.gov.br/duvidas/pt/avisos/avisoconsultacpfv3/")
link("Serpro – demonstração Consulta CPF",
     "https://apicenter.estaleiro.serpro.gov.br/documentacao/consulta-cpf/pt/demonstracao/demo-consulta-cpf-df-v3/")
link("Serpro – Consulta CNPJ (gov.br/conecta)", "https://www.gov.br/conecta/catalogo/apis/consulta-cnpj")
link("BrasilAPI", "https://brasilapi.com.br/")
link("Minha Receita", "https://minhareceita.org/")
link("OpenCNPJ", "https://opencnpj.org/")
link("Direct Data – Vínculos Societários",
     "https://www.directd.com.br/central-de-ajuda/apis/catalogo/VinculosSocietarios")
link("BigDataCorp – documentação", "https://docs.bigdatacorp.com.br/")
link("LGPD art. 20", "https://jusfree.com.br/leis/lgpd/art-20")
link("Banco Central – participantes do Open Finance",
     "https://www.bcb.gov.br/estabilidadefinanceira/openfinance_participantes")
link("BCB – dados abertos do SCR", "https://dadosabertos.bcb.gov.br/dataset/scr_data")
link("Celcoin – guia de motor de crédito", "https://celcoin.com.br/articles/motor-de-credito-qi-tech/")
link("B2E – motor de crédito", "https://b2egroup.com.br/blog/2024/09/27/motor-de-credito-da-b2e-group/")
link("Teros – decisão + pricing",
     "https://teros.com.br/blog/inovacao-integrando-modulos-motor-de-decisao-pricing")
link("Taktile – 10 critérios",
     "https://taktile.com/articles/10-things-risk-experts-look-for-in-a-modern-decision-engine")
link("Provenir – Decisioning", "https://www.provenir.com/platform/decisioning/")


def rodape(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Arial", 7.5)
    canvas.setFillColor(CINZA)
    canvas.drawString(2 * cm, 1.2 * cm, "Motor de Crédito – Base de Conhecimento (10/11/2026)")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Página {doc.page}")
    canvas.restoreState()


doc = SimpleDocTemplate(DESTINO, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                        topMargin=1.8 * cm, bottomMargin=2 * cm,
                        title="Motor de Crédito – Base de Conhecimento",
                        author="Gerado com Claude Code")
doc.build(story, onFirstPage=rodape, onLaterPages=rodape)
print("ok", DESTINO)
