"""Etapa 1 — enriquece a composição 2027 com dados do Portal de Dados Abertos do TSE.

Fontes (CDN do TSE, arquivos .zip com CSVs ';' em latin-1):
  - consulta_cand_<ANO>.zip            → nascimento, gênero, instrução, ocupação, naturalidade
  - votacao_candidato_munzona_<ANO>.zip → votos nominais por município/zona (redutos)

Cruzamento por SQ_CANDIDATO; se não houver, por (UF, cargo, número). Os 27 senadores com
mandato até 2031 são buscados nos arquivos de 2022, por UF + nome.

Nada é inferido: campo ausente na fonte sai como "[Dado não localizado na base]".

Uso:
    python -m eleicoes.etapa1_tse                 # baixa 2026 e 2022 e gera as saídas
    python -m eleicoes.etapa1_tse --dir-cache /tmp/tse --sem-2022
    python -m eleicoes.etapa1_tse --sondar         # só testa as URLs
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import logging
import sys
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .historico_camara import normalizar

log = logging.getLogger("prospeccao.etapa1")

CDN = "https://cdn.tse.jus.br/estatistica/sead/odsele"
URL_CAND = CDN + "/consulta_cand/consulta_cand_{ano}.zip"
URL_MUNZONA = CDN + "/votacao_candidato_munzona/votacao_candidato_munzona_{ano}.zip"

RAIZ = Path(__file__).resolve().parent.parent
ARQ_COMPOSICAO = RAIZ / "output" / "eleicoes2026" / "composicao_2027.json"
DIR_SAIDA = RAIZ / "output" / "eleicoes2026" / "etapa1"

AUSENTE = "[Dado não localizado na base]"
DATA_POSSE = {"camara": date(2027, 2, 1), "senado": date(2027, 2, 1)}
CARGOS = {"camara": "6", "senado": "5"}  # CD_CARGO no TSE
SUPLENTE_1, SUPLENTE_2 = "9", "10"
NOME_CARGO = {"camara": "Deputado(a) Federal", "senado": "Senador(a)"}
TOP_REDUTOS = 5

csv.field_size_limit(10**8)


# ── Download ─────────────────────────────────────────────────────────────────

def baixar(url: str, destino: Path) -> Path | None:
    """Baixa com cache; devolve None se o arquivo ainda não foi publicado (404)."""
    import requests

    if destino.exists() and destino.stat().st_size > 0:
        log.info("Cache: %s", destino.name)
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    log.info("Baixando %s", url)
    with requests.get(url, stream=True, timeout=300) as r:
        if r.status_code == 404:
            log.warning("Ainda não publicado (404): %s", url)
            return None
        r.raise_for_status()
        tmp = destino.with_suffix(".part")
        with open(tmp, "wb") as fh:
            for bloco in r.iter_content(1 << 20):
                fh.write(bloco)
        tmp.rename(destino)
    log.info("OK: %s (%.1f MB)", destino.name, destino.stat().st_size / 1e6)
    return destino


def sondar(anos: list[int]) -> dict[str, int]:
    import requests

    res = {}
    for ano in anos:
        for url in (URL_CAND.format(ano=ano), URL_MUNZONA.format(ano=ano)):
            try:
                r = requests.head(url, timeout=60, allow_redirects=True)
                res[url] = r.status_code
            except Exception as e:  # noqa: BLE001
                res[url] = -1
                log.warning("%s: %s", url, e)
    return res


# ── Leitura dos CSVs dentro do zip ───────────────────────────────────────────

def _membros_csv(zf: zipfile.ZipFile) -> list[str]:
    """Prefere os arquivos por UF; usa o _BRASIL só se for o único (evita contar em dobro)."""
    nomes = [n for n in zf.namelist() if n.lower().endswith(".csv")]
    por_uf = [n for n in nomes if "brasil" not in n.lower()]
    return por_uf or nomes


def _uf_do_arquivo(nome: str) -> str | None:
    m = re.search(r"_([A-Z]{2})\.csv$", Path(nome).name, re.IGNORECASE)
    return m.group(1).upper() if m else None


def linhas(zip_path: Path):
    """Lê os CSVs por UF; do _BRASIL, só as UFs que não têm arquivo próprio no zip."""
    with zipfile.ZipFile(zip_path) as zf:
        nomes = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        por_uf = [n for n in nomes if "brasil" not in n.lower()]
        brasil = [n for n in nomes if "brasil" in n.lower()]
        cobertas = {_uf_do_arquivo(n) for n in por_uf} - {None}
        for nome in (por_uf or brasil) + (brasil if por_uf else []):
            so_faltantes = por_uf and nome in brasil
            with zf.open(nome) as raw:
                texto = io.TextIOWrapper(raw, encoding="latin-1", newline="")
                for row in csv.DictReader(texto, delimiter=";", quotechar='"'):
                    if so_faltantes and (row.get("SG_UF") or "").strip() in cobertas:
                        continue
                    yield row


def diagnosticar(zip_path: Path) -> dict:
    """Arquivos CSV do zip e cabeçalho do primeiro — para auditar mudanças de layout do TSE."""
    with zipfile.ZipFile(zip_path) as zf:
        membros = sorted(n for n in zf.namelist() if n.lower().endswith(".csv"))
        cab = []
        if membros:
            with zf.open(_membros_csv(zf)[0]) as raw:
                cab = next(csv.reader(io.TextIOWrapper(raw, encoding="latin-1", newline=""), delimiter=";"), [])
    return {"arquivos_csv": [Path(m).name for m in membros], "colunas": cab}


def _v(row: dict, *cols: str) -> str | None:
    for c in cols:
        v = (row.get(c) or "").strip()
        if v and v not in ("#NULO#", "#NULO", "#NE#", "-1", "-3", "NÃO DIVULGÁVEL"):
            return v
    return None


def _turno1(row: dict) -> bool:
    return (row.get("NR_TURNO") or "1").strip() in ("1", "")


# ── Cruzamento ───────────────────────────────────────────────────────────────

@dataclass
class Indice:
    por_sq: dict[str, dict] = field(default_factory=dict)
    por_numero: dict[tuple[str, str, str], dict] = field(default_factory=dict)
    por_nome: dict[tuple[str, str, str], list[dict]] = field(default_factory=lambda: defaultdict(list))


def indexar_candidatos(zip_path: Path, cargos: set[str], so_eleitos: bool = False) -> Indice:
    idx = Indice()
    for row in linhas(zip_path):
        if (row.get("CD_CARGO") or "").strip() not in cargos or not _turno1(row):
            continue
        if (so_eleitos and row["CD_CARGO"].strip() not in (SUPLENTE_1, SUPLENTE_2)
                and not (row.get("DS_SIT_TOT_TURNO") or "").upper().startswith("ELEITO")):
            continue
        sq = (row.get("SQ_CANDIDATO") or "").strip()
        uf, cargo, num = row.get("SG_UF", "").strip(), row["CD_CARGO"].strip(), (row.get("NR_CANDIDATO") or "").strip()
        if sq:
            idx.por_sq[sq] = row
        if num:
            idx.por_numero[(uf, cargo, num)] = row
        for nome in (row.get("NM_CANDIDATO"), row.get("NM_URNA_CANDIDATO")):
            if nome:
                idx.por_nome[(uf, cargo, normalizar(nome))].append(row)
    log.info("%s: %d candidatos indexados", zip_path.name, len(idx.por_sq))
    return idx


def casar(p: dict, idx: Indice) -> tuple[dict | None, str]:
    cargo = CARGOS[p["casa"]]
    if p.get("sq_candidato") and p["sq_candidato"] in idx.por_sq:
        return idx.por_sq[p["sq_candidato"]], "sq_candidato"
    if p.get("numero") and (p["uf"], cargo, str(p["numero"])) in idx.por_numero:
        return idx.por_numero[(p["uf"], cargo, str(p["numero"]))], "uf+cargo+numero"
    # Senado: suplentes em exercício foram registrados como 1º/2º suplente (cargos 9 e 10)
    for cg, rotulo in [(cargo, "uf+cargo+nome")] + (
            [(SUPLENTE_1, "uf+nome (1º suplente)"), (SUPLENTE_2, "uf+nome (2º suplente)")]
            if p["casa"] == "senado" else []):
        for nome in (p.get("nome_completo"), p.get("nome_urna")):
            achados = idx.por_nome.get((p["uf"], cg, normalizar(nome or "")), [])
            if len(achados) == 1:
                return achados[0], rotulo
    return None, "nao_encontrado"


# ── Votos por município ──────────────────────────────────────────────────────

DIAG_MUNZONA: dict[str, dict] = {}


def votos_por_municipio(zip_path: Path, alvos: dict[str, str]) -> dict[str, dict[str, int]]:
    """alvos: SQ_CANDIDATO → chave. Soma as zonas de cada município (1º turno, votos nominais)."""
    acc: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    diag: dict[str, dict] = defaultdict(lambda: {"linhas": 0, "turnos": set(), "cargos": set(), "amostra_sq_dep": []})
    for row in linhas(zip_path):
        sq = (row.get("SQ_CANDIDATO") or "").strip()
        uf = (row.get("SG_UF") or "").strip()
        d = diag[uf]
        d["linhas"] += 1
        d["turnos"].add((row.get("NR_TURNO") or "").strip())
        d["cargos"].add((row.get("CD_CARGO") or "").strip())
        if (row.get("CD_CARGO") or "").strip() == "6" and len(d["amostra_sq_dep"]) < 3 and sq not in d["amostra_sq_dep"]:
            d["amostra_sq_dep"].append(sq)
        if sq not in alvos or not _turno1(row):
            continue
        mun = _v(row, "NM_MUNICIPIO") or AUSENTE
        qt = _v(row, "QT_VOTOS_NOMINAIS_VALIDOS", "QT_VOTOS_NOMINAIS", "QT_VOTOS")
        try:
            acc[sq][mun] += int(float(qt)) if qt else 0
        except ValueError:
            continue
    DIAG_MUNZONA[zip_path.name] = {uf: {**d, "turnos": sorted(d["turnos"]), "cargos": sorted(d["cargos"])}
                                   for uf, d in diag.items()}
    return acc


def redutos(mun: dict[str, int]) -> dict:
    total = sum(mun.values())
    ranking = sorted(mun.items(), key=lambda kv: -kv[1])
    def pct(v: int) -> float:
        return round(100 * v / total, 2) if total else 0.0
    top = [{"municipio": m, "votos": v, "pct": pct(v)} for m, v in ranking[:TOP_REDUTOS]]
    hhi = round(sum((v / total) ** 2 for v in mun.values()) * 10000) if total else None
    return {
        "votos_somados_municipios": total,
        "n_municipios_com_voto": sum(1 for v in mun.values() if v > 0),
        "redutos": top,
        "concentracao_top1_pct": top[0]["pct"] if top else None,
        "concentracao_top5_pct": round(sum(t["pct"] for t in top), 2) if top else None,
        "hhi": hhi,  # 0–10000; >2500 = votação muito concentrada
        "ranking_completo": [{"municipio": m, "votos": v, "pct": pct(v)} for m, v in ranking],
    }


# ── Ficha ────────────────────────────────────────────────────────────────────

def _idade(nasc: str | None, posse: date) -> int | None:
    if not nasc:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            d = datetime.strptime(nasc, fmt).date()
            return posse.year - d.year - ((posse.month, posse.day) < (d.month, d.day))
        except ValueError:
            continue
    return None


def ficha(p: dict, cand: dict | None, metodo: str, votos_mun: dict[str, int] | None) -> dict:
    c = cand or {}
    nasc = _v(c, "DT_NASCIMENTO")
    idade = _idade(nasc, DATA_POSSE[p["casa"]])
    f = {
        "chave": p["chave"],
        "nome_completo": p.get("nome_completo") or _v(c, "NM_CANDIDATO") or AUSENTE,
        "nome_urna": p.get("nome_urna") or AUSENTE,
        "sq_candidato": p.get("sq_candidato") or _v(c, "SQ_CANDIDATO") or AUSENTE,
        "data_nascimento": nasc or AUSENTE,
        "idade_na_posse": idade if idade is not None else AUSENTE,
        "genero": _v(c, "DS_GENERO") or AUSENTE,
        "grau_instrucao": _v(c, "DS_GRAU_INSTRUCAO") or AUSENTE,
        "ocupacao": _v(c, "DS_OCUPACAO") or AUSENTE,
        "municipio_nascimento": _v(c, "NM_MUNICIPIO_NASCIMENTO") or AUSENTE,
        "uf_nascimento": _v(c, "SG_UF_NASCIMENTO") or AUSENTE,
        "cargo": NOME_CARGO[p["casa"]],
        "uf": p["uf"],
        "partido": p.get("partido") or AUSENTE,
        "federacao": p.get("federacao") or _v(c, "NM_FEDERACAO", "SG_FEDERACAO") or "Sem federação",
        "situacao": p.get("situacao"),
        "origem": p.get("origem"),
        "votos_nominais": p.get("votos") if p.get("votos") is not None else AUSENTE,
        "metodo_cruzamento_tse": metodo,
    }
    if votos_mun:
        f.update(redutos(votos_mun))
    else:
        f.update({"votos_somados_municipios": AUSENTE, "n_municipios_com_voto": AUSENTE, "redutos": [],
                  "concentracao_top1_pct": AUSENTE, "concentracao_top5_pct": AUSENTE, "hhi": AUSENTE,
                  "ranking_completo": []})
    return f


COLS_CSV = [
    "chave", "nome_completo", "nome_urna", "sq_candidato", "data_nascimento", "idade_na_posse", "genero",
    "grau_instrucao", "ocupacao", "municipio_nascimento", "uf_nascimento", "cargo", "uf", "partido",
    "federacao", "situacao", "origem", "votos_nominais", "n_municipios_com_voto",
    *[f"reduto_{i}" for i in range(1, TOP_REDUTOS + 1)],
    "concentracao_top1_pct", "concentracao_top5_pct", "hhi", "metodo_cruzamento_tse",
]


def _linha_csv(f: dict) -> dict:
    r = {k: f.get(k, "") for k in COLS_CSV}
    for i in range(TOP_REDUTOS):
        red = f["redutos"][i] if i < len(f["redutos"]) else None
        r[f"reduto_{i + 1}"] = f"{red['municipio']} ({red['votos']} | {red['pct']}%)" if red else ""
    return r


# ── Orquestração ─────────────────────────────────────────────────────────────

def executar(dir_cache: Path, incluir_2022: bool = True, comp_path: Path = ARQ_COMPOSICAO,
             dir_saida: Path = DIR_SAIDA, zips: dict | None = None) -> dict:
    comp = json.loads(comp_path.read_text(encoding="utf-8"))
    parls = comp["deputados"] + comp["senadores"]
    zips = zips or {}
    for ano in ([2026, 2022] if incluir_2022 else [2026]):
        for tipo, url in (("cand", URL_CAND), ("munzona", URL_MUNZONA)):
            if (tipo, ano) not in zips:
                zips[(tipo, ano)] = baixar(url.format(ano=ano), dir_cache / Path(url.format(ano=ano)).name)

    fontes = {f"{t}_{a}": bool(z) for (t, a), z in zips.items()}
    diagnostico = {f"{t}_{a}": diagnosticar(z) for (t, a), z in zips.items() if z}
    casados: dict[str, tuple[dict | None, str, int]] = {}
    grupos = {2026: [p for p in parls if p["origem"] == "tse_2026"],
              2022: [p for p in parls if p["origem"] == "senado_2022"]}
    for ano, grupo in grupos.items():
        z = zips.get(("cand", ano))
        if not grupo:
            continue
        if not z:
            for p in grupo:
                casados[p["chave"]] = (None, f"consulta_cand_{ano} indisponível", ano)
            continue
        idx = indexar_candidatos(z, {"5", "6"} if ano == 2026 else {"5", SUPLENTE_1, SUPLENTE_2},
                                 so_eleitos=(ano == 2022))
        for p in grupo:
            cand, metodo = casar(p, idx)
            casados[p["chave"]] = (cand, metodo, ano)

    votos: dict[str, dict[str, int]] = {}
    for ano in grupos:
        z = zips.get(("munzona", ano))
        alvos = {}
        for p in grupos[ano]:
            cand = casados.get(p["chave"], (None,))[0]
            sq = (cand or {}).get("SQ_CANDIDATO") or (p.get("sq_candidato") if ano == 2026 else None)
            if sq:
                alvos[sq.strip()] = p["chave"]
        if z and alvos:
            for sq, mun in votos_por_municipio(z, alvos).items():
                votos[alvos[sq]] = mun

    fichas = []
    for p in parls:
        cand, metodo, _ = casados.get(p["chave"], (None, "nao_processado", None))
        fichas.append(ficha(p, cand, metodo, votos.get(p["chave"])))

    cobertura = {
        "data_execucao": date.today().isoformat(),
        "fontes_disponiveis": fontes,
        "total": len(fichas),
        "cruzamento": {},
        "campos_preenchidos": {},
        "divergencias_votos": [],
        "diagnostico_arquivos": diagnostico,
    }
    sem_voto_uf = sorted({f["uf"] for f in fichas if f["n_municipios_com_voto"] == AUSENTE and f["origem"] == "tse_2026"})
    cobertura["diagnostico_munzona_ufs_sem_voto"] = {
        nome: {uf: d.get(uf, "UF ausente no arquivo") for uf in sem_voto_uf} for nome, d in DIAG_MUNZONA.items()
    }
    cobertura["sq_esperados_ufs_sem_voto"] = {
        uf: [f["sq_candidato"] for f in fichas if f["uf"] == uf and f["origem"] == "tse_2026"][:3] for uf in sem_voto_uf
    }
    cont = defaultdict(int)
    for f in fichas:
        cont[f["metodo_cruzamento_tse"]] += 1
    cobertura["cruzamento"] = dict(cont)
    for campo in ("data_nascimento", "genero", "grau_instrucao", "ocupacao", "municipio_nascimento",
                  "uf_nascimento", "n_municipios_com_voto"):
        cobertura["campos_preenchidos"][campo] = sum(1 for f in fichas if f[campo] != AUSENTE)
    for f in fichas:  # controle: soma municipal × total nominal da composição
        if isinstance(f["votos_nominais"], int) and isinstance(f["votos_somados_municipios"], int):
            dif = f["votos_somados_municipios"] - f["votos_nominais"]
            if f["votos_nominais"] and abs(dif) / f["votos_nominais"] > 0.01:
                cobertura["divergencias_votos"].append(
                    {"chave": f["chave"], "nome_urna": f["nome_urna"], "composicao": f["votos_nominais"],
                     "soma_municipios": f["votos_somados_municipios"]})

    dir_saida.mkdir(parents=True, exist_ok=True)
    (dir_saida / "fichas_etapa1.json").write_text(json.dumps(fichas, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(dir_saida / "fichas_etapa1.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS_CSV, delimiter=";")
        w.writeheader()
        w.writerows(_linha_csv(f) for f in fichas)
    with open(dir_saida / "votos_por_municipio.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["chave", "nome_urna", "uf", "cargo", "posicao", "municipio", "votos", "pct"])
        for f in fichas:
            for i, r in enumerate(f["ranking_completo"], 1):
                w.writerow([f["chave"], f["nome_urna"], f["uf"], f["cargo"], i, r["municipio"], r["votos"], r["pct"]])
    (dir_saida / "cobertura.json").write_text(json.dumps(cobertura, ensure_ascii=False, indent=1), encoding="utf-8")
    return cobertura


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir-cache", type=Path, default=Path("/tmp/tse"))
    ap.add_argument("--sem-2022", action="store_true", help="não buscar os senadores de 2022")
    ap.add_argument("--sondar", action="store_true", help="só testa as URLs do TSE")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if a.sondar:
        for url, st in sondar([2026, 2022]).items():
            print(st, url)
        return 0
    cob = executar(a.dir_cache, incluir_2022=not a.sem_2022)
    print(json.dumps({k: v for k, v in cob.items() if k != "divergencias_votos"}, ensure_ascii=False, indent=1))
    print(f"Divergências de votos (>1%): {len(cob['divergencias_votos'])}")
    if not cob["fontes_disponiveis"].get("cand_2026"):
        print("::warning::consulta_cand_2026 ainda não publicado no CDN do TSE")
    if not cob["fontes_disponiveis"].get("munzona_2026"):
        print("::warning::votacao_candidato_munzona_2026 ainda não publicado no CDN do TSE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
