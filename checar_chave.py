"""Verifica se as chaves de API estão configuradas e funcionais."""

from dotenv import load_dotenv
load_dotenv()

import io
import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("cp"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def main() -> int:
    print()
    print("=" * 50)
    print("  Verificação de chaves de API")
    print("=" * 50)

    ok = True

    # ── ANTHROPIC_API_KEY ────────────────────────────
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    print()
    print("  ANTHROPIC_API_KEY")

    if not api_key or api_key == "sk-ant-api03-...":
        print("    ✗ Não configurada ou ainda é placeholder")
        print("    → Edite .env e coloque sua chave completa")
        ok = False
    else:
        print(f"    ✓ Encontrada ({api_key[:12]}...{api_key[-4:]})")
        print("    Testando conexão com a API...")

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=10,
                messages=[{"role": "user", "content": "Responda apenas: ok"}],
            )
            texto = response.content[0].text.strip()
            tokens = response.usage.input_tokens + response.usage.output_tokens
            print(f"    ✓ API respondeu: \"{texto}\" ({tokens} tokens)")
        except anthropic.AuthenticationError:
            print("    ✗ Chave inválida (401 Authentication Error)")
            print("    → Gere uma nova em console.anthropic.com/settings/keys")
            ok = False
        except anthropic.PermissionDeniedError:
            print("    ✗ Chave sem permissão (403 Permission Denied)")
            ok = False
        except anthropic.RateLimitError:
            print("    ⚠ Rate limit atingido — mas a chave é válida")
        except Exception as e:
            print(f"    ✗ Erro inesperado: {e}")
            ok = False

    # ── NEWSAPI_KEY ──────────────────────────────────
    news_key = os.environ.get("NEWSAPI_KEY", "")
    print()
    print("  NEWSAPI_KEY")

    if not news_key:
        print("    ⚠ Não configurada (fallback Google News RSS será usado)")
    elif news_key.startswith("sk-ant-"):
        print("    ⚠ Parece ser uma chave Anthropic, não da NewsAPI")
        print("    → Chaves da NewsAPI vêm de newsapi.org (formato diferente)")
        print("    → O sistema usará Google News RSS como fallback")
    else:
        print(f"    ✓ Encontrada ({news_key[:8]}...)")

    # ── LOG_TOKENS ───────────────────────────────────
    log_tokens = os.environ.get("LOG_TOKENS", "")
    print()
    print("  LOG_TOKENS")
    if log_tokens.lower() == "true":
        print("    ✓ Ativado — auditoria de tokens será gravada em output/")
    else:
        print("    ⚠ Desativado")

    # ── Resultado ────────────────────────────────────
    print()
    print("=" * 50)
    if ok:
        print("  ✓ Sistema pronto para uso")
    else:
        print("  ✗ Corrija os problemas acima antes de executar")
    print("=" * 50)
    print()

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
