"""Senadores que permanecem em 2027 (eleitos em 2022, mandato até 31/01/2031)."""

from __future__ import annotations

import requests

BASE = "https://legis.senado.leg.br/dadosabertos"
HEADERS = {"Accept": "application/json"}
TIMEOUT = 30
LEGISLATURA_2027 = "58"


def _lista_atual() -> list[dict]:
    r = requests.get(f"{BASE}/senador/lista/atual", headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    ps = r.json()["ListaParlamentarEmExercicio"]["Parlamentares"]["Parlamentar"]
    return ps if isinstance(ps, list) else [ps]


def senadores_em_exercicio() -> list[dict]:
    """Todos os 81 em exercício hoje (para marcar incumbência dos reeleitos)."""
    return [
        {
            "codigo": p["IdentificacaoParlamentar"]["CodigoParlamentar"],
            "nome": p["IdentificacaoParlamentar"]["NomeParlamentar"],
            "nome_completo": p["IdentificacaoParlamentar"].get("NomeCompletoParlamentar"),
            "uf": p["Mandato"].get("UfParlamentar") or p["IdentificacaoParlamentar"].get("UfParlamentar"),
        }
        for p in _lista_atual()
    ]


def senadores_que_permanecem() -> list[dict]:
    """Senadores cujo mandato atravessa a 58ª legislatura (2027-2031)."""
    saida: list[dict] = []
    for p in _lista_atual():
        ident = p["IdentificacaoParlamentar"]
        mandato = p["Mandato"]
        segunda = (mandato.get("SegundaLegislaturaDoMandato") or {}).get("NumeroLegislatura")
        if segunda != LEGISLATURA_2027:
            continue
        saida.append({
            "codigo": ident["CodigoParlamentar"],
            "nome": ident["NomeParlamentar"],
            "nome_completo": ident.get("NomeCompletoParlamentar"),
            "partido": ident.get("SiglaPartidoParlamentar", ""),
            "uf": mandato.get("UfParlamentar") or ident.get("UfParlamentar"),
            "participacao": mandato.get("DescricaoParticipacao", "Titular"),
        })
    return saida
