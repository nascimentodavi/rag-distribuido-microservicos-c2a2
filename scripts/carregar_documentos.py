"""
Envia os arquivos .txt de uma pasta para o servico de ingestao e acompanha a
tarefa na fila ate o worker terminar.

Uso: python scripts/carregar_documentos.py [pasta] [--url http://localhost:8001]
"""
import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _http import chamar  # noqa: E402


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("pasta", nargs="?", default="documentos")
    args.add_argument("--url", default="http://localhost:8001")
    args.add_argument("--espera", type=float, default=60, help="segundos para aguardar o worker")
    a = args.parse_args()

    arquivos = sorted(pathlib.Path(a.pasta).glob("*.txt"))
    if not arquivos:
        sys.exit(f"nenhum .txt em {a.pasta}")
    documentos = [{"origem": f.stem, "texto": f.read_text(encoding="utf-8")} for f in arquivos]

    status, resp = chamar("POST", f"{a.url}/indexar", documentos)
    if status != 202:
        sys.exit(f"falha ao enfileirar ({status}): {resp}")
    print(f"{len(documentos)} documento(s) enfileirado(s) -> tarefa {resp['tarefa_id']}")

    limite = time.monotonic() + a.espera
    while time.monotonic() < limite:
        _, tarefa = chamar("GET", f"{a.url}/tarefas/{resp['tarefa_id']}")
        print(f"  estado: {tarefa['estado']}")
        if tarefa["estado"] == "concluida":
            print(f"indice na versao {tarefa['versao_indice']} com {tarefa['trechos_no_indice']} trechos")
            return
        if tarefa["estado"] == "falhou":
            sys.exit(f"ingestao falhou: {tarefa.get('erro')}")
        time.sleep(1)
    sys.exit("o worker nao concluiu a tempo - verifique: docker compose logs ingestao-worker")


if __name__ == "__main__":
    main()
