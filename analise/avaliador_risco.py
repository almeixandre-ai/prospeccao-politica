"""Avaliador de risco político — Módulo 2 do sistema de prospecção."""

from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import json
import logging
import os
import time
from datetime import date, datetime
from pathlib import Path

import anthropic

from coleta.schemas import ProposicaoInfo
from .schemas_risco import (
    AvaliacaoDimensao,
    Evidencia,
    MatrizRisco,
    NivelConfianca,
)
from .coletores_evidencia import (
    buscar_discursos_parlamentar,
    buscar_indicadores_bcb,
    buscar_noticias,
)

log = logging.getLogger("prospeccao.avaliador")

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = (
    "Você é um especialista sênior em relações governamentais e inteligência "
    "política legislativa brasileira, com 20 anos de experiência no Congresso "
    "Nacional. Você analisa proposições legislativas e avalia riscos políticos "
    "de forma objetiva, baseando-se em evidências concretas e indicadores "
    "factuais. Suas avaliações são usadas por executivos de alto nível para "
    "tomada de decisão estratégica."
)

DIMENSOES = ["processual", "coalicao", "agenda", "atores", "exogeno"]

DIMENSAO_LABELS = {
    "processual": "Risco Processual",
    "coalicao": "Risco de Coalizão",
    "agenda": "Risco de Agenda",
    "atores": "Risco de Atores-Chave",
    "exogeno": "Risco Exógeno",
}

CRITERIOS = {
    "processual": (
        "Avalie o RISCO PROCESSUAL considerando:\n"
        "- Regime de tramitação atual (ordinário, urgência, urgência urgentíssima)\n"
        "- Número de comissões que ainda precisam analisar e tempo estimado\n"
        "- Risco de retorno à casa de origem por alteração substantiva\n"
        "- Prazo constitucional aplicável (especialmente para Medidas Provisórias)\n"
        "- Existência de apensações que podem alterar o texto-base\n"
        "- Possibilidade de requerimento de urgência ou de destaques"
    ),
    "coalicao": (
        "Avalie o RISCO DE COALIZÃO considerando:\n"
        "- Coesão da base governista sobre este tema específico\n"
        "- Posição de bancadas temáticas relevantes (ruralista, evangélica, industrial, etc.)\n"
        "- Manifestações de entidades setoriais e sociedade civil organizada\n"
        "- Histórico de votações similares e dissidências observadas\n"
        "- Alinhamento ou divergência entre Executivo e base aliada"
    ),
    "agenda": (
        "Avalie o RISCO DE AGENDA considerando:\n"
        "- Saturação atual da pauta legislativa (quantas matérias concorrem)\n"
        "- Janelas legislativas disponíveis (recesso, eleições, calendário)\n"
        "- Concorrência com outros temas prioritários do governo\n"
        "- Interesse demonstrado pela presidência da Casa em pautar o tema\n"
        "- Capacidade de obstrução da oposição via procedimentos regimentais"
    ),
    "atores": (
        "Avalie o RISCO DE ATORES-CHAVE considerando:\n"
        "- Posição política e histórico do relator designado (ou ausência de relator)\n"
        "- Poder e alinhamento do presidente da comissão competente\n"
        "- Capacidade de articulação e obstrução de líderes partidários\n"
        "- Influência de membros do governo (ministros, secretários) sobre a matéria\n"
        "- Protagonismo de parlamentares com expertise no tema"
    ),
    "exogeno": (
        "Avalie o RISCO EXÓGENO considerando:\n"
        "- Conjuntura fiscal e macroeconômica (SELIC, inflação, câmbio, resultado primário)\n"
        "- Pressões do Judiciário, TCU ou Ministério Público sobre o tema\n"
        "- Fatores internacionais (regulações estrangeiras, acordos, pressão diplomática)\n"
        "- Eventos imprevisíveis que podem acelerar ou travar a tramitação\n"
        "- Opinião pública e cobertura midiática sobre o assunto"
    ),
}

