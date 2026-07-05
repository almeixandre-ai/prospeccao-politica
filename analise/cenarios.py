"""Geração de cenários, classificação MRP e recomendações a partir da avaliação de risco."""

from __future__ import annotations

import json
import logging
import os
from typing import Literal

log = logging.getLogger("prospeccao.cenarios")

import anthropic
from pydantic import BaseModel, Field

from .avaliador_risco import AvaliacaoRisco

MODEL = "claude-sonnet-4-6"

# Pesos das dimensões para o score consolidado
PESOS = {
    "processual": 0.25,
    "coalicao": 0.20,
    "agenda": 0.20,
    "atores": 0.20,
    "exogeno": 0.15,
}

# Faixas da Matriz de Risco Político (MRP)
ZONA_FAIXAS: list[tuple[float, str]] = [
    (4.0, "Crítica"),
    (3.0, "Atenção"),
    (2.0, "Monitoramento"),
    (0.0, "Oportunidade"),
]


# ── Schemas Pydantic ─────────────────────────────────────────────────────────

class Cenario(BaseModel):
    nome: Literal["base", "otimista", "pessimista"]
    probabilidade: float = Field(ge=0.0, le=1.0, description="Probabilidade estimada (0-1)")
    narrativa: str = Field(description="Narrativa do cenário em 3-5 frases")
    principais_gatilhos: list[str] = Field(description="Eventos que ativariam este cenário")


class AcaoRecomendada(BaseModel):
    horizonte: Literal["imediato", "medio_prazo", "estrutural"]
    acao: str
    responsavel_sugerido: str = Field(default="Equipe RIG")
    prioridade: Literal["alta", "media", "baixa"]


class KPI(BaseModel):
    indicador: str
    fonte: str
    frequencia: str = Field(description="Frequência de monitoramento sugerida")


class AnaliseCompleta(BaseModel):
    score_consolidado: float = Field(ge=1.0, le=5.0)
    zona_mrp: Literal["Crítica", "Atenção", "Monitoramento", "Oportunidade"]
    cenarios: list[Cenario] = Field(min_length=3, max_length=3)
    acoes_recomendadas: list[AcaoRecomendada]
    kpis: list[KPI]


# ── Cálculos determinísticos ─────────────────────────────────────────────────

def _calcular_score(avaliacao: AvaliacaoRisco) -> float:
    dimensoes = {
        "processual": avaliacao.risco_processual.nota,
        "coalicao": avaliacao.risco_coalicao.nota,
        "agenda": avaliacao.risco_agenda.nota,
        "atores": avaliacao.risco_atores.nota,
        "exogeno": avaliacao.risco_exogeno.nota,
    }
    return round(sum(dimensoes[k] * PESOS[k] for k in PESOS), 2)


def _classificar_zona(score: float) -> str:
    for limite, zona in ZONA_FAIXAS:
        if score >= limite:
            return zona
    return "Oportunidade"


# ── Prompt para o Claude ─────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
Você é um estrategista sênior de relações governamentais (RIG) no Brasil.

Dada uma avaliação de risco político, produza um JSON COMPACTO com:

1. "cenarios": lista com 3 objetos, cada um com:
   - "nome": "base", "otimista" ou "pessimista"
   - "probabilidade": float (as 3 somam 1.0)
   - "narrativa": 2-3 frases curtas
   - "principais_gatilhos": lista de 2 strings curtas

2. "acoes_recomendadas": lista de 4-6 objetos, cada um com:
   - "horizonte": "imediato", "medio_prazo" ou "estrutural"
   - "acao": string curta (máx 80 chars)
   - "responsavel_sugerido": string curta
   - "prioridade": "alta", "media" ou "baixa"

3. "kpis": lista de 3-4 objetos, cada um com:
   - "indicador": string curta
   - "fonte": string curta
   - "frequencia": string curta

