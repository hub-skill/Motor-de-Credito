from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração lida de variáveis de ambiente ou do arquivo .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Esta API ---
    app_env: str = "dev"  # dev | staging | prod
    api_key: SecretStr  # sem valor padrão: a aplicação não sobe sem ela
    allowed_origins: list[str] = []
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    request_timeout_seconds: float = 10.0
    enable_docs: bool = False
    rate_limit: str = "60/minute"

    # --- Banco usado pela API: as tabelas existem nos dois ---
    motor_banco: Literal["postgres", "oracle"] = "postgres"

    # --- PostgreSQL (usuário da aplicação; schema credito) ---
    pg_host: str = "127.0.0.1"
    pg_port: int = 5432
    pg_database: str = "motor_credito"
    pg_user: str = "motor_app"
    pg_password: SecretStr = SecretStr("")
    pg_sslmode: str = "prefer"
    pg_pool_min: int = 1
    pg_pool_max: int = 5
    pg_statement_timeout_ms: int = 5000

    # --- Oracle (usuário da aplicação; acessa MOTOR_CREDITO por sinônimos) ---
    oracle_dsn: str = "localhost:1521/XEPDB1"
    oracle_user: str = "MOTOR_APP"
    oracle_password: SecretStr = SecretStr("")
    oracle_pool_min: int = 1
    oracle_pool_max: int = 5
    oracle_call_timeout_ms: int = 5000


@lru_cache
def get_settings() -> Settings:
    return Settings()  # valores obrigatórios (api_key) vêm do ambiente