HISTORICO_PROPOSICOES = (
    "HISTÓRICO DE PROPOSIÇÕES SIMILARES (use como referência quando pertinente):\n"
    "- LGPD (PL 53/2018→Lei 13.709/2018): ~8 anos de tramitação total (desde o "
    "PL 4060/2012). Aprovada sob pressão do GDPR europeu e após escândalos de "
    "vazamento de dados. Sancionada com vetos e ANPD criada por MP.\n"
    "- Marco Civil da Internet (PL 2126/2011→Lei 12.965/2014): ~2 anos de "
    "tramitação acelerada. Catalisada pelas revelações de Snowden sobre "
    "vigilância da NSA. Forte mobilização da sociedade civil.\n"
    "- PL das Fake News (PL 2630/2020): 5+ anos sem aprovação definitiva. "
    "Resistência coordenada das plataformas digitais. Múltiplos substitutivos "
    "e mudanças de relator. Exemplo de proposição que trava por falta de "
    "consenso intersetorial."
)


class AvaliadorRisco:
    """Avalia risco político de proposições legislativas usando Claude com evidências."""

    def __init__(self, api_key: str | None = None, output_dir: str = "output"):
        self._client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"),
        )
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._audit_path: Path | None = None

    # ── Método principal ─────────────────────────────────────────────────

    def avaliar(self, proposicao: ProposicaoInfo, ator_focal: str) -> MatrizRisco:
        """Avalia as 5 dimensões de risco e retorna a MatrizRisco consolidada."""
        ident = f"{proposicao.tipo_sigla} {proposicao.numero}/{proposicao.ano}"
        log.info("Iniciando avaliação de risco — %s para %s", ident, ator_focal)

        ident_safe = f"{proposicao.tipo_sigla}{proposicao.numero}_{proposicao.ano}"
        self._audit_path = (
            self._output_dir / f"auditoria_{ident_safe}_{date.today().isoformat()}.jsonl"
        )

        resultados: dict[str, AvaliacaoDimensao] = {}

        for dimensao in DIMENSOES:
            log.info("── Dimensão: %s ──", DIMENSAO_LABELS[dimensao])

            # 1. Coletar evidências
            evidencias = self._coletar_evidencias_dimensao(dimensao, proposicao)
            log.info("  Evidências coletadas: %d", len(evidencias))

            # 2. Montar prompt
            prompt = self._prompt_dimensao(dimensao, proposicao, evidencias, ator_focal)

            # 3. Chamar Claude
            raw = self._chamar_claude(prompt, dimensao)
            log.info(
                "  Resultado: nota=%d, confiança=%s",
                raw.get("nota", 0), raw.get("confianca", "?"),
            )

            # 4. Filtrar evidências efetivamente citadas
            citadas = self._filtrar_evidencias_citadas(
                dimensao, evidencias, raw.get("justificativa", ""),
            )
            log.info("  Evidências citadas: %d/%d", len(citadas), len(evidencias))

            # 5. Montar AvaliacaoDimensao
            alertas = raw.get("alertas", [])
            if proposicao.tipo_sigla.upper() == "PLP" and dimensao == "coalicao":
                alertas.append("PLP exige maioria absoluta para aprovação")

            resultados[dimensao] = AvaliacaoDimensao(
                dimensao=DIMENSAO_LABELS[dimensao],
                nota=raw.get("nota", 3),
                justificativa=raw.get("justificativa", "Avaliação indisponível."),
                evidencias=citadas,
                confianca=NivelConfianca(raw.get("confianca", "BAIXO")),
                alertas=alertas,
            )

        # 6. Agregar em MatrizRisco com pesos ajustados ao tipo
        pesos = MatrizRisco.pesos_por_tipo(proposicao.tipo_sigla)
        log.info("Pesos aplicados (%s): %s", proposicao.tipo_sigla, pesos)

        matriz = MatrizRisco(
            risco_processual=resultados["processual"],
            risco_coalicao=resultados["coalicao"],
            risco_agenda=resultados["agenda"],
            risco_atores=resultados["atores"],
            risco_exogeno=resultados["exogeno"],
            pesos=pesos,
        )

        log.info(
            "Avaliação concluída — Score: %.2f | Zona: %s",
            matriz.score_consolidado, matriz.zona_risco,
        )
        return matriz

    # ── Coleta de evidências por dimensão ────────────────────────────────

    def _coletar_evidencias_dimensao(
        self, dimensao: str, proposicao: ProposicaoInfo,
    ) -> list[Evidencia]:
        identificador = f"{proposicao.tipo_sigla} {proposicao.numero}/{proposicao.ano}"
        tema = proposicao.ementa[:60]

        try:
            if dimensao == "processual":
                return self._evidencias_processual(proposicao)

            if dimensao == "coalicao":
                return buscar_noticias([
                    f"{identificador} entidades",
                    f"{identificador} manifesto setor",
                ])

            if dimensao == "agenda":
                return buscar_noticias([
                    f"pauta legislativa {tema}",
                    "agenda câmara votação",
                ])

            if dimensao == "atores":
                evs: list[Evidencia] = []
                if proposicao.relator_designado:
                    evs.extend(buscar_noticias([
                        f"{proposicao.relator_designado} {identificador}",
                    ]))
                else:
                    evs.append(Evidencia(
                        fonte="Dados da proposição",
                        data_coleta=date.today().isoformat(),
                        trecho_relevante="Relator ainda não designado para esta proposição.",
                        relevancia="Ausência de relator eleva incerteza sobre direção do parecer.",
                    ))
                return evs

            if dimensao == "exogeno":
                evs_bcb = buscar_indicadores_bcb()
                evs_news = buscar_noticias([tema, "risco regulatório Brasil"])
                return evs_bcb + evs_news

        except Exception as e:
            log.warning("Erro ao coletar evidências para %s: %s", dimensao, e)

        return []

    def _evidencias_processual(self, prop: ProposicaoInfo) -> list[Evidencia]:
        partes: list[str] = [
            f"Situação: {prop.situacao_atual}",
            f"Regime: {prop.regime_tramitacao or 'Não informado'}",
            f"Comissões pendentes: {', '.join(prop.comissoes_pendentes) or 'Nenhuma'}",
            f"Relator: {prop.relator_designado or 'Não designado'}",
            f"Último evento: {prop.ultimo_evento or 'N/A'} ({prop.ultimo_evento_data or 'N/A'})",
        ]
        return [Evidencia(
            fonte="API da Câmara/Senado — dados de tramitação",
            url=prop.url_inteiro_teor,
            data_coleta=date.today().isoformat(),
            trecho_relevante=" | ".join(partes),
            relevancia="Dados oficiais de tramitação da proposição.",
        )]

    # ── Prompt por dimensão ──────────────────────────────────────────────

    def _prompt_dimensao(
        self,
        dimensao: str,
        proposicao: ProposicaoInfo,
        evidencias: list[Evidencia],
        ator_focal: str,
    ) -> str:
        identificador = f"{proposicao.tipo_sigla} {proposicao.numero}/{proposicao.ano}"

        dados_prop = (
            f"PROPOSIÇÃO: {identificador}\n"
            f"Ementa: {proposicao.ementa}\n"
            f"Situação atual: {proposicao.situacao_atual}\n"
            f"Regime de tramitação: {proposicao.regime_tramitacao or 'Não informado'}\n"
            f"Relator: {proposicao.relator_designado or 'Não designado'}\n"
            f"Autor: {proposicao.autor or 'Não informado'}\n"
            f"Comissões pendentes: {', '.join(proposicao.comissoes_pendentes) or 'Nenhuma'}\n"
            f"Último evento: {proposicao.ultimo_evento or 'N/A'} ({proposicao.ultimo_evento_data or 'N/A'})\n"
            f"Origem: {'Câmara dos Deputados' if proposicao.origem == 'camara' else 'Senado Federal'}\n"
            f"Ator focal da análise: {ator_focal}"
        )

        if evidencias:
            ev_lines = []
            for i, ev in enumerate(evidencias, 1):
                ev_lines.append(
                    f"  {i}. [{ev.fonte}] {ev.trecho_relevante}\n"
                    f"     Relevância: {ev.relevancia}"
                )
            evidencias_text = "EVIDÊNCIAS COLETADAS:\n" + "\n".join(ev_lines)
        else:
            evidencias_text = "EVIDÊNCIAS COLETADAS: nenhuma evidência externa disponível."

        criterios = CRITERIOS[dimensao]

        return (
            f"{dados_prop}\n\n"
            f"{HISTORICO_PROPOSICOES}\n\n"
            f"{evidencias_text}\n\n"
            f"TAREFA:\n{criterios}\n\n"
            f"Use os precedentes históricos acima na justificativa quando pertinente. "
            f"Cite evidências coletadas pelo número (ex: 'conforme evidência 2').\n\n"
            f"Responda EXCLUSIVAMENTE com JSON válido neste formato exato, sem markdown:\n"
            f'{{\n'
            f'  "nota": <inteiro de 1 a 5, sendo 5 o maior risco>,\n'
            f'  "justificativa": "<análise em 3-5 linhas>",\n'
            f'  "alertas": ["<flag específico 1>", "<flag específico 2>"],\n'
            f'  "confianca": "<ALTO|MEDIO|BAIXO>"\n'
            f'}}'
        )

    # ── Filtrar evidências citadas ───────────────────────────────────────

    def _filtrar_evidencias_citadas(
        self,
        dimensao: str,
        evidencias: list[Evidencia],
        justificativa: str,
    ) -> list[Evidencia]:
        """Identifica quais evidências foram usadas na justificativa via segunda chamada."""
        if not evidencias or len(evidencias) <= 1:
            return evidencias

        ev_list = "\n".join(
            f"  {i}. [{ev.fonte}] {ev.trecho_relevante[:100]}"
            for i, ev in enumerate(evidencias, 1)
        )

        prompt = (
            f"Justificativa da análise:\n\"{justificativa}\"\n\n"
            f"Evidências disponíveis:\n{ev_list}\n\n"
            f"Quais evidências (pelos números) foram efetivamente usadas ou "
            f"sustentam o raciocínio da justificativa acima?\n"
            f"Responda APENAS com JSON: [1, 3] (lista de inteiros)"
        )

        try:
            t0 = time.time()
            response = self._client.messages.create(
                model=MODEL,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            latencia = int((time.time() - t0) * 1000)

            raw = ""
            for block in response.content:
                if block.type == "text":
                    raw += block.text
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            indices = json.loads(raw)

            self._log_auditoria(
                dimensao=f"{dimensao}_evidencias",
                tokens_input=response.usage.input_tokens,
                tokens_output=response.usage.output_tokens,
                latencia_ms=latencia,
            )

            return [
                evidencias[i - 1] for i in indices
                if isinstance(i, int) and 1 <= i <= len(evidencias)
            ]

        except Exception as e:
            log.debug("Fallback: retornando todas as evidências (%s)", e)
            return evidencias

    # ── Chamada à API Claude ─────────────────────────────────────────────

    def _chamar_claude(self, prompt: str, dimensao: str) -> dict:
        """Chama a API Claude com web_search habilitado e retorna o dict parseado."""
        for tentativa in range(3):
            try:
                use_tools = tentativa < 2
                log.info(
                    "  Chamando Claude (dimensão: %s, tentativa %d, web_search=%s)...",
                    dimensao, tentativa + 1, use_tools,
                )

                create_kwargs: dict = {
                    "model": MODEL,
                    "max_tokens": 1500,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": prompt}],
                }
                if use_tools:
                    create_kwargs["tools"] = [
                        {"type": "web_search_20250305", "name": "web_search"},
                    ]

                t0 = time.time()
                response = self._client.messages.create(**create_kwargs)
                latencia = int((time.time() - t0) * 1000)

                self._log_auditoria(
                    dimensao=dimensao,
                    tokens_input=response.usage.input_tokens,
                    tokens_output=response.usage.output_tokens,
                    latencia_ms=latencia,
                )

                # Extrair texto (pode conter blocos tool_use misturados)
                raw_text = ""
                for block in response.content:
                    if block.type == "text":
                        raw_text += block.text

                raw_text = raw_text.strip()

                # Se não veio texto, tentar retry sem web_search
                if not raw_text:
                    log.warning("  Resposta sem texto (apenas tool_use) — retry sem web_search")
                    continue

                if raw_text.startswith("```"):
                    raw_text = raw_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

                parsed = json.loads(raw_text)

                if "nota" not in parsed:
                    parsed["nota"] = 3
                parsed["nota"] = max(1, min(5, int(parsed["nota"])))
                parsed.setdefault("justificativa", "Avaliação automática.")
                parsed.setdefault("alertas", [])
                parsed.setdefault("confianca", "MEDIO")

                if parsed["confianca"] not in ("ALTO", "MEDIO", "BAIXO"):
                    parsed["confianca"] = "MEDIO"

                return parsed

            except anthropic.RateLimitError:
                log.warning("  Rate limit atingido — aguardando 60s...")
                time.sleep(60)

            except json.JSONDecodeError as e:
                log.warning("  Erro ao parsear JSON da resposta: %s", e)
                log.debug("  Resposta bruta: %.300s", raw_text if raw_text else "(vazio)")
                if tentativa < 2:
                    log.info("  Tentando novamente sem web_search...")
                    continue
                return {
                    "nota": 3,
                    "justificativa": f"Erro no parsing da resposta do modelo: {e}",
                    "alertas": ["Resultado gerado por fallback — resposta do modelo não era JSON válido"],
                    "confianca": "BAIXO",
                }

            except anthropic.APIError as e:
                log.error("  Erro na API Anthropic: %s", e)
                if tentativa == 2:
                    return {
                        "nota": 3,
                        "justificativa": f"Erro na API: {e}",
                        "alertas": ["Resultado gerado por fallback — erro na API"],
                        "confianca": "BAIXO",
                    }
                time.sleep(5)

        return {
            "nota": 3,
            "justificativa": "Avaliação indisponível após múltiplas tentativas.",
            "alertas": ["Falha persistente na comunicação com o modelo"],
            "confianca": "BAIXO",
        }

    # ── Log de auditoria ─────────────────────────────────────────────────

    def _log_auditoria(
        self, *, dimensao: str,
        tokens_input: int, tokens_output: int,
        latencia_ms: int,
    ) -> None:
        if not self._audit_path:
            return
        entry = {
            "timestamp": datetime.now(tz=__import__('datetime').timezone.utc).isoformat(),
            "dimensao": dimensao,
            "modelo": MODEL,
            "tokens_input": tokens_input,
            "tokens_output": tokens_output,
            "tokens_total": tokens_input + tokens_output,
            "latencia_ms": latencia_ms,
        }
        try:
            with open(self._audit_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning("Erro ao gravar auditoria: %s", e)


# ── Compatibilidade com módulos existentes (app.py, main.py, cenarios.py) ──

AvaliacaoRisco = MatrizRisco


def avaliar_risco(
    dados_proposicao: dict, api_key: str | None = None,
) -> MatrizRisco:
    """Wrapper de compatibilidade para o pipeline existente."""
    from coleta.schemas import ProposicaoInfo

    prop = ProposicaoInfo.model_validate(dados_proposicao)
    avaliador = AvaliadorRisco(api_key=api_key)
    return avaliador.avaliar(prop, ator_focal="Organização")


# ── Teste ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    prop_mock = ProposicaoInfo(
        origem="camara",
        tipo_sigla="PL",
        numero=2338,
        ano=2023,
        ementa="Dispõe sobre o uso da Inteligência Artificial no Brasil.",
        situacao_atual="Aguardando Parecer",
        ultimo_evento="Notificação de Apensação",
        ultimo_evento_data="2026-06-17",
        autor="Senado Federal - Rodrigo Pacheco",
        relator_designado=None,
        comissoes_pendentes=["CCTCI", "CCJ"],
        regime_tramitacao="Ordinária",
    )

    avaliador = AvaliadorRisco()
    matriz = avaliador.avaliar(prop_mock, ator_focal="ABES")

    print("\n" + "=" * 60)
    print(f"Score consolidado: {matriz.score_consolidado}")
    print(f"Zona de risco: {matriz.zona_risco}")
    print("=" * 60)

    for dim_name in DIMENSOES:
        dim = getattr(matriz, f"risco_{dim_name}")
        print(f"\n{dim.dimensao}: {dim.nota}/5 (confiança: {dim.confianca.value})")
        print(f"  {dim.justificativa[:120]}...")
        if dim.alertas:
            for a in dim.alertas:
                print(f"  ⚠ {a}")
        print(f"  Evidências citadas: {len(dim.evidencias)}")
