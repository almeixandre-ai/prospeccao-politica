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
from eleicoes.interesse import AnalisadorInteresse
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
c4.metric("Com interesse prévio na pauta", int((df["iip"] > 0).sum()),
          help="Reeleitos ou que mudam de casa, com algum sinal de interesse (IIP > 0)")
c5.metric("Prioridade A + B", int(df["prioridade"].str.startswith(("A", "B")).sum()))

for a in comp.alertas:
    st.warning(a)
st.caption(f"Coleta: {comp.data_coleta} · totalização TSE: "
           f"{'100% em todas as UFs' if set(comp.totalizacao_tse.values()) == {'100,00'} else comp.totalizacao_tse}")

# ── Filtros ──────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("Prioridade de agenda")
    so_interesse = st.checkbox("Somente com interesse prévio na pauta ABES", value=True,
                               help="Parlamentares com mandato atual (reeleitos, que permanecem ou mudam de casa) "
                                    "e algum sinal de interesse: autoria, relatoria, comissão ou frente temática")
    faixas = st.multiselect("Faixa de prioridade", sorted(df["prioridade"].unique()))
    iip_min = st.slider("IIP mínimo", 0, 100, 0)
    trajetorias = st.multiselect("Trajetória", sorted(df["trajetoria"].unique()))
    st.divider()
    st.header("Filtros")
    casa = st.multiselect("Casa", ["Câmara", "Senado"], default=["Câmara", "Senado"])
    ufs = st.multiselect("UF", sorted(df["uf"].unique()))
    partidos = st.multiselect("Partido", sorted(df["partido"].dropna().unique()))
    classes = st.multiselect("Classificação", list(CLASSE_COR))
    busca = st.text_input("Buscar nome")
    st.divider()
    st.subheader("Aderência por tema")
    st.caption("Notas −2 a +2 vêm da análise com IA")
    temas_ader = st.multiselect("Temas prioritários", list(nomes_temas), format_func=nomes_temas.get)
    nota_min = st.select_slider("Nota mínima em cada tema", options=[-2, -1, 0, 1, 2], value=1,
                                disabled=not temas_ader)
    iat_min = st.slider("IAT mínimo", 0, 100, 0)

f = df[df["casa"].isin(casa)]
if ufs:
    f = f[f["uf"].isin(ufs)]
if partidos:
    f = f[f["partido"].isin(partidos)]
if classes:
    f = f[f["classificacao"].isin(classes)]
if temas_ader or iat_min:
    f = f[f["metodo"] == "ia"]
for t in temas_ader:
    f = f[f[f"tema_{t}"] >= nota_min]
if iat_min:
    f = f[f["iat"] >= iat_min]
if so_interesse:
    f = f[f["iip"] > 0]
if faixas:
    f = f[f["prioridade"].isin(faixas)]
if iip_min:
    f = f[f["iip"] >= iip_min]
if trajetorias:
    f = f[f["trajetoria"].isin(trajetorias)]
if busca:
    f = f[f["nome"].str.contains(busca, case=False) | f["nome_completo"].fillna("").str.contains(busca, case=False)]
f = f.sort_values(["iip", "iat", "votos"], ascending=False, na_position="last")

aba_lista, aba_bancadas, aba_agenda = st.tabs(["Parlamentares", "Bancadas", "Agenda ABES"])

with aba_lista:
    st.caption(f"{len(f)} parlamentares no filtro")
    colunas_temas = [c for c in f.columns if c.startswith("tema_")]
    sel = st.dataframe(
        f[["prioridade", "iip", "casa", "uf", "nome", "partido", "trajetoria", "n_proposicoes", "n_relatorias",
           "iip_comissoes", "iip_frentes", "classificacao", "iat", *colunas_temas]]
        .rename(columns={c: nomes_temas.get(c[5:], c) for c in colunas_temas}),
        hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
        column_config={
            "prioridade": st.column_config.TextColumn("Prioridade"),
            "iip": st.column_config.ProgressColumn("IIP (interesse)", min_value=0, max_value=100, format="%.0f"),
            "trajetoria": st.column_config.TextColumn("Trajetória"),
            "n_proposicoes": st.column_config.NumberColumn("Proposições", help="PL/PLP/PEC nos temas ABES (2023-2026)"),
            "n_relatorias": st.column_config.NumberColumn("Relatorias", help="Só Senado"),
            "iip_comissoes": st.column_config.ProgressColumn("Comissões", min_value=0, max_value=1, format="percent"),
            "iip_frentes": st.column_config.ProgressColumn("Frentes", min_value=0, max_value=1, format="percent"),
            "classificacao": st.column_config.TextColumn("Afinidade (IA)"),
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

        itr = AnalisadorInteresse.carregar(p)
        if itr:
            st.markdown(f"#### 🎯 Interesse na pauta ABES — **{itr.prioridade}** · IIP {itr.iip:.0f}/100")
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Autoria", f"{itr.componentes['autoria']:.0%}", help=f"{len(itr.proposicoes)} proposições nos temas")
            k2.metric("Relatoria", f"{itr.componentes['relatoria']:.0%}" if "senado" in itr.fontes else "n/d",
                      help=f"{len(itr.relatorias)} relatorias (Senado)")
            k3.metric("Comissões", f"{itr.componentes['comissoes']:.0%}", help=f"{len(itr.orgaos)} órgãos temáticos")
            k4.metric("Frentes", f"{itr.componentes['frentes']:.0%}", help=f"{len(itr.frentes)} frentes")
            for titulo_s, itens in [("📜 Proposições de autoria", itr.proposicoes), ("🧾 Relatorias", itr.relatorias),
                                    ("🏛️ Comissões e órgãos temáticos", itr.orgaos), ("🤝 Frentes parlamentares", itr.frentes)]:
                if itens:
                    with st.expander(f"{titulo_s} ({len(itens)})"):
                        for it in itens:
                            st.markdown(f"- {it}")
            st.markdown("#### 🤖 Afinidade com as posições ABES")

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
