"""Histórico no Senado — autorias, relatorias e comissões/frentes de um senador."""

from __future__ import annotations

import logging

import requests

log = logging.getLogger("prospeccao.historico_senado")

BASE = "https://legis.senado.leg.br/dadosabertos"
HEADERS = {"Accept": "application/json"}
TIMEOUT = 60
SIGLAS_PROPOSICAO = ("PL ", "PLP ", "PEC ")
SIGLAS_RELATORIA = {"PL", "PLP", "PEC", "MPV", "PLS", "PLC", "PDL"}


def _get(url: str, params: dict | None = None):
    r = requests.get(url, headers=HEADERS, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _lista(v) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def autorias(codigo: str, desde: str = "2023-02-01") -> list[dict]:
    """PL/PLP/PEC de autoria (inclui coautoria), com o primeiro signatário de cada um."""
    try:
        dados = _get(f"{BASE}/processo", {"codigoParlamentarAutor": codigo, "dataInicio": desde})
    except requests.RequestException as e:
        log.warning("Falha nas autorias do senador %s: %s", codigo, e)
        return []
    saida = []
    for p in _lista(dados):
        ident = p.get("identificacao") or ""
        if not ident.startswith(SIGLAS_PROPOSICAO):
            continue
        primeiro = (p.get("autoria") or "").split(",")[0].split("(")[0]
        saida.append({"identificacao": ident, "ementa": p.get("ementa") or "", "primeiro_autor": primeiro})
    return saida


def relatorias(codigo: str, desde: str = "2023-02-01") -> list[dict]:
    try:
        dados = _get(f"{BASE}/senador/{codigo}/relatorias")
    except requests.RequestException as e:
        log.warning("Falha nas relatorias do senador %s: %s", codigo, e)
        return []
    rels = _lista(
        (dados.get("MateriasRelatoriaParlamentar", {}).get("Parlamentar", {})
         .get("Relatorias") or {}).get("Relatoria")
    )
    vistos, saida = set(), []
    for r in rels:
        m = r.get("Materia") or {}
        if (r.get("DataDesignacao") or "") < desde or m.get("Sigla") not in SIGLAS_RELATORIA:
            continue
        ident = m.get("DescricaoIdentificacao") or f"{m.get('Sigla')} {m.get('Numero')}/{m.get('Ano')}"
        if ident in vistos:
            continue
        vistos.add(ident)
        saida.append({"identificacao": ident, "ementa": m.get("Ementa") or "",
                      "colegiado": (r.get("Comissao") or {}).get("Sigla", "")})
    return saida


def comissoes_e_frentes(codigo: str, desde: str = "2023-02-01") -> list[dict]:
    """Comissões, frentes e grupos dos quais foi membro desde o início da legislatura."""
    try:
        dados = _get(f"{BASE}/senador/{codigo}/comissoes")
    except requests.RequestException as e:
        log.warning("Falha nas comissões do senador %s: %s", codigo, e)
        return []
    coms = _lista(
        (dados.get("MembroComissaoParlamentar", {}).get("Parlamentar", {})
         .get("MembroComissoes") or {}).get("Comissao")
    )
    saida = []
    for c in coms:
        if c.get("DataFim") and c["DataFim"] < desde:
            continue
        ident = c.get("IdentificacaoComissao") or {}
        saida.append({
            "sigla": ident.get("SiglaComissao", ""),
            "nome": ident.get("NomeComissao", ""),
            "papel": c.get("DescricaoParticipacao", ""),
        })
    return saida
