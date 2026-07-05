"""Testes do Módulo 1 — coleta de dados legislativos."""

import unittest
from unittest.mock import MagicMock, patch

from coleta.schemas import ProposicaoInfo
from coleta.coletor import coletar


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _pl_2338() -> ProposicaoInfo:
    return ProposicaoInfo(
        origem="camara", tipo_sigla="PL", numero=2338, ano=2023,
        ementa="Dispõe sobre o uso da Inteligência Artificial no Brasil.",
        situacao_atual="Em Comissão",
        ultimo_evento="Notificação de Apensação",
        ultimo_evento_data="2026-06-17",
        autor="Senado Federal - Rodrigo Pacheco",
        relator_designado="Aguinaldo Ribeiro",
        comissoes_pendentes=["CCTCI", "CCJ"],
        regime_tramitacao="Prioridade",
    )


def _pl_278() -> ProposicaoInfo:
    return ProposicaoInfo(
        origem="senado", tipo_sigla="PL", numero=278, ano=2026,
        ementa="Dispõe sobre plataformas digitais e moderação de conteúdo.",
        situacao_atual="Tramitando",
        ultimo_evento="Recebimento",
        ultimo_evento_data="2026-03-18",
        autor="Sen. Exemplo",
        relator_designado=None,
        comissoes_pendentes=["CCT"],
        regime_tramitacao="Urgência",
    )


# ═══════════════════════════════════════════════════════════════════════════
# GRUPO 1 — Schema ProposicaoInfo
# ═══════════════════════════════════════════════════════════════════════════

class TestProposicaoInfoSchema(unittest.TestCase):

    def test_identificador_formatado(self):
        """tipo_sigla + numero + ano formam o identificador correto."""
        prop = _pl_2338()
        ident = f"{prop.tipo_sigla} {prop.numero}/{prop.ano}"
        self.assertEqual(ident, "PL 2338/2023")

    def test_dados_completos_com_relator(self):
        """Proposição com todos os campos preenchidos é considerada completa."""
        prop = _pl_2338()
        completo = bool(
            prop.ementa and prop.situacao_atual and prop.relator_designado
            and prop.comissoes_pendentes and prop.regime_tramitacao
        )
        self.assertTrue(completo)

    def test_dados_incompletos_sem_relator(self):
        """Proposição sem relator designado é incompleta."""
        prop = _pl_278()
        self.assertIsNone(prop.relator_designado)

    def test_comissoes_pendentes_acumula(self):
        """Lista de comissões pendentes acumula corretamente."""
        prop = _pl_2338()
        self.assertEqual(len(prop.comissoes_pendentes), 2)
        self.assertIn("CCTCI", prop.comissoes_pendentes)
        self.assertIn("CCJ", prop.comissoes_pendentes)

    def test_origem_camara(self):
        prop = _pl_2338()
        self.assertEqual(prop.origem, "camara")

    def test_origem_senado(self):
        prop = _pl_278()
        self.assertEqual(prop.origem, "senado")


# ═══════════════════════════════════════════════════════════════════════════
# GRUPO 2 — Mock data integrity
# ═══════════════════════════════════════════════════════════════════════════

class TestMockDataPL2338(unittest.TestCase):

    def setUp(self):
        self.prop = _pl_2338()

    def test_relator(self):
        self.assertEqual(self.prop.relator_designado, "Aguinaldo Ribeiro")

    def test_regime_prioridade(self):
        self.assertEqual(self.prop.regime_tramitacao, "Prioridade")

    def test_situacao_em_comissao(self):
        self.assertEqual(self.prop.situacao_atual, "Em Comissão")

    def test_autor(self):
        self.assertIn("Rodrigo Pacheco", self.prop.autor)

    def test_comissoes_minimo_2(self):
        self.assertGreaterEqual(len(self.prop.comissoes_pendentes), 2)


class TestMockDataPL278(unittest.TestCase):

    def setUp(self):
        self.prop = _pl_278()

    def test_casa_senado(self):
        self.assertEqual(self.prop.origem, "senado")

    def test_regime_urgencia(self):
        self.assertEqual(self.prop.regime_tramitacao, "Urgência")

    def test_ultimo_evento_data(self):
        self.assertEqual(self.prop.ultimo_evento_data, "2026-03-18")

    def test_sem_relator(self):
        self.assertIsNone(self.prop.relator_designado)


# ═══════════════════════════════════════════════════════════════════════════
# GRUPO 3 — Resolução de casa no coletor
# ═══════════════════════════════════════════════════════════════════════════

class TestResolucaoCasa(unittest.TestCase):

    @patch("coleta.coletor.senado_buscar")
    def test_casa_senado_chama_api_senado(self, mock_senado):
        """casa='senado' deve chamar a API do Senado."""
        mock_senado.return_value = _pl_278().model_dump()

        resultado = coletar("PL", 278, 2026, casa="senado")

        mock_senado.assert_called_once_with("PL", 278, 2026)
        self.assertEqual(resultado.origem, "senado")

    @patch("coleta.coletor.camara_buscar")
    @patch("coleta.coletor.camara_buscar_id", return_value=12345)
    def test_casa_camara_chama_api_camara(self, mock_id, mock_camara):
        """casa='camara' deve chamar a API da Câmara."""
        mock_camara.return_value = _pl_2338().model_dump()

        resultado = coletar("PL", 2338, 2023, casa="camara")

        mock_id.assert_called_once_with("PL", 2338, 2023)
        mock_camara.assert_called_once_with(12345)
        self.assertEqual(resultado.origem, "camara")

    @patch("coleta.coletor._coletar_senado")
    @patch("coleta.coletor._coletar_camara")
    def test_auto_tenta_camara_primeiro(self, mock_camara, mock_senado):
        """casa='auto' deve tentar Câmara primeiro."""
        mock_camara.return_value = _pl_2338()

        resultado = coletar("PL", 2338, 2023, casa="auto")

        mock_camara.assert_called_once()
        mock_senado.assert_not_called()

    @patch("coleta.coletor._coletar_senado")
    @patch("coleta.coletor._coletar_camara")
    def test_auto_fallback_para_senado(self, mock_camara, mock_senado):
        """casa='auto' deve tentar Senado se Câmara falhar."""
        mock_camara.side_effect = ValueError("Não encontrado")
        mock_senado.return_value = _pl_278()

        resultado = coletar("PL", 278, 2026, casa="auto")

        mock_camara.assert_called_once()
        mock_senado.assert_called_once()
        self.assertEqual(resultado.origem, "senado")


if __name__ == "__main__":
    unittest.main(verbosity=2)
