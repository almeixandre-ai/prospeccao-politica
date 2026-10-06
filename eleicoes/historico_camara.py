"""Histórico legislativo na Câmara — identifica reeleitos e suas proposições tech."""

from __future__ import annotations

import logging
import re
import unicodedata
from difflib import SequenceMatcher

import requests

log = logging.getLogger("prospeccao.historico")

BASE = "https://dadosabertos.camara.leg.br/api/v2"
HEADERS = {"Accept": "application/json"}
TIMEOUT = 30
LEGISLATURA_ATUAL = 57


def normalizar(nome: str) -> str:
    s = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode()
    s = re.sub(r"\b(DEP|DEPUTADO|DEPUTADA|SEN|SENADOR|SENADORA|DR|DRA|PROF|PROFESSOR|PROFESSORA)\b\.?", " ", s.upper())
    return " ".join(re.sub(r"[^A-Z ]", " ", s).split())


def similaridade(a: str, b: str) -> float:
    na, nb = normalizar(a), normalizar(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = set(na.split()), set(nb.split())
    # Nome de urna curto contido no nome civil/parlamentar ("TABATA AMARAL" ⊂ ...)
    if min(len(ta), len(tb)) >= 2 and (ta <= tb or tb <= ta):
        return 0.9
    ratio = SequenceMatcher(None, na, nb).ratio()
    # Primeiro nome diferente ("NEY SANTOS" x "ELY SANTOS") derruba a confiança
    return ratio if na.split()[0] == nb.split()[0] else ratio * 0.85


def deputados_legislatura(idleg: int = LEGISLATURA_ATUAL) -> list[dict]:
    r = requests.get(
        f"{BASE}/deputados",
        params={"idLegislatura": idleg, "itens": 1000, "ordem": "ASC", "ordenarPor": "nome"},
        headers=HEADERS, timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json().get("dados", [])


def casar_deputado(nome_urna: str, nome_completo: str | None, uf: str,
                   deputados: list[dict], limiar: float = 0.85) -> dict | None:
    """Encontra o deputado da legislatura atual correspondente a um eleito do TSE."""
    melhor, nota = None, 0.0
    for d in deputados:
        if d.get("siglaUf") != uf:
            continue
        s = max(similaridade(nome_urna, d.get("nome", "")),
                similaridade(nome_completo or "", d.get("nome", "")) * 0.95)
        if s > nota:
            melhor, nota = d, s
    return melhor if nota >= limiar else None


def proposicoes_autoria(id_deputado: int, desde: str = "2023-02-01") -> list[dict]:
    """PL/PLP/PEC de autoria do deputado desde o início da legislatura."""
    saida: list[dict] = []
    for pagina in range(1, 11):
        try:
            r = requests.get(
                f"{BASE}/proposicoes",
                params={
                    "idDeputadoAutor": id_deputado, "dataApresentacaoInicio": desde,
                    "siglaTipo": "PL,PLP,PEC", "itens": 100, "pagina": pagina,
                },
                headers=HEADERS, timeout=TIMEOUT,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            log.warning("Falha ao buscar proposições do deputado %s: %s", id_deputado, e)
            break
        dados = r.json().get("dados", [])
        saida.extend(dados)
        if len(dados) < 100:
            break
    return saida


def filtrar_por_agenda(proposicoes: list[dict], agenda: dict) -> list[str]:
    """Proposições cuja ementa casa com palavras-chave de algum tema da agenda."""
    achados: list[str] = []
    for p in proposicoes:
        ementa = p.get("ementa") or ""
        ementa_n = f" {normalizar(ementa)} "
        temas = [
            t["id"] for t in agenda["temas"]
            if any(f" {normalizar(k)} " in ementa_n for k in t["palavras_chave"])
        ]
        if temas:
            achados.append(
                f"{p.get('siglaTipo')} {p.get('numero')}/{p.get('ano')} [{', '.join(temas)}]: {ementa[:220]}"
            )
    return achados


def orgaos(id_deputado: int, desde: str = "2023-02-01") -> list[dict]:
    """Comissões e demais órgãos dos quais o deputado foi membro na legislatura."""
    saida: list[dict] = []
    for pagina in range(1, 6):
        try:
            r = requests.get(
                f"{BASE}/deputados/{id_deputado}/orgaos",
                params={"dataInicio": desde, "itens": 100, "pagina": pagina},
                headers=HEADERS, timeout=TIMEOUT,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            log.warning("Falha nos órgãos do deputado %s: %s", id_deputado, e)
            break
        dados = r.json().get("dados", [])
        saida.extend({"sigla": o.get("siglaOrgao", ""), "nome": o.get("nomeOrgao", ""),
                      "papel": o.get("titulo", "")} for o in dados)
        if len(dados) < 100:
            break
    return saida


def frentes(id_deputado: int, idleg: int = LEGISLATURA_ATUAL) -> list[str]:
    """Títulos das frentes parlamentares que o deputado integra na legislatura."""
    try:
        r = requests.get(f"{BASE}/deputados/{id_deputado}/frentes", headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        log.warning("Falha nas frentes do deputado %s: %s", id_deputado, e)
        return []
    return [f.get("titulo", "") for f in r.json().get("dados", []) if f.get("idLegislatura") == idleg]
