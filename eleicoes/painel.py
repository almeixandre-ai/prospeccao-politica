"""Consolida composição + avaliações numa tabela única (CLI, Streamlit, exportação)."""

from __future__ import annotations

import pandas as pd

from .avaliador_afinidade import AvaliadorAfinidade, carregar_agenda
from .interesse import AnalisadorInteresse, tem_historico
from .schemas import Composicao, Parlamentar


def todos(comp: Composicao) -> list[Parlamentar]:
    return [*comp.deputados, *comp.senadores]


def tabela(comp: Composicao) -> pd.DataFrame:
    temas = [t["id"] for t in carregar_agenda()["temas"]]
    linhas = []
    for p in todos(comp):
        a = AvaliadorAfinidade.melhor_disponivel(p)
        i = AnalisadorInteresse.carregar(p)
        if not tem_historico(p):
            prioridade = "Sem histórico (novo no Congresso)"
        else:
            prioridade = i.prioridade if i else "Pendente"
        trajetoria = {
            ("camara", True): "Reeleito(a) deputado(a)" if not p.codigo_senado else "Senado → Câmara",
            ("senado", True): ("Permanece (mandato até 2031)" if p.origem == "senado_2022"
                               else "Câmara → Senado" if p.id_camara and not p.codigo_senado
                               else "Reeleito(a) senador(a)"),
        }.get((p.casa, tem_historico(p)), "Novo(a)")
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
            "trajetoria": trajetoria,
            "iip": i.iip if i else None,
            "prioridade": prioridade,
            "iip_autoria": i.componentes.get("autoria") if i else None,
            "iip_relatoria": i.componentes.get("relatoria") if i and "senado" in i.fontes else None,
            "iip_comissoes": i.componentes.get("comissoes") if i else None,
            "iip_frentes": i.componentes.get("frentes") if i else None,
            "n_proposicoes": len(i.proposicoes) if i else None,
            "n_relatorias": len(i.relatorias) if i else None,
            "orgaos_tech": "; ".join(o.split(":")[0] for o in i.orgaos) if i else "",
            "frentes_tech": "; ".join(i.frentes) if i else "",
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
