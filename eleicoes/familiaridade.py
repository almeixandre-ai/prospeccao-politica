"""Índice de familiaridade com regulação digital — nota 0–3 em cada um dos 4 eixos do projeto (total 0–12).

Lê os dossiês de output/eleicoes2026/dossies/ e aplica regras explícitas e auditáveis:

  Eixos
    E1  IA e inovação
    E2  Proteção de dados e privacidade (LGPD)
    E3  Plataformas, concorrência e mercados digitais
    E4  Telecomunicações, cibersegurança e direitos digitais

  Sinais por eixo
    relatoria          relatoria de matéria do eixo (Senado: API; Câmara: ajustes manuais com fonte)
    autoria_principal  1º signatário de proposição NÚCLEO do eixo (termos estritos — não a lista ampla da agenda)
    coautoria          coautor de proposição núcleo
    colegiado_esp      comissão especial / GT / subcomissão dedicada ao tema
    colegiado_ger      comissão permanente temática (CCTI, CCOM, CCT, CCDD)
    lideranca          presidência ou vice-presidência de colegiado do eixo
    frente             frente parlamentar do eixo

  Nota
    3  protagonismo: ≥2 relatorias; ou relatoria + (colegiado específico titular ou ≥2 autorias);
       ou liderança em colegiado do eixo; ou colegiado específico titular + ≥2 autorias
    2  atuação consistente: 1 relatoria; ou titular de colegiado específico; ou ≥2 autorias principais;
       ou titular de colegiado permanente + ≥1 autoria
    1  sinal periférico: 1 autoria principal, coautoria, membro de colegiado ou frente
    0  sem sinal
  Volume de autoria sozinho não passa de 2 (o IIP já mostrou inflação por apresentação em massa).

  Sinal de alinhamento com a ABES (separado da nota): indícios por padrões explícitos nas ementas,
  sempre com a proposição citada. Sem indício = "indeterminado". Não usa partido nem ideologia.

Ajustes manuais (com justificativa e fonte) em eleicoes/familiaridade_ajustes.json.

Uso:  python -m eleicoes.familiaridade
"""

from __future__ import annotations

import csv
import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR_DOSSIES = RAIZ / "output" / "eleicoes2026" / "dossies"
DIR_SAIDA = RAIZ / "output" / "eleicoes2026" / "familiaridade"
ARQ_AJUSTES = Path(__file__).resolve().parent / "familiaridade_ajustes.json"

EIXOS = {
    "E1": "IA e inovação",
    "E2": "Proteção de dados e privacidade",
    "E3": "Plataformas, concorrência e mercados digitais",
    "E4": "Telecom, cibersegurança e direitos digitais",
}


def norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t.lower())


# Termos NÚCLEO por eixo (sobre o texto normalizado: minúsculas, sem acento)
NUCLEO = {
    "E1": r"inteligencia artificial|algoritm|aprendizado de maquina|deepfake|sistemas? de ia\b|lei do bem|11\.196"
          r"|fndct|fundo nacional de desenvolvimento cientifico|11\.540|lei de informatica|8\.248|10\.973|startups?"
          r"|lei complementar n.{0,3} ?182|inovacao tecnologica|pesquisa,? desenvolvimento e inovacao|sandbox",
    "E2": r"13\.709|lgpd|dados pessoais|protecao de dados|privacidade|\banpd\b|tratamento de dados|dados biometricos",
    "E3": r"plataformas? digita|redes? socia|provedores? de aplicac|mercados? digita|marketplace|big techs?"
          r"|moderacao de conteudo|servicos? digita|aplicativos? de (transporte|entrega|mensag)|streaming|influenciador",
    "E4": r"telecomunica|conectividade|banda larga|\b5g\b|internet|13\.116|9\.472|cibern|ciberseguranca|seguranca ciber"
          r"|criptograf|marco civil|12\.965|inclusao digital|data ?centers?|centros? de dados|redata|\bfust\b",
}
# E3 exige intenção regulatória/de mercado (evita "programa X divulgado em redes sociais")
E3_INTENCAO = r"obrig|dever|respons|regul|proib|vedad|veda |transparen|moderac|remoc|controle parental|publicidade|concorr|cade|consumidor|remunera|algoritm|seguranca|protec"
EXCLUIR = r"\banimais?\b|adocao de animais|festas? tipica|turistic|carnes? na cesta"

