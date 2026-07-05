"""Testes do Módulo 2 — análise de risco político."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic

from analise.schemas_risco import (
    AcaoRecomendada,
    AvaliacaoDimensao,
    Cenario,
    Evidencia,
    MatrizRisco,
    NivelConfianca,
    RelatorioProspeccao,
)
from coleta.schemas import ProposicaoInfo


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _dim(nota: int, nome: str = "Dimensão", conf: NivelConfianca = NivelConfianca.MEDIO) -> AvaliacaoDimensao:
    return AvaliacaoDimensao(
        dimensao=nome, nota=nota, justificativa="Justificativa de teste.",
        evidencias=[], confianca=conf, alertas=[],
    )


def _prop_mock() -> ProposicaoInfo:
    return ProposicaoInfo(
        origem="camara", tipo_sigla="PL", numero=2338, ano=2023,
        ementa="Dispõe sobre o uso da Inteligência Artificial no Brasil.",
        situacao_atual="Aguardando Parecer",
        ultimo_evento="Notificação de Apensação",
        ultimo_evento_data="2026-06-17",
        autor="Senado Federal - Rodrigo Pacheco",
        relator_designado=None,
        comissoes_pendentes=["CCTCI", "CCJ"],
        regime_tramitacao="Ordinária",
    )


def _matriz(notas: tuple[int, int, int, int, int],
            pesos: dict | None = None) -> MatrizRisco:
    kwargs = dict(
        risco_processual=_dim(notas[0], "Processual"),
        risco_coalicao=_dim(notas[1], "Coalizão"),
        risco_agenda=_dim(notas[2], "Agenda"),
        risco_atores=_dim(notas[3], "Atores-Chave"),
        risco_exogeno=_dim(notas[4], "Exógeno"),
    )
    if pesos:
        kwargs["pesos"] = pesos
    return MatrizRisco(**kwargs)


def _mock_claude_response(json_body: dict | str) -> MagicMock:
    """Cria um mock de resposta da API Anthropic."""
    text = json_body if isinstance(json_body, str) else json.dumps(json_body)
    block = SimpleNamespace(type="text", text=text)
    usage = SimpleNamespace(input_tokens=100, output_tokens=50)
    return SimpleNamespace(content=[block], stop_reason="end_turn", usage=usage)


def _relatorio_valido(**overrides) -> RelatorioProspeccao:
    defaults = dict(
        proposicao_id="PL 2338/2023", ator_focal="ABES",
        data_geracao="2026-06-29", matriz=_matriz((3, 3, 3, 3, 3)),
        cenarios=[
            Cenario(tipo="Base", probabilidade_estimada="50%",
                    narrativa="N.", condicoes_ativacao=["C1"]),
            Cenario(tipo="Otimista", probabilidade_estimada="25%",
                    narrativa="N.", condicoes_ativacao=["C2"]),
            Cenario(tipo="Pessimista", probabilidade_estimada="25%",
                    narrativa="N.", condicoes_ativacao=["C3"]),
        ],
        acoes=[AcaoRecomendada(horizonte="Imediato (0-30 dias)",
                               acao="Teste", prioridade="Alta")],
        kpis_monitoramento=["KPI 1"],
        sintese_executiva="Síntese de teste.",
    )
    defaults.update(overrides)
    return RelatorioProspeccao(**defaults)


# ═══════════════════════════════════════════════════════════════════════════
# GRUPO 1 — Schemas e lógica de negócio
# ═══════════════════════════════════════════════════════════════════════════

class TestMatrizRiscoScore(unittest.TestCase):

    def test_score_consolidado_pesos_padrao(self):
        """Score com pesos padrão: P=0.25, C=0.25, Ag=0.15, At=0.20, Ex=0.15."""
        m = _matriz((4, 2, 3, 5, 1))
        esperado = round(4*0.25 + 2*0.25 + 3*0.15 + 5*0.20 + 1*0.15, 2)
        self.assertEqual(m.score_consolidado, esperado)

    def test_score_notas_5_4_3_2_1(self):
        """Teste #4 — notas [5,4,3,2,1] com pesos padrão = 3.25."""
        m = _matriz((5, 4, 3, 2, 1))
        esperado = round(5*0.25 + 4*0.25 + 3*0.15 + 2*0.20 + 1*0.15, 2)
        self.assertEqual(esperado, 3.25)
        self.assertEqual(m.score_consolidado, 3.25)


