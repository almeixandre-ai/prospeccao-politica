"""Consolida composição + avaliações numa tabela única (CLI, Streamlit, exportação)."""

from __future__ import annotations

import pandas as pd

from .avaliador_afinidade import AvaliadorAfinidade, carregar_agenda
from .schemas import Composicao, Parlamentar


def todos(comp: Composicao) -> list[Parlamentar]:
    return [*comp.deputados, *comp.senadores]


def tabela(comp: Composicao) -> pd.DataFrame:
    temas = [t["id"] for t in carregar_agenda()["temas"]]
    linhas = []
    for p in todos(comp):
        a = AvaliadorAfinidade.melhor_disponivel(p)
        linha = {
            "chave": p.chave,
            "casa": "Câmara" if p.casa == "camara" else "Senado",
            "uf": p.uf,
            "nome": p.nome_urna,
            "nome_completo": p.nome_completo,
            "partido": p.partido,
            "federacao": p.federacao,
            "situacao": p.situacao,
            "votos": p.votos,
            "reeleito_ou_permanece": p.incumbente,
            "metodo": a.metodo if a else "pendente",
            "iat": a.indice_afinidade if a and a.metodo == "ia" else None,
            "cobertura": a.cobertura if a else None,
            "classificacao": a.classificacao if a else "Não avaliado",
            "perfil": a.perfil_resumo if a else "",
            "alertas": "; ".join(a.alertas if a else p.alertas),
        }
        posicoes = {t.tema_id: t.posicao for t in a.temas} if a else {}
        for t in temas:
            linha[f"tema_{t}"] = posicoes.get(t)
        linhas.append(linha)
    return pd.DataFrame(linhas)
