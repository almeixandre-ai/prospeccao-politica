"""Eleições 2026 — nova composição do Congresso × agenda ABES."""

from __future__ import annotations

import io
import os

from dotenv import load_dotenv
load_dotenv()

import pandas as pd
import streamlit as st

from eleicoes import composicao as comp_mod
from eleicoes.avaliador_afinidade import AvaliadorAfinidade, carregar_agenda
from eleicoes.painel import tabela, todos

st.set_page_config(page_title="Eleições 2026 × ABES", page_icon="🗳️", layout="wide")

CLASSE_COR = {
    "Aliado tecnológico": "#27AE60",
    "Potencial aliado": "#7DBE5A",
    "Neutro": "#F1C40F",
    "Atenção": "#C0392B",
    "Engajado — qualificar": "#2C5F8A",
    "Sem sinal": "#95A5A6",
    "Não avaliado": "#D5D8DC",
}
POSICAO_ROTULO = {2: "🟢 +2 alinhado", 1: "🟢 +1 favorável", 0: "⚪ 0 sem sinal",
                  -1: "🟠 -1 contrário", -2: "🔴 -2 oposto"}

st.markdown("## 🗳️ Eleições 2026 — Congresso 2027-2031 × agenda ABES")
st.caption(
    "Eleitos: resultados oficiais do TSE (1º turno, 04/10/2026). Senado: 2 eleitos por UF em 2026 + "
    "1 senador por UF com mandato até 2031 (API do Senado). Afinidade: propostas de campanha, "
    "manifestações públicas e histórico legislativo cotejados com a agenda ABES."
)


# ── Dados ────────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def _composicao_json() -> str | None:
    comp = comp_mod.carregar()
    return comp.model_dump_json() if comp else None


comp_json = _composicao_json()
if comp_json is None:
    st.info("A composição ainda não foi coletada.")
    if st.button("Coletar resultados do TSE e do Senado agora"):
        with st.spinner("Baixando resultados das 27 UFs..."):
            comp_mod.salvar(comp_mod.montar())
        st.cache_data.clear()
        st.rerun()
    st.stop()

comp = comp_mod.Composicao.model_validate_json(comp_json)
df = tabela(comp)
agenda = carregar_agenda()
nomes_temas = {t["id"]: t["nome"] for t in agenda["temas"]}

# ── Indicadores ──────────────────────────────────────────────────────────

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Deputados", len(comp.deputados))
c2.metric("Reeleitos na Câmara", int(sum(d.incumbente for d in comp.deputados)))
c3.metric("Senadores", len(comp.senadores),
          help="54 eleitos em 2026 + 27 com mandato até 2031")
c4.metric("Avaliados com IA", int((df["metodo"] == "ia").sum()))
c5.metric("Aliados / potenciais",
          int(df["classificacao"].isin(["Aliado tecnológico", "Potencial aliado"]).sum()))

for a in comp.alertas:
    st.warning(a)
st.caption(f"Coleta: {comp.data_coleta} · totalização TSE: "
           f"{'100% em todas as UFs' if set(comp.totalizacao_tse.values()) == {'100,00'} else comp.totalizacao_tse}")

# ── Filtros ──────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("Filtros")
    casa = st.multiselect("Casa", ["Câmara", "Senado"], default=["Câmara", "Senado"])
    ufs = st.multiselect("UF", sorted(df["uf"].unique()))
    partidos = st.multiselect("Partido", sorted(df["partido"].dropna().unique()))
    classes = st.multiselect("Classificação", list(CLASSE_COR))
    so_reeleitos = st.checkbox("Só reeleitos / que permanecem")
    busca = st.text_input("Buscar nome")

f = df[df["casa"].isin(casa)]
if ufs:
    f = f[f["uf"].isin(ufs)]
if partidos:
    f = f[f["partido"].isin(partidos)]
if classes:
    f = f[f["classificacao"].isin(classes)]
if so_reeleitos:
    f = f[f["reeleito_ou_permanece"]]
if busca:
    f = f[f["nome"].str.contains(busca, case=False) | f["nome_completo"].fillna("").str.contains(busca, case=False)]
f = f.sort_values(["iat", "cobertura", "votos"], ascending=False, na_position="last")

aba_lista, aba_bancadas, aba_agenda = st.tabs(["Parlamentares", "Bancadas", "Agenda ABES"])

