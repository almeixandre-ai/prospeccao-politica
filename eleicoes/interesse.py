"""Índice de Interesse na Pauta ABES (IIP) — hierarquiza quem tem histórico parlamentar.

Universo: membros da composição 2027-2031 com mandato na legislatura atual
(deputados reeleitos, senadores reeleitos ou que permanecem, e quem troca de casa).
Mede INTERESSE/ENGAJAMENTO na pauta, não alinhamento à posição da ABES.

Componentes (0-1 cada):
  autoria    — PL/PLP/PEC nos temas da agenda, ponderados pelo peso do tema, saturando em 3 por tema
  relatoria  — matérias da agenda relatadas no Senado (a Câmara não expõe relatorias por deputado)
  comissoes  — participação em comissões/órgãos temáticos (papel: presidente > titular > suplente)
  frentes    — frentes parlamentares ligadas à pauta digital
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel, Field, computed_field

from . import historico_camara as hc
from . import historico_senado as hs
from .avaliador_afinidade import carregar_agenda
from .composicao import DATA_DIR
from .schemas import Parlamentar

log = logging.getLogger("prospeccao.interesse")

DIR_INTERESSE = DATA_DIR / "interesse"

PESOS_COMPONENTES = {"autoria": 0.50, "relatoria": 0.20, "comissoes": 0.20, "frentes": 0.10}
SATURACAO_TEMA = 3      # proposições por tema que já contam como engajamento pleno
SATURACAO_RELATORIA = 4
SATURACAO_FRENTES = 4  # frentes mistas têm 100+ signatários: sinal fraco

FAIXAS = [(50, "A — Prioridade alta"), (30, "B — Prioridade média"), (15, "C — Interesse pontual")]


def _peso_papel(papel: str) -> float:
    p = (papel or "").lower()
    if "vice" in p:
        return 0.8
    if "presidente" in p:
        return 1.0
    if "relator" in p or "coordenador" in p:
        return 0.8
    if "suplente" in p:
        return 0.3
    return 0.6


class InteresseParlamentar(BaseModel):
    parlamentar_chave: str
    fontes: list[str] = Field(description="'camara' e/ou 'senado' — de onde vem o histórico")
    proposicoes: list[str] = Field(default_factory=list, description="'IDENT [temas] (principal?): ementa'")
    autoria_por_tema: dict[str, float] = Field(default_factory=dict)
    relatorias: list[str] = Field(default_factory=list)
    orgaos: list[str] = Field(default_factory=list, description="Comissões/órgãos temáticos e papel")
    frentes: list[str] = Field(default_factory=list)
    componentes: dict[str, float] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def iip(self) -> float:
        pesos = dict(PESOS_COMPONENTES)
        if "senado" not in self.fontes:
            pesos.pop("relatoria")  # componente indisponível → renormaliza
        total = sum(pesos.values())
        return round(100 * sum(self.componentes.get(k, 0) * w for k, w in pesos.items()) / total, 1)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def prioridade(self) -> str:
        for corte, rotulo in FAIXAS:
            if self.iip >= corte:
                return rotulo
        return "D — Interesse baixo" if self.iip > 0 else "Sem interesse identificado"


def tem_historico(p: Parlamentar) -> bool:
    return bool(p.id_camara or p.codigo_senado)


class AnalisadorInteresse:
    def __init__(self, agenda: dict | None = None):
        self._agenda = agenda or carregar_agenda()
        self._pesos = {t["id"]: float(t.get("peso", 1)) for t in self._agenda["temas"]}
        cfg = self._agenda.get("orgaos_tecnologia", {})
        self._com_camara = set(cfg.get("comissoes_camara", []))
        self._com_senado = set(cfg.get("comissoes_senado", []))
        termos = cfg.get("palavras_orgaos", []) + [k for t in self._agenda["temas"] for k in t["palavras_chave"]]
        self._termos_orgaos = [f" {hc.normalizar(k)} " for k in termos]
        self._exclusao = [f" {hc.normalizar(k)} " for k in cfg.get("termos_exclusao", [])]
        DIR_INTERESSE.mkdir(parents=True, exist_ok=True)

    # ── Cache ────────────────────────────────────────────────────────────

    @staticmethod
    def caminho(p: Parlamentar) -> Path:
        return DIR_INTERESSE / f"{p.chave}.json"

    @classmethod
    def carregar(cls, p: Parlamentar) -> InteresseParlamentar | None:
        arq = cls.caminho(p)
        return InteresseParlamentar.model_validate_json(arq.read_text(encoding="utf-8")) if arq.exists() else None

    # ── Classificadores ──────────────────────────────────────────────────

    def _temas(self, texto: str) -> list[str]:
        t = f" {hc.normalizar(texto)} "
        return [tema["id"] for tema in self._agenda["temas"]
                if any(f" {hc.normalizar(k)} " in t for k in tema["palavras_chave"])]

    def _orgao_tech(self, sigla: str, nome: str, siglas: set[str]) -> bool:
        if sigla in siglas:
            return True
        n = f" {hc.normalizar(nome)} "
        if any(k in n for k in self._exclusao):
            return False
        return any(k in n for k in self._termos_orgaos)

    # ── Coleta + cálculo ─────────────────────────────────────────────────

    def analisar(self, p: Parlamentar, forcar: bool = False) -> InteresseParlamentar | None:
        if not tem_historico(p):
            return None
        if not forcar and (ex := self.carregar(p)):
            return ex

        fontes, proposicoes, relatorias, orgaos, frentes = [], [], [], [], []
        contagem: dict[str, float] = {}

        def _conta(temas: list[str], valor: float) -> None:
            for t in temas:
                contagem[t] = contagem.get(t, 0) + valor

        if p.id_camara:
            fontes.append("camara")
            for prop in hc.proposicoes_autoria(p.id_camara):
                temas = self._temas(prop.get("ementa") or "")
                if temas:
                    _conta(temas, 1.0)
                    proposicoes.append(f"{prop.get('siglaTipo')} {prop.get('numero')}/{prop.get('ano')} "
                                       f"[{', '.join(temas)}] (Câmara): {(prop.get('ementa') or '')[:220]}")
            vistos = set()
            for o in hc.orgaos(p.id_camara):
                if self._orgao_tech(o["sigla"], o["nome"], self._com_camara):
                    rot = f"{o['sigla']} — {o['papel']} (Câmara): {o['nome'][:120]}"
                    if rot not in vistos:
                        vistos.add(rot)
                        orgaos.append(rot)
            frentes += [f for f in hc.frentes(p.id_camara) if self._orgao_tech("", f, set())]

        if p.codigo_senado:
            fontes.append("senado")
            for prop in hs.autorias(p.codigo_senado):
                temas = self._temas(prop["ementa"])
                if temas:
                    principal = max(hc.similaridade(prop["primeiro_autor"], p.nome_urna),
                                     hc.similaridade(prop["primeiro_autor"], p.nome_completo or "")) >= 0.85
                    _conta(temas, 1.0 if principal else 0.5)
                    papel = "autor principal" if principal else "coautor"
                    proposicoes.append(f"{prop['identificacao']} [{', '.join(temas)}] (Senado, {papel}): "
                                       f"{prop['ementa'][:220]}")
            for r in hs.relatorias(p.codigo_senado):
                temas = self._temas(r["ementa"])
                if temas:
                    relatorias.append(f"{r['identificacao']} [{', '.join(temas)}] ({r['colegiado']}): {r['ementa'][:200]}")
            for c in hs.comissoes_e_frentes(p.codigo_senado):
                if not self._orgao_tech(c["sigla"], c["nome"], self._com_senado):
                    continue
                if c["sigla"].upper().startswith("FP"):
                    frentes.append(c["nome"])
                else:
                    orgaos.append(f"{c['sigla']} — {c['papel']} (Senado): {c['nome'][:120]}")

        total_peso = sum(self._pesos.values()) or 1
        autoria = sum(self._pesos[t] * min(n, SATURACAO_TEMA) / SATURACAO_TEMA
                      for t, n in contagem.items()) / total_peso
        papeis = sorted((_peso_papel(o.split(" — ", 1)[1].split(" (", 1)[0]) for o in orgaos), reverse=True)
        comissoes = min(1.0, papeis[0] + 0.15 * (len(papeis) - 1)) if papeis else 0.0
        frentes = sorted(set(frentes))

        resultado = InteresseParlamentar(
            parlamentar_chave=p.chave, fontes=fontes, proposicoes=proposicoes,
            autoria_por_tema={t: round(n, 1) for t, n in contagem.items()},
            relatorias=relatorias, orgaos=orgaos, frentes=frentes,
            componentes={
                "autoria": round(autoria, 3),
                "relatoria": round(min(len(relatorias), SATURACAO_RELATORIA) / SATURACAO_RELATORIA, 3),
                "comissoes": round(comissoes, 3),
                "frentes": round(min(len(frentes), SATURACAO_FRENTES) / SATURACAO_FRENTES, 3),
            },
        )
        self.caminho(p).write_text(json.dumps(resultado.model_dump(), ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        return resultado

    def analisar_todos(self, parls: list[Parlamentar], forcar: bool = False, workers: int = 6) -> int:
        alvo = [p for p in parls if tem_historico(p)]

        def _um(p: Parlamentar):
            try:
                return self.analisar(p, forcar)
            except Exception as e:  # um parlamentar com falha não derruba o lote
                log.error("Falha em %s: %s", p.nome_urna, e)

        with ThreadPoolExecutor(max_workers=workers) as ex:
            for i, r in enumerate(ex.map(_um, alvo), 1):
                if i % 25 == 0:
                    log.info("  %d/%d analisados", i, len(alvo))
        return len(alvo)