class TestMatrizRiscoZona(unittest.TestCase):

    def test_zona_critica_score_5(self):
        m = _matriz((5, 5, 5, 5, 5))
        self.assertEqual(m.zona_risco, "Crítica")

    def test_zona_critica_limite_4(self):
        m = _matriz((4, 4, 4, 4, 4))
        self.assertEqual(m.score_consolidado, 4.0)
        self.assertEqual(m.zona_risco, "Crítica")

    def test_zona_critica_score_4_5(self):
        """Teste #5a — score ~4.5 é 'Crítica'."""
        m = _matriz((5, 5, 4, 4, 4))
        self.assertGreaterEqual(m.score_consolidado, 4.0)
        self.assertEqual(m.zona_risco, "Crítica")

    def test_zona_atencao_score_3(self):
        m = _matriz((3, 3, 3, 3, 3))
        self.assertEqual(m.zona_risco, "Atenção")

    def test_zona_atencao_score_3_5(self):
        """Teste #5b — score ~3.5 é 'Atenção'."""
        m = _matriz((4, 3, 3, 4, 3))
        self.assertGreaterEqual(m.score_consolidado, 3.0)
        self.assertLess(m.score_consolidado, 4.0)
        self.assertEqual(m.zona_risco, "Atenção")

    def test_zona_monitoramento_score_2(self):
        m = _matriz((2, 2, 2, 2, 2))
        self.assertEqual(m.zona_risco, "Monitoramento")

    def test_zona_monitoramento_score_2_5(self):
        """Teste #5c — score ~2.5 é 'Monitoramento'."""
        m = _matriz((3, 2, 2, 3, 2))
        self.assertGreaterEqual(m.score_consolidado, 2.0)
        self.assertLess(m.score_consolidado, 3.0)
        self.assertEqual(m.zona_risco, "Monitoramento")

    def test_zona_oportunidade_score_1(self):
        m = _matriz((1, 1, 1, 1, 1))
        self.assertLess(m.score_consolidado, 2.0)
        self.assertEqual(m.zona_risco, "Oportunidade")

    def test_zona_oportunidade_score_1_5(self):
        """Teste #5d — score ~1.5 é 'Oportunidade'."""
        m = _matriz((2, 1, 1, 2, 1))
        self.assertLess(m.score_consolidado, 2.0)
        self.assertEqual(m.zona_risco, "Oportunidade")


class TestPesosPorTipo(unittest.TestCase):

    def test_mpv_processual_035(self):
        """Teste #6a — MPV eleva peso processual para 0.35."""
        pesos = MatrizRisco.pesos_por_tipo("MPV")
        self.assertEqual(pesos["processual"], 0.35)

    def test_pec_coalicao_035(self):
        """Teste #6b — PEC eleva peso coalizão para 0.35."""
        pesos = MatrizRisco.pesos_por_tipo("PEC")
        self.assertEqual(pesos["coalicao"], 0.35)

    def test_pl_pesos_padrao(self):
        """Teste #6c — PL usa pesos padrão."""
        pesos = MatrizRisco.pesos_por_tipo("PL")
        self.assertEqual(pesos["processual"], 0.25)
        self.assertEqual(pesos["coalicao"], 0.25)
        self.assertEqual(pesos["agenda"], 0.15)
        self.assertEqual(pesos["atores"], 0.20)
        self.assertEqual(pesos["exogeno"], 0.15)

    def test_pesos_somam_1(self):
        for tipo in ("PL", "PLP", "PEC", "MPV"):
            pesos = MatrizRisco.pesos_por_tipo(tipo)
            self.assertAlmostEqual(sum(pesos.values()), 1.0, places=2,
                                   msg=f"Pesos de {tipo} não somam 1.0")

    def test_mpv_case_insensitive(self):
        self.assertEqual(MatrizRisco.pesos_por_tipo("mpv")["processual"], 0.35)


