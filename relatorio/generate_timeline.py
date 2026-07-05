#!/usr/bin/env python3
"""
Gera a Linha do Tempo (Timeline) do andamento legislativo, padrão ABES.

Uso:
  python3 generate_timeline.py input.json output.png

Formato do input.json:
{
  "titulo": "PL 6237/2025 \u2013 Andamento Legislativo",
  "marcos": [
    {"label": "Apresentação", "data": "mar/2025", "estado": "concluido"},
    {"label": "Comissões (CCT/CCJ)", "data": "jun/2026", "estado": "atual"},
    {"label": "Votação Câmara", "data": "prevista 2026", "estado": "pendente"},
    {"label": "Votação Senado", "data": "\u2014", "estado": "pendente"},
    {"label": "Sanção", "data": "\u2014", "estado": "pendente"}
  ]
}

estado: "concluido" | "atual" | "pendente"
"""
import sys
import json
import textwrap
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

PRETO = "#231F20"
DOURADO = "#C99A3F"
VERDE = "#2E7D32"
CINZA_CLARO = "#C9C9C9"
CINZA_TEXTO = "#7A7A7A"

COR_ESTADO = {
    "concluido": VERDE,
    "atual": DOURADO,
    "pendente": CINZA_CLARO,
}


def main():
    input_path, output_path = sys.argv[1], sys.argv[2]
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    marcos = data["marcos"]
    titulo = data.get("titulo", "Andamento Legislativo")
    n = len(marcos)

    plt.rcParams["font.family"] = "DejaVu Sans"
    fig_width = max(11.2, 2.0 * n)
    fig, ax = plt.subplots(figsize=(fig_width, 3.4), dpi=200)
    ax.set_xlim(-0.5, n - 0.5)
    ax.set_ylim(0, 3)
    ax.axis("off")

    ax.text(-0.5, 2.9, titulo, fontsize=13.5, fontweight="bold", color=PRETO, ha="left", va="top")

    y_line = 1.55
    xs = list(range(n))

    # segmentos da linha entre marcos: verde se ambos concluídos/atual já passado, cinza caso contrário
    for i in range(n - 1):
        estado_atual = marcos[i]["estado"]
        cor = VERDE if estado_atual == "concluido" else CINZA_CLARO
        ax.plot([xs[i], xs[i + 1]], [y_line, y_line], color=cor, linewidth=4, solid_capstyle="round", zorder=1)

    for i, marco in enumerate(marcos):
        cor = COR_ESTADO.get(marco["estado"], CINZA_CLARO)
        estado = marco["estado"]

        if estado == "atual":
            ax.scatter([xs[i]], [y_line], s=620, color=cor, zorder=3, edgecolors=PRETO, linewidths=2.2)
            ax.scatter([xs[i]], [y_line], s=180, color="white", zorder=4)
        else:
            ax.scatter([xs[i]], [y_line], s=420, color=cor, zorder=3, edgecolors="white", linewidths=2)

        # rótulo acima (quebrado em até 2 linhas para não colidir com o marco vizinho), data abaixo
        peso = "bold" if estado != "pendente" else "normal"
        cor_texto = PRETO if estado != "pendente" else CINZA_TEXTO
        label_wrapped = "\n".join(textwrap.wrap(marco["label"], width=14, max_lines=2))
        ax.text(xs[i], y_line + 0.45, label_wrapped, fontsize=9.8, fontweight=peso,
                color=cor_texto, ha="center", va="bottom", linespacing=1.35)
        ax.text(xs[i], y_line - 0.42, marco["data"], fontsize=9.0, color=CINZA_TEXTO, ha="center", va="top")

        if estado == "atual":
            ax.text(xs[i], y_line - 0.78, "ETAPA ATUAL", fontsize=8, fontweight="bold",
                    color=DOURADO, ha="center", va="top")

    fig.savefig(output_path, bbox_inches="tight", facecolor="white")
    print(f"Timeline salva em {output_path}")


if __name__ == "__main__":
    main()
