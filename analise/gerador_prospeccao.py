"""Gerador de prospecção política — cenários, ações, KPIs e síntese executiva."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime
from pathlib import Path

import anthropic

from coleta.schemas import ProposicaoInfo
from .schemas_risco import (
    AcaoRecomendada,
    Cenario,
    MatrizRisco,
    RelatorioProspeccao,
)

log = logging.getLogger("prospeccao.gerador")

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2000

SYSTEM_PROMPT = (
    "Você é um estrategista sênior de relações governamentais (RIG) e "
    "inteligência política legislativa no Brasil. Você produz análises "
    "prospectivas de alto nível para executivos, diretores e presidentes "
    "de associações setoriais. Sua linguagem é institucional, assertiva "
    "e orientada à ação. Você fundamenta suas análises em dados concretos "
    "e evita especulação sem base factual."
)

DIMENSAO_ATTR = {
    "Processual": "risco_processual",
    "Coalizão": "risco_coalicao",
    "Agenda": "risco_agenda",
    "Atores-Chave": "risco_atores",
    "Exógeno": "risco_exogeno",
}


class GeradorProspeccao:
    """Gera cenários, ações, KPIs e síntese a partir da MatrizRisco."""

    def __init__(self, api_key: str | None = None, output_dir: str = "output"):
        self._client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"),
        )
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._audit_path: Path | None = None

    # ── Método principal ─────────────────────────────────────────────────

    def gerar(
        self,
        proposicao: ProposicaoInfo,
        matriz: MatrizRisco,
        ator_focal: str,
    ) -> RelatorioProspeccao:
        """Gera o relatório de prospecção completo."""
        ident = f"{proposicao.tipo_sigla} {proposicao.numero}/{proposicao.ano}"
        log.info("Gerando prospecção para %s (ator: %s)", ident, ator_focal)

        ident_safe = f"{proposicao.tipo_sigla}{proposicao.numero}_{proposicao.ano}"
        self._audit_path = (
            self._output_dir / f"auditoria_{ident_safe}_{date.today().isoformat()}.jsonl"
        )

        cenarios = self._gerar_cenarios(proposicao, matriz, ator_focal)
        log.info("Cenários gerados: %d", len(cenarios))

        acoes = self._gerar_acoes(proposicao, matriz, ator_focal)
        log.info("Ações geradas: %d", len(acoes))

        kpis = self._gerar_kpis(proposicao, matriz)
        log.info("KPIs gerados: %d", len(kpis))

        sintese = self._gerar_sintese(proposicao, matriz, ator_focal)
        log.info("Síntese executiva gerada (%d chars)", len(sintese))

        return RelatorioProspeccao(
            proposicao_id=ident,
            ator_focal=ator_focal,
            data_geracao=date.today().isoformat(),
            matriz=matriz,
            cenarios=cenarios,
            acoes=acoes,
            kpis_monitoramento=kpis,
            sintese_executiva=sintese,
            limitacoes_analise=[
                "Análise baseada em dados públicos disponíveis na data de geração.",
                "Indicadores macroeconômicos podem apresentar defasagem.",
                "Cenários são projeções probabilísticas, não previsões determinísticas.",
                "Avaliação de coalizão limitada a manifestações públicas identificáveis.",
            ],
        )

    # ── Helpers ──────────────────────────────────────────────────────────

    def _dados_proposicao(self, prop: ProposicaoInfo, ator: str) -> str:
        ident = f"{prop.tipo_sigla} {prop.numero}/{prop.ano}"
        return (
            f"PROPOSIÇÃO: {ident}\n"
            f"Ementa: {prop.ementa}\n"
            f"Situação atual: {prop.situacao_atual}\n"
            f"Regime: {prop.regime_tramitacao or 'Não informado'}\n"
            f"Relator: {prop.relator_designado or 'Não designado'}\n"
            f"Autor: {prop.autor or 'Não informado'}\n"
            f"Comissões pendentes: {', '.join(prop.comissoes_pendentes) or 'Nenhuma'}\n"
            f"Origem: {'Câmara dos Deputados' if prop.origem == 'camara' else 'Senado Federal'}\n"
            f"Ator focal: {ator}"
        )

    def _resumo_matriz(self, matriz: MatrizRisco) -> str:
        lines = [
            f"AVALIAÇÃO DE RISCO — Score: {matriz.score_consolidado:.2f}/5.0 | "
            f"Zona: {matriz.zona_risco}",
        ]
        for label, attr in DIMENSAO_ATTR.items():
            dim = getattr(matriz, attr)
            lines.append(
                f"  {label}: {dim.nota}/5 ({dim.confianca.value}) — "
                f"{dim.justificativa[:120]}"
            )
            if dim.alertas:
                for a in dim.alertas:
                    lines.append(f"    ⚠ {a}")
        return "\n".join(lines)

    def _chamar_claude(self, prompt: str, etapa: str) -> str:
        """Chama a API Claude e retorna o texto bruto da resposta."""
        for tentativa in range(3):
            try:
                log.info("  Chamando Claude (%s, tentativa %d)...", etapa, tentativa + 1)
                t0 = time.time()
                response = self._client.messages.create(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                )
                latencia = int((time.time() - t0) * 1000)
                self._log_auditoria(
                    etapa=etapa,
                    tokens_input=response.usage.input_tokens,
                    tokens_output=response.usage.output_tokens,
                    latencia_ms=latencia,
                )
                raw = ""
                for block in response.content:
                    if block.type == "text":
                        raw += block.text
                return raw.strip()

            except anthropic.RateLimitError:
                log.warning("  Rate limit — aguardando 60s...")
                time.sleep(60)
            except anthropic.APIError as e:
                log.error("  Erro na API (%s): %s", etapa, e)
                if tentativa == 2:
                    raise
                time.sleep(5)

        raise RuntimeError(f"Falha persistente na API para etapa '{etapa}'")

    def _log_auditoria(
        self, *, etapa: str,
        tokens_input: int, tokens_output: int,
        latencia_ms: int,
    ) -> None:
        if not self._audit_path:
            return
        entry = {
            "timestamp": datetime.now(tz=__import__('datetime').timezone.utc).isoformat(),
            "etapa": etapa,
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

    def _parse_json(self, raw: str) -> dict | list:
        """Parseia JSON da resposta, removendo markdown fences se presentes."""
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(text)

    # ── Cenários ─────────────────────────────────────────────────────────

    def _gerar_cenarios(
        self, prop: ProposicaoInfo, matriz: MatrizRisco, ator: str,
    ) -> list[Cenario]:
        log.info("── Gerando cenários prospectivos...")

        prompt = (
            f"{self._dados_proposicao(prop, ator)}\n\n"
            f"{self._resumo_matriz(matriz)}\n\n"
            f"TAREFA: Gere EXATAMENTE 3 cenários prospectivos para esta proposição, "
            f"do ponto de vista de {ator} como ator focal que monitora esta matéria.\n\n"
            f"Os cenários devem refletir a zona de risco '{matriz.zona_risco}' "
            f"(score {matriz.score_consolidado:.2f}/5.0).\n\n"
            f"Para cada cenário:\n"
            f"- tipo: 'Base' (desdobramento mais provável), 'Otimista' (melhor caso "
            f"plausível) ou 'Pessimista' (pior caso plausível)\n"
            f"- probabilidade_estimada: faixa percentual (ex: '55-65%')\n"
            f"- narrativa: descrição em 4-6 linhas do desdobramento, com linguagem "
            f"institucional e referências concretas a atores e processos\n"
            f"- condicoes_ativacao: 2-4 eventos específicos que precisariam ocorrer "
            f"para este cenário se materializar\n\n"
            f"As probabilidades dos 3 cenários devem ser coerentes entre si.\n\n"
            f"Responda APENAS com JSON válido, sem markdown:\n"
            f'[\n'
            f'  {{"tipo": "Base", "probabilidade_estimada": "...", '
            f'"narrativa": "...", "condicoes_ativacao": ["...", "..."]}},\n'
            f'  {{"tipo": "Otimista", ...}},\n'
            f'  {{"tipo": "Pessimista", ...}}\n'
            f']'
        )

        try:
            raw = self._chamar_claude(prompt, "cenários")
            parsed = self._parse_json(raw)

            if isinstance(parsed, dict):
                parsed = parsed.get("cenarios", [parsed])

            cenarios = [Cenario.model_validate(c) for c in parsed[:3]]

            if len(cenarios) < 3:
                log.warning("Claude retornou %d cenários, esperados 3", len(cenarios))
                tipos_faltantes = {"Base", "Otimista", "Pessimista"} - {c.tipo for c in cenarios}
                for tipo in tipos_faltantes:
                    cenarios.append(Cenario(
                        tipo=tipo,
                        probabilidade_estimada="N/D",
                        narrativa=f"Cenário {tipo} não gerado automaticamente.",
                        condicoes_ativacao=["Dados insuficientes para projeção"],
                    ))

            return cenarios[:3]

        except Exception as e:
            log.error("Erro ao gerar cenários: %s", e)
            return [
                Cenario(tipo=t, probabilidade_estimada="N/D",
                        narrativa=f"Cenário {t} indisponível: {e}",
                        condicoes_ativacao=["Erro na geração"])
                for t in ("Base", "Otimista", "Pessimista")
            ]

    # ── Ações recomendadas ───────────────────────────────────────────────

    def _gerar_acoes(
        self, prop: ProposicaoInfo, matriz: MatrizRisco, ator: str,
    ) -> list[AcaoRecomendada]:
        log.info("── Gerando ações recomendadas...")

        # Identificar dimensões críticas (nota >= 3)
        dimensoes_criticas = []
        for label, attr in DIMENSAO_ATTR.items():
            dim = getattr(matriz, attr)
            if dim.nota >= 3:
                dimensoes_criticas.append(f"{label} ({dim.nota}/5): {dim.justificativa[:100]}")

        criticas_text = "\n".join(f"  - {d}" for d in dimensoes_criticas) if dimensoes_criticas else "  Nenhuma dimensão com nota >= 3."

        prompt = (
            f"{self._dados_proposicao(prop, ator)}\n\n"
            f"{self._resumo_matriz(matriz)}\n\n"
            f"DIMENSÕES QUE DEMANDAM AÇÃO (nota >= 3):\n{criticas_text}\n\n"
            f"TAREFA: Gere um plano de ações recomendadas para {ator}, considerando "
            f"a zona de risco '{matriz.zona_risco}'.\n\n"
            f"Requisitos:\n"
            f"- Mínimo 6 ações, distribuídas nos 3 horizontes temporais\n"
            f"- Horizontes: 'Imediato (0-30 dias)', 'Médio prazo (1-3 meses)', "
            f"'Estrutural (3-12 meses)'\n"
            f"- Cada ação deve ser ESPECÍFICA e ACIONÁVEL — nível de detalhe esperado:\n"
            f"  'Solicitar reunião com o Dep. [nome] para apresentar contribuição "
            f"técnica sobre art. 15 do substitutivo'\n"
            f"  'Articular nota conjunta com [entidade parceira] sobre impacto no "
            f"setor antes da votação na comissão'\n"
            f"- Não use ações genéricas como 'monitorar a situação' ou 'acompanhar'\n"
            f"- Inclua responsável sugerido (ex: 'Gerente de RIG', 'Diretoria "
            f"Jurídica', 'Comitê de Policy')\n"
            f"- Prioridade: 'Alta', 'Média' ou 'Baixa'\n\n"
            f"Responda APENAS com JSON válido, sem markdown:\n"
            f'[{{"horizonte": "...", "acao": "...", '
            f'"responsavel_sugerido": "...", "prioridade": "..."}}, ...]'
        )

        try:
            raw = self._chamar_claude(prompt, "ações")
            parsed = self._parse_json(raw)

            if isinstance(parsed, dict):
                # Pode vir como {"acoes": [...]} ou agrupado por horizonte
                if "acoes" in parsed:
                    parsed = parsed["acoes"]
                elif "acoes_recomendadas" in parsed:
                    parsed = parsed["acoes_recomendadas"]
                else:
                    flat: list[dict] = []
                    for key, val in parsed.items():
                        if isinstance(val, list):
                            for item in val:
                                if isinstance(item, dict):
                                    item.setdefault("horizonte", key)
                                    flat.append(item)
                    parsed = flat

            acoes = []
            for item in parsed:
                item.setdefault("prioridade", "Média")
                item.setdefault("responsavel_sugerido", None)
                acoes.append(AcaoRecomendada.model_validate(item))

            if len(acoes) < 6:
                log.warning("Claude retornou %d ações, esperadas >= 6", len(acoes))

            return acoes

        except Exception as e:
            log.error("Erro ao gerar ações: %s", e)
            return [
                AcaoRecomendada(
                    horizonte="Imediato (0-30 dias)",
                    acao=f"Revisar manualmente — erro na geração automática: {e}",
                    prioridade="Alta",
                ),
            ]

    # ── KPIs ─────────────────────────────────────────────────────────────

    def _gerar_kpis(
        self, prop: ProposicaoInfo, matriz: MatrizRisco,
    ) -> list[str]:
        log.info("── Gerando KPIs de monitoramento...")

        ident = f"{prop.tipo_sigla} {prop.numero}/{prop.ano}"

        prompt = (
            f"{self._resumo_matriz(matriz)}\n\n"
            f"PROPOSIÇÃO: {ident}\n"
            f"Situação: {prop.situacao_atual}\n"
            f"Relator: {prop.relator_designado or 'Não designado'}\n"
            f"Comissões: {', '.join(prop.comissoes_pendentes) or 'Nenhuma'}\n\n"
            f"TAREFA: Gere uma lista de 6 a 10 KPIs de monitoramento para "
            f"acompanhamento contínuo do risco político desta proposição.\n\n"
            f"Cada KPI deve ser um GATILHO OBSERVÁVEL que sinaliza mudança de "
            f"cenário. Exemplos do formato e nível de especificidade esperados:\n"
            f"- 'Designação de novo relator na Comissão Especial'\n"
            f"- 'Inclusão em pauta do plenário com data confirmada'\n"
            f"- 'Manifestação pública de liderança do [partido] contrária ao PL'\n"
            f"- 'Decisão do STF sobre [tema correlato] com impacto direto'\n"
            f"- 'Protocolo de requerimento de urgência por líder da base'\n\n"
            f"Não inclua indicadores genéricos como 'acompanhar a tramitação'.\n"
            f"Cada KPI deve ser verificável e ter um 'gatilho' claro.\n\n"
            f"Responda APENAS com JSON válido, sem markdown:\n"
            f'["KPI 1", "KPI 2", ...]'
        )

        try:
            raw = self._chamar_claude(prompt, "kpis")
            parsed = self._parse_json(raw)

            if isinstance(parsed, dict):
                parsed = parsed.get("kpis", parsed.get("kpis_monitoramento", []))

            kpis = [str(k) for k in parsed if isinstance(k, str)]

            if len(kpis) < 6:
                log.warning("Claude retornou %d KPIs, esperados >= 6", len(kpis))

            return kpis[:10]

        except Exception as e:
            log.error("Erro ao gerar KPIs: %s", e)
            return [
                f"Movimentações de tramitação do {ident}",
                "Designação ou substituição de relator",
                "Requerimentos de urgência protocolados",
            ]

    # ── Síntese executiva ────────────────────────────────────────────────

    def _gerar_sintese(
        self, prop: ProposicaoInfo, matriz: MatrizRisco, ator: str,
    ) -> str:
        log.info("── Gerando síntese executiva...")

        prompt = (
            f"{self._dados_proposicao(prop, ator)}\n\n"
            f"{self._resumo_matriz(matriz)}\n\n"
            f"TAREFA: Escreva um parágrafo executivo de 3-5 linhas para leitura "
            f"por decisores de alto nível (diretores, presidentes de associações, "
            f"conselheiros) sobre o risco político desta proposição.\n\n"
            f"Requisitos:\n"
            f"- Tom assertivo e direto, sem jargão excessivo\n"
            f"- Deve conter: zona de risco atual, cenário mais provável, e a "
            f"principal recomendação de ação\n"
            f"- Perspectiva de {ator} como ator interessado\n"
            f"- Não use bullet points — escreva em prosa corrida\n"
            f"- Não inclua cabeçalho nem título — apenas o parágrafo\n\n"
            f"Responda APENAS com o texto do parágrafo, sem aspas nem formatação."
        )

        try:
            raw = self._chamar_claude(prompt, "síntese")
            # Remover aspas externas e markdown residual
            text = raw.strip().strip('"').strip("'")
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            return text

        except Exception as e:
            log.error("Erro ao gerar síntese: %s", e)
            return (
                f"Proposição classificada na zona de risco '{matriz.zona_risco}' "
                f"(score {matriz.score_consolidado:.2f}/5.0). "
                f"Recomenda-se acompanhamento ativo por {ator}."
            )


# ── Teste ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    from .schemas_risco import AvaliacaoDimensao, Evidencia, NivelConfianca

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

    # Mock da MatrizRisco (para testar sem rodar o avaliador)
    def _dim(nome: str, nota: int, just: str, conf: NivelConfianca,
             alertas: list[str] | None = None) -> AvaliacaoDimensao:
        return AvaliacaoDimensao(
            dimensao=nome, nota=nota, justificativa=just,
            evidencias=[], confianca=conf, alertas=alertas or [],
        )

    matriz_mock = MatrizRisco(
        risco_processual=_dim(
            "Risco Processual", 4,
            "Tramitação em regime ordinário com apensações que elevam complexidade. "
            "Ausência de relator gera incerteza sobre prazo e direção do parecer.",
            NivelConfianca.ALTO, ["Relator não designado"],
        ),
        risco_coalicao=_dim(
            "Risco de Coalizão", 3,
            "Base governista dividida. Setor produtivo pede regulação leve, "
            "sociedade civil pressiona por restrições mais rígidas.",
            NivelConfianca.MEDIO,
        ),
        risco_agenda=_dim(
            "Risco de Agenda", 3,
            "Pauta concorrida no segundo semestre. Reformas fiscais e eleições "
            "municipais disputam espaço na agenda legislativa.",
            NivelConfianca.MEDIO,
        ),
        risco_atores=_dim(
            "Risco de Atores-Chave", 5,
            "Sem relator designado e sem comissão definida, há vácuo de liderança. "
            "Presidente da comissão favorável a regulação rígida.",
            NivelConfianca.ALTO,
            ["Relator não designado", "Presidente de comissão com viés regulatório"],
        ),
        risco_exogeno=_dim(
            "Risco Exógeno", 3,
            "Debate global sobre IA se intensifica. Incidentes com IA no Brasil "
            "podem gerar pressão pública por votação acelerada.",
            NivelConfianca.BAIXO,
        ),
    )

    print(f"Score: {matriz_mock.score_consolidado} | Zona: {matriz_mock.zona_risco}")
    print()

    gerador = GeradorProspeccao()
    relatorio = gerador.gerar(prop_mock, matriz_mock, ator_focal="ABES")

    print("\n" + "=" * 60)
    print("RELATÓRIO DE PROSPECÇÃO")
    print("=" * 60)

    print(f"\nProposição: {relatorio.proposicao_id}")
    print(f"Ator focal: {relatorio.ator_focal}")
    print(f"Data: {relatorio.data_geracao}")
    print(f"Score: {relatorio.matriz.score_consolidado} | Zona: {relatorio.matriz.zona_risco}")

    print("\n── Cenários ──")
    for c in relatorio.cenarios:
        print(f"\n  {c.tipo} ({c.probabilidade_estimada})")
        print(f"  {c.narrativa[:150]}...")
        for cond in c.condicoes_ativacao:
            print(f"    → {cond}")

    print("\n── Ações Recomendadas ──")
    for a in relatorio.acoes:
        print(f"  [{a.horizonte}] {a.acao}")
        print(f"    Responsável: {a.responsavel_sugerido} | Prioridade: {a.prioridade}")

    print("\n── KPIs ──")
    for k in relatorio.kpis_monitoramento:
        print(f"  • {k}")

    print("\n── Síntese Executiva ──")
    print(f"  {relatorio.sintese_executiva}")

    print("\n── Limitações ──")
    for lim in relatorio.limitacoes_analise:
        print(f"  - {lim}")
