"""Consulta a API aberta da Câmara dos Deputados."""

from __future__ import annotations

import requests

from .schemas import ProposicaoInfo

BASE = "https://dadosabertos.camara.leg.br/api/v2"
HEADERS = {"Accept": "application/json"}
TIMEOUT = 30


def _get(url: str, params: dict | None = None) -> dict:
    r = requests.get(url, headers=HEADERS, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def buscar_id(sigla_tipo: str, numero: int, ano: int) -> int:
    """Resolve o ID interno da API a partir de sigla/número/ano."""
    dados = _get(
        f"{BASE}/proposicoes",
        params={"siglaTipo": sigla_tipo, "numero": numero, "ano": ano},
    ).get("dados", [])
    if not dados:
        raise ValueError(
            f"Proposição {sigla_tipo} {numero}/{ano} não encontrada na Câmara"
        )
    return dados[0]["id"]


def buscar_proposicao(id_proposicao: int) -> dict:
    """Retorna dados padronizados de uma proposição da Câmara pelo seu ID numérico."""

    dados = _get(f"{BASE}/proposicoes/{id_proposicao}")["dados"]

    ementa = dados.get("ementa", "")
    status = dados.get("statusProposicao") or {}
    situacao = status.get("descricaoSituacao", "Não informada")
    regime = status.get("descricaoTramitacao", None)
    url_teor = dados.get("urlInteiroTeor")
    tipo_sigla = dados.get("siglaTipo", "")
    numero = dados.get("numero", 0)
    ano = dados.get("ano", 0)

    # Último evento via tramitações (mais recente primeiro)
    ultimo_evento = None
    ultimo_evento_data = None
    try:
        trams = _get(
            f"{BASE}/proposicoes/{id_proposicao}/tramitacoes",
            params={"ordem": "DESC", "ordenarPor": "dataHora", "itens": 1},
        )
        items = trams.get("dados", [])
        if items:
            ultimo_evento = items[0].get("descricaoSituacao")
            ultimo_evento_data = items[0].get("dataHora", "")[:10]
    except requests.RequestException:
        pass

    if not ultimo_evento:
        ultimo_evento = status.get("descricaoTramitacao")
        ultimo_evento_data = (status.get("dataHora") or "")[:10] or None

    # Relator — último despacho que designa relator
    relator = None
    try:
        trams_all = _get(
            f"{BASE}/proposicoes/{id_proposicao}/tramitacoes",
            params={"ordem": "DESC", "ordenarPor": "dataHora", "itens": 100},
        )
        for t in trams_all.get("dados", []):
            despacho = (t.get("despacho") or "").lower()
            if "relator" in despacho:
                parts = (t.get("despacho") or "").split("Relator")
                if len(parts) > 1:
                    relator = parts[-1].strip(": .-,")
                break
    except requests.RequestException:
        pass

    # Autor
    autor = None
    try:
        autores = _get(f"{BASE}/proposicoes/{id_proposicao}/autores").get("dados", [])
        if autores:
            autor = autores[0].get("nome")
    except requests.RequestException:
        pass

    # Comissões que ainda irão analisar (órgãos do despacho atual)
    comissoes_pendentes: list[str] = []
    despacho_atual = status.get("despacho", "") or ""
    if despacho_atual:
        import re
        comissoes_pendentes = re.findall(r"\b(C[A-Z]{2,}(?:SP)?)\b", despacho_atual)

    info = ProposicaoInfo(
        origem="camara",
        tipo_sigla=tipo_sigla,
        numero=numero,
        ano=ano,
        ementa=ementa,
        situacao_atual=situacao,
        ultimo_evento=ultimo_evento,
        ultimo_evento_data=ultimo_evento_data,
        autor=autor,
        relator_designado=relator,
        comissoes_pendentes=comissoes_pendentes,
        regime_tramitacao=regime,
        url_inteiro_teor=url_teor,
    )
    return info.model_dump()
