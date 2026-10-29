"""
Servico 2 - RECUPERACAO: dada uma pergunta, acha os trechos mais relevantes.

Fluxo de POST /buscar:
  1. pede a ingestao (REST) para vetorizar a pergunta -> recebe o vetor e a
     versao do indice usado;
  2. se a versao mudou, atualiza o cache local do indice (GET /indice com
     If-None-Match: so baixa de novo quando houve reindexacao);
  3. calcula a similaridade do cosseno da pergunta com todos os trechos;
  4. REORDENA os melhores candidatos (reranking) combinando a similaridade
     com a cobertura dos termos da pergunta, e devolve os top_k.

Degradacao: se a ingestao estiver fora do ar mas houver indice em cache,
a busca continua em modo lexico (so cobertura de termos) em vez de falhar.

Rodar: uvicorn servicos.recuperacao.app:app --port 8002
"""
import logging
import os
import threading

import numpy as np
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from scipy.sparse import csr_matrix

from servicos.comum.resiliencia import com_retentativa
from servicos.comum.texto import palavras_relevantes

log = logging.getLogger("recuperacao")
app = FastAPI(title="Recuperacao - C2.A2")

URL_INGESTAO = os.getenv("URL_INGESTAO", "http://localhost:8001")
TEMPO_LIMITE = (2, float(os.getenv("INGESTAO_TIMEOUT", "5")))  # (conexao, leitura)
PESO_SIMILARIDADE = float(os.getenv("RERANK_PESO_SIMILARIDADE", "0.7"))


class Consulta(BaseModel):
    pergunta: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=3, ge=1, le=20)
    reranking: bool = True
    min_similaridade: float = Field(default=0.05, ge=0, le=1)


class IngestaoIndisponivel(Exception):
    pass


def _retentavel(erro):
    if isinstance(erro, requests.HTTPError):
        return erro.response is not None and erro.response.status_code >= 500
    return isinstance(erro, (requests.ConnectionError, requests.Timeout))


def _chamar_ingestao(metodo, rota, **kwargs):
    """REST para a ingestao com tempo-limite e ate 3 tentativas (erros transitorios)."""
    def tentativa():
        r = requests.request(metodo, f"{URL_INGESTAO}{rota}", timeout=TEMPO_LIMITE, **kwargs)
        if r.status_code >= 500:
            r.raise_for_status()
        return r
    try:
        return com_retentativa(tentativa, tentativas=3, espera_base=0.2,
                               retentar_se=_retentavel)
    except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as erro:
        raise IngestaoIndisponivel(str(erro)) from erro


class CacheIndice:
    """Copia local do indice da ingestao, renovada so quando a versao muda."""

    def __init__(self):
        self._trava = threading.Lock()
        self.versao = None
        self.etag = None
        self.itens = []
        self.matriz = None
        self.termos = []

    def atualizar(self):
        with self._trava:
            cabecalhos = {"If-None-Match": self.etag} if self.etag else {}
            r = _chamar_ingestao("GET", "/indice", headers=cabecalhos)
            if r.status_code == 304:
                return
            r.raise_for_status()
            dados = r.json()
            itens = dados["itens"]
            linhas = [i for i, item in enumerate(itens) for _ in item["indices"]]
            colunas = [c for item in itens for c in item["indices"]]
            valores = [v for item in itens for v in item["valores"]]
            self.matriz = csr_matrix((valores, (linhas, colunas)),
                                     shape=(len(itens), max(dados["dimensao"], 1)))
            self.itens = [{k: item[k] for k in ("id", "origem", "posicao", "texto")}
                          for item in itens]
            self.termos = [palavras_relevantes(item["texto"]) for item in itens]
            self.versao = dados["versao"]
            self.etag = r.headers.get("etag")
            log.info("cache do indice atualizado: versao %s, %d trechos",
                     self.versao, len(self.itens))


cache = CacheIndice()


def _vetorizar(pergunta):
    r = _chamar_ingestao("POST", "/vetorizar", json={"texto": pergunta})
    if r.status_code == 409:
        raise HTTPException(409, detail=r.json()["detail"])
    r.raise_for_status()
    return r.json()


def _similaridades(vetor):
    """Cosseno entre a pergunta e todos os trechos de uma vez.

    O TF-IDF ja entrega vetores com norma 1, entao o cosseno vira um produto
    escalar - a mesma conta de comum.embeddings.similaridade(), em lote.
    """
    q = np.zeros(cache.matriz.shape[1])
    q[vetor["indices"]] = vetor["valores"]
    norma = np.linalg.norm(q)
    if norma == 0:
        return np.zeros(len(cache.itens))
    return cache.matriz @ (q / norma)


def _cobertura(termos_pergunta, termos_trecho):
    """Fracao dos termos relevantes da pergunta que aparecem no trecho."""
    if not termos_pergunta:
        return 0.0
    return len(termos_pergunta & termos_trecho) / len(termos_pergunta)


@app.post("/buscar")
def buscar(consulta: Consulta):
    """Devolve os top_k trechos mais parecidos com a pergunta."""
    termos_pergunta = palavras_relevantes(consulta.pergunta)
    modo = "vetorial"
    try:
        vetor = _vetorizar(consulta.pergunta)
        if vetor["versao"] != cache.versao:
            cache.atualizar()
            if vetor["versao"] != cache.versao:  # reindexou entre as duas chamadas
                vetor = _vetorizar(consulta.pergunta)
        similaridades = _similaridades(vetor)
    except IngestaoIndisponivel as erro:
        if cache.matriz is None:
            raise HTTPException(503, detail=f"servico de ingestao indisponivel e sem indice em cache: {erro}")
        log.warning("ingestao indisponivel (%s); usando busca lexica no cache", erro)
        modo = "lexico (degradado: ingestao indisponivel)"
        similaridades = np.zeros(len(cache.itens))

    candidatos = []
    for i, item in enumerate(cache.itens):
        sim = float(similaridades[i])
        cob = _cobertura(termos_pergunta, cache.termos[i])
        if modo == "vetorial":
            if sim < consulta.min_similaridade:
                continue
            pontuacao = (PESO_SIMILARIDADE * sim + (1 - PESO_SIMILARIDADE) * cob
                         if consulta.reranking else sim)
        else:
            if cob == 0:
                continue
            pontuacao = cob
        candidatos.append({**item, "similaridade": round(sim, 4),
                           "cobertura": round(cob, 4), "pontuacao": round(pontuacao, 4)})

    if consulta.reranking and modo == "vetorial":
        # 1a fase: os melhores por similaridade; 2a fase: reordena pela pontuacao
        candidatos.sort(key=lambda c: c["similaridade"], reverse=True)
        candidatos = candidatos[:max(consulta.top_k * 4, 10)]
    candidatos.sort(key=lambda c: c["pontuacao"], reverse=True)

    return {"pergunta": consulta.pergunta, "versao_indice": cache.versao, "modo": modo,
            "reranking": consulta.reranking and modo == "vetorial",
            "resultados": candidatos[:consulta.top_k]}


@app.get("/saude")
def saude():
    try:
        ingestao = _chamar_ingestao("GET", "/saude").json().get("status", "?")
    except IngestaoIndisponivel:
        ingestao = "indisponivel"
    return {"status": "ok" if ingestao == "ok" else "degradado",
            "ingestao": ingestao, "versao_indice_em_cache": cache.versao,
            "trechos_em_cache": len(cache.itens)}
