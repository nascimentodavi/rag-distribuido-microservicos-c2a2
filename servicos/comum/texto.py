"""
Funcoes de texto compartilhadas: normalizacao, palavras relevantes e
divisao de documentos em trechos (chunking).
"""
import re
import unicodedata

# Palavras muito comuns que nao ajudam a medir relevancia.
STOPWORDS = set("""
a o as os um uma uns umas de da do das dos e em no na nos nas por pelo pela
pelos pelas para pra com sem que se ao aos ou mas como mais menos ja nao sim
ser e sao foi era eh esta estao isso isto esse essa este esta aquele aquela
entre sobre ate quando qual quais quem onde porque tem ter seu sua seus suas
lhe ele ela eles elas voce voces me te nosso nossa muito pouco cada todo toda
diz dizer afirma faz fazer pode podem deve devem the of and
""".split())


def normalizar(texto: str) -> str:
    """Minusculas e sem acentos: 'Particao' e 'particao' viram o mesmo termo."""
    sem_acento = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return sem_acento.lower()


def palavras_relevantes(texto: str) -> set:
    """Conjunto de termos com 3+ letras que nao sao stopwords."""
    termos = re.findall(r"[a-z0-9]+", normalizar(texto))
    return {t for t in termos if len(t) >= 3 and t not in STOPWORDS}


def dividir_em_trechos(texto: str, tamanho_max=500, sobreposicao=1) -> list:
    """Divide o texto em trechos de ate ~tamanho_max caracteres.

    Respeita paragrafos e frases; `sobreposicao` frases do fim de um trecho
    sao repetidas no inicio do proximo para nao perder contexto na fronteira.
    """
    trechos = []
    for paragrafo in re.split(r"\n\s*\n", texto.strip()):
        paragrafo = " ".join(paragrafo.split())
        if not paragrafo:
            continue
        frases = re.split(r"(?<=[.!?;])\s+", paragrafo)
        atual = []
        for frase in frases:
            if atual and len(" ".join(atual + [frase])) > tamanho_max:
                trechos.append(" ".join(atual))
                atual = atual[-sobreposicao:] if sobreposicao else []
                # se a sobreposicao sozinha ja estoura, comeca do zero
                if len(" ".join(atual + [frase])) > tamanho_max:
                    atual = []
            atual.append(frase)
        if atual:
            trechos.append(" ".join(atual))
    return trechos
