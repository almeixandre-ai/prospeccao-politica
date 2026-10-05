"""Avaliador de afinidade com a agenda ABES — o 'match' parlamentar × setor de software.

Combina dois tipos de evidência, no mesmo espírito do AvaliadorRisco:
  1. Histórico legislativo objetivo (API da Câmara) para quem já é deputado;
  2. Propostas de campanha 2026 e manifestações públicas, buscadas via web_search.

Cada tema da agenda recebe uma posição de -2 (contrário) a +2 (alinhado), com
evidências e grau de confiança; o Índice de Afinidade Tecnológica (IAT) é
derivado no schema AvaliacaoAfinidade.
"""

from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import json
import logging
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path

import anthropic

from analise.schemas_risco import Evidencia, NivelConfianca
from . import historico_camara
from .composicao import DATA_DIR
from .schemas import AvaliacaoAfinidade, AvaliacaoTema, Parlamentar

log = logging.getLogger("prospeccao.afinidade")

MODEL = os.environ.get("ELEICOES_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("ELEICOES_EFFORT", "medium")
MAX_BUSCAS = int(os.environ.get("ELEICOES_MAX_BUSCAS", "6"))

ARQ_AGENDA = Path(__file__).resolve().parent / "agenda_abes.json"
DIR_AVALIACOES = DATA_DIR / "afinidade"

SYSTEM_PROMPT = (
    "Você é analista sênior de relações institucionais e governamentais (RIG) do setor "
    "de software no Brasil, a serviço da ABES (Associação Brasileira das Empresas de "
    "Software). Você mapeia parlamentares recém-eleitos para identificar aliados da "
    "agenda de tecnologia. Você é rigoroso: só atribui posição a um tema quando há "
    "evidência concreta e atribuível ao próprio parlamentar (proposta de campanha, "
    "projeto de lei de autoria, voto nominal, declaração pública). Filiação partidária, "
    "ideologia ou suposições não são evidência. Na ausência de sinal, a posição é 0."
)


def carregar_agenda(caminho: Path = ARQ_AGENDA) -> dict:
    return json.loads(caminho.read_text(encoding="utf-8"))


class AvaliadorAfinidade:
    """Avalia o alinhamento de cada parlamentar à agenda ABES."""

    def __init__(self, api_key: str | None = None, agenda: dict | None = None):
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._cliente: anthropic.Anthropic | None = None
        self._agenda = agenda or carregar_agenda()
        self._pesos = {t["id"]: float(t.get("peso", 1)) for t in self._agenda["temas"]}
        DIR_AVALIACOES.mkdir(parents=True, exist_ok=True)
        self._audit_path = DIR_AVALIACOES / f"auditoria_{date.today().isoformat()}.jsonl"

    @property
    def _client(self) -> anthropic.Anthropic:
        # Criado sob demanda: a triagem sem IA não exige chave da API
        if self._cliente is None:
            self._cliente = anthropic.Anthropic(api_key=self._api_key)
        return self._cliente

    # ── Cache ────────────────────────────────────────────────────────────

    @staticmethod
    def caminho(p: Parlamentar, metodo: str = "ia") -> Path:
        pasta = DIR_AVALIACOES if metodo == "ia" else DIR_AVALIACOES / "triagem"
        return pasta / f"{p.chave}.json"

    @classmethod
    def carregar(cls, p: Parlamentar, metodo: str = "ia") -> AvaliacaoAfinidade | None:
        arq = cls.caminho(p, metodo)
        if not arq.exists():
            return None
        return AvaliacaoAfinidade.model_validate_json(arq.read_text(encoding="utf-8"))

    @classmethod
    def melhor_disponivel(cls, p: Parlamentar) -> AvaliacaoAfinidade | None:
        """Avaliação completa (IA) se existir; senão a triagem."""
        return cls.carregar(p, "ia") or cls.carregar(p, "triagem")

    @staticmethod
    def _gravar(a: AvaliacaoAfinidade, arq: Path) -> None:
        arq.parent.mkdir(parents=True, exist_ok=True)
        arq.write_text(json.dumps(a.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")

    # ── Método principal ─────────────────────────────────────────────────

    def avaliar(self, p: Parlamentar, forcar: bool = False) -> AvaliacaoAfinidade:
        if not forcar and (existente := self.carregar(p)):
            return existente

        log.info("Avaliando %s (%s-%s, %s)", p.nome_urna, p.partido, p.uf, p.casa)
        historico: list[str] = []
        if p.id_camara:
            props = historico_camara.proposicoes_autoria(p.id_camara)
            historico = historico_camara.filtrar_por_agenda(props, self._agenda)
            log.info("  Histórico Câmara: %d proposições, %d aderentes à agenda", len(props), len(historico))

        raw = self._chamar_claude(self._prompt(p, historico), p.chave)
        avaliacao = self._montar(p, raw, historico)
        self._gravar(avaliacao, self.caminho(p))
        log.info("  IAT %.1f — %s (cobertura %.0f%%)", avaliacao.indice_afinidade,
                 avaliacao.classificacao, avaliacao.cobertura * 100)
        return avaliacao

    def triagem_sem_ia(self, p: Parlamentar) -> AvaliacaoAfinidade:
        """Triagem gratuita só com o histórico da Câmara (palavras-chave nas ementas).

        Mede engajamento temático, não a direção do voto/posição; por isso usa
        posição +1 com confiança BAIXA e não grava no cache das avaliações completas.
        """
        historico: list[str] = []
        if p.id_camara:
            historico = historico_camara.filtrar_por_agenda(
                historico_camara.proposicoes_autoria(p.id_camara), self._agenda,
            )
        temas = []
        for t in self._agenda["temas"]:
            itens = [h for h in historico if t["id"] in h.split("[", 1)[1].split("]", 1)[0].split(", ")]
            temas.append(AvaliacaoTema(
                tema_id=t["id"], posicao=1 if itens else 0,
                justificativa=(f"Autor(a) de {len(itens)} proposição(ões) sobre o tema — direção a confirmar."
                               if itens else "Sem proposições de autoria sobre o tema."),
                confianca=NivelConfianca.BAIXO,
            ))
        avaliacao = AvaliacaoAfinidade(
            parlamentar_chave=p.chave, data_geracao=date.today().isoformat(), temas=temas,
            historico_legislativo=historico, pesos=self._pesos, metodo="triagem",
            alertas=[*p.alertas, "Triagem por palavras-chave (sem IA) — mede engajamento, não alinhamento"],
        )
        self._gravar(avaliacao, self.caminho(p, "triagem"))
        return avaliacao

    # ── Prompt ───────────────────────────────────────────────────────────

    def _prompt(self, p: Parlamentar, historico: list[str]) -> str:
        cargo = "Deputado(a) Federal" if p.casa == "camara" else "Senador(a)"
        if p.origem == "tse_2026":
            contexto = f"Eleito(a) em 04/10/2026 ({p.situacao}, {p.votos or '?'} votos)."
        else:
            contexto = "Senador(a) eleito(a) em 2022, com mandato até 2031 (não disputou o Senado em 2026)."

        temas = "\n".join(
            f"- [{t['id']}] {t['nome']} (peso {t.get('peso', 1)})\n"
            f"    Posição ABES: {t['posicao_abes']}\n"
            f"    Sinais contrários: {t.get('sinais_contrarios') or '—'}"
            for t in self._agenda["temas"]
        )
        hist = "\n".join(f"  {i}. {h}" for i, h in enumerate(historico, 1)) or "  (nenhuma — novato na Câmara ou sem proposições aderentes)"

        return (
            f"PARLAMENTAR: {p.nome_urna} ({p.nome_completo or 'nome civil n/d'})\n"
            f"Cargo a partir de 2027: {cargo} por {p.uf} — {p.partido}"
            f"{' / ' + p.federacao if p.federacao else ''}\n"
            f"{contexto}\n"
            f"Já exercia mandato na mesma casa: {'sim' if p.incumbente else 'não'}\n\n"
            f"PROPOSIÇÕES DE AUTORIA ADERENTES À AGENDA (API da Câmara, 2023-2026):\n{hist}\n\n"
            f"AGENDA ABES:\n{temas}\n\n"
            f"TAREFA:\n"
            f"1. Use a busca na web para encontrar as PROPOSTAS DE CAMPANHA 2026 deste(a) parlamentar "
            f"(site oficial, redes sociais, entrevistas, sabatinas, planos registrados) e manifestações "
            f"públicas ou votos sobre tecnologia, inovação, IA, dados, tributação digital, educação digital.\n"
            f"2. Para cada tema da agenda, atribua uma posição: +2 (defende claramente a posição ABES), "
            f"+1 (sinais favoráveis), 0 (sem evidência ou ambíguo), -1 (sinais contrários), "
            f"-2 (defende claramente o oposto). Sem evidência atribuível ao parlamentar = 0.\n"
            f"3. Cite as fontes com URL. Cuidado com homônimos: confirme UF e partido.\n\n"
            f"Responda EXCLUSIVAMENTE com JSON válido, sem markdown, neste formato:\n"
            f'{{\n'
            f'  "perfil_resumo": "<2-3 linhas: trajetória e bandeiras principais da campanha>",\n'
            f'  "temas": [\n'
            f'    {{"tema_id": "<id>", "posicao": <-2..2>, "justificativa": "<1-3 linhas>",\n'
            f'      "confianca": "<ALTO|MEDIO|BAIXO>",\n'
            f'      "evidencias": [{{"fonte": "<veículo/página>", "url": "<url>", "trecho_relevante": "<até 300 caracteres>"}}]}}\n'
            f'  ],\n'
            f'  "alertas": ["<ex.: homônimo, candidatura sub judice, sem presença digital>"]\n'
            f'}}\n'
            f"Inclua todos os {len(self._agenda['temas'])} temas, mesmo com posição 0."
        )

    # ── Chamada ao Claude com web_search ─────────────────────────────────

    def _chamar_claude(self, prompt: str, chave: str) -> dict:
        messages: list[dict] = [{"role": "user", "content": prompt}]
        kwargs = dict(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            output_config={"effort": EFFORT},
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": MAX_BUSCAS}],
        )
        usar_fallback = True

        for tentativa in range(4):
            try:
                t0 = time.time()
                if usar_fallback:
                    resp = self._client.beta.messages.create(
                        **kwargs, messages=messages,
                        betas=["server-side-fallback-2026-07-01"],
                        extra_body={"fallbacks": "default"},
                    )
                else:
                    resp = self._client.messages.create(**kwargs, messages=messages)
                self._log_auditoria(chave, resp, int((time.time() - t0) * 1000))
            except anthropic.BadRequestError as e:
                if usar_fallback:
                    log.info("  Fallback server-side indisponível (%s) — seguindo sem ele", e.message)
                    usar_fallback = False
                    continue
                raise
            except anthropic.RateLimitError:
                log.warning("  Rate limit — aguardando 60s...")
                time.sleep(60)
                continue

            if resp.stop_reason == "pause_turn":
                # Busca longa: devolve o conteúdo para o modelo continuar de onde parou
                messages.append({"role": "assistant", "content": resp.content})
                continue
            if resp.stop_reason == "refusal":
                return {"alertas": ["Modelo recusou a análise"], "temas": []}

            texto = "".join(b.text for b in resp.content if b.type == "text").strip()
            return self._parse_json(texto)

        return {"alertas": ["Falha persistente na chamada ao modelo"], "temas": []}

    @staticmethod
    def _parse_json(texto: str) -> dict:
        if "```" in texto:
            texto = texto.split("```", 2)[1].removeprefix("json").strip()
        ini, fim = texto.find("{"), texto.rfind("}")
        try:
            return json.loads(texto[ini:fim + 1])
        except (json.JSONDecodeError, ValueError) as e:
            log.warning("  Resposta não era JSON válido: %s", e)
            return {"alertas": ["Resposta do modelo não era JSON válido"], "temas": []}

    # ── Montagem ─────────────────────────────────────────────────────────

    def _montar(self, p: Parlamentar, raw: dict, historico: list[str]) -> AvaliacaoAfinidade:
        hoje = date.today().isoformat()
        por_id = {t.get("tema_id"): t for t in raw.get("temas", []) if isinstance(t, dict)}
        temas: list[AvaliacaoTema] = []
        for t in self._agenda["temas"]:
            r = por_id.get(t["id"], {})
            conf = str(r.get("confianca", "BAIXO")).upper()
            evidencias = [
                Evidencia(
                    fonte=str(e.get("fonte", "web"))[:200], url=e.get("url"), data_coleta=hoje,
                    trecho_relevante=str(e.get("trecho_relevante", ""))[:500],
                    relevancia=f"Tema: {t['nome']}",
                )
                for e in r.get("evidencias", []) if isinstance(e, dict)
            ]
            try:
                posicao = max(-2, min(2, int(r.get("posicao", 0))))
            except (TypeError, ValueError):
                posicao = 0
            temas.append(AvaliacaoTema(
                tema_id=t["id"], posicao=posicao,
                justificativa=r.get("justificativa", "Sem evidência localizada."),
                evidencias=evidencias,
                confianca=NivelConfianca(conf) if conf in NivelConfianca.__members__ else NivelConfianca.BAIXO,
            ))
        return AvaliacaoAfinidade(
            parlamentar_chave=p.chave, data_geracao=hoje, temas=temas,
            historico_legislativo=historico, perfil_resumo=raw.get("perfil_resumo", ""),
            pesos=self._pesos, alertas=[*p.alertas, *raw.get("alertas", [])],
        )

    # ── Auditoria ────────────────────────────────────────────────────────

    def _log_auditoria(self, chave: str, resp, latencia_ms: int) -> None:
        u = resp.usage
        buscas = getattr(getattr(u, "server_tool_use", None), "web_search_requests", 0) or 0
        entry = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "parlamentar": chave, "modelo": resp.model,
            "tokens_input": u.input_tokens, "tokens_output": u.output_tokens,
            "buscas_web": buscas, "stop_reason": resp.stop_reason, "latencia_ms": latencia_ms,
        }
        try:
            with open(self._audit_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning("Erro ao gravar auditoria: %s", e)