class TestRelatorioProspeccaoValidacao(unittest.TestCase):

    def test_exatamente_3_cenarios(self):
        r = _relatorio_valido()
        self.assertEqual(len(r.cenarios), 3)

    def test_rejeita_2_cenarios(self):
        """Teste #10 — 2 cenários levanta ValidationError."""
        with self.assertRaises(Exception):
            _relatorio_valido(cenarios=[
                Cenario(tipo="Base", probabilidade_estimada="50%",
                        narrativa="N.", condicoes_ativacao=["C1"]),
                Cenario(tipo="Otimista", probabilidade_estimada="50%",
                        narrativa="N.", condicoes_ativacao=["C2"]),
            ])

    def test_rejeita_4_cenarios(self):
        with self.assertRaises(Exception):
            _relatorio_valido(cenarios=[
                Cenario(tipo=t, probabilidade_estimada="25%",
                        narrativa="N.", condicoes_ativacao=["C"])
                for t in ("Base", "Otimista", "Pessimista", "Extra")
            ])


class TestEvidenciaValidacao(unittest.TestCase):

    def test_rejeita_trecho_maior_que_500(self):
        with self.assertRaises(Exception):
            Evidencia(
                fonte="Fonte", data_coleta="2026-01-01",
                trecho_relevante="A" * 501, relevancia="R",
            )

    def test_aceita_trecho_com_500(self):
        ev = Evidencia(
            fonte="Fonte", data_coleta="2026-01-01",
            trecho_relevante="A" * 500, relevancia="R",
        )
        self.assertEqual(len(ev.trecho_relevante), 500)


# ═══════════════════════════════════════════════════════════════════════════
# GRUPO 2 — Coletores de evidência
# ═══════════════════════════════════════════════════════════════════════════

class TestBuscarIndicadoresBCB(unittest.TestCase):

    @patch("analise.coletores_evidencia.requests.get")
    def test_retorna_resultado_com_falhas_parciais(self, mock_get):
        """Teste #7 — IPCA timeout, SELIC ok → evidência com IPCA 'N/D'."""
        import requests as req

        def side_effect(url, **kwargs):
            if "sgs.13522" in url or "sgs.1/" in url:
                raise req.exceptions.Timeout("timeout")
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            if "sgs.11/" in url:
                resp.json.return_value = [{"data": "01/06/2026", "valor": "14.75"}]
            elif "sgs.5793" in url:
                resp.json.return_value = [{"data": "01/05/2026", "valor": "1.23"}]
            return resp

        mock_get.side_effect = side_effect

        from analise.coletores_evidencia import buscar_indicadores_bcb
        resultado = buscar_indicadores_bcb()

        self.assertEqual(len(resultado), 1)
        self.assertIn("14.75", resultado[0].trecho_relevante)
        self.assertIn("N/D", resultado[0].trecho_relevante)
        self.assertNotIn("Exception", resultado[0].trecho_relevante)


class TestBuscarNoticias(unittest.TestCase):

    @patch.dict("os.environ", {}, clear=True)
    @patch("analise.coletores_evidencia.requests.get")
    def test_retorna_vazia_sem_api_key_e_rss_falha(self, mock_get):
        mock_get.side_effect = Exception("connection error")
        from analise.coletores_evidencia import buscar_noticias
        resultado = buscar_noticias(["teste"], dias=7)
        self.assertIsInstance(resultado, list)
        self.assertEqual(len(resultado), 0)

    @patch.dict("os.environ", {"NEWSAPI_KEY": "fake-key"})
    @patch("analise.coletores_evidencia.requests.get")
    def test_trata_429_sem_excecao(self, mock_get):
        import requests as req
        resp = MagicMock()
        resp.status_code = 429
        resp.raise_for_status.side_effect = req.exceptions.HTTPError("429")
        mock_get.return_value = resp
        from analise.coletores_evidencia import buscar_noticias
        resultado = buscar_noticias(["regulação IA"], dias=7)
        self.assertIsInstance(resultado, list)
        self.assertEqual(len(resultado), 0)


# ═══════════════════════════════════════════════════════════════════════════
# GRUPO 3 — Avaliador de risco (mock Anthropic)
# ═══════════════════════════════════════════════════════════════════════════

