-- =============================================================================
-- Motor de Crédito – usuários do Oracle (executar como SYSTEM no XEPDB1)
--   MOTOR_CREDITO: dono das tabelas, schema-only (NO AUTHENTICATION = sem login)
--   MOTOR_APP:     usuário da aplicação, só CREATE SESSION + grants nas tabelas
-- A senha do MOTOR_APP vem da variável ORACLE_PASSWORD do .env: o script
-- criar_tabelas.py troca &senha_motor_app por ela e nunca a exibe.
-- No SQL*Plus, o &senha_motor_app é pedido no terminal.
-- =============================================================================

CREATE USER motor_credito NO AUTHENTICATION
    DEFAULT TABLESPACE users
    QUOTA 2G ON users
/
CREATE USER motor_app IDENTIFIED BY "&senha_motor_app"
    DEFAULT TABLESPACE users
    QUOTA 0 ON users
/
GRANT CREATE SESSION TO motor_app
/
