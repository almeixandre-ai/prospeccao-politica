"""Integração com o Notion: envia ações recomendadas para um Database."""

from __future__ import annotations

import os
from datetime import date
from typing import Any

from notion_client import Client
from notion_client.errors import APIResponseError


def _client(token: str | None = None) -> Client:
    return Client(auth=token or os.environ["NOTION_TOKEN"])


def _garantir_schema(client: Client, db_id: str) -> None:
    """Garante que o database tem as colunas necessárias. Cria as que faltam."""
    COLUNAS = {
        "Horizonte": {"select": {}},
        "Prioridade": {"select": {}},
        "Responsável": {"rich_text": {}},
        "Status": {"select": {}},
        "Proposição": {"rich_text": {}},
        "Data de criação": {"date": {}},
    }
    try:
        db = client.databases.retrieve(database_id=db_id)
        existentes = set((db.get("properties") or {}).keys())
        novas = {k: v for k, v in COLUNAS.items() if k not in existentes}
        if novas:
            client.databases.update(database_id=db_id, properties=novas)
    except APIResponseError:
        pass  # se não conseguir criar, tenta enviar com o que tem


def _prop_title(text: str) -> dict:
    return {"title": [{"text": {"content": text[:2000]}}]}


def _prop_select(value: str) -> dict:
    return {"select": {"name": value}}


def _prop_text(text: str) -> dict:
    return {"rich_text": [{"text": {"content": str(text)[:2000]}}]}


def _prop_date(d: str) -> dict:
    return {"date": {"start": d}}


def _corpo_pagina(acao: dict, proposicao: str) -> list[dict]:
    """Monta o corpo da página com os detalhes da ação."""
    linhas = [
        ("📋 Proposição", proposicao),
        ("⏱️ Horizonte", acao.get("horizonte", "—").replace("_", " ").capitalize()),
        ("🎯 Prioridade", acao.get("prioridade", "—").capitalize()),
        ("👤 Responsável sugerido", acao.get("responsavel_sugerido", "—")),
        ("📅 Criado em", date.today().strftime("%d/%m/%Y")),
    ]
    blocos = []
    for label, valor in linhas:
        blocos.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {"type": "text", "text": {"content": f"{label}: "}, "annotations": {"bold": True}},
                    {"type": "text", "text": {"content": valor}},
                ]
            },
        })
    return blocos


def criar_acao(
    acao: dict,
    proposicao: str,
    database_id: str | None = None,
    token: str | None = None,
) -> str:
    """Cria uma página no Notion para uma ação recomendada.

    Returns:
        URL da página criada.
    """
    db_id = database_id or os.environ["NOTION_DATABASE_ID"]
    client = _client(token)
    _garantir_schema(client, db_id)

    nome = acao.get("acao", "Ação sem título")
    horizonte = acao.get("horizonte", "imediato")
    prioridade = acao.get("prioridade", "media")
    responsavel = acao.get("responsavel_sugerido", "Equipe RIG")

    properties: dict[str, Any] = {
        "Nome": _prop_title(nome),
        "Horizonte": _prop_select(horizonte),
        "Prioridade": _prop_select(prioridade),
        "Responsável ": _prop_text(responsavel),   # espaço no final — nome exato no database
        "Status": _prop_select("A fazer"),
        "Proposição": _prop_text(proposicao),
        "Data de criação": _prop_date(date.today().isoformat()),
    }

    page = client.pages.create(
        parent={"database_id": db_id},
        properties=properties,
        children=_corpo_pagina(acao, proposicao),
    )
    return page.get("url", "")


def enviar_acoes(
    acoes: list[dict],
    proposicao: str,
    database_id: str | None = None,
    token: str | None = None,
) -> list[dict]:
    """Envia uma lista de ações para o Notion.

    Returns:
        Lista de dicts com: acao (nome), url, sucesso, erro.
    """
    resultados = []
    for acao in acoes:
        try:
            url = criar_acao(acao, proposicao, database_id, token)
            resultados.append({
                "acao": acao.get("acao", ""),
                "url": url,
                "sucesso": True,
                "erro": None,
            })
        except APIResponseError as e:
            resultados.append({
                "acao": acao.get("acao", ""),
                "url": None,
                "sucesso": False,
                "erro": str(e),
            })
    return resultados


def testar_conexao(token: str | None = None, database_id: str | None = None) -> tuple[bool, str]:
    """Verifica se token e database_id estão corretos.

    Returns:
        (ok: bool, mensagem: str)
    """
    try:
        db_id = database_id or os.environ.get("NOTION_DATABASE_ID", "")
        if not db_id:
            return False, "NOTION_DATABASE_ID não configurado."
        client = _client(token)
        db = client.databases.retrieve(database_id=db_id)
        titulo_raw = (db.get("title") or [{}])
        titulo = titulo_raw[0].get("plain_text", "sem título") if titulo_raw else "sem título"
        return True, f"Conectado ao database: \"{titulo}\""
    except APIResponseError as e:
        return False, f"Erro de API: {e}"
    except Exception as e:
        return False, f"Erro: {e}"
