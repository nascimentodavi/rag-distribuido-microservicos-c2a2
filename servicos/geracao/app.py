"""
Servico 3 - GERACAO: monta o prompt com o contexto e chama o LLM.

POST /perguntar:
  1. busca os trechos relevantes no servico de recuperacao (REST);
  2. numera os trechos ([1], [2]...) para o LLM poder citar as fontes;
  3. chama o LLM protegido por tres camadas de resiliencia:
       retentativa ( disjuntor ( tempo-limite ( LLM ) ) )
     - tempo-limite: cada tentativa tem prazo maximo (LLM_TIMEOUT);
     - disjuntor: cada tentativa que falha conta; com o circuito aberto
       nem se tenta, a recusa e imediata;
     - retentativa: erros transitorios sao repetidos com backoff, exceto
       quando o circuito esta aberto ou o erro e permanente (4xx);
  4. avalia automaticamente se a resposta esta fundamentada no contexto.

Se o LLM falhar, o servico DEGRADA COM ELEGANCIA: responde 503 com
Retry-After, estado do disjuntor e os trechos recuperados (as fontes
continuam uteis para quem perguntou), em vez de um erro 500.

Rodar: uvicorn servicos.geracao.app:app --port 8003
"""
import logging
import os
import time

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from servicos.comum import llm
from servicos.comum.circuit_breaker import CircuitBreaker, CircuitoAberto
from servicos.comum.resiliencia import TempoEsgotado, com_retentativa, com_tempo_limite
from servicos.geracao.avaliacao import avaliar
from servicos.geracao.injetor_falhas import MODOS, InjetorFalhas

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [geracao] %(levelname)s %(message)s")
log = logging.getLogger("geracao")

app = FastAPI(title="Geracao - C2.A2")
URL_RECUPERACAO = os.getenv("URL_RECUPERACAO", "http://localhost:8002")
TEMPO_LIMITE_RECUPERACAO = (2, float(os.getenv("RECUPERACAO_TIMEOUT", "10")))
LLM_TENTATIVAS = int(os.getenv("LLM_TENTATIVAS", "3"))

disjuntor = CircuitBreaker(
    limite_falhas=int(os.getenv("DISJUNTOR_LIMITE_FALHAS", "3")),
    espera_segundos=float(os.getenv("DISJUNTOR_ESPERA_SEGUNDOS", "20")),
)
injetor = InjetorFalhas()


class Pergunta(BaseModel):
    pergunta: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=3, ge=1, le=10)


class ModoFalha(BaseModel):
    modo: str = Field(description="normal | erro | lentidao | intermitente")


def _erro_permanente(erro):
    """4xx (exceto 429) nao melhora repetindo: chave invalida, pedido errado..."""
    resposta = getattr(erro, "response", None)
    return (isinstance(erro, requests.HTTPError) and resposta is not None
            and 400 <= resposta.status_code < 500 and resposta.status_code != 429)


def _buscar_trechos(pergunta, top_k):
    def tentativa():
        r = requests.post(f"{URL_RECUPERACAO}/buscar",
                          json={"pergunta": pergunta, "top_k": top_k},
                          timeout=TEMPO_LIMITE_RECUPERACAO)
        if r.status_code >= 500:
            r.raise_for_status()
        return r
    try:
        r = com_retentativa(tentativa, tentativas=2, espera_base=0.3,
                            retentar_se=lambda e: not _erro_permanente(e))
    except requests.RequestException as erro:
        raise HTTPException(503, detail=f"servico de recuperacao indisponivel: {erro}")
    if r.status_code == 409:
        raise HTTPException(409, detail=r.json().get("detail"))
    if r.status_code >= 400:
        raise HTTPException(502, detail=f"recuperacao respondeu {r.status_code}: {r.text[:200]}")
    return r.json()


