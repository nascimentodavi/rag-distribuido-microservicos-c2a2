"""
Demonstra o circuit breaker do servico de geracao, de ponta a ponta:

  1. LLM saudavel                       -> 200, disjuntor FECHADO
  2. simula a API do LLM fora do ar     -> retentativas falham, disjuntor ABRE
  3. nova pergunta                      -> recusa imediata (sem chamar o LLM)
  4. LLM volta, espera o tempo do disjuntor -> chamada de teste (MEIO-ABERTO)
     tem sucesso e o disjuntor FECHA de novo

Uso: python scripts/demo_resiliencia.py [--url http://localhost:8003]
"""
import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _http import chamar  # noqa: E402

PERGUNTA = {"pergunta": "Quais sao os estados do circuit breaker?"}


def perguntar(url):
    inicio = time.monotonic()
    status, r = chamar("POST", f"{url}/perguntar", PERGUNTA)
    ms = (time.monotonic() - inicio) * 1000
    _, saude = chamar("GET", f"{url}/saude")
    d = saude["disjuntor"]
    print(f"   HTTP {status} em {ms:6.0f} ms | chamadas ao LLM: "
          f"{r['metadados']['tentativas_llm']} | disjuntor: {d['estado'].upper()} "
          f"(falhas consecutivas {d['falhas_consecutivas']}/{d['limite_falhas']})")
    if status == 503:
        print(f"   motivo: {r['motivo']}")
    return saude


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--url", default="http://localhost:8003")
    url = args.parse_args().url

    chamar("POST", f"{url}/admin/falhas", {"modo": "normal"})
    print("1) LLM saudavel")
    perguntar(url)

    print("\n2) Simulando a API do LLM fora do ar (POST /admin/falhas modo=erro)")
    chamar("POST", f"{url}/admin/falhas", {"modo": "erro"})
    saude = perguntar(url)

    print("\n3) Nova pergunta com o circuito aberto: recusa imediata")
    perguntar(url)

    espera = saude["disjuntor"]["reabre_teste_em_segundos"]
    print(f"\n4) LLM volta ao normal; aguardando {espera:.0f}s ate o disjuntor liberar o teste...")
    chamar("POST", f"{url}/admin/falhas", {"modo": "normal"})
    time.sleep(espera + 0.5)
    perguntar(url)
    print("\nPronto: o disjuntor passou por fechado -> aberto -> meio-aberto -> fechado.")


if __name__ == "__main__":
    main()
