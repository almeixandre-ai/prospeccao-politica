"""Regras do índice de familiaridade (0–3 por eixo)."""

import unittest

from eleicoes import familiaridade as fm


def _dossie(**kw):
    base = {"parlamentar_chave": "camara_XX_1", "nome_urna": "TESTE", "casa_2027": "camara", "uf": "XX",
            "partido": "P", "iip": 10, "prioridade": "B", "proposicoes_agenda": [], "relatorias_agenda": [],
            "orgaos": [], "frentes": [], "limitacoes": []}
    base.update(kw)
    return base


def _prop(i, ementa, principal=True):
    return {"identificacao": f"PL {i}/2025", "ementa": ementa, "e_autor_principal": principal, "url": None}


IA = "Dispõe sobre o uso de inteligência artificial em serviços públicos."


class TestEixos(unittest.TestCase):
    def test_termos_nucleo(self):
        self.assertEqual(fm.eixos_da_ementa(IA), ["E1"])
        self.assertIn("E2", fm.eixos_da_ementa("Altera a Lei nº 13.709, de 14 de agosto de 2018"))
        self.assertIn("E4", fm.eixos_da_ementa("Altera a Lei nº 9.472 sobre serviços de telecomunicações"))

    def test_exclusoes_e_intencao_regulatoria(self):
        self.assertEqual(fm.eixos_da_ementa("Programa de adoção de animais divulgado em plataformas digitais"), [])
        self.assertEqual(fm.eixos_da_ementa("Campanha educativa divulgada nas redes sociais"), [])
        self.assertIn("E3", fm.eixos_da_ementa("Obriga plataformas digitais a oferecer controle parental"))


class TestNotas(unittest.TestCase):
    def test_volume_sozinho_nao_passa_de_2(self):
        d = _dossie(proposicoes_agenda=[_prop(i, IA) for i in range(30)])
        self.assertEqual(fm.calcular(d, {})["notas"]["E1"], 2)

    def test_relatoria_mais_colegiado_especifico_da_3(self):
        d = _dossie(relatorias_agenda=[{"identificacao": "PL 9/2024", "ementa": IA}],
                    orgaos=["PL233823 — Titular (Câmara): Comissão Especial ... IA"])
        self.assertEqual(fm.calcular(d, {})["notas"]["E1"], 3)

    def test_vice_de_comissao_permanente_nao_e_lideranca(self):
        d = _dossie(orgaos=["CCOM — 3º Vice-Presidente (Câmara): Comissão de Comunicação"])
        r = fm.calcular(d, {})
        self.assertEqual(r["notas"]["E3"], 1)

    def test_frente_so_da_1_e_ajuste_manual_com_fonte(self):
        d = _dossie(frentes=["Frente Parlamentar Mista da Economia e Cidadania Digitais (Frente Digital)"])
        self.assertEqual(fm.calcular(d, {})["notas"]["E1"], 1)
        aj = {"camara_XX_1": {"sinais": [{"eixo": "E1", "tipo": "relatoria", "id": "PL 1/2025",
                                          "descricao": "x", "fonte": "https://exemplo"}] * 3}}
        self.assertEqual(fm.calcular(d, aj)["notas"]["E1"], 3)

    def test_alinhamento_so_com_evidencia(self):
        neutro = fm.calcular(_dossie(proposicoes_agenda=[_prop(1, IA)]), {})
        self.assertEqual(neutro["sinal_alinhamento_abes"], "indeterminado")
        bancos = _dossie(proposicoes_agenda=[_prop(2, "Responsabilidade objetiva das instituições financeiras em fraudes")])
        self.assertEqual(fm.calcular(bancos, {})["sinal_alinhamento_abes"], "indeterminado")
        prov = _dossie(proposicoes_agenda=[_prop(3, "Estabelece a responsabilidade solidária dos provedores de aplicações")])
        self.assertEqual(fm.calcular(prov, {})["sinal_alinhamento_abes"], "atenção (indícios)")


if __name__ == "__main__":
    unittest.main()
