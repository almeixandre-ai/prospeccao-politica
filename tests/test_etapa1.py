"""Testes da Etapa 1 (enriquecimento TSE) com arquivos sintéticos no layout do Portal de Dados Abertos."""

import csv
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from eleicoes import etapa1_tse as e1


def _zip(path: Path, arquivos: dict[str, list[dict]]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for nome, rows in arquivos.items():
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), delimiter=";", quoting=csv.QUOTE_ALL)
            w.writeheader()
            w.writerows(rows)
            zf.writestr(nome, buf.getvalue().encode("latin-1"))
    return path


def _cand(sq, uf, cargo, num, nome, urna, sit="ELEITO POR QP", **kw):
    base = {"NR_TURNO": "1", "SG_UF": uf, "CD_CARGO": cargo, "SQ_CANDIDATO": sq, "NR_CANDIDATO": num,
            "NM_CANDIDATO": nome, "NM_URNA_CANDIDATO": urna, "DT_NASCIMENTO": "15/03/1980",
            "DS_GENERO": "FEMININO", "DS_GRAU_INSTRUCAO": "SUPERIOR COMPLETO", "DS_OCUPACAO": "ADVOGADO",
            "SG_UF_NASCIMENTO": "MG", "NM_MUNICIPIO_NASCIMENTO": "BELO HORIZONTE", "DS_SIT_TOT_TURNO": sit}
    base.update(kw)
    return base


def _mz(sq, uf, mun, zona, votos, turno="1"):
    return {"NR_TURNO": turno, "SG_UF": uf, "NM_MUNICIPIO": mun, "NR_ZONA": zona, "SQ_CANDIDATO": sq,
            "QT_VOTOS_NOMINAIS_VALIDOS": str(votos)}


