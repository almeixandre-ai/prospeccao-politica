#!/usr/bin/env python3
"""
Gera o Dashboard de Risco para um único PL (variante de prospecção política):
  - painel esquerdo: velocímetro (gauge) do Score MRP, com zona de risco colorida
  - painel direito: barras horizontais com a pontuação das 5 dimensões de risco

Uso:
  python3 generate_risk_dashboard.py input.json output.png

Formato do input.json:
{
  "score_mrp": 3.25,
  "score_max": 5.0,
  "zona": "Aten\u00e7\u00e3o",
  "dimensoes": [
    {"nome": "Processual", "pontuacao": 4, "confianca": "MEDIO"},
    {"nome": "Coaliz\u00e3o", "pontuacao": 2, "confianca": "MEDIO"},
    {"nome": "Agenda", "pontuacao": 4, "confianca": "ALTO"},
    {"nome": "Atores-Chave", "pontuacao": 3, "confianca": "BAIXO"},
    {"nome": "Ex\u00f3geno", "pontuacao": 3, "confianca": "ALTO"}
  ]
}
"""
import sys
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Wedge, Circle

PRETO = "#231F20"
DOURADO = "#C99A3F"
CINZA_TXT = "#5A5A5A"
VERMELHO = "#C0392B"
AMBAR = "#D9A61A"
VERDE = "#2E7D32"


def cor_por_pontuacao(p, pmax=5):
    frac = p / pmax
    if frac >= 0.7:
        return VERMELHO
    if frac >= 0.45:
        return AMBAR
    return VERDE


def main():
    input_path, output_path = sys.argv[1], sys.argv[2]
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    score = data["score_mrp"]
    score_max = data.get("score_max", 5.0)
    zona = data.get("zona", "")
    dims = data["dimensoes"]

    plt.rcParams["font.family"] = "DejaVu Sans"
    fig = plt.figure(figsize=(10.6, 4.0), dpi=200)
    gs = fig.add_gridspec(1, 2, width_ratios=[0.85, 1.35], wspace=0.4)

    # ---- Painel esquerdo: gauge ----
    ax0 = fig.add_subplot(gs[0])
    ax0.set_xlim(-1.25, 1.25)
    ax0.set_ylim(-1.05, 1.3)
    ax0.axis("off")
    ax0.set_aspect("equal")

    # três zonas do semicírculo: verde (0-45%), amber (45-70%), vermelho (70-100%)
    zonas = [(0, 81, VERDE), (81, 126, AMBAR), (126, 180, VERMELHO)]
    for theta1, theta2, cor in zonas:
        ax0.add_patch(Wedge((0, 0), 1.0, 180 - theta2, 180 - theta1, width=0.28, facecolor=cor, edgecolor="white", linewidth=1.5))

    # ponteiro (fica inteiramente dentro do semicírculo superior, nunca cruza os textos abaixo)
    frac = min(max(score / score_max, 0), 1)
    angle = np.deg2rad(180 - frac * 180)
    ax0.plot([0, 0.60 * np.cos(angle)], [0, 0.60 * np.sin(angle)], color=PRETO, linewidth=3, solid_capstyle="round", zorder=2)
    ax0.add_patch(Circle((0, 0), 0.05, facecolor=PRETO, zorder=2))

    # textos ficam todos abaixo do eixo do semicírculo (y < 0), sem risco de cruzar o ponteiro
    ax0.text(0, -0.30, f"{score:.2f}", ha="center", va="center", fontsize=30, fontweight="bold", color=PRETO, zorder=6)
    ax0.text(0, -0.54, f"/ {score_max:.1f}  Score MRP", ha="center", va="center", fontsize=10.5, color=CINZA_TXT, zorder=6)
    cor_zona = cor_por_pontuacao(score, score_max)
    ax0.text(0, -0.82, zona.upper(), ha="center", va="center", fontsize=12, fontweight="bold", color=cor_zona, zorder=6)

    # ---- Painel direito: barras das 5 dimensões ----
    ax1 = fig.add_subplot(gs[1])
    nomes = [d["nome"] for d in dims][::-1]
    pontuacoes = [d["pontuacao"] for d in dims][::-1]
    confiancas = [d["confianca"] for d in dims][::-1]
    cores = [cor_por_pontuacao(p) for p in pontuacoes]
    y = np.arange(len(nomes))

    ax1.barh(y, pontuacoes, color=cores, height=0.58, zorder=3)
    ax1.barh(y, [5] * len(nomes), color="#EDEDED", height=0.58, zorder=1)
    ax1.barh(y, pontuacoes, color=cores, height=0.58, zorder=2)

    for i, (p, c) in enumerate(zip(pontuacoes, confiancas)):
        ax1.text(p + 0.12, i, f"{p}/5", va="center", fontsize=10, fontweight="bold", color=PRETO)
        ax1.text(5.35, i, f"conf. {c.lower()}", va="center", fontsize=8.3, color=CINZA_TXT, style="italic")

    ax1.set_yticks(y)
    ax1.set_yticklabels(nomes, fontsize=10.8, color=PRETO)
    ax1.set_xlim(0, 7.4)
    ax1.set_xticks([])
    for spine in ["top", "right", "bottom", "left"]:
        ax1.spines[spine].set_visible(False)
    ax1.set_title("Pontua\u00e7\u00e3o por Dimens\u00e3o de Risco", fontsize=12.5, fontweight="bold", color=PRETO, pad=12, loc="left")

    fig.savefig(output_path, bbox_inches="tight", facecolor="white")
    print(f"Dashboard de risco salvo em {output_path}")


if __name__ == "__main__":
    main()
