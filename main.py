"""Ponto de entrada do sistema de prospecção política legislativa."""

from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

from coleta.schemas import ProposicaoInfo

log = logging.getLogger("prospeccao")


# ── Mock ─────────────────────────────────────────────────────────────────────

def _proposicao_mock(tipo: str, numero: int, ano: int) -> ProposicaoInfo:
    return ProposicaoInfo(
        origem="camara",
        tipo_sigla=tipo.upper(),
        numero=numero,
        ano=ano,
        ementa="Dispõe sobre o uso da Inteligência Artificial no Brasil.",
        situacao_atual="Aguardando Parecer",
        ultimo_evento="Notificação de Apensação",
        ultimo_evento_data="2026-06-17",
        autor="Senado Federal - Rodrigo Pacheco",
        relator_designado=None,
        comissoes_pendentes=["CCTCI", "CCJ"],
        regime_tramitacao="Ordinária",
    )


# ── Resumo no terminal ──────────────────────────────────────────────────────

_SEMAFORO = {5: "\U0001f534", 4: "\U0001f7e0", 3: "\U0001f7e1"}


def _semaforo(nota: int) -> str:
    return _SEMAFORO.get(nota, "\U0001f7e2")


def _imprimir_resumo(relatorio) -> None:
    m = relatorio.matriz
    print()
    print("=" * 62)
    print(f"  PROSPECÇÃO POLÍTICA — {relatorio.proposicao_id}")
    print("=" * 62)
    print(f"  Zona de risco: {m.zona_risco}  |  Score: {m.score_consolidado:.2f}/5.0")
    print()

    dimensoes = [
        ("Processual", m.risco_processual),
        ("Coalizão", m.risco_coalicao),
        ("Agenda", m.risco_agenda),
        ("Atores-Chave", m.risco_atores),
        ("Exógeno", m.risco_exogeno),
    ]
    for label, dim in dimensoes:
        print(f"  {_semaforo(dim.nota)} {label:15s} {dim.nota}/5  ({dim.confianca.value})")
    print()

    base = next((c for c in relatorio.cenarios if c.tipo == "Base"), None)
    if base:
        primeira_linha = base.narrativa.split(".")[0] + "."
        print(f"  Cenário base ({base.probabilidade_estimada}): {primeira_linha[:90]}")

    imediatas = [a for a in relatorio.acoes if "Imediato" in a.horizonte]
    if imediatas:
        print(f"  Ação imediata: {imediatas[0].acao[:90]}")

    print(f"  KPIs de monitoramento: {len(relatorio.kpis_monitoramento)}")
    print()
    print(f"  Síntese: {relatorio.sintese_executiva[:120]}...")
    print("=" * 62)


# ── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Sistema de Prospecção Política Legislativa",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemplos:\n"
            '  python main.py --tipo PL --numero 2338 --ano 2023 --ator "ABES" --mock\n'
            '  python main.py --tipo PL --numero 2338 --ano 2023 --ator "ABES" --casa camara\n'
            '  python main.py --tipo PL --numero 2338 --ano 2023 --ator "ABES" --so-coleta'
        ),
    )
    p.add_argument("--tipo", required=True, choices=["PL", "PLP", "PEC", "MPV"],
                    help="Tipo da proposição")
    p.add_argument("--numero", required=True, type=int, help="Número da proposição")
    p.add_argument("--ano", required=True, type=int, help="Ano da proposição")
    p.add_argument("--ator", required=True, help="Entidade ou empresa focal")
    p.add_argument("--casa", default="auto", choices=["camara", "senado", "auto"],
                    help="Casa legislativa (padrão: auto)")
    p.add_argument("--mock", action="store_true",
                    help="Usa dados simulados de coleta (não consulta APIs)")
    p.add_argument("--saida", default="output", help="Pasta de saída (padrão: output/)")
    p.add_argument("--verbose", action="store_true", help="Logs detalhados")
    p.add_argument("--so-coleta", action="store_true",
                    help="Executa apenas a coleta e salva JSON")
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    tipo = args.tipo.upper()
    ident = f"{tipo} {args.numero}/{args.ano}"
    hoje = date.today().isoformat()
    ator_safe = args.ator.replace(" ", "_")
    saida_dir = Path(args.saida)
    saida_dir.mkdir(parents=True, exist_ok=True)

    log.info("=" * 62)
    log.info("SISTEMA DE PROSPECÇÃO POLÍTICA LEGISLATIVA")
    log.info("=" * 62)
    log.info("Proposição: %s", ident)
    log.info("Ator focal: %s", args.ator)
    log.info("Casa: %s", args.casa)
    log.info("-" * 62)

    # ── Etapa 1: Coleta ──────────────────────────────────────────────────

    log.info("[1/4] Coletando dados da proposição...")

    if args.mock:
        log.info("  Modo mock ativado — usando dados simulados")
        proposicao = _proposicao_mock(tipo, args.numero, args.ano)
    else:
        from coleta.coletor import coletar
        proposicao = coletar(tipo, args.numero, args.ano, casa=args.casa)

    log.info("  Situação: %s", proposicao.situacao_atual)
    log.info("  Relator: %s", proposicao.relator_designado or "Não designado")
    log.info("[1/4] Coleta concluída.")

    # Se --so-coleta, salva JSON e encerra
    if args.so_coleta:
        nome = f"COLETA_{tipo}_{args.numero}_{args.ano}_{ator_safe}_{hoje}.json"
        caminho = saida_dir / nome
        caminho.write_text(
            json.dumps(proposicao.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("Coleta salva em: %s", caminho.resolve())
        return

    # ── Etapa 2: Avaliação de risco ──────────────────────────────────────

    log.info("[2/4] Avaliando risco por dimensão...")

    from analise.avaliador_risco import AvaliadorRisco
    avaliador = AvaliadorRisco()
    matriz = avaliador.avaliar(proposicao, ator_focal=args.ator)

    log.info("  Score: %.2f | Zona: %s", matriz.score_consolidado, matriz.zona_risco)
    log.info("[2/4] Avaliação concluída.")

    # ── Etapa 3: Geração de cenários e recomendações ─────────────────────

    log.info("[3/4] Gerando cenários e recomendações...")

    from analise.gerador_prospeccao import GeradorProspeccao
    gerador = GeradorProspeccao()
    relatorio = gerador.gerar(proposicao, matriz, ator_focal=args.ator)

    log.info("[3/4] Prospecção concluída.")

    # ── Etapa 4: Salvar output ───────────────────────────────────────────

    log.info("[4/4] Salvando relatório...")

    nome = f"RPP_{tipo}_{args.numero}_{args.ano}_{ator_safe}_{hoje}.json"
    caminho = saida_dir / nome
    caminho.write_text(
        json.dumps(relatorio.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    log.info("  Arquivo: %s", caminho.resolve())
    log.info("[4/4] Pipeline finalizado.")

    # ── Resumo no terminal ───────────────────────────────────────────────

    _imprimir_resumo(relatorio)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.warning("Interrompido pelo usuário.")
        sys.exit(130)
    except Exception as e:
        log.error("Erro fatal: %s", e, exc_info=True)
        sys.exit(1)
