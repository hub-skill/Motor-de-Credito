import os

# Definido antes de importar a aplicação (main.py lê a configuração na importação).
# Sobrescreve o .env local: os testes de API usam um repositório falso, nunca o banco real.
os.environ.update(
    {
        "API_KEY": "chave-de-teste-com-pelo-menos-32-caracteres",
        "ALLOWED_HOSTS": '["test"]',
        "ENABLE_DOCS": "false",
        "RATE_LIMIT": "1000/minute",
        "REQUEST_TIMEOUT_SECONDS": "2",
    }
)

# Documentos válidos (dígitos verificadores corretos), usados só em testes.
CPF_VALIDO = "52998224725"
CNPJ_VALIDO = "00000000000191"
