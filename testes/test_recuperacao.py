import pytest
from fastapi.testclient import TestClient

from servicos.recuperacao import app as app_recuperacao
from testes.conftest import DOCUMENTOS, Roteador


@pytest.fixture
def recuperacao(ingestao, monkeypatch):
    roteador = Roteador()
    roteador.apps[app_recuperacao.URL_INGESTAO] = ingestao
    monkeypatch.setattr(app_recuperacao.requests, "request", roteador)
    monkeypatch.setattr(app_recuperacao, "cache", app_recuperacao.CacheIndice())
    cliente = TestClient(app_recuperacao.app)
    cliente.roteador = roteador
    return cliente


def test_busca_devolve_trecho_mais_relevante_primeiro(ingestao, recuperacao):
    ingestao.indexar(DOCUMENTOS)
    resp = recuperacao.post("/buscar", json={"pergunta": "O que diz o teorema CAP?", "top_k": 2})
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["modo"] == "vetorial" and corpo["reranking"] is True
    assert corpo["resultados"][0]["origem"] == "cap"
    assert len(corpo["resultados"]) <= 2


def test_pergunta_sem_relacao_nao_traz_trechos(ingestao, recuperacao):
    ingestao.indexar(DOCUMENTOS)
    resp = recuperacao.post("/buscar", json={"pergunta": "receita de bolo de cenoura"})
    assert resp.json()["resultados"] == []


def test_cache_acompanha_reindexacao(ingestao, recuperacao):
    ingestao.indexar(DOCUMENTOS[:1])
    assert recuperacao.post("/buscar", json={"pergunta": "raft lider"}).json()["resultados"] == []
    ingestao.indexar(DOCUMENTOS[1:])
    corpo = recuperacao.post("/buscar", json={"pergunta": "raft lider"}).json()
    assert corpo["versao_indice"] == 2
    assert corpo["resultados"][0]["origem"] == "raft"


def test_indice_vazio_devolve_409(ingestao, recuperacao):
    assert recuperacao.post("/buscar", json={"pergunta": "algo"}).status_code == 409


def test_ingestao_fora_do_ar_degrada_para_busca_lexica(ingestao, recuperacao):
    ingestao.indexar(DOCUMENTOS)
    recuperacao.post("/buscar", json={"pergunta": "aquece o cache"})
    recuperacao.roteador.fora_do_ar.add(app_recuperacao.URL_INGESTAO)
    corpo = recuperacao.post("/buscar", json={"pergunta": "eleicao de lider no Raft"}).json()
    assert corpo["modo"].startswith("lexico")
    assert corpo["resultados"][0]["origem"] == "raft"


def test_ingestao_fora_do_ar_sem_cache_devolve_503(recuperacao):
    recuperacao.roteador.fora_do_ar.add(app_recuperacao.URL_INGESTAO)
    assert recuperacao.post("/buscar", json={"pergunta": "algo"}).status_code == 503
