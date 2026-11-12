-- =============================================================================
-- Motor de Crédito – log de erros da API (Oracle 21c)
-- Executar como DBA (SYSTEM) no XEPDB1, depois de 02_tabelas_cgu.
-- Cada comando termina numa linha com "/". Reexecutar não dá problema.
--
-- Uma linha por resposta de erro (4xx e 5xx) da API. Só metadados: NUNCA CPF, CNPJ, nome
-- ou corpo da requisição. A aplicação (MOTOR_APP) só INSERE; não lê, altera nem apaga.
-- Limpeza (como administrador), ex.: manter 90 dias:
--   DELETE FROM motor_credito.log_erros WHERE ocorrido_em < SYSTIMESTAMP - INTERVAL '90' DAY;
-- =============================================================================

CREATE TABLE motor_credito.log_erros (
    id            NUMBER GENERATED ALWAYS AS IDENTITY,
    ocorrido_em   TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    request_id    VARCHAR2(64)   NOT NULL,
    metodo        VARCHAR2(10)   NOT NULL,
    rota          VARCHAR2(200)  NOT NULL,
    status        NUMBER(3)      NOT NULL,
    codigo        VARCHAR2(40)   NOT NULL,
    titulo        VARCHAR2(200)  NOT NULL,
    tipo_excecao  VARCHAR2(200),
    duracao_ms    NUMBER(10),
    ambiente      VARCHAR2(20)   NOT NULL,

    CONSTRAINT pk_log_erros         PRIMARY KEY (id),
    CONSTRAINT ck_log_erros_status  CHECK (status BETWEEN 400 AND 599),
    CONSTRAINT ck_log_erros_duracao CHECK (duracao_ms >= 0)
)
/
CREATE INDEX motor_credito.idx_log_erros_ocorrido_em ON motor_credito.log_erros (ocorrido_em)
/
COMMENT ON TABLE motor_credito.log_erros IS 'Respostas de erro (4xx e 5xx) da API Python. Só metadados, sem dados pessoais.'
/
COMMENT ON COLUMN motor_credito.log_erros.id IS 'Identificador interno.'
/
COMMENT ON COLUMN motor_credito.log_erros.ocorrido_em IS 'Momento da gravação (alguns milissegundos depois da resposta).'
/
COMMENT ON COLUMN motor_credito.log_erros.request_id IS 'Mesmo request_id devolvido ao cliente no corpo do erro e no header X-Request-ID.'
/
COMMENT ON COLUMN motor_credito.log_erros.metodo IS 'Método HTTP (POST, GET...).'
/
COMMENT ON COLUMN motor_credito.log_erros.rota IS 'Caminho pedido, sem query string (truncado em 200 caracteres).'
/
COMMENT ON COLUMN motor_credito.log_erros.status IS 'Status HTTP da resposta (400 a 599).'
/
COMMENT ON COLUMN motor_credito.log_erros.codigo IS 'Campo code do erro (ex.: entrada_invalida, banco_indisponivel).'
/
COMMENT ON COLUMN motor_credito.log_erros.titulo IS 'Campo title do erro.'
/
COMMENT ON COLUMN motor_credito.log_erros.tipo_excecao IS 'Tipo da exceção, só em erro_interno (500). O stack trace fica no log da aplicação.'
/
COMMENT ON COLUMN motor_credito.log_erros.duracao_ms IS 'Tempo da requisição até o erro, em milissegundos.'
/
COMMENT ON COLUMN motor_credito.log_erros.ambiente IS 'APP_ENV da API (dev, staging, prod).'
/
-- A aplicação só insere (sem SELECT, UPDATE ou DELETE) e enxerga a tabela pelo sinônimo.
GRANT INSERT ON motor_credito.log_erros TO motor_app
/
CREATE OR REPLACE SYNONYM motor_app.log_erros FOR motor_credito.log_erros
/
