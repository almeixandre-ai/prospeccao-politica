"""Coletor unificado — resolve a casa e retorna ProposicaoInfo."""

from __future__ import annotations

import logging

import requests

from .api_camara import buscar_id as camara_buscar_id
from .api_camara import buscar_proposicao as camara_buscar
from .api_senado import buscar_proposicao as senado_buscar
from .schemas import ProposicaoInfo

log = logging.getLogger("prospeccao.coletor")


def coletar(
    tipo: str, numero: int, ano: int, casa: str = "auto",
) -> ProposicaoInfo:
    """Coleta dados de uma proposição.

    Args:
        tipo: Sigla do tipo (PL, PLP, PEC, MPV).
        numero: Número da proposição.
        ano: Ano da proposição.
        casa: 'camara', 'senado' ou 'auto' (tenta Câmara primeiro).
    """
    tipo = tipo.upper()

    if casa == "camara":
        return _coletar_camara(tipo, numero, ano)

    if casa == "senado":
        return _coletar_senado(tipo, numero, ano)

    # auto: tenta Câmara, depois Senado
    log.info("Modo auto — tentando Câmara primeiro...")
    try:
        return _coletar_camara(tipo, numero, ano)
    except (ValueError, requests.RequestException) as e:
        log.info("Não encontrado na Câmara (%s) — tentando Senado...", e)

    return _coletar_senado(tipo, numero, ano)


def _coletar_camara(tipo: str, numero: int, ano: int) -> ProposicaoInfo:
    log.info("Buscando %s %d/%d na Câmara...", tipo, numero, ano)
    id_prop = camara_buscar_id(tipo, numero, ano)
    log.info("ID interno: %d", id_prop)
    dados = camara_buscar(id_prop)
    return ProposicaoInfo.model_validate(dados)


def _coletar_senado(tipo: str, numero: int, ano: int) -> ProposicaoInfo:
    log.info("Buscando %s %d/%d no Senado...", tipo, numero, ano)
    dados = senado_buscar(tipo, numero, ano)
    return ProposicaoInfo.model_validate(dados)
