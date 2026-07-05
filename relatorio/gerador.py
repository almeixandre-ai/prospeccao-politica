"""Gerador de relatório .docx — baseado no template visual ABES."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Optional

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from analise.avaliador_risco import AvaliacaoRisco
from analise.cenarios import AnaliseCompleta
from coleta.schemas import ProposicaoInfo

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "template_abes.docx"

CONFIANCA_LABEL = {"alto": "Alto", "medio": "Médio", "baixo": "Baixo"}
CENARIO_LABEL = {"base": "Base (mais provável)", "otimista": "Otimista", "pessimista": "Pessimista"}
ZONA_EMOJI = {"Crítica": "⛔", "Atenção": "⚠", "Monitoramento": "ℹ", "Oportunidade": "✅"}
HORIZONTE_LABEL = {
    "imediato": "Imediato (0–30 dias)",
    "medio_prazo": "Médio Prazo (1–6 meses)",
    "estrutural": "Estrutural (6+ meses)",
}
DIMENSAO_KEYS = ["risco_processual", "risco_coalicao", "risco_agenda", "risco_atores", "risco_exogeno"]
DIMENSAO_LABELS = {
    "risco_processual": "Processual", "risco_coalicao": "Coalizão",
    "risco_agenda": "Agenda", "risco_atores": "Atores-Chave",
    "risco_exogeno": "Exógeno",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _set_cell_text(cell, text: str) -> None:
    """Substitui o texto de uma célula preservando a formatação do primeiro run."""
    for p in cell.paragraphs:
        if p.runs:
            p.runs[0].text = text
            for r in p.runs[1:]:
                r.text = ""
            return
    cell.paragraphs[0].text = text


def _set_para_run(paragraph, index: int, text: str) -> None:
    """Substitui o texto de um run específico dentro de um parágrafo."""
    runs = paragraph.runs
    if index < len(runs):
        runs[index].text = text


def _clear_cell(cell) -> None:
    for p in cell.paragraphs:
        for r in p.runs:
            r.text = ""


def _clone_row(table, source_row_idx: int):
    """Clona uma row da tabela (incluindo formatação) e a insere logo após."""
    source = table.rows[source_row_idx]
    new_tr = deepcopy(source._tr)
    source._tr.addnext(new_tr)
    return new_tr


def _add_row_from_template(table, template_row_idx: int, values: list[str]):
    """Adiciona uma nova linha copiando o estilo de template_row_idx."""
    src_row = table.rows[template_row_idx]
    new_tr = deepcopy(src_row._tr)
    table._tbl.append(new_tr)
    # Preencher as células
    row_cells = new_tr.findall(qn("w:tc"))
    for i, val in enumerate(values):
        if i < len(row_cells):
            # Limpar e preencher
            for p in row_cells[i].findall(qn("w:p")):
                for r in p.findall(qn("w:r")):
                    for t in r.findall(qn("w:t")):
                        t.text = ""
            # Setar no primeiro run do primeiro parágrafo
            first_p = row_cells[i].findall(qn("w:p"))
            if first_p:
                runs = first_p[0].findall(qn("w:r"))
                if runs:
                    ts = runs[0].findall(qn("w:t"))
                    if ts:
                        ts[0].text = val
                        ts[0].set(qn("xml:space"), "preserve")
    return new_tr


def _set_shading(cell, hex_color: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    # Remover shading existente
    for old in tc_pr.findall(qn("w:shd")):
        tc_pr.remove(old)
    shading = tc_pr.makeelement(qn("w:shd"), {
        qn("w:val"): "clear", qn("w:color"): "auto", qn("w:fill"): hex_color,
    })
    tc_pr.append(shading)


# ── Preenchimento de cada tabela ─────────────────────────────────────────────

def _fill_banner(table, prop: ProposicaoInfo, ator: str,
                 avaliacao: AvaliacaoRisco, analise: AnaliseCompleta) -> None:
    """Tabela 0: Banner com título, zona e score."""
    left = table.rows[0].cells[0]
    # P0: título (mantém)
    # P1: "PL X/Y · ATOR · DATA"
    _set_para_run(left.paragraphs[1], 0,
                  f"{prop.tipo_sigla} {prop.numero}/{prop.ano}  ·  {ator}  ·  {date.today().strftime('%d/%m/%Y')}")
    # P2: ementa
    ementa_short = prop.ementa[:120] + ("..." if len(prop.ementa) > 120 else "")
    _set_para_run(left.paragraphs[2], 0, ementa_short)

    right = table.rows[0].cells[1]
    emoji = ZONA_EMOJI.get(analise.zona_mrp, "⚠")
    # P0: zona
    _set_para_run(right.paragraphs[0], 0, f"{emoji} {analise.zona_mrp.upper()}")
    # P1: "Score MRP" (mantém)
    # P2: score
    _set_para_run(right.paragraphs[2], 0, f"{analise.score_consolidado:.2f} / 5,0")


def _fill_summary_strip(table, prop: ProposicaoInfo, analise: AnaliseCompleta) -> None:
    """Tabela 1: Faixa de resumo rápido."""
    cenario_base = next((c for c in analise.cenarios if c.nome == "base"), None)

    _set_cell_text(table.rows[0].cells[0], f"Situação: {prop.situacao_atual}")
    _set_cell_text(table.rows[0].cells[1], f"Relator: {prop.relator_designado or 'Não designado'}")
    _set_cell_text(table.rows[0].cells[2], f"Regime: {prop.regime_tramitacao or 'Não informado'}")
    if cenario_base:
        _set_cell_text(table.rows[0].cells[3], f"Cenário base: {cenario_base.probabilidade:.0%}")


def _fill_mensagem_principal(table, avaliacao: AvaliacaoRisco,
                              analise: AnaliseCompleta) -> None:
    """Tabela 2: Mensagem principal + métricas."""
    left = table.rows[0].cells[0]
    # P0: "MENSAGEM PRINCIPAL" (mantém)
    # P1: resumo
    resumo = (
        avaliacao.resumo_executivo
        if hasattr(avaliacao, "resumo_executivo")
        else f"Zona de risco: {avaliacao.zona_risco} (score {avaliacao.score_consolidado:.2f}/5.0)"
    )
    _set_para_run(left.paragraphs[1], 0, resumo)

    right = table.rows[0].cells[1]
    # P0: score
    _set_para_run(right.paragraphs[0], 0, f"{analise.score_consolidado:.2f}")
    # P1: "Score MRP / 5,0" (mantém)
    # P2: probabilidade cenário base
    cenario_base = next((c for c in analise.cenarios if c.nome == "base"), None)
    if cenario_base:
        _set_para_run(right.paragraphs[2], 0, f"{cenario_base.probabilidade:.0%}")
    # P3: "Cenário base" (mantém)
    # P4: nível de risco
    pontuacoes = [getattr(avaliacao, k).nota for k in DIMENSAO_KEYS]
    max_score = max(pontuacoes)
    nivel = "ALTO" if max_score >= 4 else "MÉDIO" if max_score >= 3 else "BAIXO"
    _set_para_run(right.paragraphs[4], 0, nivel)
    # P5: descrição risco
    _set_para_run(right.paragraphs[5], 0, "Risco máximo nas dimensões")


def _fill_termo_referencia(table, prop: ProposicaoInfo) -> None:
    """Tabela 3: Termo de referência (2x4)."""
    _set_cell_text(table.rows[1].cells[0], f"{prop.tipo_sigla} {prop.numero}/{prop.ano}")
    _set_cell_text(table.rows[1].cells[1], prop.situacao_atual)
    evento = f"{prop.ultimo_evento or 'N/A'} ({prop.ultimo_evento_data or 'N/A'})"
    _set_cell_text(table.rows[1].cells[2], evento)
    _set_cell_text(table.rows[1].cells[3], prop.relator_designado or "Não designado")


def _fill_dimensoes(table, avaliacao: AvaliacaoRisco) -> None:
    """Tabela 4: Dimensões de risco (6x4 — header + 5 dimensões)."""
    for i, key in enumerate(DIMENSAO_KEYS):
        row = table.rows[i + 1]
        dim = getattr(avaliacao, key)
        label = DIMENSAO_LABELS.get(key, key.replace("risco_", "").capitalize())
        _set_cell_text(row.cells[0], label)
        _set_cell_text(row.cells[1], f"{dim.nota}/5")
        conf = dim.confianca.value if hasattr(dim.confianca, "value") else str(dim.confianca)
        _set_cell_text(row.cells[2], CONFIANCA_LABEL.get(conf, conf))
        _set_cell_text(row.cells[3], dim.justificativa)


def _fill_cenarios(table, analise: AnaliseCompleta) -> None:
    """Tabela 5: Cenários (3x2)."""
    for i, cenario in enumerate(analise.cenarios):
        if i >= len(table.rows):
            break
        row = table.rows[i]
        left = row.cells[0]
        right = row.cells[1]

        label = CENARIO_LABEL.get(cenario.nome, cenario.nome.capitalize())

        # Esquerda: P0 = probabilidade, P1 = nome
        _set_para_run(left.paragraphs[0], 0, f"{cenario.probabilidade:.0%}")
        _set_para_run(left.paragraphs[1], 0, label)

        # Direita: P0 = narrativa, P1 = gatilhos
        _set_para_run(right.paragraphs[0], 0, cenario.narrativa)
        gatilhos_text = " · ".join(cenario.principais_gatilhos) if cenario.principais_gatilhos else ""
        if len(right.paragraphs) > 1 and right.paragraphs[1].runs:
            # P1 tem 2 runs: "Gatilhos: " (bold) + texto
            runs = right.paragraphs[1].runs
            if len(runs) >= 2:
                runs[0].text = "Gatilhos: "
                runs[1].text = gatilhos_text
            elif len(runs) == 1:
                runs[0].text = f"Gatilhos: {gatilhos_text}"


def _fill_acoes(table, analise: AnaliseCompleta) -> None:
    """Tabela 6: Plano de ações. Remove linhas do template e reconstrói."""
    # Manter header (row 0) e templates de separador (row 1) e ação (row 2)
    # Guardar referências XML dos templates antes de limpar
    tbl = table._tbl
    all_trs = tbl.findall(qn("w:tr"))

    if len(all_trs) < 3:
        return

    header_tr = all_trs[0]
    separator_tr = deepcopy(all_trs[1])
    action_tr = deepcopy(all_trs[2])

    # Remover todas as linhas exceto o header
    for tr in all_trs[1:]:
        tbl.remove(tr)

    # Adicionar ações por horizonte
    for h_key, h_label in HORIZONTE_LABEL.items():
        acoes = [a for a in analise.acoes_recomendadas if a.horizonte == h_key]
        if not acoes:
            continue

        # Inserir separador de horizonte
        sep = deepcopy(separator_tr)
        tbl.append(sep)
        for tc in sep.findall(qn("w:tc")):
            for p in tc.findall(qn("w:p")):
                for r in p.findall(qn("w:r")):
                    for t in r.findall(qn("w:t")):
                        t.text = h_label
                        t.set(qn("xml:space"), "preserve")

        # Inserir cada ação
        for acao in acoes:
            row_tr = deepcopy(action_tr)
            tbl.append(row_tr)
            tcs = row_tr.findall(qn("w:tc"))
            vals = [acao.acao, acao.responsavel_sugerido, acao.prioridade.capitalize()]
            for ci, val in enumerate(vals):
                if ci < len(tcs):
                    for p in tcs[ci].findall(qn("w:p")):
                        for r in p.findall(qn("w:r")):
                            for t in r.findall(qn("w:t")):
                                t.text = val
                                t.set(qn("xml:space"), "preserve")
                            break
                        break

            # Ajustar cor da prioridade
            if len(tcs) >= 3:
                prio_cell = tcs[2]
                tc_pr = prio_cell.find(qn("w:tcPr"))
                if tc_pr is not None:
                    for old_shd in tc_pr.findall(qn("w:shd")):
                        tc_pr.remove(old_shd)
                    prio_colors = {"Alta": "F0565C", "Media": "FFB71A", "Baixa": "0E6BEA"}
                    fill = prio_colors.get(acao.prioridade.capitalize(), "0E6BEA")
                    shd = tc_pr.makeelement(qn("w:shd"), {
                        qn("w:val"): "clear", qn("w:color"): "auto", qn("w:fill"): fill,
                    })
                    tc_pr.append(shd)


def _fill_kpis(table, analise: AnaliseCompleta) -> None:
    """Tabela 7: KPIs. Remove linhas do template e reconstrói."""
    tbl = table._tbl
    all_trs = tbl.findall(qn("w:tr"))

    if len(all_trs) < 2:
        return

    header_tr = all_trs[0]
    template_tr = deepcopy(all_trs[1])

    # Remover todas as linhas exceto header
    for tr in all_trs[1:]:
        tbl.remove(tr)

    freq_colors = {
        "diária": "F0565C", "semanal": "F0565C",
        "quinzenal": "FFB71A", "mensal": "0E6BEA",
    }

    for kpi in analise.kpis:
        row_tr = deepcopy(template_tr)
        tbl.append(row_tr)
        tcs = row_tr.findall(qn("w:tc"))
        vals = [kpi.indicador, kpi.fonte, kpi.frequencia]

        for ci, val in enumerate(vals):
            if ci < len(tcs):
                for p in tcs[ci].findall(qn("w:p")):
                    for r in p.findall(qn("w:r")):
                        for t in r.findall(qn("w:t")):
                            t.text = val
                            t.set(qn("xml:space"), "preserve")
                        break
                    break

        # Cor da frequência
        if len(tcs) >= 3:
            freq_cell = tcs[2]
            tc_pr = freq_cell.find(qn("w:tcPr"))
            if tc_pr is not None:
                for old_shd in tc_pr.findall(qn("w:shd")):
                    tc_pr.remove(old_shd)
                fill = freq_colors.get(kpi.frequencia.lower(), "0E6BEA")
                shd = tc_pr.makeelement(qn("w:shd"), {
                    qn("w:val"): "clear", qn("w:color"): "auto", qn("w:fill"): fill,
                })
                tc_pr.append(shd)


def _fill_footer(doc: Document, prop: ProposicaoInfo, ator: str) -> None:
    """Parágrafo 20: rodapé."""
    for p in doc.paragraphs:
        if "Prospecção Política" in p.text and "Gerado em" in p.text:
            if p.runs:
                p.runs[0].text = (
                    f"{ator}  ·  {prop.tipo_sigla} {prop.numero}/{prop.ano}  ·  "
                    f"Prospecção Política  ·  Gerado em {date.today().strftime('%d/%m/%Y')}"
                )
                for r in p.runs[1:]:
                    r.text = ""
            break


def _fill_section_headings(doc: Document, prop: ProposicaoInfo) -> None:
    """Atualiza títulos de seção (mantém numeração e formatação)."""
    # Os títulos já estão no template, não precisam ser alterados
    pass


# ── Função principal ─────────────────────────────────────────────────────────

def gerar_relatorio(
    proposicao: ProposicaoInfo | dict,
    avaliacao: AvaliacaoRisco | dict,
    analise: AnaliseCompleta | dict,
    ator_focal: str,
    output_path: str | Path,
    logo_path: Optional[str] = None,
) -> Path:
    """Gera o relatório .docx preenchendo o template ABES."""
    if isinstance(proposicao, dict):
        proposicao = ProposicaoInfo.model_validate(proposicao)
    if isinstance(avaliacao, dict):
        avaliacao = AvaliacaoRisco.model_validate(avaliacao)
    if isinstance(analise, dict):
        analise = AnaliseCompleta.model_validate(analise)

    doc = Document(str(TEMPLATE))
    tables = doc.tables

    _fill_banner(tables[0], proposicao, ator_focal, avaliacao, analise)
    _fill_summary_strip(tables[1], proposicao, analise)
    _fill_mensagem_principal(tables[2], avaliacao, analise)
    _fill_termo_referencia(tables[3], proposicao)
    _fill_dimensoes(tables[4], avaliacao)
    _fill_cenarios(tables[5], analise)
    _fill_acoes(tables[6], analise)
    _fill_kpis(tables[7], analise)
    _fill_footer(doc, proposicao, ator_focal)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))

    return output_path
