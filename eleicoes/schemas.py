"""Schemas Pydantic v2 da composição 2027-2031 e da análise de afinidade ABES."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, computed_field

from analise.schemas_risco import Evidencia, NivelConfianca


class Parlamentar(BaseModel):
    """Membro da nova composição (Câmara ou Senado) a partir de 01/02/2027."""

    casa: str = Field(description="'camara' ou 'senado'")
    uf: str
    nome_urna: str
    nome_completo: Optional[str] = None
    partido: str
    federacao: Optional[str] = None
    numero: Optional[str] = None
    votos: Optional[int] = None
    situacao: str = Field(description="Ex.: 'Eleito por QP', 'Eleito', 'Mandato até 2031'")
    origem: str = Field(description="'tse_2026' (eleito agora) ou 'senado_2022' (permanece)")
    sq_candidato: Optional[str] = None
    id_camara: Optional[int] = Field(default=None, description="ID na API da Câmara, se já foi deputado")
    codigo_senado: Optional[str] = None
    incumbente: bool = Field(default=False, description="Já exercia mandato na mesma casa (2023-2027)")
    alertas: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def chave(self) -> str:
        """Identificador estável para cache de avaliações."""
        base = self.sq_candidato or self.codigo_senado or self.nome_urna
        return f"{self.casa}_{self.uf}_{base}".replace(" ", "_")


class Composicao(BaseModel):
    """Nova composição das duas casas, com metadados de totalização."""

    data_coleta: str
    totalizacao_tse: dict[str, str] = Field(
        default_factory=dict, description="UF → % de seções totalizadas no momento da coleta",
    )
    deputados: list[Parlamentar]
    senadores: list[Parlamentar]
    alertas: list[str] = Field(default_factory=list)


class AvaliacaoTema(BaseModel):
    """Posição inferida do parlamentar sobre um tema da agenda ABES."""

    tema_id: str
    posicao: int = Field(ge=-2, le=2, description="-2 contrário … 0 neutro/sem sinal … +2 alinhado")
    justificativa: str
    evidencias: list[Evidencia] = Field(default_factory=list)
    confianca: NivelConfianca


class AvaliacaoAfinidade(BaseModel):
    """Resultado do 'match' entre propostas/histórico do parlamentar e a agenda ABES."""

    parlamentar_chave: str
    data_geracao: str
    temas: list[AvaliacaoTema]
    historico_legislativo: list[str] = Field(
        default_factory=list, description="Proposições de autoria aderentes à agenda (incumbentes)",
    )
    perfil_resumo: str = ""
    pesos: dict[str, float] = Field(default_factory=dict)
    alertas: list[str] = Field(default_factory=list)
    metodo: str = Field(
        default="ia", description="'ia' (propostas + web + histórico) ou 'triagem' (só palavras-chave)",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cobertura(self) -> float:
        """Fração do peso da agenda com algum sinal (posição ≠ 0)."""
        total = sum(self.pesos.values()) or 1.0
        com_sinal = sum(self.pesos.get(t.tema_id, 0) for t in self.temas if t.posicao != 0)
        return round(com_sinal / total, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def indice_afinidade(self) -> float:
        """Índice de Afinidade Tecnológica (IAT), 0-100; 50 = neutro."""
        sinais = [t for t in self.temas if t.posicao != 0]
        if not sinais:
            return 50.0
        peso = sum(self.pesos.get(t.tema_id, 1.0) for t in sinais)
        media = sum(t.posicao * self.pesos.get(t.tema_id, 1.0) for t in sinais) / peso
        # Encolhe em direção ao neutro quando há poucos temas com sinal
        fator = min(1.0, 0.4 + self.cobertura)
        return round(50 + 25 * media * fator, 1)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def classificacao(self) -> str:
        if self.cobertura == 0:
            return "Sem sinal"
        if self.metodo == "triagem":
            return "Engajado — qualificar"
        s = self.indice_afinidade
        if s >= 75:
            return "Aliado tecnológico"
        if s >= 60:
            return "Potencial aliado"
        if s >= 40:
            return "Neutro"
        return "Atenção"