REGRAS: Seja conciso. Frases curtas. Sem explicações fora do JSON. \
Responda APENAS com o JSON, sem markdown.\
"""


def _repair_json(raw: str) -> str:
    """Tenta fechar um JSON truncado adicionando delimitadores faltantes."""
    # Fechar string aberta
    in_string = False
    escaped = False
    for ch in raw:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
    if in_string:
        raw += '"'

    # Contar e fechar colchetes/chaves pendentes
    stack = []
    in_str = False
    esc = False
    for ch in raw:
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()

    raw += "".join(reversed(stack))
    return raw


def gerar_cenarios(
    avaliacao: AvaliacaoRisco,
    dados_proposicao: dict | None = None,
    api_key: str | None = None,
) -> AnaliseCompleta:
    """Gera análise completa: score, zona MRP, cenários, ações e KPIs.

    Args:
        avaliacao: Resultado da avaliação de risco (AvaliacaoRisco).
        dados_proposicao: Dicionário original da coleta (para contexto adicional).
        api_key: Chave Anthropic. Se omitida, usa ANTHROPIC_API_KEY do ambiente.
    """
    score = _calcular_score(avaliacao)
    zona = _classificar_zona(score)

    contexto = {
        "avaliacao_risco": avaliacao.model_dump(),
        "score_consolidado": score,
        "zona_mrp": zona,
    }
    if dados_proposicao:
        contexto["dados_proposicao"] = dados_proposicao

    client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    user_msg = (
        "Com base na avaliação de risco abaixo, gere os cenários, ações "
        "recomendadas e KPIs de monitoramento.\n\n"
        f"```json\n{json.dumps(contexto, ensure_ascii=False, indent=2)}\n```"
    )

    messages = [{"role": "user", "content": user_msg}]
    raw = ""

    # Tenta até 2x: se a resposta vier truncada, envia de volta para continuar
    for attempt in range(2):
        response = client.messages.create(
            model=MODEL,
            max_tokens=8192,
            system=SYSTEM_PROMPT,
            messages=messages,
        )

        raw += response.content[0].text

        if response.stop_reason != "max_tokens":
            break

        # Resposta truncada — pede para continuar
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": "Continue o JSON exatamente de onde parou."})

    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    # Tentar reparar JSON truncado: fechar strings, arrays e objetos pendentes
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        repaired = _repair_json(raw)
        parsed = json.loads(repaired)

    parsed["score_consolidado"] = score
    parsed["zona_mrp"] = zona

    log.info("Chaves recebidas do Claude: %s", list(parsed.keys()))
    log.info("Tipo de 'cenarios': %s", type(parsed.get("cenarios")).__name__)

    _normalizar_resposta(parsed)

    log.info("Após normalização — cenarios: %s, acoes: %s, kpis: %s",
             type(parsed.get("cenarios")).__name__,
             type(parsed.get("acoes_recomendadas")).__name__,
             type(parsed.get("kpis")).__name__)

    return AnaliseCompleta.model_validate(parsed)


def _normalizar_resposta(parsed: dict) -> None:
    """Normaliza nomes de campos que o Claude pode variar."""

    # Cenários: dict agrupado por nome → lista, "tipo" → "nome"
    cenarios = parsed.get("cenarios", [])
    if isinstance(cenarios, dict):
        flat_c: list[dict] = []
        for nome, val in cenarios.items():
            if isinstance(val, dict):
                val.setdefault("nome", nome)
                flat_c.append(val)
        cenarios = flat_c
        parsed["cenarios"] = cenarios
    for c in cenarios:
        if "nome" not in c:
            for alt in ("tipo", "type", "cenario"):
                if alt in c:
                    c["nome"] = c.pop(alt)
                    break
        if "principais_gatilhos" not in c:
            for alt in ("gatilhos", "gatilhos_principais", "triggers",
                        "gatilhos_ativadores", "eventos_gatilho"):
                if alt in c:
                    c["principais_gatilhos"] = c.pop(alt)
                    break
            else:
                c["principais_gatilhos"] = []

    # Ações: encontrar a chave certa
    acoes = None
    for key in ("acoes_recomendadas", "acoes", "plano_acoes",
                "plano_de_acoes", "recomendacoes"):
        if key in parsed:
            acoes = parsed.pop(key)
            break
    if acoes is None:
        acoes = []

    # Se veio como dict agrupado por horizonte → achatar em lista
    if isinstance(acoes, dict):
        flat: list[dict] = []
        for horizonte, lista in acoes.items():
            if isinstance(lista, list):
                for a in lista:
                    a.setdefault("horizonte", horizonte)
                    flat.append(a)
        acoes = flat

    for a in acoes:
        a.setdefault("prioridade", "media")
        a.setdefault("responsavel_sugerido", "Equipe RIG")
        # Normalizar "responsavel" → "responsavel_sugerido"
        if "responsavel" in a and "responsavel_sugerido" not in a:
            a["responsavel_sugerido"] = a.pop("responsavel")
    parsed["acoes_recomendadas"] = acoes

    # KPIs: encontrar a chave certa (busca em qualquer chave que contenha "kpi" ou "indicador")
    if "kpis" not in parsed:
        found = False
        for key in list(parsed.keys()):
            if key == "kpis":
                continue
            val = parsed[key]
            if isinstance(val, list) and val and isinstance(val[0], dict):
                lower = key.lower()
                if "kpi" in lower or "indicador" in lower or "monitoramento" in lower:
                    parsed["kpis"] = parsed.pop(key)
                    found = True
                    break
        if not found:
            parsed["kpis"] = []

    kpis = parsed["kpis"]
    for k in kpis:
        if "indicador" not in k:
            for alt in ("nome", "name", "kpi", "descricao"):
                if alt in k:
                    k["indicador"] = k.pop(alt)
                    break
        k.setdefault("fonte", "A definir")
        k.setdefault("frequencia", "Semanal")
