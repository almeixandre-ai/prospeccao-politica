"""Coletores de evidências para fundamentar a avaliação de risco político."""

from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import logging
import os
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from urllib.parse import quote_plus

import requests

from .schemas_risco import Evidencia

log = logging.getLogger("prospeccao.coletores")

TIMEOUT = 20
HOJE = lambda: date.today().isoformat()


# ── FUNÇÃO 1: Notícias ──────────────────────────────────────────────────────

def buscar_noticias(termos: list[str], dias: int = 30) -> list[Evidencia]:
    """Busca notícias recentes sobre os termos fornecidos.

    Usa NewsAPI se NEWSAPI_KEY estiver configurada, caso contrário
    faz fallback para o Google News RSS.
    """
    api_key = os.environ.get("NEWSAPI_KEY")
    evidencias: list[Evidencia] = []

    for termo in termos:
        try:
            if api_key:
                novas = _buscar_newsapi(termo, dias, api_key)
            else:
                log.info("NEWSAPI_KEY não configurada — usando Google News RSS")
                novas = _buscar_google_rss(termo)
            evidencias.extend(novas[:3])
        except Exception as e:
            log.warning("Erro ao buscar notícias para '%s': %s", termo, e)

        if len(evidencias) >= 10:
            break

    return evidencias[:10]


