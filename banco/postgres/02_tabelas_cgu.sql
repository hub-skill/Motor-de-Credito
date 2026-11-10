-- =============================================================================
-- Motor de Crédito – tabelas das listas da CGU (CEIS, CNEP e PEP) – PostgreSQL
-- Executar como dono do schema (postgres) no banco motor_credito.
-- Pode ser executado de novo: o que já existe é mantido.
-- Fonte: https://portaldatransparencia.gov.br/download-de-dados (ceis, cnep, pep)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Sanções: CEIS (inidôneas e suspensas) + CNEP (punidas), uma linha por sanção
-- -----------------------------------------------------------------------------
create table if not exists credito.sancoes (
    id                       bigint generated always as identity,
    cadastro                 varchar(10)    not null,
    codigo_sancao            bigint         not null,
    tipo_pessoa              char(1),
    documento                varchar(20)    not null,
    nome_sancionado          varchar(200),
    nome_informado_orgao     varchar(200),
    razao_social             varchar(200),
    nome_fantasia            varchar(100),
    numero_processo          varchar(80),
    categoria                varchar(120),
    valor_multa              numeric(15,2),
    data_inicio              date,
    data_fim                 date,
    data_publicacao          date,
    publicacao               varchar(150),
    detalhamento_publicacao  text,
    data_transito_julgado    date,
    abrangencia              varchar(100),
    orgao_sancionador        varchar(300),
    uf_orgao                 char(2),
    esfera_orgao             varchar(20),
    fundamentacao_legal      text,
    data_origem              date,
    origem_informacao        varchar(150),
    observacoes              text,
    arquivo_origem           varchar(60)    not null,
    carregado_em             timestamptz    not null default now(),

    constraint pk_sancoes                    primary key (id),
    constraint uk_sancoes_cadastro_codigo    unique (cadastro, codigo_sancao),
    constraint ck_sancoes_cadastro           check (cadastro in ('CEIS', 'CNEP')),
    constraint ck_sancoes_tipo_pessoa        check (tipo_pessoa in ('F', 'J')),
    constraint ck_sancoes_valor_multa        check (valor_multa >= 0)
);

create index if not exists idx_sancoes_documento on credito.sancoes (documento);

comment on table  credito.sancoes                         is 'Sanções do CEIS e do CNEP (CGU/Portal da Transparência). Recarregada a cada arquivo diário.';
comment on column credito.sancoes.id                      is 'Identificador interno.';
comment on column credito.sancoes.cadastro                is 'Lista de origem: CEIS ou CNEP.';
comment on column credito.sancoes.codigo_sancao           is 'Código da sanção na CGU. Único por cadastro.';
comment on column credito.sancoes.tipo_pessoa             is 'F = pessoa física, J = pessoa jurídica. Nulo quando a CGU não informa.';
comment on column credito.sancoes.documento               is 'CPF ou CNPJ do sancionado, só dígitos, como veio no arquivo (pode haver documentos malformados).';
comment on column credito.sancoes.nome_sancionado         is 'Nome do sancionado.';
comment on column credito.sancoes.nome_informado_orgao    is 'Nome informado pelo órgão sancionador.';
comment on column credito.sancoes.razao_social            is 'Razão social no cadastro da Receita (PJ).';
comment on column credito.sancoes.nome_fantasia           is 'Nome fantasia no cadastro da Receita (PJ).';
comment on column credito.sancoes.numero_processo         is 'Número do processo administrativo ou judicial.';
comment on column credito.sancoes.categoria               is 'Categoria da sanção (impedimento, suspensão, inidoneidade, multa...).';
comment on column credito.sancoes.valor_multa             is 'Valor da multa em reais (somente CNEP).';
comment on column credito.sancoes.data_inicio             is 'Início da sanção.';
comment on column credito.sancoes.data_fim                is 'Fim da sanção. Nulo = sem prazo determinado.';
comment on column credito.sancoes.data_publicacao         is 'Data de publicação da sanção.';
comment on column credito.sancoes.publicacao              is 'Meio de publicação (ex.: Diário Oficial).';
comment on column credito.sancoes.detalhamento_publicacao is 'Detalhamento do meio de publicação.';
comment on column credito.sancoes.data_transito_julgado   is 'Data do trânsito em julgado, quando houver.';
comment on column credito.sancoes.abrangencia             is 'Abrangência da sanção.';
comment on column credito.sancoes.orgao_sancionador       is 'Órgão que aplicou a sanção.';
comment on column credito.sancoes.uf_orgao                is 'UF do órgão sancionador.';
comment on column credito.sancoes.esfera_orgao            is 'Esfera do órgão: FEDERAL, ESTADUAL ou MUNICIPAL.';
comment on column credito.sancoes.fundamentacao_legal     is 'Fundamentação legal da sanção.';
comment on column credito.sancoes.data_origem             is 'Data da informação na origem.';
comment on column credito.sancoes.origem_informacao       is 'Órgão de origem da informação.';
comment on column credito.sancoes.observacoes             is 'Observações da CGU.';
comment on column credito.sancoes.arquivo_origem          is 'Nome do arquivo de onde a linha foi carregada (ex.: 20261110_CEIS.csv).';
comment on column credito.sancoes.carregado_em            is 'Momento da carga.';

-- -----------------------------------------------------------------------------
-- PEP: pessoas expostas politicamente (CPF mascarado pela CGU)
-- -----------------------------------------------------------------------------
create table if not exists credito.peps (
    id                     bigint generated always as identity,
    cpf_mascarado          varchar(20)    not null,
    cpf_miolo              varchar(20)    not null,
    nome                   varchar(100)   not null,
    sigla_funcao           varchar(10),
    descricao_funcao       varchar(100),
    nivel_funcao           varchar(10),
    nome_orgao             varchar(100),
    data_inicio_exercicio  date,
    data_fim_exercicio     date,
    data_fim_carencia      date,
    arquivo_origem         varchar(60)    not null,
    carregado_em           timestamptz    not null default now(),

    constraint pk_peps primary key (id)
);

create index if not exists idx_peps_cpf_miolo_nome on credito.peps (cpf_miolo, nome);

comment on table  credito.peps                       is 'Pessoas expostas politicamente (CGU/Portal da Transparência). Recarregada a cada arquivo mensal.';
comment on column credito.peps.id                    is 'Identificador interno.';
comment on column credito.peps.cpf_mascarado         is 'CPF como publicado pela CGU, mascarado: ***.999.999-**.';
comment on column credito.peps.cpf_miolo             is 'Os 6 dígitos visíveis do CPF. Cruzamento com clientes: cpf_miolo + nome.';
comment on column credito.peps.nome                  is 'Nome da pessoa exposta politicamente.';
comment on column credito.peps.sigla_funcao          is 'Sigla da função (ex.: VEREAD, PREFEI).';
comment on column credito.peps.descricao_funcao      is 'Descrição da função exercida.';
comment on column credito.peps.nivel_funcao          is 'Nível da função, quando informado.';
comment on column credito.peps.nome_orgao            is 'Órgão de exercício.';
comment on column credito.peps.data_inicio_exercicio is 'Início do exercício da função.';
comment on column credito.peps.data_fim_exercicio    is 'Fim do exercício. Nulo = não informada pela CGU.';
comment on column credito.peps.data_fim_carencia     is 'Fim da carência (a pessoa continua PEP até esta data). Nulo = não informada.';
comment on column credito.peps.arquivo_origem        is 'Nome do arquivo de onde a linha foi carregada (ex.: 202609_PEP.csv).';
comment on column credito.peps.carregado_em          is 'Momento da carga.';
