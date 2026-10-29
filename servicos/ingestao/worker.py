"""
Worker de INGESTAO: consome a fila do Redis, divide os documentos em trechos,
gera os embeddings e persiste o indice em disco.

E a etapa assincrona do fluxo: a API so enfileira e responde 202 na hora;
o trabalho pesado (reajustar o vetorizador e revetorizar tudo) acontece aqui,
sem segurar a conexao do cliente.

Rodar: python -m servicos.ingestao.worker
"""
import logging
import os
import signal
import time

import redis

from servicos.ingestao import fila
from servicos.ingestao.armazenamento import Armazenamento, reindexar

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [worker-ingestao] %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CAMINHO_INDICE = os.getenv("CAMINHO_INDICE", "dados/indice.joblib")

_parar = False


def _pedir_parada(*_):
    global _parar
    _parar = True
    log.info("sinal recebido: termino a mensagem atual e encerro")


def processar(armazenamento, mensagem):
    novo = reindexar(armazenamento.atual(), mensagem["documentos"])
    armazenamento.salvar(novo)
    return {"versao_indice": novo["versao"], "trechos_no_indice": len(novo["trechos"])}


def executar():
    signal.signal(signal.SIGTERM, _pedir_parada)
    signal.signal(signal.SIGINT, _pedir_parada)
    armazenamento = Armazenamento(CAMINHO_INDICE)
    log.info("indice em %s (versao %d)", CAMINHO_INDICE, armazenamento.atual()["versao"])

    r, espera_reconexao = None, 1
    while not _parar:
        try:
            if r is None:
                r = fila.conectar()
                r.ping()
                n = fila.recuperar_pendentes(r)
                log.info("conectado ao Redis; %d mensagem(ns) pendente(s) recuperada(s)", n)
                espera_reconexao = 1

            bruta, mensagem = fila.receber(r, espera=2)
            if mensagem is None:
                continue

            log.info("tarefa %s: %d documento(s), tentativa %d",
                     mensagem["tarefa_id"], len(mensagem["documentos"]),
                     mensagem["tentativas"] + 1)
            fila.marcar_processando(r, mensagem)
            try:
                resultado = processar(armazenamento, mensagem)
            except Exception as erro:
                estado = fila.rejeitar(r, bruta, mensagem, erro)
                log.exception("tarefa %s falhou -> %s", mensagem["tarefa_id"], estado)
                time.sleep(min(5, 2 ** mensagem["tentativas"] * 0.5))
                continue
            fila.confirmar(r, bruta, mensagem, **resultado)
            log.info("tarefa %s concluida: %s", mensagem["tarefa_id"], resultado)

        except redis.RedisError as erro:
            # Redis fora do ar: reconecta com recuo exponencial, sem derrubar o worker
            log.warning("Redis indisponivel (%s); nova tentativa em %ds", erro, espera_reconexao)
            r = None
            time.sleep(espera_reconexao)
            espera_reconexao = min(espera_reconexao * 2, 30)


if __name__ == "__main__":
    executar()
