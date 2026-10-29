import functools
import time

import pytest
from fastapi.testclient import TestClient

from servicos.comum import llm
from servicos.comum.circuit_breaker import CircuitBreaker
from servicos.comum.resiliencia import com_retentativa
from servicos.geracao import app as app_geracao
from servicos.geracao.avaliacao import avaliar
from servicos.geracao.injetor_falhas import InjetorFalhas
from servicos.recuperacao import app as app_recuperacao
from testes.conftest import DOCUMENTOS, Roteador


@pytest.fixture
def sistema(ingestao, monkeypatch):
    """Os tres servicos ligados em memoria: geracao -> recuperacao -> ingestao."""
    roteador = Roteador()
    roteador.apps[app_recuperacao.URL_INGESTAO] = ingestao
    roteador.apps[app_geracao.URL_RECUPERACAO] = TestClient(app_recuperacao.app)
    monkeypatch.setattr(app_recuperacao.requests, "request", roteador)
    monkeypatch.setattr(app_recuperacao, "cache", app_recuperacao.CacheIndice())
    monkeypatch.setattr(app_geracao.requests, "post",
                        lambda url, **kw: roteador("POST", url, **kw))
    monkeypatch.setattr(app_geracao, "disjuntor", CircuitBreaker(limite_falhas=3, espera_segundos=60))
    monkeypatch.setattr(app_geracao, "injetor", InjetorFalhas())
    monkeypatch.setattr(llm, "API_KEY", "")  # modo simulado
    monkeypatch.setattr(app_geracao, "com_retentativa",  # sem esperar o backoff
                        functools.partial(com_retentativa, dormir=lambda s: None))
    ingestao.indexar(DOCUMENTOS)
    cliente = TestClient(app_geracao.app)
    cliente.roteador = roteador
    return cliente


def test_fluxo_ponta_a_ponta_com_fontes_e_avaliacao(sistema):
    resp = sistema.post("/perguntar", json={"pergunta": "O que diz o teorema CAP?"})
    assert resp.status_code == 200
    corpo = resp.json()
    assert "consistencia e disponibilidade" in corpo["resposta"]
    assert corpo["fontes"][0]["origem"] == "cap"
    assert corpo["avaliacao"]["veredito"] == "fundamentada"
    assert corpo["metadados"]["tentativas_llm"] == 1


def test_pergunta_sem_contexto_nao_chama_llm(sistema):
    corpo = sistema.post("/perguntar", json={"pergunta": "receita de bolo de cenoura"}).json()
    assert corpo["fontes"] == [] and corpo["metadados"]["tentativas_llm"] == 0


def test_llm_fora_do_ar_retenta_abre_disjuntor_e_degrada(sistema):
    sistema.post("/admin/falhas", json={"modo": "erro"})
    resp = sistema.post("/perguntar", json={"pergunta": "eleicao de lider no Raft"})
    assert resp.status_code == 503
    corpo = resp.json()
    assert corpo["metadados"]["tentativas_llm"] == 3   # retentou
    assert corpo["disjuntor"]["estado"] == "aberto"   # 3 falhas abriram o circuito
    assert corpo["fontes"][0]["origem"] == "raft"      # degradou com as fontes
    assert "Retry-After" in resp.headers

    # com o circuito aberto a recusa e imediata, sem tocar no LLM
    resp = sistema.post("/perguntar", json={"pergunta": "eleicao de lider no Raft"})
    assert resp.status_code == 503
    assert resp.json()["metadados"]["tentativas_llm"] == 1
    assert resp.json()["motivo"].startswith("circuito aberto")
    assert app_geracao.disjuntor.status()["total_recusadas"] == 1


def test_erro_intermitente_e_absorvido_pela_retentativa(sistema, monkeypatch):
    falhas = iter([True, False])
    monkeypatch.setattr(app_geracao.injetor, "modo", "intermitente")
    monkeypatch.setattr("servicos.geracao.injetor_falhas.random.random",
                        lambda: 0.0 if next(falhas) else 1.0)
    resp = sistema.post("/perguntar", json={"pergunta": "o que e circuit breaker?"})
    assert resp.status_code == 200
    assert resp.json()["metadados"]["tentativas_llm"] == 2
    assert app_geracao.disjuntor.estado == "fechado"


def test_tempo_limite_do_llm(sistema, monkeypatch):
    monkeypatch.setattr(llm, "TIMEOUT", 0.05)
    monkeypatch.setattr(llm, "gerar", lambda p, c: time.sleep(0.3) or "tarde demais")
    resp = sistema.post("/perguntar", json={"pergunta": "teorema CAP", "top_k": 1})
    assert resp.status_code == 503
    assert resp.json()["metadados"]["tentativas_llm"] == 3
    assert resp.json()["motivo"].startswith("tempo-limite")
    assert app_geracao.disjuntor.status()["ultima_falha"].startswith("TempoEsgotado")


def test_recuperacao_fora_do_ar_responde_503(sistema):
    sistema.roteador.fora_do_ar.add(app_geracao.URL_RECUPERACAO)
    resp = sistema.post("/perguntar", json={"pergunta": "teorema CAP"})
    assert resp.status_code == 503
    assert "recuperacao indisponivel" in resp.json()["detail"]


def test_avaliacao_detecta_resposta_sem_fundamento():
    contexto = ["[1] (fonte: cap) O teorema CAP trata de consistencia e disponibilidade."]
    boa = avaliar("teorema CAP", "O teorema CAP trata de consistencia e disponibilidade [1].", contexto)
    ruim = avaliar("teorema CAP", "Bananas amarelas crescem rapidamente em climas tropicais.", contexto)
    assert boa["veredito"] == "fundamentada" and boa["cita_fontes"]
    assert ruim["veredito"] == "pouco fundamentada"
