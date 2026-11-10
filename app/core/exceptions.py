class ErroDeDominio(Exception):
    """Base para erros de regra de negócio. Cada subclasse define status e código."""

    status_code: int = 400
    codigo: str = "erro_de_dominio"
    mensagem: str = "Requisição inválida."


class ProcessamentoExpirou(ErroDeDominio):
    status_code = 504
    codigo = "timeout"
    mensagem = "O processamento excedeu o tempo limite."


class BancoIndisponivel(ErroDeDominio):
    status_code = 503
    codigo = "banco_indisponivel"
    mensagem = "Banco de dados indisponível. Tente novamente."


class BancoExpirou(ErroDeDominio):
    status_code = 504
    codigo = "banco_timeout"
    mensagem = "O banco de dados não respondeu dentro do tempo limite."
