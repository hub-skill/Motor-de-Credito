-- =============================================================================
-- Motor de Crédito – criação do banco, do schema e do usuário da aplicação
-- PostgreSQL 15+ (testado na sintaxe do 18)
--
-- Como executar (como superusuário postgres, no terminal):
--   & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h 127.0.0.1 -d postgres -f "01_criar_banco_usuario.sql"
--
-- O psql vai pedir:
--   1) a senha do postgres (para conectar);
--   2) a nova senha do usuário motor_app, duas vezes (\password).
-- As senhas são digitadas só no terminal: não ficam neste arquivo nem no histórico.
--
-- Pode ser executado de novo sem erro: o que já existe é mantido.
-- =============================================================================

\set ON_ERROR_STOP on

-- 1. Usuário da aplicação (sem superusuário, sem criar bancos ou papéis)
select 'create role motor_app login nosuperuser nocreatedb nocreaterole'
 where not exists (select 1 from pg_roles where rolname = 'motor_app')
\gexec

\echo
\echo '>>> Defina a senha do usuário motor_app (será pedida duas vezes):'
\password motor_app

-- 2. Banco da aplicação
select 'create database motor_credito encoding ''UTF8'' template template0'
 where not exists (select 1 from pg_database where datname = 'motor_credito')
\gexec

revoke all on database motor_credito from public;
grant connect on database motor_credito to motor_app;

-- 3. Schema e permissões (dentro do banco novo)
\connect motor_credito

create schema if not exists credito authorization postgres;
comment on schema credito is 'Tabelas do motor de crédito para venda parcelada.';

-- Ninguém além do dono cria objetos no public (padrão desde o PG 15; garantido aqui).
revoke create on schema public from public;

grant usage on schema credito to motor_app;
grant select, insert, update, delete on all tables in schema credito to motor_app;
grant usage, select on all sequences in schema credito to motor_app;

-- Tabelas criadas depois (pelo postgres, dono do schema) já nascem com as permissões.
alter default privileges for role postgres in schema credito
    grant select, insert, update, delete on tables to motor_app;
alter default privileges for role postgres in schema credito
    grant usage, select on sequences to motor_app;

-- O motor_app enxerga as tabelas do schema credito sem digitar "credito."
alter role motor_app in database motor_credito set search_path = credito;

-- 4. Conferência
\echo
\echo '>>> Resultado:'
select current_database()                                    as banco,
       (select rolname from pg_roles where rolname = 'motor_app') as usuario,
       has_database_privilege('motor_app', 'motor_credito', 'CONNECT') as pode_conectar,
       has_schema_privilege('motor_app', 'credito', 'USAGE')           as usa_schema,
       has_schema_privilege('motor_app', 'credito', 'CREATE')          as cria_no_schema;