COLEGIADOS = {
    # sigla: (eixos, tipo)
    "PL233823": (["E1"], "esp"), "CTIA": (["E1"], "esp"), "SUBIA": (["E1"], "esp"), "GT-IA": (["E1"], "esp"),
    "GTREDES": (["E3"], "esp"), "GTAMBDIG": (["E3", "E2"], "esp"), "SUBTAPD": (["E3"], "esp"),
    "SUBANAT": (["E4"], "esp"),
    "CCTI": (["E1", "E4"], "ger"), "CCT": (["E1", "E4"], "ger"),
    "CCOM": (["E3", "E4"], "ger"), "CCDD": (["E2", "E3", "E4"], "ger"),
}
FRENTES = {
    "E1": r"ciencia, tecnologia|startups|economia e cidadania digitais",
    "E2": r"economia e cidadania digitais",
    "E3": r"economia e cidadania digitais|violencia em ambiente digital",
    "E4": r"telecomunicacoes|conectividade|ciberseguranca|economia e cidadania digitais",
}

# Indícios de alinhamento com a agenda ABES (agenda_abes.json: posicao_abes × sinais_contrarios)
FAVORAVEL = [
    (r"desoneracao da folha", "Desoneração da folha"),
    (r"(lei do bem|11\.196|fndct|11\.540).*(fortalec|amplia|destina|garant|veda|execucao)|vedar a limitacao de empenho.*inovacao",
     "Fortalece incentivos/fundos de P&D"),
    (r"(startups?|182).*(ampli|isencao|incentiv|fomento|estimul)", "Fomento a startups"),
    (r"avaliacao de impacto regulatorio", "Avaliação de impacto regulatório"),
    (r"sandbox", "Sandbox regulatório"),
    (r"(data ?center|centros? de dados|redata).*(incentiv|atracao|fomento|regime)", "Atração de data centers"),
]
ATENCAO = [
    (r"responsabilidade (civil )?(objetiva|solidaria)", "Responsabilidade objetiva/solidária"),
    (r"(proib|vedad|veda ).{0,60}(uso|utilizacao).{0,30}inteligencia artificial", "Proibição de uso de IA"),
    (r"(armazenamento|localizacao|servidores?).{0,60}(territorio nacional|no brasil|no pais)", "Localização de dados"),
    (r"(contribuicao|cide|tributo|taxa).{0,60}servicos digitais", "Tributo sobre serviços digitais"),
    (r"(acesso|quebra).{0,40}criptograf", "Acesso a dados criptografados"),
    (r"(todos os|quaisquer) (provedores|fornecedores)", "Obrigação ampla a qualquer provedor"),
]


def eixos_da_ementa(ementa: str) -> list[str]:
    t = norm(ementa)
    if re.search(EXCLUIR, t):
        return []
    out = [e for e, rx in NUCLEO.items() if re.search(rx, t)]
    if "E3" in out and not re.search(E3_INTENCAO, t):
        out.remove("E3")
    return out


def _papel(o: str) -> str:
    return norm(o.split(" — ", 1)[1].split("(")[0]) if " — " in o else ""


