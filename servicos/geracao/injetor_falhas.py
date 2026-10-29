"""
Injetor de falhas para DEMONSTRAR a resiliencia sem precisar derrubar a internet.

Envolve o cliente de LLM do kit e, conforme o modo, simula o comportamento
de uma API externa instavel:
  normal       -> chama o LLM (real ou simulado) normalmente
  erro         -> toda chamada falha (API fora do ar)
  lentidao     -> a chamada demora mais que o tempo-limite
  intermitente -> falha com probabilidade LLM_TAXA_FALHA (padrao 50%)

O modo inicial vem de LLM_SIMULAR_FALHA e pode ser trocado em tempo de
execucao por POST /admin/falhas no servico de geracao.
"""
import os
import random
import time

from servicos.comum import llm

MODOS = ("normal", "erro", "lentidao", "intermitente")


class FalhaSimulada(ConnectionError):
    """Imita um erro de rede/5xx da API do LLM."""


class InjetorFalhas:

    def __init__(self):
        self.modo = os.getenv("LLM_SIMULAR_FALHA", "normal") or "normal"
        self.taxa = float(os.getenv("LLM_TAXA_FALHA", "0.5"))

    def gerar(self, pergunta, contexto):
        if self.modo == "erro":
            raise FalhaSimulada("falha simulada: API do LLM fora do ar")
        if self.modo == "intermitente" and random.random() < self.taxa:
            raise FalhaSimulada("falha simulada: erro intermitente da API do LLM")
        if self.modo == "lentidao":
            time.sleep(llm.TIMEOUT + 2)
        return llm.gerar(pergunta, contexto)
