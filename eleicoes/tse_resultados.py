"""Resultados oficiais do TSE (Eleições 2026) — eleitos para Câmara e Senado.

Fonte: arquivos JSON públicos do sistema de divulgação de resultados
(https://resultados.tse.jus.br), os mesmos usados pelo app "Resultados".

Obs.: o dataset "Correspondências esperadas e efetivadas" do Portal de Dados
Abertos registra a correspondência urna↔seção (auditoria), não votos nem eleitos.
Por isso a fonte de eleitos aqui é o arquivo de resultados por UF/cargo.
"""

from __future__ import annotations

import logging

import requests

log = logging.getLogger("prospeccao.tse")

BASE = "https://resultados.tse.jus.br/oficial"
CICLO = "ele2026"
TIMEOUT = 60

UFS = [
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA",
    "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
]

CARGO_GOVERNADOR = 3
CARGO_SENADOR = 5
CARGO_DEP_FEDERAL = 6


def _get(url: str) -> dict:
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.json()


def codigo_eleicao_estadual() -> str:
    """Descobre o código da eleição estadual de 1º turno de 2026 no config do TSE."""
    cfg = _get(f"{BASE}/comum/config/ele-c.json")
    for pleito in cfg.get("pl", []):
        if pleito.get("c") != CICLO:
            continue
        for ele in pleito.get("e", []):
            cargos = {c["cd"] for a in ele.get("abr", []) for c in a.get("cp", [])}
            if ele.get("t") == "1" and str(CARGO_DEP_FEDERAL) in cargos:
                return ele["cd"]
    raise ValueError("Eleição estadual de 2026 (1º turno) não encontrada no config do TSE")


def resultado_uf(cd_eleicao: str, uf: str, cargo: int) -> dict:
    """Arquivo de resultado consolidado de um cargo em uma UF."""
    uf_l = uf.lower()
    url = (
        f"{BASE}/{CICLO}/{cd_eleicao}/dados/{uf_l}/"
        f"{uf_l}-c{cargo:04d}-e{int(cd_eleicao):06d}-u.json"
    )
    return _get(url)


def candidatos(resultado: dict) -> list[dict]:
    """Achata agremiações/partidos e devolve todos os candidatos com o partido anexado."""
    saida: list[dict] = []
    for carg in resultado.get("carg", []):
        federacoes = {f.get("n"): f.get("sg") for f in carg.get("fed", [])}
        for agr in carg.get("agr", []):
            for par in agr.get("par", []):
                for cand in par.get("cand", []):
                    saida.append({
                        **cand,
                        "partido": par.get("sg"),
                        "federacao": federacoes.get(par.get("nfed")) or None,
                    })
    return saida


def eleitos(resultado: dict) -> list[dict]:
    return [c for c in candidatos(resultado) if str(c.get("st", "")).startswith("Eleito")]


def percentual_totalizado(resultado: dict) -> str:
    return (resultado.get("s") or {}).get("pst", "?")
