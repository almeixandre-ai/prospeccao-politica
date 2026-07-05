"""Interface web Streamlit para prospecção política."""

from __future__ import annotations

import os
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import streamlit as st

# Carregar secrets do Streamlit Cloud (sobrescreve .env se existir)
def _load_st_secrets():
    try:
        for key in ("ANTHROPIC_API_KEY", "NOTION_TOKEN", "NOTION_DATABASE_ID", "NEWSAPI_KEY"):
            val = st.secrets.get(key)
            if val:
                os.environ[key] = val
    except Exception:
        pass

_load_st_secrets()

# ── Configuração da página ───────────────────────────────────────────────────

st.set_page_config(
    page_title="Prospecção Política",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS customizado ──────────────────────────────────────────────────────────

st.markdown("""
<style>
    .main-header {
        font-size: 2rem;
        font-weight: 700;
        color: #1B2A4A;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1rem;
        color: #5A6A7A;
        margin-bottom: 2rem;
    }
    .metric-card {
        background: #F8F9FB;
        border-radius: 12px;
        padding: 1.2rem;
        border-left: 4px solid #2C5F8A;
    }
    .zona-critica   { background: #C0392B; color: white; padding: 6px 16px; border-radius: 6px; font-weight: 700; }
    .zona-atencao   { background: #E67E22; color: white; padding: 6px 16px; border-radius: 6px; font-weight: 700; }
    .zona-monit     { background: #F1C40F; color: #333;  padding: 6px 16px; border-radius: 6px; font-weight: 700; }
    .zona-oport     { background: #27AE60; color: white; padding: 6px 16px; border-radius: 6px; font-weight: 700; }
    .stProgress > div > div > div > div { background: #2C5F8A; }
</style>
""", unsafe_allow_html=True)

# ── Constantes ───────────────────────────────────────────────────────────────

ZONA_CSS = {
    "Crítica": "zona-critica",
    "Atenção": "zona-atencao",
    "Monitoramento": "zona-monit",
    "Oportunidade": "zona-oport",
}

ZONA_COLOR = {
    "Crítica": "#C0392B",
    "Atenção": "#E67E22",
    "Monitoramento": "#F1C40F",
    "Oportunidade": "#27AE60",
}

DIMENSAO_LABELS = {
    "risco_processual": "Processual",
    "risco_coalicao": "Coalizão",
    "risco_agenda": "Agenda",
    "risco_atores": "Atores-Chave",
    "risco_exogeno": "Exógeno",
}

HORIZONTE_LABEL = {
    "imediato": "⚡ Imediato (0-30 dias)",
    "medio_prazo": "📅 Médio Prazo (1-6 meses)",
    "estrutural": "🏗️ Estrutural (6+ meses)",
}


# ── Funções de parsing ──────────────────────────────────────────────────────

def parse_pl(valor: str) -> tuple[str, int, int]:
    valor = valor.strip()
    partes = valor.split()
    if len(partes) == 2:
        sigla = partes[0].upper()
        num_ano = partes[1]
    elif len(partes) == 1:
        sigla = "PL"
        num_ano = partes[0]
    else:
        raise ValueError(f"Formato inválido: '{valor}'")

    if "/" not in num_ano:
        raise ValueError(f"Informe número/ano (ex: 2338/2023)")

    numero_str, ano_str = num_ano.split("/", 1)
    return sigla, int(numero_str), int(ano_str)


# ── Renderização da Matriz de Risco ─────────────────────────────────────────

def render_matriz_risco(avaliacao, analise):
    """Renderiza a matriz 5×5 de risco político como HTML."""

    pontuacoes = [
        avaliacao.risco_processual.nota,
        avaliacao.risco_coalicao.nota,
        avaliacao.risco_agenda.nota,
        avaliacao.risco_atores.nota,
        avaliacao.risco_exogeno.nota,
    ]
    avg = sum(pontuacoes) / len(pontuacoes)
    prop_impact = round(max(pontuacoes))
    prop_prob = round(avg)

    def zone_color(impact: int, prob: int) -> str:
        score = (impact + prob) / 2
        if score >= 4.0:
            return "#C0392B"
        if score >= 3.0:
            return "#E67E22"
        if score >= 2.0:
            return "#F1C40F"
        return "#27AE60"

    html = """
    <table style="border-collapse:collapse; margin:auto; font-family:Calibri,sans-serif;">
      <tr>
        <td style="background:#1B2A4A;color:white;padding:8px 12px;font-size:11px;text-align:center;
                    border:1px solid #ccc;font-weight:600;">Impacto ↓ / Prob →</td>
    """
    for c in range(1, 6):
        html += f'<td style="background:#1B2A4A;color:white;padding:8px 14px;text-align:center;border:1px solid #ccc;font-weight:600;">{c}</td>'
    html += "</tr>"

    for r in range(1, 6):
        impact = 6 - r
        html += "<tr>"
        html += f'<td style="background:#1B2A4A;color:white;padding:8px 14px;text-align:center;border:1px solid #ccc;font-weight:600;">{impact}</td>'
        for prob in range(1, 6):
            bg = zone_color(impact, prob)
            is_pos = impact == prop_impact and prob == prop_prob
            marker = "★" if is_pos else ""
            border = "3px solid #1B2A4A" if is_pos else "1px solid rgba(255,255,255,0.3)"
            font_size = "20px" if is_pos else "14px"
            html += (
                f'<td style="background:{bg};color:white;padding:10px 14px;text-align:center;'
                f'border:{border};font-size:{font_size};font-weight:700;">{marker}</td>'
            )
        html += "</tr>"

    html += "</table>"

    # Legenda
    html += """
    <div style="display:flex;gap:16px;justify-content:center;margin-top:12px;font-size:13px;font-family:Calibri,sans-serif;">
      <span>★ Posição atual</span>
      <span style="color:#C0392B;">■ Crítica (≥4.0)</span>
      <span style="color:#E67E22;">■ Atenção (≥3.0)</span>
      <span style="color:#F1C40F;">■ Monitoramento (≥2.0)</span>
      <span style="color:#27AE60;">■ Oportunidade (&lt;2.0)</span>
    </div>
    """
    return html


# ── Sidebar: formulário ─────────────────────────────────────────────────────

with st.sidebar:
    st.markdown('<p class="main-header">🏛️ Prospecção Política</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Análise de risco legislativo</p>', unsafe_allow_html=True)

    st.divider()

    pl_input = st.text_input(
        "Proposição",
        placeholder="2338/2023 ou PEC 45/2019",
        help="Formatos aceitos: NUMERO/ANO ou SIGLA NUMERO/ANO",
    )

    casa = st.selectbox("Casa Legislativa", ["camara", "senado"], format_func=lambda x: x.capitalize())

    ator = st.text_input("Ator Focal", placeholder="Nome da organização")

    logo_file = st.file_uploader("Logotipo (opcional)", type=["png", "jpg", "jpeg"])

    st.divider()

    api_key_input = st.text_input(
        "Chave API Anthropic",
        type="password",
        placeholder="sk-ant-...",
        help="Necessária para as etapas de análise com Claude",
        value=os.environ.get("ANTHROPIC_API_KEY", ""),
    )

    st.divider()

    run_button = st.button("🚀 Executar Análise", type="primary", use_container_width=True)


# ── Pipeline principal ──────────────────────────────────────────────────────

if run_button:
    # Validação
    errors = []
    if not pl_input:
        errors.append("Informe a proposição.")
    if not ator:
        errors.append("Informe o ator focal.")
    if not api_key_input:
        errors.append("Informe a chave API Anthropic na barra lateral.")

    if errors:
        for e in errors:
            st.error(e)
        st.stop()

    try:
        sigla, numero, ano = parse_pl(pl_input)
    except ValueError as e:
        st.error(str(e))
        st.stop()

    # Salvar logo temporário se fornecido
    logo_path = None
    if logo_file:
        logo_path = Path("output") / f"_logo_tmp.{logo_file.name.split('.')[-1]}"
        logo_path.parent.mkdir(parents=True, exist_ok=True)
        logo_path.write_bytes(logo_file.read())
        logo_path = str(logo_path)

    st.markdown(f"### Analisando **{sigla} {numero}/{ano}** — {casa.capitalize()}")

    progress = st.progress(0, text="Iniciando pipeline...")
    status_container = st.container()

    # ── Etapa 1: Coleta ──────────────────────────────────────────────────

    with status_container:
        with st.status("📡 Coletando dados da proposição...", expanded=True) as s1:
            try:
                if casa == "camara":
                    from coleta.api_camara import buscar_id, buscar_proposicao as buscar_camara

                    st.write("Buscando ID na API da Câmara...")
                    id_prop = buscar_id(sigla, numero, ano)
                    st.write(f"ID encontrado: `{id_prop}`")

                    st.write("Consultando detalhes e tramitações...")
                    dados = buscar_camara(id_prop)
                else:
                    from coleta.api_senado import buscar_proposicao as buscar_senado

                    st.write("Consultando API do Senado...")
                    dados = buscar_senado(sigla, numero, ano)

                st.write(f"**Situação:** {dados.get('situacao_atual', '—')}")
                s1.update(label="✅ Coleta concluída", state="complete")
            except Exception as e:
                s1.update(label="❌ Erro na coleta", state="error")
                st.error(f"Falha ao coletar dados: {e}")
                st.stop()

    progress.progress(25, text="Coleta concluída — iniciando avaliação de risco...")

    # ── Etapa 2: Avaliação de Risco ──────────────────────────────────────

    with status_container:
        with st.status("🧠 Avaliando risco político via Claude...", expanded=True) as s2:
            try:
                from analise.avaliador_risco import avaliar_risco

                st.write("Enviando dados para análise com Claude Sonnet 4.6...")
                avaliacao = avaliar_risco(dados, api_key=api_key_input)

                st.write(f"**Score consolidado:** {avaliacao.score_consolidado:.2f}/5.0")
                for dim_key, dim_label in DIMENSAO_LABELS.items():
                    dim = getattr(avaliacao, dim_key)
                    st.write(f"  {dim_label}: {dim.nota}/5 (confiança: {dim.confianca.value})")

                s2.update(label="✅ Avaliação concluída", state="complete")
            except Exception as e:
                s2.update(label="❌ Erro na avaliação", state="error")
                st.error(f"Falha na avaliação de risco: {e}")
                st.stop()

    progress.progress(50, text="Avaliação concluída — gerando cenários...")

    # ── Etapa 3: Cenários ────────────────────────────────────────────────

    with status_container:
        with st.status("🔮 Gerando cenários e recomendações...", expanded=True) as s3:
            try:
                from analise.cenarios import gerar_cenarios

                st.write("Gerando cenários, ações e KPIs com Claude Sonnet 4.6...")
                analise = gerar_cenarios(avaliacao, dados, api_key=api_key_input)

                st.write(f"**Score consolidado:** {analise.score_consolidado:.2f}")
                st.write(f"**Zona MRP:** {analise.zona_mrp}")
                for c in analise.cenarios:
                    st.write(f"  Cenário {c.nome.capitalize()}: {c.probabilidade:.0%}")

                s3.update(label="✅ Cenários concluídos", state="complete")
            except Exception as e:
                s3.update(label="❌ Erro nos cenários", state="error")
                st.error(f"Falha na geração de cenários: {e}")
                st.stop()

    progress.progress(75, text="Cenários concluídos — gerando relatório...")

    # ── Etapa 4: Relatório ───────────────────────────────────────────────

    with status_container:
        with st.status("📄 Gerando relatório .docx...", expanded=False) as s4:
            try:
                from relatorio.gerador import gerar_relatorio

                hoje = date.today().strftime("%Y-%m-%d")
                filename = f"relatorio_{sigla}{numero}_{ano}_{hoje}.docx"
                output_path = Path("output") / filename

                path = gerar_relatorio(
                    proposicao=dados,
                    avaliacao=avaliacao,
                    analise=analise,
                    ator_focal=ator,
                    output_path=output_path,
                    logo_path=logo_path,
                )

                s4.update(label="✅ Relatório gerado", state="complete")
            except Exception as e:
                s4.update(label="❌ Erro no relatório", state="error")
                st.error(f"Falha ao gerar relatório: {e}")
                st.stop()

    progress.progress(100, text="Pipeline concluído!")

    # Salvar resultados no session_state para persistir após reruns
    st.session_state["resultado"] = {
        "dados": dados,
        "avaliacao": avaliacao,
        "analise": analise,
        "path": path,
        "filename": filename,
        "sigla": sigla,
        "numero": numero,
        "ano": ano,
    }

# ── Exibição dos resultados ─────────────────────────────────────────────────

if "resultado" in st.session_state:
    r = st.session_state["resultado"]
    dados = r["dados"]
    avaliacao = r["avaliacao"]
    analise = r["analise"]
    path = r["path"]

    st.divider()
    st.markdown(f"## Resultados — {r['sigla']} {r['numero']}/{r['ano']}")

    # ── Métricas de resumo ───────────────────────────────────────────────

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Score Consolidado", f"{analise.score_consolidado:.2f} / 5.0")
    with col2:
        zona = analise.zona_mrp
        css_class = ZONA_CSS.get(zona, "zona-monit")
        st.markdown(f"**Zona MRP**")
        st.markdown(f'<span class="{css_class}">{zona}</span>', unsafe_allow_html=True)
    with col3:
        st.metric("Score Consolidado", f"{avaliacao.score_consolidado:.2f} / 5.0")
    with col4:
        st.metric("Situação", dados.get("situacao_atual", "—"))

    # ── Tabs ─────────────────────────────────────────────────────────────

    tab_matriz, tab_dimensoes, tab_cenarios, tab_acoes, tab_kpis = st.tabs([
        "🎯 Matriz de Risco",
        "📊 Dimensões",
        "🔮 Cenários",
        "📋 Plano de Ações",
        "📈 KPIs",
    ])

    # identificação da proposição para o Notion
    _proposicao_id = f"{r['sigla']} {r['numero']}/{r['ano']}"

    # ── Tab: Matriz de Risco ─────────────────────────────────────────────

    with tab_matriz:
        st.markdown("### Matriz de Risco Político (MRP)")
        st.markdown(render_matriz_risco(avaliacao, analise), unsafe_allow_html=True)

        st.markdown("---")
        st.markdown(f"**Zona de risco:** {avaliacao.zona_risco} (score {avaliacao.score_consolidado:.2f}/5.0)")

    # ── Tab: Dimensões ───────────────────────────────────────────────────

    with tab_dimensoes:
        st.markdown("### Avaliação das Cinco Dimensões")

        for dim_key, dim_label in DIMENSAO_LABELS.items():
            dim = getattr(avaliacao, dim_key)
            with st.expander(f"{dim_label} — {dim.nota}/5 (confiança: {dim.confianca.value})", expanded=False):
                cols = st.columns([1, 4])
                with cols[0]:
                    color = "#27AE60" if dim.nota <= 2 else "#E67E22" if dim.nota <= 3 else "#C0392B"
                    st.markdown(
                        f'<div style="font-size:48px;font-weight:700;color:{color};text-align:center;">'
                        f'{dim.nota}</div>',
                        unsafe_allow_html=True,
                    )
                with cols[1]:
                    st.write(dim.justificativa)
                    st.caption(f"Confiança: {dim.confianca.value}")

    # ── Tab: Cenários ────────────────────────────────────────────────────

    with tab_cenarios:
        st.markdown("### Cenários Prospectivos")

        nome_emoji = {"base": "📌", "otimista": "🟢", "pessimista": "🔴"}
        nome_color = {"base": "#2C5F8A", "otimista": "#27AE60", "pessimista": "#C0392B"}

        for cenario in analise.cenarios:
            emoji = nome_emoji.get(cenario.nome, "📌")
            color = nome_color.get(cenario.nome, "#333")
            st.markdown(
                f'<h4 style="color:{color};">{emoji} Cenário {cenario.nome.capitalize()} '
                f'— {cenario.probabilidade:.0%}</h4>',
                unsafe_allow_html=True,
            )
            st.write(cenario.narrativa)
            if cenario.principais_gatilhos:
                st.markdown("**Principais gatilhos:**")
                for g in cenario.principais_gatilhos:
                    st.markdown(f"- {g}")
            st.divider()

    # ── Tab: Ações ───────────────────────────────────────────────────────

    with tab_acoes:
        st.markdown("### Plano de Ações Recomendadas")

        # Inicializar seleção de ações no session_state
        acoes_key = f"acoes_selecionadas_{_proposicao_id}"
        if acoes_key not in st.session_state:
            st.session_state[acoes_key] = {i: True for i in range(len(analise.acoes_recomendadas))}

        for h_key, h_label in HORIZONTE_LABEL.items():
            acoes_h = [(i, a) for i, a in enumerate(analise.acoes_recomendadas) if a.horizonte == h_key]
            if not acoes_h:
                continue

            st.markdown(f"#### {h_label}")

            for i, a in acoes_h:
                prio_emoji = {"alta": "🔴", "media": "🟡", "baixa": "🟢"}.get(a.prioridade, "⚪")
                col_chk, col_info = st.columns([1, 10])
                with col_chk:
                    st.session_state[acoes_key][i] = st.checkbox(
                        "", value=st.session_state[acoes_key].get(i, True),
                        key=f"acao_{_proposicao_id}_{i}",
                    )
                with col_info:
                    st.markdown(
                        f"**{prio_emoji} {a.acao}**  \n"
                        f"<small>Responsável: {a.responsavel_sugerido} &nbsp;|&nbsp; "
                        f"Prioridade: {a.prioridade.capitalize()}</small>",
                        unsafe_allow_html=True,
                    )
            st.markdown("")

        # ── Envio ao Notion ──────────────────────────────────────────────
        st.divider()
        st.markdown("#### 📤 Enviar para o Notion")

        notion_token = os.environ.get("NOTION_TOKEN", "")
        notion_db = os.environ.get("NOTION_DATABASE_ID", "")

        if not notion_token or not notion_db:
            st.warning("Credenciais do Notion não encontradas no `.env`. Configure `NOTION_TOKEN` e `NOTION_DATABASE_ID`.")
        else:
            acoes_selecionadas = [
                analise.acoes_recomendadas[i]
                for i, marcado in st.session_state[acoes_key].items()
                if marcado
            ]
            n_sel = len(acoes_selecionadas)

            col_btn, col_info = st.columns([2, 5])
            with col_btn:
                enviar = st.button(
                    f"📤 Enviar {n_sel} ação(ões) ao Notion",
                    type="primary",
                    use_container_width=True,
                    disabled=(n_sel == 0),
                )
            with col_info:
                if n_sel == 0:
                    st.caption("Selecione ao menos uma ação acima.")
                else:
                    st.caption(f"{n_sel} ação(ões) selecionada(s) para envio.")

            if enviar and acoes_selecionadas:
                from integracao.notion import enviar_acoes

                acoes_dict = [a.model_dump() for a in acoes_selecionadas]

                with st.spinner(f"Enviando {n_sel} ação(ões) ao Notion..."):
                    resultados = enviar_acoes(acoes_dict, _proposicao_id)

                sucesso = [r for r in resultados if r["sucesso"]]
                falha = [r for r in resultados if not r["sucesso"]]

                if sucesso:
                    st.success(f"✅ {len(sucesso)} ação(ões) enviada(s) ao Notion com sucesso!")
                    for res in sucesso:
                        st.markdown(f"- [{res['acao'][:60]}]({res['url']})")

                if falha:
                    st.error(f"❌ {len(falha)} ação(ões) com erro:")
                    for res in falha:
                        st.markdown(f"- **{res['acao'][:60]}**: {res['erro']}")

    # ── Tab: KPIs ────────────────────────────────────────────────────────

    with tab_kpis:
        st.markdown("### KPIs de Monitoramento")
        kpi_rows = []
        for kpi in analise.kpis:
            kpi_rows.append({
                "Indicador": kpi.indicador,
                "Fonte": kpi.fonte,
                "Frequência": kpi.frequencia,
            })
        st.table(kpi_rows)

    # ── Download ─────────────────────────────────────────────────────────

    st.divider()

    col_dl1, col_dl2, _ = st.columns([2, 2, 4])
    with col_dl1:
        with open(path, "rb") as f:
            st.download_button(
                label="📥 Baixar Relatório .docx",
                data=f.read(),
                file_name=r["filename"],
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                type="primary",
                use_container_width=True,
            )
    with col_dl2:
        st.markdown(f"<small>Arquivo: <code>{r['filename']}</code></small>", unsafe_allow_html=True)

elif not run_button:
    # Tela inicial
    st.markdown('<p class="main-header">🏛️ Prospecção Política Legislativa</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">Análise de risco de proposições legislativas com inteligência artificial</p>', unsafe_allow_html=True)

    st.info("👈 Preencha os campos na barra lateral e clique em **Executar Análise** para começar.")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("#### 📡 Coleta")
        st.markdown("Dados em tempo real das APIs da Câmara e do Senado.")

    with col2:
        st.markdown("#### 🧠 Análise IA")
        st.markdown("Avaliação de risco em 5 dimensões + cenários via Claude.")

    with col3:
        st.markdown("#### 📄 Relatório")
        st.markdown("Documento .docx profissional pronto para download.")
