"""Cliente HTTP minimo (so biblioteca padrao) usado pelos scripts."""
import json
import urllib.error
import urllib.request


def chamar(metodo, url, corpo=None, timeout=30):
    """Devolve (status, json). Erros HTTP tambem devolvem o corpo JSON."""
    dados = json.dumps(corpo).encode() if corpo is not None else None
    pedido = urllib.request.Request(url, data=dados, method=metodo,
                                    headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as erro:
        try:
            return erro.code, json.loads(erro.read() or b"null")
        except ValueError:
            return erro.code, None
