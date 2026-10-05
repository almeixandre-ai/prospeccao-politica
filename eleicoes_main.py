"""CLI — Eleições 2026: nova composição do Congresso × agenda ABES."""

from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import argparse
import logging
import sys

from eleicoes import composicao as comp_mod
from eleicoes.avaliador_afinidade import AvaliadorAfinidade
from eleicoes.composicao import DATA_DIR
from eleicoes.painel import tabela, todos

log = logging.getLogger("prospeccao.eleicoes")


def _carregar_ou_falhar():
    comp = comp_mod.carregar()
    if comp is None:
        sys.exit("Composição ainda não coletada. Rode: python eleicoes_main.py composicao")
    return comp


def _filtrar(parls, args):
    if getattr(args, "uf", None):
        parls = [p for p in parls if p.uf in {u.upper() for u in args.uf}]
    if getattr(args, "casa", None):
        parls = [p for p in parls if p.casa == args.casa]
    if getattr(args, "nome", None):
        alvo = args.nome.upper()
        parls = [p for p in parls if alvo in p.nome_urna.upper() or alvo in (p.nome_completo or "").upper()]
    return parls


def cmd_composicao(args) -> None:
    comp = comp_mod.montar()
    caminho = comp_mod.salvar(comp)
    print(f"Deputados: {len(comp.deputados)} | Senadores: {len(comp.senadores)}")
    print(f"Deputados reeleitos: {sum(d.incumbente for d in comp.deputados)}")
    print(f"Senadores eleitos em 2026: {sum(s.origem == 'tse_2026' for s in comp.senadores)} "
          f"| permanecem (2022): {sum(s.origem == 'senado_2022' for s in comp.senadores)}")
    for a in comp.alertas:
        print(f"  ⚠ {a}")
    print(f"Salvo em: {caminho}")


def cmd_triagem(args) -> None:
    comp = _carregar_ou_falhar()
    parls = [p for p in _filtrar(todos(comp), args) if p.id_camara]
    av = AvaliadorAfinidade()
    for i, p in enumerate(parls, 1):
        a = av.triagem_sem_ia(p)
        log.info("[%d/%d] %s-%s %s: %d proposições aderentes", i, len(parls), p.partido, p.uf,
                 p.nome_urna, len(a.historico_legislativo))
    print(f"Triagem concluída para {len(parls)} parlamentares com histórico na Câmara.")


def cmd_avaliar(args) -> None:
    comp = _carregar_ou_falhar()
    parls = _filtrar(todos(comp), args)
    if not args.forcar:
        parls = [p for p in parls if AvaliadorAfinidade.carregar(p, "ia") is None]
    parls = parls[: args.limite] if args.limite else parls
    if not parls:
        print("Nada a avaliar (todos já avaliados — use --forcar para refazer).")
        return
    print(f"Avaliando {len(parls)} parlamentar(es) com IA + busca web...")
    av = AvaliadorAfinidade()
    for i, p in enumerate(parls, 1):
        try:
            a = av.avaliar(p, forcar=args.forcar)
            print(f"[{i}/{len(parls)}] {p.nome_urna} ({p.partido}-{p.uf}): "
                  f"IAT {a.indice_afinidade:.1f} — {a.classificacao}")
        except Exception as e:
            log.error("Falha em %s: %s", p.nome_urna, e)


def cmd_ranking(args) -> None:
    comp = _carregar_ou_falhar()
    df = tabela(comp)
    if args.uf:
        df = df[df["uf"].isin([u.upper() for u in args.uf])]
    if args.casa:
        df = df[df["casa"] == ("Câmara" if args.casa == "camara" else "Senado")]
    df = df.sort_values(["iat", "cobertura"], ascending=False, na_position="last")
    saida = DATA_DIR / "ranking_afinidade.xlsx"
    df.to_excel(saida, index=False)
    print(df[["casa", "uf", "nome", "partido", "metodo", "iat", "cobertura", "classificacao"]]
          .head(args.top).to_string(index=False))
    print(f"\nPlanilha completa: {saida}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Eleições 2026 — composição do Congresso × agenda ABES")
    p.add_argument("--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("composicao", help="Coleta eleitos (TSE) + senadores que permanecem (Senado)")

    for nome, ajuda in [("triagem", "Triagem gratuita pelo histórico da Câmara (sem IA)"),
                        ("avaliar", "Match com a agenda ABES via IA + busca web"),
                        ("ranking", "Ranking consolidado e exportação para Excel")]:
        sp = sub.add_parser(nome, help=ajuda)
        sp.add_argument("--uf", nargs="+", help="Uma ou mais UFs (ex.: SP RJ)")
        sp.add_argument("--casa", choices=["camara", "senado"])
        if nome != "ranking":
            sp.add_argument("--nome", help="Trecho do nome do parlamentar")
        if nome == "avaliar":
            sp.add_argument("--limite", type=int, help="Máximo de parlamentares nesta execução")
            sp.add_argument("--forcar", action="store_true", help="Refaz avaliações já existentes")
        if nome == "ranking":
            sp.add_argument("--top", type=int, default=30)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    {"composicao": cmd_composicao, "triagem": cmd_triagem,
     "avaliar": cmd_avaliar, "ranking": cmd_ranking}[args.cmd](args)


if __name__ == "__main__":
    main()