with aba_lista:
    st.caption(f"{len(f)} parlamentares no filtro")
    colunas_temas = [c for c in f.columns if c.startswith("tema_")]
    sel = st.dataframe(
        f[["casa", "uf", "nome", "partido", "situacao", "votos", "classificacao", "iat", "cobertura",
           *colunas_temas]].rename(columns={c: nomes_temas.get(c[5:], c) for c in colunas_temas}),
        hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
        column_config={
            "iat": st.column_config.ProgressColumn("IAT", min_value=0, max_value=100, format="%.0f"),
            "cobertura": st.column_config.ProgressColumn("Cobertura", min_value=0, max_value=1, format="percent"),
            "votos": st.column_config.NumberColumn("Votos", format="%d"),
        },
    )

    buf = io.BytesIO()
    f.to_excel(buf, index=False)
    st.download_button("⬇️ Exportar seleção (Excel)", buf.getvalue(), "eleicoes2026_abes.xlsx")

    linhas = sel.selection.rows if sel and sel.selection else []
    if linhas:
        chave = f.iloc[linhas[0]]["chave"]
        p = next(x for x in todos(comp) if x.chave == chave)
        st.divider()
        st.markdown(f"### {p.nome_urna} — {p.partido}/{p.uf} "
                    f"({'Deputado(a) Federal' if p.casa == 'camara' else 'Senador(a)'})")
        st.caption(f"{p.nome_completo or ''} · {p.situacao}"
                   f"{f' · {p.votos:,} votos'.replace(',', '.') if p.votos else ''}"
                   f"{' · reeleito(a)/permanece' if p.incumbente else ' · novo(a) na casa'}")

        tem_chave = bool(os.environ.get("ANTHROPIC_API_KEY"))
        ia = AvaliadorAfinidade.carregar(p, "ia")
        rotulo = "🔄 Refazer análise com IA" if ia else "🤖 Analisar propostas com IA"
        if st.button(rotulo, disabled=not tem_chave,
                     help=None if tem_chave else "Configure ANTHROPIC_API_KEY no .env"):
            with st.spinner("Buscando propostas de campanha e cruzando com a agenda ABES..."):
                try:
                    AvaliadorAfinidade().avaliar(p, forcar=True)
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Falha na análise: {e}")

        a = AvaliadorAfinidade.melhor_disponivel(p)
        if a is None:
            st.info("Ainda não avaliado.")
        else:
            cor = CLASSE_COR.get(a.classificacao, "#95A5A6")
            st.markdown(
                f"<span style='background:{cor};color:white;padding:6px 14px;border-radius:6px;"
                f"font-weight:700'>{a.classificacao}</span> &nbsp; "
                + (f"IAT <b>{a.indice_afinidade:.0f}</b>/100 · " if a.metodo == "ia" else "")
                + f"cobertura da agenda {a.cobertura:.0%} · método: {a.metodo} · {a.data_geracao}",
                unsafe_allow_html=True,
            )
            if a.perfil_resumo:
                st.write(a.perfil_resumo)
            for al in a.alertas:
                st.warning(al)
            for t in sorted(a.temas, key=lambda t: (-abs(t.posicao), t.tema_id)):
                rotulo_t = (POSICAO_ROTULO[t.posicao] if a.metodo == "ia"
                            else ("🔵 engajado" if t.posicao else "⚪ sem proposições"))
                with st.expander(f"{rotulo_t} —{nomes_temas.get(t.tema_id, t.tema_id)} "
                                 f"(confiança {t.confianca.value})", expanded=t.posicao != 0 and a.metodo == "ia"):
                    st.write(t.justificativa)
                    for e in t.evidencias:
                        link = f"[{e.fonte}]({e.url})" if e.url else e.fonte
                        st.markdown(f"- {link}: {e.trecho_relevante}")
            if a.historico_legislativo:
                with st.expander(f"📜 Proposições de autoria aderentes à agenda ({len(a.historico_legislativo)})"):
                    for h in a.historico_legislativo:
                        st.markdown(f"- {h}")

with aba_bancadas:
    c1, c2 = st.columns(2)
    for col, nome_casa in [(c1, "Câmara"), (c2, "Senado")]:
        base = df[df["casa"] == nome_casa]
        col.markdown(f"**{nome_casa}** — composição por partido")
        col.bar_chart(base["partido"].value_counts().rename("cadeiras"), horizontal=True, height=420)
    st.markdown("**Classificação por partido** (parlamentares avaliados)")
    aval = df[df["metodo"] != "pendente"]
    if aval.empty:
        st.info("Nenhuma avaliação ainda.")
    else:
        st.dataframe(pd.crosstab(aval["partido"], aval["classificacao"], margins=True, margins_name="Total"),
                     width="stretch")

with aba_agenda:
    st.caption(f"Arquivo: eleicoes/agenda_abes.json · versão {agenda.get('versao')} — {agenda.get('observacao', '')}")
    for t in agenda["temas"]:
        with st.expander(f"{t['nome']} (peso {t.get('peso', 1)})"):
            st.markdown(f"**Posição ABES:** {t['posicao_abes']}")
            if t.get("sinais_contrarios"):
                st.markdown(f"**Sinais contrários:** {t['sinais_contrarios']}")
            st.caption("Palavras-chave da triagem: " + ", ".join(t["palavras_chave"]))
    st.markdown(
        "**Como ler o IAT (Índice de Afinidade Tecnológica):** cada tema recebe de −2 a +2 com base em "
        "evidência atribuível ao parlamentar; a média ponderada pelos pesos é convertida para 0-100 (50 = neutro) "
        "e encolhida em direção ao neutro quando poucos temas têm sinal. ≥75 aliado · 60-75 potencial aliado · "
        "40-60 neutro · <40 atenção. A **triagem** (sem IA) apenas indica engajamento temático pelo histórico "
        "de proposições na Câmara — não mede a direção da posição."
    )
