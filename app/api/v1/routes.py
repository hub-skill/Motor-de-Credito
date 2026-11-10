from datetime import date

from anyio import fail_after
from fastapi import APIRouter, Depends, Request

from app.api.deps import CacheOrigem, get_cache_origem, get_repositorio, verificar_api_key
from app.core.config import Settings, get_settings
from app.core.exceptions import ProcessamentoExpirou
from app.core.limiter import limiter
from app.repositorios.base import RegistroPep, RepositorioListas
from app.schemas.triagem import (
    EntradaTriagem,
    FonteSaida,
    MotivoSaida,
    PepSaida,
    SaidaTriagem,
    SancaoSaida,
)
from app.services.documentos import mascarar, miolo_cpf, normalizar_documento
from app.services.triagem import sancao_vigente, triar

router = APIRouter(prefix="/api/v1", tags=["triagem"])


@router.post(
    "/triagem",
    response_model=SaidaTriagem,
    dependencies=[Depends(verificar_api_key)],
    summary="Verifica um CPF/CNPJ nas listas de sanções (CEIS/CNEP) e de PEP da CGU",
    responses={
        401: {"description": "API key ausente ou inválida"},
        413: {"description": "Corpo muito grande"},
        422: {"description": "CPF/CNPJ inválido"},
        429: {"description": "Limite de requisições excedido"},
        503: {"description": "Banco de dados indisponível"},
        504: {"description": "Tempo limite excedido"},
    },
)
@limiter.limit(lambda: get_settings().rate_limit)
async def triagem(
    request: Request,  # exigido pelo slowapi
    entrada: EntradaTriagem,
    settings: Settings = Depends(get_settings),
    repo: RepositorioListas = Depends(get_repositorio),
    cache: CacheOrigem = Depends(get_cache_origem),
) -> SaidaTriagem:
    # POST (e não GET) para o documento não aparecer em URLs, logs de proxy e histórico.
    documento, tipo = normalizar_documento(entrada.documento)
    hoje = date.today()
    try:
        with fail_after(settings.request_timeout_seconds):
            sancoes = await repo.buscar_sancoes(documento)
            candidatos: list[RegistroPep] = []
            if tipo == "CPF" and entrada.nome:
                candidatos = await repo.buscar_peps_por_miolo(miolo_cpf(documento))
            origem = await cache.obter(repo)
    except TimeoutError as exc:
        raise ProcessamentoExpirou() from exc

    r = triar(tipo, entrada.nome, sancoes, candidatos, hoje)
    return SaidaTriagem(
        documento=mascarar(documento, tipo),
        tipo=tipo,
        resultado=r.resultado,
        motivos=[MotivoSaida(codigo=m.codigo, texto=m.texto) for m in r.motivos],
        sancoes=[
            SancaoSaida(
                cadastro=s.cadastro,
                categoria=s.categoria,
                orgao_sancionador=s.orgao_sancionador,
                uf_orgao=s.uf_orgao,
                data_inicio=s.data_inicio,
                data_fim=s.data_fim,
                numero_processo=s.numero_processo,
                vigente=sancao_vigente(s, hoje),
            )
            for s in sancoes
        ],
        pep=PepSaida(
            verificado=r.pep_verificado,
            ativo=r.pep_ativo,
            funcoes=sorted({p.descricao_funcao for p in r.peps if p.descricao_funcao}),
        ),
        consultado_em=hoje,
        fonte=FonteSaida(banco=origem.banco, arquivos=list(origem.arquivos), carregado_em=origem.carregado_em),
    )