def calcular(d: dict, ajustes: dict) -> dict:
    sinais = {e: {"relatoria": [], "autoria_principal": [], "coautoria": [], "colegiado_esp": [],
                  "colegiado_ger": [], "lideranca": [], "frente": []} for e in EIXOS}
    for p in d["proposicoes_agenda"]:
        ementa = f"{p['ementa']} {p.get('ementa_detalhada') or ''}"
        for e in eixos_da_ementa(ementa):
            item = {"id": p["identificacao"], "ementa": p["ementa"][:300], "url": p.get("url"), "situacao": p.get("situacao")}
            sinais[e]["autoria_principal" if p.get("e_autor_principal") else "coautoria"].append(item)
    for r in d["relatorias_agenda"]:
        for e in eixos_da_ementa(r["ementa"]):
            sinais[e]["relatoria"].append({"id": r["identificacao"], "ementa": r["ementa"][:300],
                                           "colegiado": r.get("colegiado"), "url": r.get("url")})
    for o in d["orgaos"]:
        sigla = o.split(" — ")[0]
        if sigla not in COLEGIADOS:
            continue
        eixos, tipo = COLEGIADOS[sigla]
        papel = _papel(o)
        for e in eixos:
            # liderança = presidência, ou 1ª vice-presidência de colegiado ESPECÍFICO (2º/3º vice não contam)
            if (papel.startswith("presidente") or
                    (tipo == "esp" and re.match(r"(1o|1º|primeiro) vice", papel))):
                sinais[e]["lideranca"].append(o[:160])
            if papel.startswith("relator"):  # relator do próprio colegiado (ex.: comissão especial do PL 2338)
                sinais[e]["relatoria"].append({"id": sigla, "ementa": o[:300], "colegiado": sigla, "url": None})
                sinais[e]["lideranca"].append(o[:160])
            if tipo == "esp":
                sinais[e]["colegiado_esp"].append(o[:160])
            elif "titular" in papel or "presidente" in papel:
                sinais[e]["colegiado_ger"].append(o[:160])
    for f in d["frentes"]:
        for e, rx in FRENTES.items():
            if re.search(rx, norm(f)):
                sinais[e]["frente"].append(f)

    # ajustes manuais: sinais adicionais com fonte (ex.: relatorias na Câmara)
    aj = ajustes.get(d["parlamentar_chave"], {})
    for s in aj.get("sinais", []):
        sinais[s["eixo"]][s["tipo"]].append({"id": s.get("id"), "ementa": s.get("descricao"), "url": s.get("fonte"),
                                             "manual": True})

    notas, justif = {}, {}
    for e, s in sinais.items():
        n_rel, n_pri = len(s["relatoria"]), len({x["id"] for x in s["autoria_principal"]})
        esp_tit = any("titular" in _papel(x) or "presidente" in _papel(x) for x in s["colegiado_esp"] if isinstance(x, str))
        esp_tit = esp_tit or any(isinstance(x, dict) for x in s["colegiado_esp"])
        lider = bool(s["lideranca"])
        if n_rel >= 2 or (n_rel >= 1 and (esp_tit or n_pri >= 2)) or lider or (esp_tit and n_pri >= 2):
            nota = 3
        elif n_rel >= 1 or esp_tit or n_pri >= 2 or (s["colegiado_ger"] and n_pri >= 1):
            nota = 2
        elif n_pri or s["coautoria"] or s["colegiado_esp"] or s["colegiado_ger"] or s["frente"]:
            nota = 1
        else:
            nota = 0
        if e in aj.get("nota", {}):
            nota = aj["nota"][e]["valor"]
        notas[e] = nota
        partes = []
        if n_rel: partes.append(f"{n_rel} relatoria(s)")
        if n_pri: partes.append(f"{n_pri} autoria(s) principal(is)")
        if s["coautoria"]: partes.append(f"{len(s['coautoria'])} coautoria(s)")
        if lider: partes.append("liderança em colegiado")
        if s["colegiado_esp"]: partes.append("colegiado específico" + (" (titular)" if esp_tit else ""))
        if s["colegiado_ger"]: partes.append("titular de comissão permanente")
        if s["frente"]: partes.append(f"{len(s['frente'])} frente(s)")
        if e in aj.get("nota", {}):
            partes.append(f"AJUSTE MANUAL: {aj['nota'][e]['justificativa']}")
        justif[e] = "; ".join(partes) or "sem sinal"

    fav, ate = [], []
    for p in d["proposicoes_agenda"]:
        if not p.get("e_autor_principal"):
            continue
        t = norm(f"{p['ementa']} {p.get('ementa_detalhada') or ''}")
        fav += [{"id": p["identificacao"], "indicio": r, "url": p.get("url")} for rx, r in FAVORAVEL if re.search(rx, t)]
        ate += [{"id": p["identificacao"], "indicio": r, "url": p.get("url")} for rx, r in ATENCAO if re.search(rx, t)]
    fav += aj.get("alinhamento_favoravel", [])
    ate += aj.get("alinhamento_atencao", [])
    sinal = ("misto" if fav and ate else "favorável (indícios)" if fav else "atenção (indícios)" if ate else "indeterminado")

    alertas = list(aj.get("alertas", []))
    if len({p["identificacao"] for p in d["proposicoes_agenda"] if p.get("e_autor_principal")}) >= 40:
        alertas.append("Alto volume de autoria — verificar substância antes de tratar como especialista")
    alertas += d.get("limitacoes", [])

    return {
        "parlamentar_chave": d["parlamentar_chave"], "nome_urna": d["nome_urna"], "casa_2027": d["casa_2027"],
        "uf": d["uf"], "partido": d["partido"], "iip": d["iip"], "prioridade_iip": d["prioridade"],
        "notas": notas, "total": sum(notas.values()), "justificativas": justif,
        "sinal_alinhamento_abes": sinal, "indicios_favoraveis": fav, "indicios_atencao": ate,
        "perfil_resumo": aj.get("perfil_resumo", ""), "alertas": alertas, "evidencias": sinais,
        "data_calculo": date.today().isoformat(),
    }


