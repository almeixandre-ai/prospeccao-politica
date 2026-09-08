"""Consulta a API aberta do Senado Federal (endpoint /processo, ativo desde 2026)."""

from __future__ import annotations

import requests

from .schemas import ProposicaoInfo

BASE = "https://legis.senado.leg.br/dadosabertos"
HEADERS = {"Accept": "application/json"}
TIMEOUT = 30


def _get(url: str, params: dict | None = None) -> dict | list:
    r = requests.get(url, headers=HEADERS, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _safe(d, *keys, default=None):
    cur = d
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k)
        elif isinstance(cur, list) and isinstance(k, int):
            cur = cur[k] if k < len(cur) else None
        else:
            return default
        if cur is None:
            return default
    return cur if cur is not None else default


def _buscar_processo(sigla: str, numero: int, ano: int) -> dict | None:
    """Localiza o processo no Senado via /processo.

    Tenta primeiro com sigla exata; se não encontrar, busca só por número/ano
    para capturar casos onde a sigla mudou (ex: PL → PEC ao entrar no Senado).
    """
    # Tentativa 1: sigla + número + ano
    resultado = _get(f"{BASE}/processo", params={"sigla": sigla, "numero": numero, "ano": ano})
    if isinstance(resultado, list) and resultado:
        return resultado[0]

    # Tentativa 2: somente número + ano (captura mudança de sigla, ex: PL → PEC no Senado)
    # A API já filtra por número/ano — todos os resultados já correspondem
    resultado = _get(f"{BASE}/processo", params={"numero": numero, "ano": ano})
    if isinstance(resultado, list) and resultado:
        # Preferir tramitando=Sim e siglas legislativas sobre requerimentos/outros
        SIGLAS_PREF = {"PL", "PEC", "PLP", "MPV", "PDL", "PDS", "PRC"}
        tramitando = [c for c in resultado if c.get("tramitando") == "Sim"]
        legis = [c for c in (tramitando or resultado) if c.get("sigla", "").upper() in SIGLAS_PREF]
        return (legis or tramitando or resultado)[0]

    return None


def _buscar_relator(codigo_materia: int | str) -> str | None:
    """Retorna o nome do relator atual via /materia/relatorias/{codigoMateria}.

    O endpoint legado ainda está ativo apesar da depreciação formal.
    Retorna o relator sem data de destituição (ativo), ou o mais recente.
    """
    try:
        data = _get(f"{BASE}/materia/relatorias/{codigo_materia}")
        relators = (
            data.get("RelatoriaMateria", {})
            .get("Materia", {})
            .get("HistoricoRelatoria", {})
            .get("Relator", [])
        )
        if isinstance(relators, dict):
            relators = [relators]
        if not relators:
            return None
        # Preferir relator sem data de destituição (ainda ativo)
        ativos = [r for r in relators if not r.get("DataDestituicao")]
        candidatos = ativos or relators
        ultimo = candidatos[-1]
        nome = _safe(ultimo, "IdentificacaoParlamentar", "NomeParlamentar")
        tratamento = _safe(ultimo, "IdentificacaoParlamentar", "FormaTratamento", default="")
        comissao = _safe(ultimo, "IdentificacaoComissao", "SiglaComissao", default="")
        partes = []
        if tratamento:
            partes.append(tratamento)
        if nome:
            partes.append(nome)
        if comissao:
            partes.append(f"({comissao})")
        return " ".join(partes) if partes else None
    except Exception:
        return None


def buscar_proposicao(sigla: str, numero: int, ano: int) -> dict:
    """Retorna dados padronizados de uma matéria do Senado.

    Args:
        sigla: Tipo da matéria (ex: "PL", "PEC", "PLP").
        numero: Número da matéria.
        ano: Ano da matéria.
    """
    resumo = _buscar_processo(sigla, numero, ano)
    if resumo is None:
        raise ValueError(f"Matéria {sigla} {numero}/{ano} não encontrada no Senado.")

    id_processo = resumo.get("id")
    sigla_real = resumo.get("sigla", sigla).upper()

    # Detalhes completos
    detalhe: dict = {}
    if id_processo:
        try:
            det = _get(f"{BASE}/processo/{id_processo}")
            if isinstance(det, dict):
                detalhe = det
        except requests.RequestException:
            pass

    # Ementa
    ementa = (
        _safe(detalhe, "conteudo", "ementa")
        or resumo.get("ementa", "")
    )

    # Situação atual
    situacao = (
        _safe(detalhe, "situacaoAtual")
        or resumo.get("situacaoAtual")
    )
    if not situacao:
        tramitando = detalhe.get("tramitando") or resumo.get("tramitando", "")
        situacao = "Em tramitação" if tramitando == "Sim" else "Encerrada"

    # Último evento — último informeLegislativo da primeira autuação
    ultimo_evento = None
    ultimo_evento_data = None
    autuacoes = detalhe.get("autuacoes", [])
    if autuacoes:
        informes = _safe(autuacoes, 0, "informesLegislativos", default=[])
        if isinstance(informes, list) and informes:
            last = informes[-1]
            ultimo_evento = last.get("descricao")
            raw_data = last.get("data", "")
            ultimo_evento_data = raw_data[:10] if raw_data else None

    # Relator — via endpoint de relatorias da matéria (ainda ativo)
    relator = None
    codigo_materia = detalhe.get("codigoMateria") or resumo.get("codigoMateria")
    if codigo_materia:
        relator = _buscar_relator(codigo_materia)

    # Autor original da iniciativa
    autor = None
    autoria_ini = detalhe.get("autoriaIniciativa", [])
    if isinstance(autoria_ini, list) and autoria_ini:
        autor = autoria_ini[0].get("autor")
    if not autor:
        autor = _safe(detalhe, "documento", "resumoAutoria") or resumo.get("autoria")

    # Comissão/local atual — última situação registrada (mais recente)
    comissoes_pendentes: list[str] = []
    if autuacoes:
        situacoes_list = _safe(autuacoes, 0, "situacoes", default=[])
        if isinstance(situacoes_list, list) and situacoes_list:
            # Usar a última situação (mais recente) e também capturar o local atual
            ultima_sit = situacoes_list[-1]
            colegiado_sigla = _safe(ultima_sit, "colegiado", "sigla")
            colegiado_nome = _safe(ultima_sit, "colegiado", "nome")
            if colegiado_sigla:
                label = f"{colegiado_sigla}"
                if colegiado_nome and colegiado_nome != colegiado_sigla:
                    label = f"{colegiado_sigla} – {colegiado_nome}"
                comissoes_pendentes.append(label)

    # Regime de tramitação — não exposto diretamente no novo endpoint
    regime = None

    # URL do inteiro teor
    url_teor = _safe(detalhe, "documento", "url") or resumo.get("urlDocumento")

    numero_val = int(str(resumo.get("numero", numero)).lstrip("0") or numero)
    ano_val = int(resumo.get("ano", ano))

    info = ProposicaoInfo(
        origem="senado",
        tipo_sigla=sigla_real,
        numero=numero_val,
        ano=ano_val,
        ementa=ementa,
        situacao_atual=situacao,
        ultimo_evento=ultimo_evento,
        ultimo_evento_data=ultimo_evento_data,
        autor=autor,
        relator_designado=relator,
        comissoes_pendentes=comissoes_pendentes,
        regime_tramitacao=regime,
        url_inteiro_teor=url_teor,
    )
    return info.model_dump()
