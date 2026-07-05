from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class ProposicaoInfo(BaseModel):
    origem: str  # "camara" | "senado"
    tipo_sigla: str
    numero: int
    ano: int
    ementa: str
    situacao_atual: str
    ultimo_evento: Optional[str] = None
    ultimo_evento_data: Optional[str] = None
    autor: Optional[str] = None
    relator_designado: Optional[str] = None
    comissoes_pendentes: list[str] = []
    regime_tramitacao: Optional[str] = None
    url_inteiro_teor: Optional[str] = None