def _chamar_llm(pergunta, contexto, metricas):
    def chamada_real():
        # so conta quando o disjuntor deixa passar (recusa nao chega ao LLM)
        metricas["tentativas_llm"] += 1
        return com_tempo_limite(injetor.gerar, llm.TIMEOUT, pergunta, contexto)

    def tentativa():
        return disjuntor.chamar(chamada_real)

    return com_retentativa(
        tentativa, tentativas=LLM_TENTATIVAS, espera_base=0.5,
        retentar_se=lambda e: not isinstance(e, CircuitoAberto) and not _erro_permanente(e))


@app.post("/perguntar")
def perguntar(p: Pergunta):
    inicio = time.monotonic()
    busca = _buscar_trechos(p.pergunta, p.top_k)
    trechos = busca["resultados"]
    fontes = [{"n": n, "origem": t["origem"], "trecho": t["id"],
               "pontuacao": t.get("pontuacao")} for n, t in enumerate(trechos, 1)]
    metricas = {"modo_busca": busca.get("modo"), "versao_indice": busca.get("versao_indice"),
                "modo_llm": "api" if llm.API_KEY else "simulado", "tentativas_llm": 0}

    if not trechos:
        # nada relevante: nao gasta chamada ao LLM e nao inventa resposta
        return {"pergunta": p.pergunta,
                "resposta": "Nao encontrei nos documentos indexados informacao para responder a essa pergunta.",
                "fontes": [], "contexto": [], "avaliacao": None,
                "metadados": {**metricas, "disjuntor": disjuntor.estado,
                              "tempo_ms": round((time.monotonic() - inicio) * 1000)}}

    contexto = [f"[{n}] (fonte: {t['origem']}) {t['texto']}" for n, t in enumerate(trechos, 1)]

    try:
        resposta = _chamar_llm(p.pergunta, contexto, metricas)
    except Exception as erro:
        if isinstance(erro, CircuitoAberto):
            motivo, espera = "circuito aberto: o LLM falhou repetidamente e esta em quarentena", erro.tentar_novamente_em
        elif isinstance(erro, TempoEsgotado):
            motivo, espera = f"tempo-limite do LLM esgotado ({erro})", disjuntor.espera_segundos
        else:
            motivo, espera = f"falha ao chamar o LLM: {type(erro).__name__}: {erro}", disjuntor.espera_segundos
        log.warning("LLM indisponivel (%s); devolvendo resposta degradada", motivo)
        return JSONResponse(status_code=503, headers={"Retry-After": str(max(1, round(espera)))}, content={
            "pergunta": p.pergunta,
            "erro": "LLM indisponivel no momento",
            "motivo": motivo,
            "resposta_degradada": ("Nao foi possivel gerar a resposta agora. "
                                   "Estes sao os trechos mais relevantes encontrados nos documentos:"),
            "fontes": fontes,
            "contexto": contexto,
            "disjuntor": disjuntor.status(),
            "metadados": {**metricas, "tempo_ms": round((time.monotonic() - inicio) * 1000)},
        })

    return {"pergunta": p.pergunta, "resposta": resposta, "fontes": fontes,
            "contexto": contexto, "avaliacao": avaliar(p.pergunta, resposta, contexto),
            "metadados": {**metricas, "disjuntor": disjuntor.estado,
                          "tempo_ms": round((time.monotonic() - inicio) * 1000)}}


@app.post("/admin/falhas")
def configurar_falhas(m: ModoFalha):
    """Liga/desliga a simulacao de falhas do LLM (para testar o disjuntor)."""
    if m.modo not in MODOS:
        raise HTTPException(422, detail=f"modo deve ser um de {MODOS}")
    injetor.modo = m.modo
    log.info("simulacao de falhas do LLM: %s", m.modo)
    return {"modo": injetor.modo, "disjuntor": disjuntor.status()}


@app.get("/saude")
def saude():
    return {"status": "ok" if disjuntor.estado == "fechado" else "degradado",
            "llm": "api" if llm.API_KEY else "simulado",
            "llm_timeout_s": llm.TIMEOUT, "simulacao_falhas": injetor.modo,
            "disjuntor": disjuntor.status()}
