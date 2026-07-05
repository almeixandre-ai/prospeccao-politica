"""Smoke test — verifica módulos, dependências e ambiente do sistema."""

from __future__ import annotations

import importlib
import io
import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Garantir que o diretório raiz do projeto esteja no path
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ── Config ───────────────────────────────────────────────────────────────────

MODULOS = [
    "coleta.schemas",
    "coleta.coletor",
    "analise.schemas_risco",
    "analise.coletores_evidencia",
    "analise.avaliador_risco",
    "analise.gerador_prospeccao",
]

DEPS = ["requests", "pydantic", "anthropic"]

ENV_OBRIGATORIAS = {"ANTHROPIC_API_KEY": "Obrigatória para chamadas à API Claude"}
ENV_OPCIONAIS = {"NEWSAPI_KEY": "Opcional — fallback RSS ativo se ausente"}

MOCKS = [
    {
        "tipo_sigla": "PL", "numero": 2338, "ano": 2023, "origem": "camara",
        "ementa": "Dispõe sobre o uso da Inteligência Artificial no Brasil.",
        "situacao_atual": "Aguardando Parecer",
        "ultimo_evento": "Notificação de Apensação",
        "ultimo_evento_data": "2026-06-17",
        "autor": "Senado Federal - Rodrigo Pacheco",
        "relator_designado": "Dep. Fulano da Silva",
        "comissoes_pendentes": ["CCTCI", "CCJ"],
        "regime_tramitacao": "Ordinária",
    },
    {
        "tipo_sigla": "PL", "numero": 278, "ano": 2026, "origem": "senado",
        "ementa": "Dispõe sobre plataformas digitais e moderação de conteúdo.",
        "situacao_atual": "Tramitando",
        "autor": "Sen. Exemplo",
        "relator_designado": None,
        "comissoes_pendentes": ["CCT"],
        "regime_tramitacao": "Urgência",
    },
]

OK = "✓"
FAIL = "✗"
WARN = "⚠"


# ── Verificações ─────────────────────────────────────────────────────────────

def check_modulos() -> tuple[list[str], list[str]]:
    sucesso, falha = [], []
    for mod in MODULOS:
        try:
            importlib.import_module(mod)
            sucesso.append(mod)
        except Exception as e:
            falha.append(f"{mod} — {type(e).__name__}: {e}")
    return sucesso, falha


def check_env() -> tuple[list[str], list[str], list[str]]:
    ok, ausente, avisos = [], [], []
    for var, desc in ENV_OBRIGATORIAS.items():
        if os.environ.get(var):
            ok.append(f"{var} configurada")
        else:
            ausente.append(f"{var} AUSENTE ({desc})")
    for var, desc in ENV_OPCIONAIS.items():
        if os.environ.get(var):
            ok.append(f"{var} configurada")
        else:
            avisos.append(f"{var} não configurada ({desc})")
    return ok, ausente, avisos


def check_deps() -> tuple[list[str], list[str]]:
    ok, falha = [], []
    for dep in DEPS:
        try:
            mod = importlib.import_module(dep)
            ver = getattr(mod, "__version__", getattr(mod, "VERSION", "?"))
            ok.append(f"{dep} {ver}")
        except ImportError:
            falha.append(f"{dep} — não instalada (pip install {dep})")
    return ok, falha


def check_mocks() -> tuple[list[str], list[str]]:
    ok, falha = [], []
    try:
        from coleta.schemas import ProposicaoInfo
    except ImportError as e:
        falha.append(f"Não foi possível importar ProposicaoInfo: {e}")
        return ok, falha

    for mock_data in MOCKS:
        ident = f"{mock_data['tipo_sigla']} {mock_data['numero']}/{mock_data['ano']}"
        try:
            prop = ProposicaoInfo.model_validate(mock_data)

            completo = bool(
                prop.ementa and prop.situacao_atual and prop.comissoes_pendentes is not None
            )

            partes = []
            if completo:
                partes.append("dados completos")
            else:
                partes.append("dados INCOMPLETOS")

            n_com = len(prop.comissoes_pendentes)
            partes.append(f"{n_com} comiss{'ão' if n_com == 1 else 'ões'}")

            if prop.relator_designado:
                partes.append("relator identificado")
            else:
                partes.append("sem relator")

            if prop.regime_tramitacao:
                partes.append(f"regime {prop.regime_tramitacao}")

            if prop.origem:
                casa = "Câmara" if prop.origem == "camara" else "Senado"
                partes.append(f"casa {casa}")

            ok.append(f"{ident} — {', '.join(partes)}")

        except Exception as e:
            falha.append(f"{ident} — {type(e).__name__}: {e}")

    return ok, falha


# ── Relatório ────────────────────────────────────────────────────────────────

def main() -> int:
    total, passou = 0, 0

    print()
    print("═" * 42)
    print("  SMOKE TEST — Sistema de Prospecção")
    print("═" * 42)

    # Módulos
    mod_ok, mod_fail = check_modulos()
    total += len(mod_ok) + len(mod_fail)
    passou += len(mod_ok)

    print("  Módulos")
    for m in mod_ok:
        print(f"    {OK} {m}")
    for m in mod_fail:
        print(f"    {FAIL} {m}")

    # Variáveis de ambiente
    env_ok, env_ausente, env_warn = check_env()
    total += len(env_ok) + len(env_ausente)
    passou += len(env_ok)

    print()
    print("  Variáveis de ambiente")
    for e in env_ok:
        print(f"    {OK} {e}")
    for e in env_ausente:
        print(f"    {FAIL} {e}")
    for e in env_warn:
        print(f"    {WARN} {e}")

    # Dependências
    dep_ok, dep_fail = check_deps()
    total += len(dep_ok) + len(dep_fail)
    passou += len(dep_ok)

    print()
    print("  Dependências")
    for d in dep_ok:
        print(f"    {OK} {d}")
    for d in dep_fail:
        print(f"    {FAIL} {d}")

    # Coleta mock
    mock_ok, mock_fail = check_mocks()
    total += len(mock_ok) + len(mock_fail)
    passou += len(mock_ok)

    print()
    print("  Coleta mock")
    for m in mock_ok:
        print(f"    {OK} {m}")
    for m in mock_fail:
        print(f"    {FAIL} {m}")

    # Resultado
    critico = bool(mod_fail or dep_fail)
    acoes = []
    for d in dep_fail:
        nome = d.split(" —")[0]
        acoes.append(f"pip install {nome}")
    if env_ausente:
        acoes.append("Configurar ANTHROPIC_API_KEY no ambiente")

    print()
    print("═" * 42)
    status = "FALHA" if critico else "OK"
    print(f"  RESULTADO: {passou}/{total} verificações ok — {status}")
    for a in acoes:
        print(f"  Execute: {a}")
    print("═" * 42)
    print()

    return 1 if critico else 0


if __name__ == "__main__":
    sys.exit(main())
