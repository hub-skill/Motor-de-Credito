-- =============================================================================
-- Motor de Crédito – log de erros da API (PostgreSQL)
-- Executar como dono do schema (postgres) no banco motor_credito, depois de 02_tabelas_cgu.
-- Pode ser executado de novo: o que já existe é mantido.
--
-- Uma linha por resposta de erro (4xx e 5xx) da API. Só metadados: NUNCA CPF, CNPJ, nome
-- ou corpo da requisição. A aplicação (motor_app) só INSERE; não lê, altera nem apaga.
-- Limpeza (como administrador), ex.: manter 90 dias:
--   delete from credito.log_erros where ocorrido_em < now() - interval '90 days';
-- =============================================================================

create table if not exists credito.log_erros (
    id            bigint        generated always as identity,
    ocorrido_em   timestamptz   not null default now(),
    request_id    varchar(64)   not null,
    metodo        varchar(10)   not null,
    rota          varchar(200)  not null,
    status        smallint      not null,
    codigo        varchar(40)   not null,
    titulo        varchar(200)  not null,
    tipo_excecao  varchar(200),
    duracao_ms    integer,
    ambiente      varchar(20)   not null,

    constraint pk_log_erros          primary key (id),
    constraint ck_log_erros_status   check (status between 400 and 599),
    constraint ck_log_erros_duracao  check (duracao_ms >= 0)
);

create index if not exists idx_log_erros_ocorrido_em on credito.log_erros (ocorrido_em);

comment on table  credito.log_erros              is 'Respostas de erro (4xx e 5xx) da API Python. Só metadados, sem dados pessoais.';
comment on column credito.log_erros.id           is 'Identificador interno.';
comment on column credito.log_erros.ocorrido_em  is 'Momento da gravação (alguns milissegundos depois da resposta).';
comment on column credito.log_erros.request_id   is 'Mesmo request_id devolvido ao cliente no corpo do erro e no header X-Request-ID.';
comment on column credito.log_erros.metodo       is 'Método HTTP (POST, GET...).';
comment on column credito.log_erros.rota         is 'Caminho pedido, sem query string (truncado em 200 caracteres).';
comment on column credito.log_erros.status       is 'Status HTTP da resposta (400 a 599).';
comment on column credito.log_erros.codigo       is 'Campo code do erro (ex.: entrada_invalida, banco_indisponivel).';
comment on column credito.log_erros.titulo       is 'Campo title do erro.';
comment on column credito.log_erros.tipo_excecao is 'Tipo da exceção, só em erro_interno (500). O stack trace fica no log da aplicação.';
comment on column credito.log_erros.duracao_ms   is 'Tempo da requisição até o erro, em milissegundos.';
comment on column credito.log_erros.ambiente     is 'APP_ENV da API (dev, staging, prod).';

-- A aplicação só insere. Os privilégios padrão do schema dariam select/update/delete: retirados aqui.
revoke all on credito.log_erros from motor_app;
grant insert on credito.log_erros to motor_app;
