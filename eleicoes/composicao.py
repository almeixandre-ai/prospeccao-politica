"""Monta a composição da Câmara e do Senado para a legislatura 2027-2031."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from . import historico_camara, senado_composicao, tse_resultados
from .schemas import Composicao, Parlamentar

log = logging.getLogger("prospeccao.composicao")

DATA_DIR = Path(__file__).resolve().parent.parent / "output" / "eleicoes2026"
ARQ_COMPOSICAO = DATA_DIR / "composicao_2027.json"

VAGAS_CAMARA = 513
VAGAS_SENADO = 81
SENADORES_ELEITOS_POR_UF = 2


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def montar(ufs: list[str] | None = None) -> Composicao:
    ufs = ufs or tse_resultados.UFS
    cd_ele = tse_resultados.codigo_eleicao_estadual()
    log.info("Eleição estadual 2026 (1º turno): código %s", cd_ele)

    deps_atuais = historico_camara.deputados_legislatura()
    sen_atuais = senado_composicao.senadores_em_exercicio()
    log.info("Referência: %d deputados na 57ª legislatura, %d senadores em exercício",
             len(deps_atuais), len(sen_atuais))

    deputados: list[Parlamentar] = []
    senadores: list[Parlamentar] = []
    totalizacao: dict[str, str] = {}
    alertas: list[str] = []
    governadores_por_uf: dict[str, list[dict]] = {}

    for uf in ufs:
        log.info("[%s] Baixando resultados do TSE...", uf)
        res_dep = tse_resultados.resultado_uf(cd_ele, uf, tse_resultados.CARGO_DEP_FEDERAL)
        res_sen = tse_resultados.resultado_uf(cd_ele, uf, tse_resultados.CARGO_SENADOR)
        totalizacao[uf] = tse_resultados.percentual_totalizado(res_dep)
        try:
            res_gov = tse_resultados.resultado_uf(cd_ele, uf, tse_resultados.CARGO_GOVERNADOR)
            governadores_por_uf[uf] = [
                c for c in tse_resultados.candidatos(res_gov)
                if str(c.get("st", "")).startswith(("Eleito", "2º turno"))
            ]
        except Exception as e:  # informativo apenas
            log.debug("Sem resultado de governador para %s: %s", uf, e)

        vagas = _int((res_dep.get("carg") or [{}])[0].get("nv"))
        eleitos_dep = tse_resultados.eleitos(res_dep)
        if vagas and len(eleitos_dep) != vagas:
            alertas.append(f"{uf}: {len(eleitos_dep)} deputados eleitos para {vagas} vagas")

        for c in eleitos_dep:
            dep = historico_camara.casar_deputado(c.get("nmu", ""), c.get("nm"), uf, deps_atuais)
            deputados.append(Parlamentar(
                casa="camara", uf=uf, nome_urna=c.get("nmu", ""), nome_completo=c.get("nm"),
                partido=c.get("partido") or "", federacao=c.get("federacao"),
                numero=c.get("n"), votos=_int(c.get("vap")), situacao=c.get("st", ""),
                origem="tse_2026", sq_candidato=c.get("sqcand"),
                id_camara=dep["id"] if dep else None, incumbente=dep is not None,
            ))

        eleitos_sen = tse_resultados.eleitos(res_sen)
        if len(eleitos_sen) != SENADORES_ELEITOS_POR_UF:
            alertas.append(f"{uf}: {len(eleitos_sen)} senadores eleitos (esperado 2)")
        for c in eleitos_sen:
            atual = next(
                (s for s in sen_atuais if s["uf"] == uf and max(
                    historico_camara.similaridade(c.get("nmu", ""), s["nome"]),
                    historico_camara.similaridade(c.get("nm", ""), s.get("nome_completo") or ""),
                ) >= 0.85),
                None,
            )
            dep = historico_camara.casar_deputado(c.get("nmu", ""), c.get("nm"), uf, deps_atuais)
            p = Parlamentar(
                casa="senado", uf=uf, nome_urna=c.get("nmu", ""), nome_completo=c.get("nm"),
                partido=c.get("partido") or "", federacao=c.get("federacao"),
                numero=c.get("n"), votos=_int(c.get("vap")), situacao=c.get("st", ""),
                origem="tse_2026", sq_candidato=c.get("sqcand"),
                codigo_senado=atual["codigo"] if atual else None,
                id_camara=dep["id"] if dep else None, incumbente=atual is not None,
            )
            if dep and not atual:
                p.alertas.append("Deputado(a) federal na legislatura atual")
            senadores.append(p)

    for s in senado_composicao.senadores_que_permanecem():
        if s["uf"] not in ufs:
            continue
        p = Parlamentar(
            casa="senado", uf=s["uf"], nome_urna=s["nome"], nome_completo=s.get("nome_completo"),
            partido=s.get("partido", ""), situacao="Mandato até 2031", origem="senado_2022",
            codigo_senado=s["codigo"], incumbente=True,
        )
        if s.get("participacao") and s["participacao"] != "Titular":
            p.alertas.append(f"Em exercício como {s['participacao']}")
        for g in governadores_por_uf.get(s["uf"], []):
            if historico_camara.similaridade(g.get("nmu", ""), s["nome"]) >= 0.85:
                p.alertas.append(
                    f"Disputou governo em 2026 ({g.get('st')}) — se assumir, o suplente ocupa a vaga"
                )
        senadores.append(p)

    if set(ufs) == set(tse_resultados.UFS):
        if len(deputados) != VAGAS_CAMARA:
            alertas.append(f"Câmara: {len(deputados)} eleitos identificados (esperado {VAGAS_CAMARA})")
        if len(senadores) != VAGAS_SENADO:
            alertas.append(f"Senado: {len(senadores)} senadores na composição (esperado {VAGAS_SENADO})")
    pendentes = [uf for uf, p in totalizacao.items() if p not in ("100,00", "100")]
    if pendentes:
        alertas.append("Totalização incompleta em: " + ", ".join(f"{u} ({totalizacao[u]}%)" for u in pendentes))

    return Composicao(
        data_coleta=date.today().isoformat(), totalizacao_tse=totalizacao,
        deputados=deputados, senadores=senadores, alertas=alertas,
    )


def salvar(comp: Composicao, caminho: Path = ARQ_COMPOSICAO) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(comp.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    return caminho


def carregar(caminho: Path = ARQ_COMPOSICAO) -> Composicao | None:
    if not caminho.exists():
        return None
    return Composicao.model_validate_json(caminho.read_text(encoding="utf-8"))
