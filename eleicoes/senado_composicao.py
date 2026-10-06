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
    """Senadores cujo mandato atravessa a 58ª legislatura (2027-2031).

    A lista "atual" pode trazer titular e suplente do mesmo mandato no dia de uma troca
    (ex.: retorno do titular). Fica quem está de fato em exercício — último exercício sem
    data de fim —, um por mandato.
    """
    por_mandato: dict[str, dict] = {}
    for p in _lista_atual():
        ident = p["IdentificacaoParlamentar"]
        mandato = p["Mandato"]
        segunda = (mandato.get("SegundaLegislaturaDoMandato") or {}).get("NumeroLegislatura")
        if segunda != LEGISLATURA_2027:
            continue
        exercicios = (mandato.get("Exercicios") or {}).get("Exercicio") or []
        exercicios = exercicios if isinstance(exercicios, list) else [exercicios]
        ultimo = max(exercicios, key=lambda e: e.get("DataInicio", ""), default={})
        em_exercicio = not ultimo.get("DataFim")
        chave = mandato.get("CodigoMandato") or ident["CodigoParlamentar"]
        atual = por_mandato.get(chave)
        if atual and (atual["_em_exercicio"] or not em_exercicio):
            continue
        por_mandato[chave] = {
            "_em_exercicio": em_exercicio,
            "codigo": ident["CodigoParlamentar"],
            "nome": ident["NomeParlamentar"],
            "nome_completo": ident.get("NomeCompletoParlamentar"),
            "partido": ident.get("SiglaPartidoParlamentar", ""),
            "uf": mandato.get("UfParlamentar") or ident.get("UfParlamentar"),
            "participacao": mandato.get("DescricaoParticipacao", "Titular"),
        }
    return [{k: v for k, v in d.items() if not k.startswith("_")} for d in por_mandato.values()]