class TestEtapa1(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        comp = {
            "deputados": [
                {"casa": "camara", "uf": "AC", "nome_urna": "FULANA", "nome_completo": "FULANA DE TAL",
                 "partido": "PT", "federacao": None, "numero": "1301", "votos": 1000, "situacao": "Eleito por QP",
                 "origem": "tse_2026", "sq_candidato": "111", "chave": "camara_AC_111"},
                # sem SQ coincidente → deve casar pelo número
                {"casa": "camara", "uf": "AC", "nome_urna": "BELTRANO", "nome_completo": "BELTRANO X",
                 "partido": "PL", "federacao": None, "numero": "2222", "votos": 500, "situacao": "Eleito por média",
                 "origem": "tse_2026", "sq_candidato": "999", "chave": "camara_AC_999"},
            ],
            "senadores": [
                {"casa": "senado", "uf": "AC", "nome_urna": "Sicrano", "nome_completo": "SICRANO DA SILVA",
                 "partido": "MDB", "federacao": None, "numero": None, "votos": None, "situacao": "Mandato até 2031",
                 "origem": "senado_2022", "sq_candidato": None, "chave": "senado_AC_77"},
            ],
        }
        self.comp = self.tmp / "comp.json"
        self.comp.write_text(json.dumps(comp), encoding="utf-8")
        z = {
            ("cand", 2026): _zip(self.tmp / "c26.zip", {
                "consulta_cand_2026_AC.csv": [
                    _cand("111", "AC", "6", "1301", "FULANA DE TAL", "FULANA"),
                    _cand("222", "AC", "6", "2222", "BELTRANO X", "BELTRANO", DT_NASCIMENTO="#NULO#",
                          DS_GENERO="MASCULINO"),
                    _cand("333", "AC", "6", "1301", "OUTRO", "OUTRO", NR_TURNO="2"),  # 2º turno: ignorar
                ],
                "consulta_cand_2026_BRASIL.csv": [_cand("111", "AC", "6", "1301", "DUP", "DUP")],  # ignorado
            }),
            ("munzona", 2026): _zip(self.tmp / "m26.zip", {
                "votacao_candidato_munzona_2026_AC.csv": [
                    _mz("111", "AC", "RIO BRANCO", "1", 500), _mz("111", "AC", "RIO BRANCO", "9", 100),
                    _mz("111", "AC", "CRUZEIRO DO SUL", "4", 300), _mz("111", "AC", "XAPURI", "5", 100),
                    _mz("222", "AC", "RIO BRANCO", "1", 400), _mz("222", "AC", "BRASILEIA", "2", 50),
                ]}),
            ("cand", 2022): _zip(self.tmp / "c22.zip", {
                "consulta_cand_2022_AC.csv": [
                    _cand("777", "AC", "5", "151", "SICRANO DA SILVA", "SICRANO", sit="ELEITO", DS_GENERO="MASCULINO"),
                ]}),
            ("munzona", 2022): _zip(self.tmp / "m22.zip", {
                "votacao_candidato_munzona_2022_AC.csv": [_mz("777", "AC", "RIO BRANCO", "1", 9000)]}),
        }
        self.saida = self.tmp / "out"
        self.cob = e1.executar(self.tmp, comp_path=self.comp, dir_saida=self.saida, zips=z)
        self.fichas = {f["chave"]: f for f in json.loads((self.saida / "fichas_etapa1.json").read_text("utf-8"))}

    def test_demografia_e_idade_na_posse(self):
        f = self.fichas["camara_AC_111"]
        self.assertEqual(f["genero"], "FEMININO")
        self.assertEqual(f["idade_na_posse"], 46)  # 15/03/1980 → 01/02/2027
        self.assertEqual(f["municipio_nascimento"], "BELO HORIZONTE")
        self.assertEqual(f["metodo_cruzamento_tse"], "sq_candidato")

    def test_fallback_por_numero_e_campo_nulo(self):
        f = self.fichas["camara_AC_999"]
        self.assertEqual(f["metodo_cruzamento_tse"], "uf+cargo+numero")
        self.assertEqual(f["data_nascimento"], e1.AUSENTE)
        self.assertEqual(f["idade_na_posse"], e1.AUSENTE)
        self.assertEqual(f["n_municipios_com_voto"], 2)  # votos via SQ do TSE (222), não o da composição

    def test_redutos_somam_zonas_e_percentuais(self):
        f = self.fichas["camara_AC_111"]
        self.assertEqual(f["redutos"][0], {"municipio": "RIO BRANCO", "votos": 600, "pct": 60.0})
        self.assertEqual(f["concentracao_top5_pct"], 100.0)
        self.assertEqual(f["votos_somados_municipios"], 1000)
        self.assertEqual(f["hhi"], 4600)

    def test_senador_2022_por_nome(self):
        f = self.fichas["senado_AC_77"]
        self.assertEqual(f["metodo_cruzamento_tse"], "uf+cargo+nome")
        self.assertEqual(f["genero"], "MASCULINO")
        self.assertEqual(f["votos_somados_municipios"], 9000)
        self.assertEqual(f["votos_nominais"], e1.AUSENTE)

    def test_divergencia_e_csv(self):
        chaves = [d["chave"] for d in self.cob["divergencias_votos"]]
        self.assertIn("camara_AC_999", chaves)  # 450 no TSE × 500 na composição
        self.assertNotIn("camara_AC_111", chaves)
        with open(self.saida / "fichas_etapa1.csv", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh, delimiter=";"))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["reduto_1"], "RIO BRANCO (600 | 60.0%)")

    def test_fonte_indisponivel_marca_ausente(self):
        out = self.tmp / "out2"
        cob = e1.executar(self.tmp, comp_path=self.comp, dir_saida=out,
                          zips={("cand", 2026): None, ("munzona", 2026): None,
                                ("cand", 2022): None, ("munzona", 2022): None})
        f = json.loads((out / "fichas_etapa1.json").read_text("utf-8"))[0]
        self.assertEqual(f["genero"], e1.AUSENTE)
        self.assertEqual(f["redutos"], [])
        self.assertFalse(cob["fontes_disponiveis"]["cand_2026"])


if __name__ == "__main__":
    unittest.main()
