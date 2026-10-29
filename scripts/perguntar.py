"""
Faz uma pergunta ao servico de geracao e mostra resposta, fontes e avaliacao.

Uso: python scripts/perguntar.py "o que e o teorema CAP?" [--url http://localhost:8003]
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _http import chamar  # noqa: E402


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("pergunta")
    args.add_argument("--url", default="http://localhost:8003")
    args.add_argument("--top-k", type=int, default=3)
    args.add_argument("--json", action="store_true", help="mostra a resposta bruta")
    a = args.parse_args()

    status, r = chamar("POST", f"{a.url}/perguntar", {"pergunta": a.pergunta, "top_k": a.top_k})
    if a.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return
    print(f"HTTP {status}\n")
    if status == 200:
        print(r["resposta"], "\n")
        print("Fontes:")
        for f in r["fontes"]:
            print(f"  [{f['n']}] {f['origem']} ({f['trecho']}, pontuacao {f['pontuacao']})")
        if r["avaliacao"]:
            print("\nAvaliacao:", r["avaliacao"])
        print("Metadados:", r["metadados"])
    elif status == 503 and r and "disjuntor" in r:
        print(f"{r['erro']} - {r['motivo']}")
        print(f"Disjuntor: {r['disjuntor']['estado']}\n")
        print(r["resposta_degradada"])
        for trecho in r["contexto"]:
            print("  ", trecho[:160])
    else:
        print(r)


if __name__ == "__main__":
    main()
