"""
Servico 1 - INGESTAO/EMBEDDINGS: recebe documentos, gera embeddings e armazena.

  POST /indexar          -> valida e PUBLICA na fila do Redis (202 Accepted);
                            quem indexa de fato e o worker (worker.py)
  GET  /tarefas/{id}     -> acompanha o processamento de uma ingestao
  GET  /indice           -> trechos + vetores esparsos (consumido pela recuperacao);
                            suporta ETag/If-None-Match para cache no cliente
  POST /vetorizar        -> vetoriza um texto com o MESMO vetorizador do indice
                            (a recuperacao usa para vetorizar a pergunta)
  GET  /saude

Rodar: uvicorn servicos.ingestao.app:app --port 8001
"""
import os

import redis
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from servicos.ingestao import fila
from servicos.ingestao.armazenamento import Armazenamento

app = FastAPI(title="Ingestao - C2.A2")

CAMINHO_INDICE = os.getenv("CAMINHO_INDICE", "dados/indice.joblib")
armazenamento = Armazenamento(CAMINHO_INDICE)
_redis = fila.conectar()


class Documento(BaseModel):
    texto: str = Field(min_length=1, max_length=1_000_000)
    origem: str | None = Field(default=None, max_length=200,
                               description="nome do documento; reenviar a mesma origem substitui o conteudo")


class Texto(BaseModel):
    texto: str = Field(min_length=1, max_length=10_000)


def _redis_indisponivel(erro):
    return HTTPException(503, detail=f"fila de ingestao indisponivel (Redis): {erro}")


@app.post("/indexar", status_code=202)
def indexar(docs: list[Documento]):
    if not docs:
        raise HTTPException(422, detail="envie ao menos um documento")
    try:
        tarefa_id = fila.enfileirar(_redis, [d.model_dump() for d in docs])
    except redis.RedisError as erro:
        raise _redis_indisponivel(erro)
    return {"tarefa_id": tarefa_id, "estado": "na_fila", "documentos": len(docs),
            "acompanhar": f"/tarefas/{tarefa_id}"}


@app.get("/tarefas/{tarefa_id}")
def tarefa(tarefa_id: str):
    try:
        dados = fila.consultar_tarefa(_redis, tarefa_id)
    except redis.RedisError as erro:
        raise _redis_indisponivel(erro)
    if dados is None:
        raise HTTPException(404, detail="tarefa nao encontrada (ou expirada)")
    return {"tarefa_id": tarefa_id, **dados}


@app.get("/indice")
def indice(request: Request, response: Response):
    atual = armazenamento.atual()
    etag = f'"{atual["versao"]}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    vetorizador = atual["vetorizador"]
    return {
        "versao": atual["versao"],
        "dimensao": vetorizador.dimensao if vetorizador else 0,
        "total": len(atual["trechos"]),
        "itens": [{**trecho, "indices": indices, "valores": valores}
                  for trecho, (indices, valores) in zip(atual["trechos"], atual["vetores"])],
    }


@app.post("/vetorizar")
def vetorizar(t: Texto):
    atual = armazenamento.atual()
    if atual["vetorizador"] is None:
        raise HTTPException(409, detail="indice vazio: indexe documentos antes de perguntar")
    indices, valores = atual["vetorizador"].vetorizar_esparso(t.texto)
    return {"versao": atual["versao"], "dimensao": atual["vetorizador"].dimensao,
            "indices": indices, "valores": valores}


@app.get("/documentos")
def documentos():
    atual = armazenamento.atual()
    return {"versao": atual["versao"],
            "documentos": [{"origem": o, "caracteres": len(t)}
                           for o, t in sorted(atual["documentos"].items())]}


@app.get("/saude")
def saude():
    atual = armazenamento.atual()
    try:
        filas = fila.tamanho_filas(_redis)
        estado_redis = "ok"
    except redis.RedisError as erro:
        filas, estado_redis = None, f"indisponivel: {erro}"
    return {"status": "ok" if estado_redis == "ok" else "degradado",
            "redis": estado_redis, "filas": filas,
            "versao_indice": atual["versao"], "documentos": len(atual["documentos"]),
            "trechos": len(atual["trechos"])}