class TestPromptDimensao(unittest.TestCase):

    def setUp(self):
        with patch("anthropic.Anthropic"):
            from analise.avaliador_risco import AvaliadorRisco
            self.avaliador = AvaliadorRisco(api_key="fake-key")
        self.prop = _prop_mock()

    def test_prompt_inclui_identificador(self):
        prompt = self.avaliador._prompt_dimensao("processual", self.prop, [], "ABES")
        self.assertIn("PL 2338/2023", prompt)

    def test_prompt_inclui_ator_focal(self):
        prompt = self.avaliador._prompt_dimensao("coalicao", self.prop, [], "Federação XYZ")
        self.assertIn("Federação XYZ", prompt)

    def test_prompt_inclui_criterios_dimensao(self):
        prompt = self.avaliador._prompt_dimensao("exogeno", self.prop, [], "ABES")
        self.assertIn("conjuntura fiscal", prompt.lower())

    def test_prompt_inclui_evidencias(self):
        ev = Evidencia(
            fonte="Teste", data_coleta="2026-01-01",
            trecho_relevante="Evidência específica.", relevancia="Relevância.",
        )
        prompt = self.avaliador._prompt_dimensao("processual", self.prop, [ev], "ABES")
        self.assertIn("Evidência específica.", prompt)

    def test_prompt_inclui_historico(self):
        """Prompt deve incluir contexto histórico (LGPD, Marco Civil, Fake News)."""
        prompt = self.avaliador._prompt_dimensao("processual", self.prop, [], "ABES")
        self.assertIn("LGPD", prompt)
        self.assertIn("Marco Civil", prompt)
        self.assertIn("Fake News", prompt)


class TestChamarClaude(unittest.TestCase):

    def setUp(self):
        self.mock_client = MagicMock()
        with patch("anthropic.Anthropic", return_value=self.mock_client):
            from analise.avaliador_risco import AvaliadorRisco
            self.avaliador = AvaliadorRisco(api_key="fake-key")
        self.avaliador._client = self.mock_client
        self.avaliador._audit_path = None

    def test_retry_em_rate_limit(self):
        """Teste #9 — retry em 429, 2 chamadas, resultado correto."""
        resposta_ok = _mock_claude_response({
            "nota": 4, "justificativa": "OK.", "alertas": [], "confianca": "ALTO",
        })
        self.mock_client.messages.create.side_effect = [
            anthropic.RateLimitError(
                message="rate limit",
                response=MagicMock(status_code=429, headers={}),
                body={"error": {"message": "rate limit"}},
            ),
            resposta_ok,
        ]
        with patch("time.sleep"):
            resultado = self.avaliador._chamar_claude("prompt", "processual")
        self.assertEqual(resultado["nota"], 4)
        self.assertEqual(resultado["confianca"], "ALTO")
        self.assertEqual(self.mock_client.messages.create.call_count, 2)

    def test_fallback_em_json_invalido(self):
        """Teste #8 — '{"nota": inválido}' retorna nota=3, confiança=BAIXO."""
        self.mock_client.messages.create.return_value = _mock_claude_response(
            '{"nota": inválido}'
        )
        resultado = self.avaliador._chamar_claude("prompt", "agenda")
        self.assertEqual(resultado["nota"], 3)
        self.assertEqual(resultado["confianca"], "BAIXO")
        self.assertTrue(any("fallback" in a.lower() for a in resultado["alertas"]))

    def test_fallback_em_texto_livre(self):
        """Texto não-JSON retorna nota=3, confiança=BAIXO."""
        self.mock_client.messages.create.return_value = _mock_claude_response(
            "isto não é JSON {{{"
        )
        resultado = self.avaliador._chamar_claude("prompt", "coalicao")
        self.assertEqual(resultado["nota"], 3)
        self.assertEqual(resultado["confianca"], "BAIXO")

    def test_resposta_com_markdown_fences(self):
        body = '```json\n{"nota": 5, "justificativa": "J.", "alertas": [], "confianca": "ALTO"}\n```'
        self.mock_client.messages.create.return_value = _mock_claude_response(body)
        resultado = self.avaliador._chamar_claude("prompt", "atores")
        self.assertEqual(resultado["nota"], 5)
        self.assertEqual(resultado["confianca"], "ALTO")

    def test_nota_clampada_entre_1_e_5(self):
        """Notas fora do range são clampeadas."""
        self.mock_client.messages.create.return_value = _mock_claude_response(
            '{"nota": 99, "justificativa": "J.", "alertas": [], "confianca": "ALTO"}'
        )
        resultado = self.avaliador._chamar_claude("prompt", "exogeno")
        self.assertEqual(resultado["nota"], 5)

    def test_confianca_invalida_vira_medio(self):
        """Confiança desconhecida é normalizada para MEDIO."""
        self.mock_client.messages.create.return_value = _mock_claude_response(
            '{"nota": 3, "justificativa": "J.", "alertas": [], "confianca": "ALTÍSSIMO"}'
        )
        resultado = self.avaliador._chamar_claude("prompt", "agenda")
        self.assertEqual(resultado["confianca"], "MEDIO")


