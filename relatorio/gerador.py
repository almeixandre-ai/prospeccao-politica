"""Gerador de relatório .docx — padrão visual institucional ABES."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Optional

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor, Emu, Inches

from analise.avaliador_risco import AvaliacaoRisco
from analise.cenarios import AnaliseCompleta
from coleta.schemas import ProposicaoInfo

# ── Caminhos ──────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
RELATORIO_DIR = Path(__file__).resolve().parent

# ── Cores institucionais ABES ─────────────────────────────────────────────────

PRETO = "231F20"
DOURADO = "C99A3F"
CINZA_RODAPE = "404040"
CINZA_LINHA = "999999"
BRANCO = "FFFFFF"
CINZA_BG = "F5F5F5"

# ── Constantes ────────────────────────────────────────────────────────────────

DIMENSAO_KEYS = ["risco_processual", "risco_coalicao", "risco_agenda", "risco_atores", "risco_exogeno"]
DIMENSAO_LABELS = {
    "risco_processual": "Processual", "risco_coalicao": "Coalizão",
    "risco_agenda": "Agenda", "risco_atores": "Atores-Chave", "risco_exogeno": "Exógeno",
}
CENARIO_LABEL = {"base": "Cenário Base", "otimista": "Cenário Otimista", "pessimista": "Cenário Pessimista"}
CENARIO_COR = {"base": "2C5F8A", "otimista": "2E7D32", "pessimista": "C0392B"}
HORIZONTE_LABEL = {
    "imediato": "Imediato (0–30 dias)",
    "medio_prazo": "Médio Prazo (1–6 meses)",
    "estrutural": "Estrutural (6+ meses)",
}
ZONA_COR = {"Crítica": "C0392B", "Atenção": "D9A61A", "Monitoramento": "2C5F8A", "Oportunidade": "2E7D32"}
PRIO_COR = {"alta": "C0392B", "media": "D9A61A", "baixa": "2E7D32"}


# ── Helpers XML / docx ────────────────────────────────────────────────────────

def _set_font(run, size_pt: float, bold=False, color=PRETO, font="Arial"):
    run.font.name = font
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    run.font.color.rgb = RGBColor.from_string(color)


def _para(doc_or_cell, text="", size=11, bold=False, color=PRETO,
          align=WD_ALIGN_PARAGRAPH.JUSTIFY, space_before=0, space_after=6) -> object:
    """Adiciona parágrafo com formatação ABES."""
    if hasattr(doc_or_cell, "add_paragraph"):
        p = doc_or_cell.add_paragraph()
    else:
        p = doc_or_cell.paragraphs[0] if doc_or_cell.paragraphs else doc_or_cell.add_paragraph()
    p.alignment = align
    pf = p.paragraph_format
    pf.space_before = Pt(space_before)
    pf.space_after = Pt(space_after)
    if text:
        run = p.add_run(text)
        _set_font(run, size, bold, color)
    return p


def _heading1(doc, text: str):
    """Título H1 — 14pt bold preto, linha dourada inferior."""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    pf = p.paragraph_format
    pf.space_before = Pt(14)
    pf.space_after = Pt(6)
    # Borda dourada inferior
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "12")
    bottom.set(qn("w:space"), "4")
    bottom.set(qn("w:color"), DOURADO)
    pBdr.append(bottom)
    pPr.append(pBdr)
    run = p.add_run(text)
    _set_font(run, 14, bold=True, color=PRETO)
    return p


def _heading2(doc, text: str):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run(text)
    _set_font(run, 12, bold=True, color=PRETO)
    return p


def _set_cell_bg(cell, hex_color: str):
    tcPr = cell._tc.get_or_add_tcPr()
    for s in tcPr.findall(qn("w:shd")):
        tcPr.remove(s)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def _set_cell_borders(cell, color="DDDDDD", size="4"):
    tcPr = cell._tc.get_or_add_tcPr()
    tcBorders = OxmlElement("w:tcBorders")
    for side in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), size)
        el.set(qn("w:color"), color)
        tcBorders.append(el)
    tcPr.append(tcBorders)


def _cell_text(cell, text: str, size=10, bold=False, color=PRETO,
               align=WD_ALIGN_PARAGRAPH.LEFT, wrap=True):
    for p in cell.paragraphs:
        for r in p.runs:
            r.text = ""
    p = cell.paragraphs[0]
    p.alignment = align
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run(text)
    _set_font(run, size, bold, color)


def _no_space_table(table):
    """Remove espaçamento extra das células."""
    tbl = table._tbl
    tblPr = tbl.find(qn("w:tblPr"))
    if tblPr is None:
        tblPr = OxmlElement("w:tblPr")
        tbl.insert(0, tblPr)
    tblStyle = OxmlElement("w:tblStyle")
    tblStyle.set(qn("w:val"), "TableGrid")


def _page_setup(doc):
    """A4 com margens ABES."""
    section = doc.sections[0]
    section.page_height = Emu(29700 * 914.4)   # 297mm
    section.page_width = Emu(21000 * 914.4)    # 210mm
    section.top_margin = Cm(2.5)
    section.bottom_margin = Cm(3.0)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(2.5)
    section.header_distance = Cm(1.0)
    section.footer_distance = Cm(1.2)


def _build_header(doc):
    """Cabeçalho: logotipo ABES à esquerda."""
    section = doc.sections[0]
    header = section.header
    for p in header.paragraphs:
        p.clear()
    p = header.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    logo_path = ASSETS / "abes-logo.png"
    if logo_path.exists():
        run = p.add_run()
        run.add_picture(str(logo_path), width=Cm(4.5))


def _build_footer(doc, prop: ProposicaoInfo, ator: str):
    """Rodapé: endereço centralizado + bloco social à direita."""
    section = doc.sections[0]
    footer = section.footer
    for p in footer.paragraphs:
        p.clear()

    # Linha divisória + endereço
    p_addr = footer.paragraphs[0]
    p_addr.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_addr.paragraph_format.space_before = Pt(4)
    pPr = p_addr._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    top = OxmlElement("w:top")
    top.set(qn("w:val"), "single"); top.set(qn("w:sz"), "4")
    top.set(qn("w:space"), "6"); top.set(qn("w:color"), CINZA_LINHA)
    pBdr.append(top); pPr.append(pBdr)
    run = p_addr.add_run(
        "Avenida Ibirapuera, 2.907 – 8º andar, cj. 811 – CEP 04029200 – São Paulo – SP   |  tel: (11) 5094-3100"
    )
    _set_font(run, 7.5, color=CINZA_RODAPE)

    # Bloco social
    p_social = footer.add_paragraph()
    p_social.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    social_path = ASSETS / "abes-footer-social.png"
    if social_path.exists():
        run_s = p_social.add_run()
        run_s.add_picture(str(social_path), width=Cm(5.5))

    # Identificação do relatório
    p_id = footer.add_paragraph()
    p_id.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_id = p_id.add_run(
        f"{ator}  ·  {prop.tipo_sigla} {prop.numero}/{prop.ano}  ·  "
        f"Prospecção Política  ·  {date.today().strftime('%d/%m/%Y')}"
    )
    _set_font(run_id, 7.5, color=CINZA_RODAPE)


# ── Geração do dashboard de risco ────────────────────────────────────────────

def _gerar_dashboard(avaliacao: AvaliacaoRisco, analise: AnaliseCompleta) -> Optional[Path]:
    """Gera a imagem do dashboard de risco com gauge + barras."""
    script = RELATORIO_DIR / "generate_risk_dashboard.py"
    if not script.exists():
        return None
    try:
        input_data = {
            "score_mrp": analise.score_consolidado,
            "score_max": 5.0,
            "zona": analise.zona_mrp,
            "dimensoes": [
                {
                    "nome": DIMENSAO_LABELS[k],
                    "pontuacao": getattr(avaliacao, k).nota,
                    "confianca": getattr(avaliacao, k).confianca.value.upper(),
                }
                for k in DIMENSAO_KEYS
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(input_data, f, ensure_ascii=False)
            input_path = f.name
        output_path = Path(tempfile.mktemp(suffix=".png"))
        subprocess.run(
            [sys.executable, str(script), input_path, str(output_path)],
            check=True, capture_output=True,
        )
        return output_path if output_path.exists() else None
    except Exception:
        return None


def _gerar_timeline(prop: ProposicaoInfo) -> Optional[Path]:
    """Gera a linha do tempo legislativa."""
    script = RELATORIO_DIR / "generate_timeline.py"
    if not script.exists():
        return None
    try:
        marcos = []
        if prop.ultimo_evento_data:
            marcos.append({"label": "Último evento", "data": prop.ultimo_evento_data, "estado": "concluido"})
        marcos.append({"label": prop.situacao_atual[:20] if prop.situacao_atual else "Situação atual",
                       "data": date.today().strftime("%d/%m/%Y"), "estado": "atual"})
        marcos.append({"label": "Próxima etapa", "data": "a definir", "estado": "pendente"})

        input_data = {
            "titulo": f"{prop.tipo_sigla} {prop.numero}/{prop.ano} – Andamento Legislativo",
            "marcos": marcos,
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(input_data, f, ensure_ascii=False)
            input_path = f.name
        output_path = Path(tempfile.mktemp(suffix=".png"))
        subprocess.run(
            [sys.executable, str(script), input_path, str(output_path)],
            check=True, capture_output=True,
        )
        return output_path if output_path.exists() else None
    except Exception:
        return None


# ── Seções do relatório ───────────────────────────────────────────────────────

def _secao_capa(doc, prop: ProposicaoInfo, ator: str,
                avaliacao: AvaliacaoRisco, analise: AnaliseCompleta):
    """Banner de capa com identificação e zona de risco."""
    # Tabela 1×2: esquerda = identificação, direita = zona/score
    table = doc.add_table(rows=1, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    col_w = [Cm(12), Cm(5)]
    for i, w in enumerate(col_w):
        table.columns[i].width = w

    left = table.rows[0].cells[0]
    right = table.rows[0].cells[1]
    _set_cell_bg(left, PRETO)
    zona_cor = ZONA_COR.get(analise.zona_mrp, "2C5F8A")
    _set_cell_bg(right, zona_cor)

    # Esquerda
    p1 = left.paragraphs[0]
    p1.paragraph_format.space_before = Pt(10)
    r1 = p1.add_run("RELATÓRIO DE PROSPECÇÃO POLÍTICA LEGISLATIVA")
    _set_font(r1, 9, bold=True, color=DOURADO)

    p2 = left.add_paragraph()
    r2 = p2.add_run(f"{prop.tipo_sigla} {prop.numero}/{prop.ano}  ·  {ator}  ·  {date.today().strftime('%d/%m/%Y')}")
    _set_font(r2, 10, bold=True, color=BRANCO)

    ementa_short = prop.ementa[:160] + ("…" if len(prop.ementa) > 160 else "")
    p3 = left.add_paragraph()
    p3.paragraph_format.space_after = Pt(10)
    r3 = p3.add_run(ementa_short)
    _set_font(r3, 9, color="CCCCCC")

    # Direita
    pr1 = right.paragraphs[0]
    pr1.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pr1.paragraph_format.space_before = Pt(12)
    rr1 = pr1.add_run(analise.zona_mrp.upper())
    _set_font(rr1, 13, bold=True, color=BRANCO)

    pr2 = right.add_paragraph()
    pr2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rr2 = pr2.add_run("ZONA MRP")
    _set_font(rr2, 8, color=BRANCO)

    pr3 = right.add_paragraph()
    pr3.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rr3 = pr3.add_run(f"{analise.score_consolidado:.2f} / 5,0")
    _set_font(rr3, 18, bold=True, color=BRANCO)

    pr4 = right.add_paragraph()
    pr4.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pr4.paragraph_format.space_after = Pt(12)
    rr4 = pr4.add_run("Score MRP")
    _set_font(rr4, 8, color=BRANCO)

    doc.add_paragraph()


def _secao_termo_referencia(doc, prop: ProposicaoInfo):
    _heading1(doc, "1. Termo de Referência")

    table = doc.add_table(rows=2, cols=4)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    headers = ["Proposição", "Situação Atual", "Último Evento", "Relator"]
    for i, h in enumerate(headers):
        c = table.rows[0].cells[i]
        _set_cell_bg(c, PRETO)
        _cell_text(c, h, size=9, bold=True, color=BRANCO, align=WD_ALIGN_PARAGRAPH.CENTER)

    vals = [
        f"{prop.tipo_sigla} {prop.numero}/{prop.ano}",
        prop.situacao_atual or "Não informada",
        f"{prop.ultimo_evento or 'N/A'}\n({prop.ultimo_evento_data or 'N/A'})",
        prop.relator_designado or "Não designado",
    ]
    for i, v in enumerate(vals):
        c = table.rows[1].cells[i]
        _set_cell_bg(c, CINZA_BG)
        _cell_text(c, v, size=9, align=WD_ALIGN_PARAGRAPH.CENTER)

    doc.add_paragraph()


def _secao_dashboard(doc, img_path: Optional[Path]):
    if not img_path or not img_path.exists():
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    run.add_picture(str(img_path), width=Cm(16))
    doc.add_paragraph()


def _secao_timeline(doc, img_path: Optional[Path]):
    if not img_path or not img_path.exists():
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    run.add_picture(str(img_path), width=Cm(16))
    doc.add_paragraph()


def _secao_dimensoes(doc, avaliacao: AvaliacaoRisco):
    _heading1(doc, "2. Avaliação das Dimensões de Risco")

    table = doc.add_table(rows=6, cols=4)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # Larguras relativas
    widths = [Cm(3), Cm(1.8), Cm(2.2), Cm(10)]
    for i, w in enumerate(widths):
        for row in table.rows:
            row.cells[i].width = w

    headers = ["Dimensão", "Nota", "Confiança", "Justificativa"]
    for i, h in enumerate(headers):
        c = table.rows[0].cells[i]
        _set_cell_bg(c, PRETO)
        _cell_text(c, h, size=9, bold=True, color=BRANCO, align=WD_ALIGN_PARAGRAPH.CENTER)

    CONFIANCA_LABEL = {"alto": "Alto", "medio": "Médio", "baixo": "Baixo",
                       "ALTO": "Alto", "MEDIO": "Médio", "BAIXO": "Baixo"}
    NOTA_COR = {1: "2E7D32", 2: "2E7D32", 3: "D9A61A", 4: "C0392B", 5: "C0392B"}

    for i, key in enumerate(DIMENSAO_KEYS):
        row = table.rows[i + 1]
        dim = getattr(avaliacao, key)
        conf_val = dim.confianca.value if hasattr(dim.confianca, "value") else str(dim.confianca)

        _set_cell_bg(row.cells[0], CINZA_BG)
        _cell_text(row.cells[0], DIMENSAO_LABELS[key], size=9, bold=True)

        nota_cor = NOTA_COR.get(dim.nota, PRETO)
        _set_cell_bg(row.cells[1], nota_cor)
        _cell_text(row.cells[1], f"{dim.nota}/5", size=11, bold=True,
                   color=BRANCO, align=WD_ALIGN_PARAGRAPH.CENTER)

        _set_cell_bg(row.cells[2], CINZA_BG)
        _cell_text(row.cells[2], CONFIANCA_LABEL.get(conf_val, conf_val),
                   size=9, align=WD_ALIGN_PARAGRAPH.CENTER)

        _set_cell_bg(row.cells[3], BRANCO)
        _cell_text(row.cells[3], dim.justificativa, size=9,
                   align=WD_ALIGN_PARAGRAPH.JUSTIFY)

    doc.add_paragraph()


def _secao_cenarios(doc, analise: AnaliseCompleta):
    _heading1(doc, "3. Cenários Prospectivos")

    for cenario in analise.cenarios:
        cor = CENARIO_COR.get(cenario.nome, "2C5F8A")
        label = CENARIO_LABEL.get(cenario.nome, cenario.nome.capitalize())

        table = doc.add_table(rows=1, cols=2)
        table.style = "Table Grid"
        table.alignment = WD_TABLE_ALIGNMENT.CENTER

        left = table.rows[0].cells[0]
        right = table.rows[0].cells[1]
        left.width = Cm(3)
        right.width = Cm(14)
        _set_cell_bg(left, cor)
        _set_cell_bg(right, BRANCO)

        pl = left.paragraphs[0]
        pl.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pl.paragraph_format.space_before = Pt(8)
        rl = pl.add_run(f"{cenario.probabilidade:.0%}")
        _set_font(rl, 16, bold=True, color=BRANCO)
        pl2 = left.add_paragraph()
        pl2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pl2.paragraph_format.space_after = Pt(8)
        rl2 = pl2.add_run(label)
        _set_font(rl2, 8, bold=True, color=BRANCO)

        pr1 = right.paragraphs[0]
        pr1.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        pr1.paragraph_format.space_before = Pt(6)
        rr1 = pr1.add_run(cenario.narrativa)
        _set_font(rr1, 9, color=PRETO)

        if cenario.principais_gatilhos:
            pr2 = right.add_paragraph()
            pr2.alignment = WD_ALIGN_PARAGRAPH.LEFT
            pr2.paragraph_format.space_after = Pt(6)
            rg1 = pr2.add_run("Gatilhos: ")
            _set_font(rg1, 9, bold=True, color=PRETO)
            rg2 = pr2.add_run(" · ".join(cenario.principais_gatilhos))
            _set_font(rg2, 9, color=PRETO)

        doc.add_paragraph().paragraph_format.space_after = Pt(4)


def _secao_acoes(doc, analise: AnaliseCompleta):
    _heading1(doc, "4. Plano de Ações Recomendadas")

    table = doc.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    headers = ["Ação", "Horizonte", "Responsável", "Prioridade"]
    widths = [Cm(9), Cm(3.5), Cm(3), Cm(2)]
    for i, (h, w) in enumerate(zip(headers, widths)):
        c = table.rows[0].cells[i]
        c.width = w
        _set_cell_bg(c, PRETO)
        _cell_text(c, h, size=9, bold=True, color=BRANCO, align=WD_ALIGN_PARAGRAPH.CENTER)

    for h_key, h_label in HORIZONTE_LABEL.items():
        acoes = [a for a in analise.acoes_recomendadas if a.horizonte == h_key]
        if not acoes:
            continue

        # Separador de horizonte
        sep_row = table.add_row()
        merged = sep_row.cells[0].merge(sep_row.cells[1]).merge(sep_row.cells[2]).merge(sep_row.cells[3])
        _set_cell_bg(merged, "E8F0F8")
        _cell_text(merged, h_label, size=9, bold=True, color="2C5F8A")

        for acao in acoes:
            row = table.add_row()
            _set_cell_bg(row.cells[0], BRANCO)
            _cell_text(row.cells[0], acao.acao, size=9, align=WD_ALIGN_PARAGRAPH.JUSTIFY)

            _set_cell_bg(row.cells[1], CINZA_BG)
            _cell_text(row.cells[1], h_label.split("(")[0].strip(), size=9, align=WD_ALIGN_PARAGRAPH.CENTER)

            _set_cell_bg(row.cells[2], CINZA_BG)
            _cell_text(row.cells[2], acao.responsavel_sugerido, size=9)

            prio_cor = PRIO_COR.get(acao.prioridade.lower(), "2C5F8A")
            _set_cell_bg(row.cells[3], prio_cor)
            _cell_text(row.cells[3], acao.prioridade.capitalize(), size=9,
                       bold=True, color=BRANCO, align=WD_ALIGN_PARAGRAPH.CENTER)

    doc.add_paragraph()


def _secao_kpis(doc, analise: AnaliseCompleta):
    _heading1(doc, "5. KPIs de Monitoramento")

    table = doc.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    headers = ["Indicador", "Fonte", "Frequência"]
    widths = [Cm(8), Cm(5), Cm(4)]
    FREQ_COR = {"diária": "C0392B", "semanal": "C0392B",
                "quinzenal": "D9A61A", "mensal": "2C5F8A"}

    for i, (h, w) in enumerate(zip(headers, widths)):
        c = table.rows[0].cells[i]
        c.width = w
        _set_cell_bg(c, PRETO)
        _cell_text(c, h, size=9, bold=True, color=BRANCO, align=WD_ALIGN_PARAGRAPH.CENTER)

    for kpi in analise.kpis:
        row = table.add_row()
        _set_cell_bg(row.cells[0], BRANCO)
        _cell_text(row.cells[0], kpi.indicador, size=9)
        _set_cell_bg(row.cells[1], CINZA_BG)
        _cell_text(row.cells[1], kpi.fonte, size=9)
        freq_cor = FREQ_COR.get(kpi.frequencia.lower(), "2C5F8A")
        _set_cell_bg(row.cells[2], freq_cor)
        _cell_text(row.cells[2], kpi.frequencia, size=9, bold=True,
                   color=BRANCO, align=WD_ALIGN_PARAGRAPH.CENTER)

    doc.add_paragraph()


# ── Função principal ──────────────────────────────────────────────────────────

def gerar_relatorio(
    proposicao: ProposicaoInfo | dict,
    avaliacao: AvaliacaoRisco | dict,
    analise: AnaliseCompleta | dict,
    ator_focal: str,
    output_path: str | Path,
    logo_path: Optional[str] = None,
) -> Path:
    """Gera o relatório .docx no padrão visual institucional ABES."""
    if isinstance(proposicao, dict):
        proposicao = ProposicaoInfo.model_validate(proposicao)
    if isinstance(avaliacao, dict):
        avaliacao = AvaliacaoRisco.model_validate(avaliacao)
    if isinstance(analise, dict):
        analise = AnaliseCompleta.model_validate(analise)

    doc = Document()
    _page_setup(doc)
    _build_header(doc)
    _build_footer(doc, proposicao, ator_focal)

    # Gerar imagens (não bloqueia se falhar)
    dashboard_img = _gerar_dashboard(avaliacao, analise)
    timeline_img = _gerar_timeline(proposicao)

    # Seções do relatório
    _secao_capa(doc, proposicao, ator_focal, avaliacao, analise)
    _secao_termo_referencia(doc, proposicao)

    if dashboard_img:
        _heading2(doc, "Dashboard de Risco")
        _secao_dashboard(doc, dashboard_img)

    if timeline_img:
        _heading2(doc, "Andamento Legislativo")
        _secao_timeline(doc, timeline_img)

    _secao_dimensoes(doc, avaliacao)
    _secao_cenarios(doc, analise)
    _secao_acoes(doc, analise)
    _secao_kpis(doc, analise)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))

    # Limpar temporários
    for img in (dashboard_img, timeline_img):
        if img and img.exists():
            try:
                img.unlink()
            except Exception:
                pass

    return output_path
