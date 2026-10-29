"""
Avaliacao automatica e simples da resposta (extensao opcional).

Nao usa outro modelo: mede por sobreposicao de termos se a resposta esta
apoiada nos trechos recuperados.
  fundamentacao      -> fracao dos termos da resposta presentes no contexto
  cobertura_pergunta -> fracao dos termos da pergunta presentes no contexto
  cita_fontes        -> a resposta referencia algum trecho como [n]?
"""
import re

from servicos.comum.texto import palavras_relevantes

LIMIAR_FUNDAMENTADA = 0.6


def _fracao(parte, todo):
    return round(len(parte & todo) / len(parte), 3) if parte else 0.0


def avaliar(pergunta, resposta, contexto):
    termos_contexto = palavras_relevantes(" ".join(contexto))
    # ignora o cabecalho do modo simulado, que nao e conteudo da resposta
    corpo = re.sub(r"\[MODO SIMULADO[^\]]*\]", "", resposta)
    fundamentacao = _fracao(palavras_relevantes(corpo), termos_contexto)
    cobertura = _fracao(palavras_relevantes(pergunta), termos_contexto)
    return {
        "fundamentacao": fundamentacao,
        "cobertura_pergunta": cobertura,
        "cita_fontes": bool(re.search(r"\[\d+\]", corpo)),
        "veredito": ("fundamentada" if fundamentacao >= LIMIAR_FUNDAMENTADA
                     else "pouco fundamentada"),
    }
