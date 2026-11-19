"""Dossiê legislativo por parlamentar — insumo da avaliação qualitativa de afinidade (Etapa 2).

Para cada parlamentar selecionado (por padrão, prioridades A e B do IIP), grava
output/eleicoes2026/dossies/<chave>.json com:
  - proposições de autoria aderentes à agenda, com EMENTA COMPLETA, link, situação,
    palavras-chave e se o parlamentar é o autor principal (Câmara e Senado);
  - relatorias aderentes (Senado);
  - votos nominais em Plenário nas proposições-chave de eleicoes/votacoes_chave.json (Câmara);
  - comissões e frentes (copiadas da ficha de interesse).

Só coleta fatos das APIs oficiais — a interpretação fica para a etapa de avaliação.

Uso:
    python -m eleicoes.dossie                  # A + B
    python -m eleicoes.dossie --prioridades A B C
    python -m eleicoes.dossie --chaves camara_SP_250002546642
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date
from pathlib import Path

import requests

from . import historico_camara as hc
from . import historico_senado as hs
from .composicao import ARQ_COMPOSICAO, DATA_DIR

log = logging.getLogger("prospeccao.dossie")

DIR_INTERESSE = DATA_DIR / "interesse"
DIR_DOSSIES = DATA_DIR / "dossies"
ARQ_AGENDA = Path(__file__).resolve().parent / "agenda_abes.json"
ARQ_VOTACOES = Path(__file__).resolve().parent / "votacoes_chave.json"
PAUSA = 0.15  # cortesia com as APIs públicas


def _get(url: str, params: dict | None = None, tentativas: int = 3):
    for i in range(tentativas):
        try:
            r = requests.get(url, params=params, headers={"Accept": "application/json"}, timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            time.sleep(PAUSA)
            return r.json()
        except requests.RequestException as e:
            log.warning("GET %s (%s/%s): %s", url, i + 1, tentativas, e)
            time.sleep(2 * (i + 1))
    return None


def temas_da_ementa(texto: str, agenda: dict) -> list[str]:
    n = f" {hc.normalizar(texto)} "
    return [t["id"] for t in agenda["temas"] if any(f" {hc.normalizar(k)} " in n for k in t["palavras_chave"])]


# ── Câmara ───────────────────────────────────────────────────────────────────

def proposicoes_camara(id_dep: int, agenda: dict) -> list[dict]:
    saida = []
    for p in hc.proposicoes_autoria(id_dep):
        if not temas_da_ementa(p.get("ementa") or "", agenda):
            continue  # filtro barato antes de buscar o detalhe (evita milhares de chamadas)
        detalhe = (_get(f"{hc.BASE}/proposicoes/{p['id']}") or {}).get("dados", {})
        ementa = detalhe.get("ementa") or p.get("ementa") or ""
        texto = f"{ementa} {detalhe.get('keywords') or ''} {detalhe.get('ementaDetalhada') or ''}"
        temas = temas_da_ementa(texto, agenda)
        if not temas:
            continue
        autores = (_get(f"{hc.BASE}/proposicoes/{p['id']}/autores") or {}).get("dados", [])
        principal = next((a for a in autores if a.get("ordemAssinatura") == 1), autores[0] if autores else {})
        status = detalhe.get("statusProposicao") or {}
        saida.append({
            "identificacao": f"{p['siglaTipo']} {p['numero']}/{p['ano']}",
            "temas": temas,
            "ementa": ementa,
            "ementa_detalhada": detalhe.get("ementaDetalhada"),
            "keywords": detalhe.get("keywords"),
            "autor_principal": principal.get("nome"),
            "e_autor_principal": str(id_dep) in (principal.get("uri") or ""),
            "n_coautores": len(autores),
            "situacao": status.get("descricaoSituacao"),
            "data_apresentacao": (detalhe.get("dataApresentacao") or "")[:10],
            "url": f"https://www.camara.leg.br/propostas-legislativas/{p['id']}",
            "url_inteiro_teor": detalhe.get("urlInteiroTeor"),
            "casa": "camara",
        })
    return saida


def resolver_votacoes_chave(cfg: list[dict]) -> list[dict]:
    """Votações nominais de Plenário das proposições-chave, com o voto de cada deputado."""
    votacoes = []
    for item in cfg:
        busca = _get(f"{hc.BASE}/proposicoes", {"siglaTipo": item["sigla"], "numero": item["numero"],
                                                 "ano": item["ano"], "itens": 5}) or {}
        achadas = busca.get("dados", [])
        if not achadas:
            log.info("Proposição-chave não encontrada: %s %s/%s", item["sigla"], item["numero"], item["ano"])
            continue
        pid = achadas[0]["id"]
        for v in (_get(f"{hc.BASE}/proposicoes/{pid}/votacoes") or {}).get("dados", []):
            if v.get("siglaOrgao") != "PLEN":
                continue
            votos = (_get(f"{hc.BASE}/votacoes/{v['id']}/votos") or {}).get("dados", [])
            if not votos:
                continue  # votação simbólica
            votacoes.append({
                "proposicao": f"{item['sigla']} {item['numero']}/{item['ano']}", "tema": item["tema"],
                "nota": item["nota"], "id_votacao": v["id"], "data": (v.get("dataHoraRegistro") or v.get("data") or "")[:10],
                "descricao": v.get("descricao"), "aprovacao": v.get("aprovacao"),
                "url": f"https://www.camara.leg.br/propostas-legislativas/{pid}",
                "votos": {str(x["deputado_"]["id"]): x.get("tipoVoto") for x in votos if x.get("deputado_")},
            })
        log.info("%s %s/%s: %d votações nominais", item["sigla"], item["numero"], item["ano"],
                 sum(1 for x in votacoes if x["proposicao"] == f"{item['sigla']} {item['numero']}/{item['ano']}"))
    return votacoes


# ── Senado ───────────────────────────────────────────────────────────────────

def _url_senado(ident: str) -> str:
    return f"https://www25.senado.leg.br/web/atividade/materias/-/materia?q={requests.utils.quote(ident)}"


def proposicoes_senado(codigo: str, nome: str, agenda: dict) -> list[dict]:
    saida = []
    for p in hs.autorias(codigo):
        temas = temas_da_ementa(p["ementa"], agenda)
        if temas:
            saida.append({"identificacao": p["identificacao"], "temas": temas, "ementa": p["ementa"],
                          "autor_principal": p.get("primeiro_autor"),
                          "e_autor_principal": hc.similaridade(p.get("primeiro_autor") or "", nome) > 0.8,
                          "url": _url_senado(p["identificacao"]), "casa": "senado"})
    return saida


def relatorias_senado(codigo: str, agenda: dict) -> list[dict]:
    return [{**r, "temas": t, "url": _url_senado(r["identificacao"])}
            for r in hs.relatorias(codigo) if (t := temas_da_ementa(r["ementa"], agenda))]


# ── Orquestração ─────────────────────────────────────────────────────────────

def selecionar(prioridades: list[str], chaves: list[str] | None) -> list[dict]:
    comp = json.loads(ARQ_COMPOSICAO.read_text(encoding="utf-8"))
    parls = {p["chave"]: p for p in comp["deputados"] + comp["senadores"]}
    if chaves:
        return [parls[k] for k in chaves if k in parls]
    sel = []
    for f in sorted(DIR_INTERESSE.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if d["prioridade"][:1] in prioridades and d["parlamentar_chave"] in parls:
            sel.append(parls[d["parlamentar_chave"]])
    return sel


def montar(p: dict, agenda: dict, votacoes: list[dict]) -> dict:
    interesse_arq = DIR_INTERESSE / f"{p['chave']}.json"
    interesse = json.loads(interesse_arq.read_text(encoding="utf-8")) if interesse_arq.exists() else {}
    props, rels, votos = [], [], []
    if p.get("id_camara"):
        props += proposicoes_camara(p["id_camara"], agenda)
        for v in votacoes:
            if (voto := v["votos"].get(str(p["id_camara"]))):
                votos.append({k: v[k] for k in ("proposicao", "tema", "nota", "data", "descricao", "aprovacao", "url")}
                             | {"voto": voto})
    if p.get("codigo_senado"):
        props += proposicoes_senado(str(p["codigo_senado"]), p.get("nome_completo") or p["nome_urna"], agenda)
        rels += relatorias_senado(str(p["codigo_senado"]), agenda)
    return {
        "parlamentar_chave": p["chave"], "nome_urna": p["nome_urna"], "nome_completo": p.get("nome_completo"),
        "casa_2027": p["casa"], "uf": p["uf"], "partido": p.get("partido"), "federacao": p.get("federacao"),
        "incumbente": p.get("incumbente"), "id_camara": p.get("id_camara"), "codigo_senado": p.get("codigo_senado"),
        "data_coleta": date.today().isoformat(),
        "iip": interesse.get("iip"), "prioridade": interesse.get("prioridade"),
        "proposicoes_agenda": props, "relatorias_agenda": rels, "votos_chave": votos,
        "orgaos": interesse.get("orgaos", []), "frentes": interesse.get("frentes", []),
        "limitacoes": [x for x in (
            None if p.get("id_camara") else "Sem passagem pela Câmara na legislatura 2023-2027: sem votos nominais coletados",
            "Votos nominais do Senado não coletados nesta versão" if p.get("codigo_senado") else None,
        ) if x],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prioridades", nargs="+", default=["A", "B"])
    ap.add_argument("--chaves", nargs="*")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    agenda = json.loads(ARQ_AGENDA.read_text(encoding="utf-8"))
    sel = selecionar(a.prioridades, a.chaves)
    log.info("%d parlamentares selecionados", len(sel))
    cfg = json.loads(ARQ_VOTACOES.read_text(encoding="utf-8"))["camara"]
    votacoes = resolver_votacoes_chave(cfg)
    DIR_DOSSIES.mkdir(parents=True, exist_ok=True)
    (DIR_DOSSIES / "_votacoes_chave.json").write_text(
        json.dumps([{k: v for k, v in x.items() if k != "votos"} | {"n_votos": len(x["votos"])} for x in votacoes],
                   ensure_ascii=False, indent=1), encoding="utf-8")
    resumo = []
    for i, p in enumerate(sel, 1):
        d = montar(p, agenda, votacoes)
        (DIR_DOSSIES / f"{p['chave']}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        resumo.append((p["chave"], len(d["proposicoes_agenda"]), len(d["relatorias_agenda"]), len(d["votos_chave"])))
        log.info("[%d/%d] %s: %d proposições, %d relatorias, %d votos-chave", i, len(sel), p["nome_urna"], *resumo[-1][1:])
    print(f"Dossiês: {len(resumo)} | proposições: {sum(r[1] for r in resumo)} | relatorias: {sum(r[2] for r in resumo)}"
          f" | votos-chave: {sum(r[3] for r in resumo)} | votações nominais: {len(votacoes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