# ═══════════════════════════════════════════════════════════════════════════
# GRUPO 4 — Integração mock-to-mock
# ═══════════════════════════════════════════════════════════════════════════

class TestIntegracaoMockToMock(unittest.TestCase):

    def _resp(self, nota: int) -> dict:
        return {
            "nota": nota,
            "justificativa": f"Análise com nota {nota}.",
            "alertas": ["Alerta"],
            "confianca": "MEDIO",
        }

    def test_pipeline_completo_produz_relatorio_valido(self):
        """Pipeline avaliador + gerador com Claude mockado produz RelatorioProspeccao válido."""
        prop = _prop_mock()

        # ── Avaliador ──
        respostas_avaliador = [_mock_claude_response(self._resp(n)) for n in (4, 3, 3, 5, 2)]
        mock_client_a = MagicMock()
        mock_client_a.messages.create.side_effect = respostas_avaliador

        with patch("anthropic.Anthropic", return_value=mock_client_a):
            from analise.avaliador_risco import AvaliadorRisco
            avaliador = AvaliadorRisco(api_key="fake")
        avaliador._client = mock_client_a
        avaliador._audit_path = None

        with patch("analise.avaliador_risco.buscar_noticias", return_value=[]), \
             patch("analise.avaliador_risco.buscar_indicadores_bcb", return_value=[]), \
             patch("analise.avaliador_risco.buscar_discursos_parlamentar", return_value=[]):
            matriz = avaliador.avaliar(prop, "ABES")

        self.assertIsInstance(matriz, MatrizRisco)
        self.assertEqual(matriz.risco_processual.nota, 4)
        self.assertEqual(matriz.risco_atores.nota, 5)

        # ── Gerador ──
        cenarios_json = json.dumps([
            {"tipo": "Base", "probabilidade_estimada": "55-65%",
             "narrativa": "PL avança.", "condicoes_ativacao": ["Relator designado"]},
            {"tipo": "Otimista", "probabilidade_estimada": "15-25%",
             "narrativa": "Acordo.", "condicoes_ativacao": ["Acordo"]},
            {"tipo": "Pessimista", "probabilidade_estimada": "20-30%",
             "narrativa": "Crise.", "condicoes_ativacao": ["Crise"]},
        ])
        acoes_json = json.dumps([
            {"horizonte": "Imediato (0-30 dias)", "acao": f"Ação {i}",
             "responsavel_sugerido": "RIG", "prioridade": "Alta"}
            for i in range(6)
        ])
        kpis_json = json.dumps([f"KPI {i}" for i in range(6)])
        sintese = "Zona de Atenção com score 3.50. Recomenda-se articulação."

        mock_client_g = MagicMock()
        mock_client_g.messages.create.side_effect = [
            _mock_claude_response(cenarios_json),
            _mock_claude_response(acoes_json),
            _mock_claude_response(kpis_json),
            _mock_claude_response(sintese),
        ]

        with patch("anthropic.Anthropic", return_value=mock_client_g):
            from analise.gerador_prospeccao import GeradorProspeccao
            gerador = GeradorProspeccao(api_key="fake")
        gerador._client = mock_client_g
        gerador._audit_path = None

        relatorio = gerador.gerar(prop, matriz, "ABES")

        self.assertIsInstance(relatorio, RelatorioProspeccao)
        self.assertEqual(relatorio.proposicao_id, "PL 2338/2023")
        self.assertEqual(relatorio.ator_focal, "ABES")
        self.assertEqual(len(relatorio.cenarios), 3)
        self.assertEqual(relatorio.cenarios[0].tipo, "Base")
        self.assertGreaterEqual(len(relatorio.acoes), 6)
        self.assertGreaterEqual(len(relatorio.kpis_monitoramento), 6)
        self.assertGreater(len(relatorio.limitacoes_analise), 0)
        self.assertEqual(relatorio.matriz.score_consolidado, matriz.score_consolidado)
        self.assertEqual(relatorio.matriz.zona_risco, matriz.zona_risco)


if __name__ == "__main__":
    unittest.main(verbosity=2)