def _buscar_newsapi(termo: str, dias: int, api_key: str) -> list[Evidencia]:
    desde = (date.today() - timedelta(days=dias)).isoformat()
    r = requests.get(
        "https://newsapi.org/v2/everything",
        params={
            "q": termo,
            "language": "pt",
            "sortBy": "publishedAt",
            "pageSize": 5,
            "from": desde,
            "apiKey": api_key,
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    artigos = r.json().get("articles", [])

    resultado: list[Evidencia] = []
    for art in artigos:
        desc = (art.get("description") or art.get("title") or "")[:400]
        resultado.append(Evidencia(
            fonte=art.get("source", {}).get("name", "Desconhecido"),
            url=art.get("url"),
            data_coleta=HOJE(),
            trecho_relevante=desc,
            relevancia=f"Cobertura sobre: {termo}",
        ))
    return resultado


def _buscar_google_rss(termo: str) -> list[Evidencia]:
    url = f"https://news.google.com/rss/search?q={quote_plus(termo)}&hl=pt-BR&gl=BR"
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()

    root = ET.fromstring(r.content)
    items = root.findall(".//item")

    resultado: list[Evidencia] = []
    for item in items[:5]:
        title = item.findtext("title", "")
        link = item.findtext("link", "")
        # Google News RSS coloca o veículo após " - " no título
        parts = title.rsplit(" - ", 1)
        veiculo = parts[1].strip() if len(parts) == 2 else "Google News"
        manchete = parts[0].strip()

        desc_el = item.findtext("description", "")
        # A description do Google News RSS é HTML; extrair texto simples
        desc = desc_el.replace("<b>", "").replace("</b>", "")
        if "<" in desc:
            desc = manchete
        desc = desc[:400]

        resultado.append(Evidencia(
            fonte=veiculo,
            url=link,
            data_coleta=HOJE(),
            trecho_relevante=desc,
            relevancia=f"Cobertura sobre: {manchete[:80]}",
        ))
    return resultado


# ── FUNÇÃO 2: Indicadores BCB ───────────────────────────────────────────────

_SERIES_BCB = {
    "SELIC (% a.a.)": "https://api.bcb.gov.br/dados/serie/bcdata.sgs.11/dados/ultimos/1?formato=json",
    "IPCA acumulado 12m (%)": "https://api.bcb.gov.br/dados/serie/bcdata.sgs.13522/dados/ultimos/1?formato=json",
    "Câmbio USD/BRL": "https://api.bcb.gov.br/dados/serie/bcdata.sgs.1/dados/ultimos/1?formato=json",
    "Resultado primário (R$ mi)": "https://api.bcb.gov.br/dados/serie/bcdata.sgs.5793/dados/ultimos/1?formato=json",
}


def buscar_indicadores_bcb() -> list[Evidencia]:
    """Consulta indicadores macroeconômicos do Banco Central do Brasil."""
    linhas: list[str] = []

    for nome, url in _SERIES_BCB.items():
        try:
            r = requests.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            dados = r.json()
            if dados:
                valor = dados[-1].get("valor", "N/D")
                data_ref = dados[-1].get("data", "")
                linhas.append(f"{nome}: {valor} (ref. {data_ref})")
            else:
                linhas.append(f"{nome}: N/D")
        except Exception as e:
            log.warning("Erro ao buscar %s: %s", nome, e)
            linhas.append(f"{nome}: N/D")

    trecho = " | ".join(linhas)

    return [Evidencia(
        fonte="Banco Central do Brasil — Sistema Gerenciador de Séries Temporais",
        url="https://www3.bcb.gov.br/sgspub/",
        data_coleta=HOJE(),
        trecho_relevante=trecho[:500],
        relevancia="Contexto macroeconômico para avaliação de risco exógeno fiscal",
    )]


# ── FUNÇÃO 3: Discursos parlamentares ───────────────────────────────────────

def buscar_discursos_parlamentar(
    deputado_id: int,
    tema: str,
    dias: int = 90,
) -> list[Evidencia]:
    """Busca discursos de um deputado que mencionem o tema na API da Câmara."""
    data_inicio = (date.today() - timedelta(days=dias)).isoformat()

    try:
        r = requests.get(
            f"https://dadosabertos.camara.leg.br/api/v2/deputados/{deputado_id}/discursos",
            params={
                "dataInicio": data_inicio,
                "ordenarPor": "dataHoraInicio",
                "ordem": "DESC",
                "itens": 20,
            },
            headers={"Accept": "application/json"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
    except Exception as e:
        log.warning("Erro ao buscar discursos do deputado %d: %s", deputado_id, e)
        return []

    discursos = r.json().get("dados", [])
    tema_lower = tema.lower()
    evidencias: list[Evidencia] = []

    for d in discursos:
        sumario = d.get("transcricao") or d.get("sumario") or ""
        keywords = d.get("keywords") or ""
        texto_busca = f"{sumario} {keywords}".lower()

        if tema_lower not in texto_busca:
            continue

        data_discurso = (d.get("dataHoraInicio") or "")[:10]
        trecho = sumario[:400]

        evidencias.append(Evidencia(
            fonte="Discurso em plenário — Câmara dos Deputados",
            url=d.get("urlTexto"),
            data_coleta=HOJE(),
            trecho_relevante=trecho if trecho else f"Discurso em {data_discurso} mencionando '{tema}'",
            relevancia=f"Posicionamento declarado sobre {tema}",
        ))

        if len(evidencias) >= 3:
            break

    return evidencias


# ── Teste ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    print("=" * 60)
    print("TESTE DOS COLETORES DE EVIDÊNCIA")
    print("=" * 60)

    # 1. Notícias
    print("\n--- Notícias ---")
    termos = ["Marco Legal Inteligência Artificial", "PL 2338 congresso"]
    noticias = buscar_noticias(termos, dias=30)
    print(f"Total: {len(noticias)} evidências")
    for ev in noticias:
        print(f"  [{ev.fonte}] {ev.trecho_relevante[:80]}...")
        if ev.url:
            print(f"    URL: {ev.url[:80]}")

    # 2. Indicadores BCB
    print("\n--- Indicadores BCB ---")
    bcb = buscar_indicadores_bcb()
    for ev in bcb:
        print(f"  {ev.trecho_relevante}")

    # 3. Discursos
    print("\n--- Discursos (Aguinaldo Ribeiro, ID 204484) ---")
    discursos = buscar_discursos_parlamentar(204484, "inteligência artificial")
    print(f"Total: {len(discursos)} evidências")
    for ev in discursos:
        print(f"  [{ev.fonte}] {ev.trecho_relevante[:80]}...")
