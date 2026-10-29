import fakeredis
import pytest
from fastapi.testclient import TestClient

from servicos.ingestao import app as modulo_app
from servicos.ingestao import fila, worker
from servicos.ingestao.armazenamento import Armazenamento


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    r = fakeredis.FakeRedis(decode_responses=True)
    armazenamento = Armazenamento(str(tmp_path / "indice.joblib"))
    monkeypatch.setattr(modulo_app, "_redis", r)
    monkeypatch.setattr(modulo_app, "armazenamento", armazenamento)
    return TestClient(modulo_app.app), r, armazenamento


def processar_fila(r, armazenamento):
    """Faz o papel do worker: consome tudo o que estiver na fila."""
    while True:
        bruta, msg = fila.receber(r, espera=0.1)
        if msg is None:
            return
        fila.marcar_processando(r, msg)
        fila.confirmar(r, bruta, msg, **worker.processar(armazenamento, msg))


def test_indexar_so_enfileira_e_worker_indexa(ambiente):
    cliente, r, armazenamento = ambiente
    resp = cliente.post("/indexar", json=[
        {"texto": "O teorema CAP trata de consistencia e disponibilidade.", "origem": "cap"},
        {"texto": "Raft elege um lider por maioria.", "origem": "raft"}])
    assert resp.status_code == 202
    tarefa_id = resp.json()["tarefa_id"]
    assert cliente.get(f"/tarefas/{tarefa_id}").json()["estado"] == "na_fila"
    assert cliente.get("/indice").json()["total"] == 0  # ainda nao processado

    processar_fila(r, armazenamento)

    assert cliente.get(f"/tarefas/{tarefa_id}").json()["estado"] == "concluida"
    indice = cliente.get("/indice").json()
    assert indice["versao"] == 1 and indice["total"] == 2
    assert {i["origem"] for i in indice["itens"]} == {"cap", "raft"}


def test_reenviar_mesma_origem_substitui_documento(ambiente):
    cliente, r, armazenamento = ambiente
    cliente.post("/indexar", json=[{"texto": "versao antiga", "origem": "a"}])
    cliente.post("/indexar", json=[{"texto": "versao nova", "origem": "a"}])
    processar_fila(r, armazenamento)
    itens = cliente.get("/indice").json()["itens"]
    assert [i["texto"] for i in itens] == ["versao nova"]


def test_indice_persiste_entre_reinicios(ambiente, tmp_path):
    cliente, r, armazenamento = ambiente
    cliente.post("/indexar", json=[{"texto": "dados persistidos", "origem": "p"}])
    processar_fila(r, armazenamento)
    reaberto = Armazenamento(armazenamento.caminho)  # "reinicia" o servico
    assert reaberto.atual()["documentos"] == {"p": "dados persistidos"}


def test_etag_evita_baixar_indice_inalterado(ambiente):
    cliente, r, armazenamento = ambiente
    cliente.post("/indexar", json=[{"texto": "algum texto", "origem": "x"}])
    processar_fila(r, armazenamento)
    etag = cliente.get("/indice").headers["etag"]
    assert cliente.get("/indice", headers={"If-None-Match": etag}).status_code == 304


def test_vetorizar_exige_indice(ambiente):
    cliente, _, _ = ambiente
    assert cliente.post("/vetorizar", json={"texto": "oi"}).status_code == 409


def test_falha_repetida_vai_para_fila_de_mortas(ambiente):
    _, r, _ = ambiente
    fila.enfileirar(r, [{"texto": "x", "origem": "x"}])
    for _ in range(fila.MAX_TENTATIVAS):
        bruta, msg = fila.receber(r, espera=0.1)
        estado = fila.rejeitar(r, bruta, msg, RuntimeError("disco cheio"))
    assert estado == "falhou"
    assert fila.tamanho_filas(r) == {"na_fila": 0, "processando": 0, "mortas": 1}


def test_mensagem_em_processamento_e_recuperada_apos_queda(ambiente):
    _, r, _ = ambiente
    fila.enfileirar(r, [{"texto": "x", "origem": "x"}])
    fila.receber(r, espera=0.1)  # worker pegou e "morreu" sem confirmar
    assert fila.tamanho_filas(r)["processando"] == 1
    assert fila.recuperar_pendentes(r) == 1
    assert fila.tamanho_filas(r)["na_fila"] == 1