def faixa(total: int) -> str:
    return ("Referência (9–12)" if total >= 9 else "Familiarizado (6–8)" if total >= 6
            else "Interesse pontual (3–5)" if total >= 3 else "Baixa familiaridade (0–2)")


def main(argv: list[str] | None = None) -> int:
    ajustes = json.loads(ARQ_AJUSTES.read_text(encoding="utf-8")).get("parlamentares", {}) if ARQ_AJUSTES.exists() else {}
    res = [calcular(json.loads(f.read_text(encoding="utf-8")), ajustes)
           for f in sorted(DIR_DOSSIES.glob("*.json")) if not f.name.startswith("_")]
    res.sort(key=lambda r: (-r["total"], -(r["iip"] or 0)))
    for r in res:
        r["faixa"] = faixa(r["total"])
    DIR_SAIDA.mkdir(parents=True, exist_ok=True)
    (DIR_SAIDA / "indice_familiaridade.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    cols = ["posicao", "nome_urna", "casa_2027", "uf", "partido", *[f"{e} {n}" for e, n in EIXOS.items()], "total",
            "faixa", "sinal_alinhamento_abes", "indicios", "iip", "alertas", "chave"]
    with open(DIR_SAIDA / "indice_familiaridade.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(cols)
        for i, r in enumerate(res, 1):
            ind = [f"+ {x['id']}: {x['indicio']}" for x in r["indicios_favoraveis"]] + \
                  [f"! {x['id']}: {x['indicio']}" for x in r["indicios_atencao"]]
            w.writerow([i, r["nome_urna"], r["casa_2027"], r["uf"], r["partido"], *r["notas"].values(), r["total"],
                        r["faixa"], r["sinal_alinhamento_abes"], " | ".join(ind), r["iip"], " | ".join(r["alertas"]),
                        r["parlamentar_chave"]])
    print(f"{len(res)} parlamentares → {DIR_SAIDA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
