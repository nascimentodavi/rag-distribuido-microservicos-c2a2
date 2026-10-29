import fakeredis
import pytest
import requests
from fastapi.testclient import TestClient
from requests.structures import CaseInsensitiveDict

from servicos.ingestao import app as app_ingestao
from servicos.ingestao import fila, worker
from servicos.ingestao.armazenamento import Armazenamento


def para_requests(resp_httpx, url):
    """Converte a resposta do TestClient (httpx) em requests.Response."""
    resp = requests.Response()
    resp.status_code = resp_httpx.status_code
    resp._content = resp_httpx.content
    resp.headers = CaseInsensitiveDict(resp_httpx.headers)
    resp.url = url
    return resp


class Roteador:
    """Substitui requests.request: entrega cada URL ao app FastAPI certo."""

    def __init__(self):
        self.apps = {}
        self.fora_do_ar = set()

    def __call__(self, metodo, url, timeout=None, **kwargs):
        for base, cliente in self.apps.items():
            if url.startswith(base):
                if base in self.fora_do_ar:
                    raise requests.ConnectionError(f"{base} recusou a conexao")
                resp = cliente.request(metodo, url[len(base):], **kwargs)
                return para_requests(resp, url)
        raise AssertionError(f"URL inesperada: {url}")


@pytest.fixture
def ingestao(tmp_path, monkeypatch):
    """API de ingestao em memoria + funcao que roda o worker sobre a fila."""
    r = fakeredis.FakeRedis(decode_responses=True)
    armazenamento = Armazenamento(str(tmp_path / "indice.joblib"))
    monkeypatch.setattr(app_ingestao, "_redis", r)
    monkeypatch.setattr(app_ingestao, "armazenamento", armazenamento)
    cliente = TestClient(app_ingestao.app)

    def indexar(documentos):
        assert cliente.post("/indexar", json=documentos).status_code == 202
        while True:
            bruta, msg = fila.receber(r, espera=0.1)
            if msg is None:
                break
            fila.confirmar(r, bruta, msg, **worker.processar(armazenamento, msg))

    cliente.indexar = indexar
    cliente.redis = r
    cliente.armazenamento = armazenamento
    return cliente


DOCUMENTOS = [
    {"origem": "cap", "texto": "O teorema CAP afirma que, diante de uma particao de rede, "
                               "um sistema distribuido precisa escolher entre consistencia e disponibilidade."},
    {"origem": "raft", "texto": "Raft e um algoritmo de consenso baseado em eleicao de lider e log replicado. "
                                "Uma operacao e confirmada quando a maioria dos nos registra."},
    {"origem": "disjuntor", "texto": "O circuit breaker abre depois de falhas seguidas e recusa chamadas "
                                     "ate que um tempo de espera passe, protegendo a dependencia instavel."},
]
