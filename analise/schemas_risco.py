"""Schemas Pydantic v2 para o módulo de avaliação de risco político."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, computed_field, field_validator


class NivelConfianca(str, Enum):
    """Grau de confiança na avaliação de uma dimensão de risco."""

    ALTO = "ALTO"
    MEDIO = "MEDIO"
    BAIXO = "BAIXO"


class Evidencia(BaseModel):
    """Fonte consultada que embasa a avaliação de uma dimensão."""

    fonte: str = Field(description="Nome da fonte consultada")
    url: Optional[str] = None
    data_coleta: str = Field(description="Data em que a evidência foi coletada (YYYY-MM-DD)")
    trecho_relevante: str = Field(
        max_length=500,
        description="Resumo do que foi encontrado na fonte",
    )
    relevancia: str = Field(description="Por que esta evidência importa para a dimensão avaliada")


class AvaliacaoDimensao(BaseModel):
    """Resultado da avaliação de uma das cinco dimensões de risco político."""

    dimensao: str = Field(description="Nome da dimensão avaliada")
    nota: int = Field(ge=1, le=5, description="Nota de risco de 1 (muito baixo) a 5 (muito alto)")
    justificativa: str = Field(description="Análise em 3-5 linhas fundamentando a nota")
    evidencias: list[Evidencia] = Field(default_factory=list)
    confianca: NivelConfianca = Field(description="Grau de confiança na avaliação")
    alertas: list[str] = Field(
        default_factory=list,
        description="Flags específicos — ex: 'Relator sem histórico público'",
    )


class MatrizRisco(BaseModel):
    """Consolidação das cinco dimensões de risco político com score ponderado."""

    risco_processual: AvaliacaoDimensao
    risco_coalicao: AvaliacaoDimensao
    risco_agenda: AvaliacaoDimensao
    risco_atores: AvaliacaoDimensao
    risco_exogeno: AvaliacaoDimensao
    pesos: dict[str, float] = Field(default={
        "processual": 0.25,
        "coalicao": 0.25,
        "agenda": 0.15,
        "atores": 0.20,
        "exogeno": 0.15,
    })

    @staticmethod
    def pesos_por_tipo(tipo: str) -> dict[str, float]:
        """Retorna pesos ajustados ao tipo de proposição."""
        tipo = tipo.upper()
        if tipo == "MPV":
            return {
                "processual": 0.35, "coalicao": 0.20,
                "agenda": 0.10, "atores": 0.20, "exogeno": 0.15,
            }
        if tipo == "PEC":
            return {
                "processual": 0.20, "coalicao": 0.35,
                "agenda": 0.10, "atores": 0.20, "exogeno": 0.15,
            }
        return {
            "processual": 0.25, "coalicao": 0.25,
            "agenda": 0.15, "atores": 0.20, "exogeno": 0.15,
        }

    @field_validator("pesos")
    @classmethod
    def _pesos_somam_um(cls, v: dict[str, float]) -> dict[str, float]:
        total = sum(v.values())
        if not (0.99 <= total <= 1.01):
            raise ValueError(f"Pesos devem somar 1.0, somaram {total:.2f}")
        return v

    @computed_field  # type: ignore[prop-decorator]
    @property
    def score_consolidado(self) -> float:
        """Média ponderada das notas das cinco dimensões."""
        notas = {
            "processual": self.risco_processual.nota,
            "coalicao": self.risco_coalicao.nota,
            "agenda": self.risco_agenda.nota,
            "atores": self.risco_atores.nota,
            "exogeno": self.risco_exogeno.nota,
        }
        return round(sum(notas[k] * self.pesos[k] for k in self.pesos), 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def zona_risco(self) -> str:
        """Classificação qualitativa derivada do score consolidado."""
        s = self.score_consolidado
        if s >= 4.0:
            return "Crítica"
        if s >= 3.0:
            return "Atenção"
        if s >= 2.0:
            return "Monitoramento"
        return "Oportunidade"


class Cenario(BaseModel):
    """Narrativa prospectiva descrevendo um desdobramento possível."""

    tipo: str = Field(description="'Base', 'Otimista' ou 'Pessimista'")
    probabilidade_estimada: str = Field(description="Faixa estimada — ex: '55-65%'")
    narrativa: str = Field(description="Descrição do desdobramento em 3-5 frases")
    condicoes_ativacao: list[str] = Field(
        description="Eventos ou condições que ativariam este cenário",
    )


class AcaoRecomendada(BaseModel):
    """Ação sugerida organizada por horizonte temporal."""

    horizonte: str = Field(
        description="'Imediato (0-30 dias)', 'Médio prazo (1-3 meses)' ou 'Estrutural (3-12 meses)'",
    )
    acao: str
    responsavel_sugerido: Optional[str] = None
    prioridade: str = Field(description="'Alta', 'Média' ou 'Baixa'")


class RelatorioProspeccao(BaseModel):
    """Produto final do sistema de prospecção política legislativa."""

    proposicao_id: str = Field(description="Identificador da proposição — ex: 'PL 2338/2023'")
    ator_focal: str = Field(description="Organização ou ator para quem a análise é dirigida")
    data_geracao: str = Field(description="Data de geração do relatório (YYYY-MM-DD)")
    matriz: MatrizRisco
    cenarios: list[Cenario] = Field(min_length=3, max_length=3)
    acoes: list[AcaoRecomendada]
    kpis_monitoramento: list[str] = Field(
        description="Indicadores para acompanhamento contínuo do risco",
    )
    sintese_executiva: str = Field(
        description="Resumo em 3-5 linhas para decisores",
    )
    limitacoes_analise: list[str] = Field(
        default_factory=list,
        description="Ressalvas metodológicas e lacunas de dados",
    )
