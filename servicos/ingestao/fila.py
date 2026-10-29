"""
Fila de ingestao sobre Redis (mensageria entre a API e o worker).

Padrao "fila confiavel":
  - a API faz LPUSH da mensagem em FILA;
  - o worker faz BLMOVE atomico de FILA para PROCESSANDO: se ele morrer no
    meio, a mensagem nao se perde - continua em PROCESSANDO e volta para a
    fila quando o worker reinicia (recuperar_pendentes);
  - sucesso -> LREM de PROCESSANDO (ack);
  - falha   -> volta para a fila com tentativas+1; passou do limite, vai para
    a fila de mensagens mortas (DLQ) para analise manual.

O estado de cada tarefa fica em um hash (rag:tarefa:<id>) para o cliente
consultar em GET /tarefas/<id>.
"""
import json
import os
import time
import uuid

import redis

FILA = "rag:ingestao:fila"
PROCESSANDO = "rag:ingestao:processando"
MORTAS = "rag:ingestao:dlq"
PREFIXO_TAREFA = "rag:tarefa:"
VALIDADE_TAREFA = 24 * 3600
MAX_TENTATIVAS = int(os.getenv("INGESTAO_MAX_TENTATIVAS", "3"))


def conectar():
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return redis.Redis.from_url(url, decode_responses=True,
                                socket_connect_timeout=3, socket_timeout=10)


def _atualizar_tarefa(r, tarefa_id, **campos):
    chave = PREFIXO_TAREFA + tarefa_id
    campos["atualizada_em"] = time.time()
    r.hset(chave, mapping={k: str(v) for k, v in campos.items()})
    r.expire(chave, VALIDADE_TAREFA)


def enfileirar(r, documentos):
    """Publica os documentos na fila e devolve o id da tarefa."""
    tarefa_id = uuid.uuid4().hex
    mensagem = json.dumps({"tarefa_id": tarefa_id, "documentos": documentos,
                           "tentativas": 0})
    _atualizar_tarefa(r, tarefa_id, estado="na_fila", documentos=len(documentos),
                      tentativas=0, criada_em=time.time())
    r.lpush(FILA, mensagem)
    return tarefa_id


def consultar_tarefa(r, tarefa_id):
    return r.hgetall(PREFIXO_TAREFA + tarefa_id) or None


def tamanho_filas(r):
    return {"na_fila": r.llen(FILA), "processando": r.llen(PROCESSANDO),
            "mortas": r.llen(MORTAS)}


def recuperar_pendentes(r):
    """Devolve para a fila o que ficou em PROCESSANDO (worker caiu no meio).

    Supoe um unico worker; com varios, cada um teria a sua lista PROCESSANDO.
    """
    recuperadas = 0
    while r.lmove(PROCESSANDO, FILA, "RIGHT", "LEFT"):
        recuperadas += 1
    return recuperadas


def receber(r, espera=5):
    """Bloqueia ate `espera` segundos por uma mensagem. Devolve (bruta, dict)."""
    bruta = r.blmove(FILA, PROCESSANDO, espera, "RIGHT", "LEFT")
    if bruta is None:
        return None, None
    return bruta, json.loads(bruta)


def confirmar(r, bruta, mensagem, **resultado):
    _atualizar_tarefa(r, mensagem["tarefa_id"], estado="concluida", **resultado)
    r.lrem(PROCESSANDO, 1, bruta)


def marcar_processando(r, mensagem):
    _atualizar_tarefa(r, mensagem["tarefa_id"], estado="processando",
                      tentativas=mensagem["tentativas"] + 1)


def rejeitar(r, bruta, mensagem, erro):
    """Falha no processamento: tenta de novo ou manda para a DLQ."""
    mensagem["tentativas"] += 1
    mensagem["ultimo_erro"] = str(erro)[:300]
    pipe = r.pipeline()
    pipe.lrem(PROCESSANDO, 1, bruta)
    if mensagem["tentativas"] >= MAX_TENTATIVAS:
        pipe.lpush(MORTAS, json.dumps(mensagem))
        estado = "falhou"
    else:
        # LPUSH: volta para o fim da fila, atras das mensagens que ja esperavam
        pipe.lpush(FILA, json.dumps(mensagem))
        estado = "na_fila"
    pipe.execute()
    _atualizar_tarefa(r, mensagem["tarefa_id"], estado=estado,
                      tentativas=mensagem["tentativas"], erro=mensagem["ultimo_erro"])
    return estado
