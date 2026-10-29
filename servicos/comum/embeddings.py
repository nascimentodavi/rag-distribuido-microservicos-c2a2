"""
Embeddings da disciplina - PRONTO, NAO PRECISA ALTERAR.

Transforma texto em vetor de numeros. Usa TF-IDF (offline, sem download).
Se quiser trocar por um modelo de embeddings de verdade (sentence-transformers),
basta manter a mesma interface: ajustar(textos) e vetorizar(texto).

Voce NAO precisa entender a matematica. Precisa saber:
  - vetorizar(texto) devolve uma lista de numeros
  - similaridade(a, b) devolve o quanto dois vetores se parecem (0 a 1)
"""
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from servicos.comum.texto import STOPWORDS


class Vetorizador:

    def __init__(self):
        # strip_accents: "particao" e "partição" viram o mesmo termo;
        # stop_words: "de", "que", "o"... nao podem gerar similaridade sozinhas
        self._tfidf = TfidfVectorizer(ngram_range=(1, 2), min_df=1,
                                      strip_accents="unicode",
                                      stop_words=sorted(STOPWORDS))
        self._ajustado = False

    def ajustar(self, textos):
        """Aprende o vocabulario a partir dos documentos indexados."""
        self._tfidf.fit(textos)
        self._ajustado = True

    def vetorizar(self, texto):
        if not self._ajustado:
            raise RuntimeError("chame ajustar() antes de vetorizar()")
        return self._tfidf.transform([texto]).toarray()[0].tolist()

    @property
    def dimensao(self):
        return len(self._tfidf.vocabulary_) if self._ajustado else 0

    def vetorizar_esparso(self, texto):
        """Igual a vetorizar(), mas so com as posicoes nao nulas.

        Devolve (indices, valores). Com TF-IDF quase tudo e zero, entao
        trafegar so o que importa reduz muito o tamanho das mensagens.
        """
        if not self._ajustado:
            raise RuntimeError("chame ajustar() antes de vetorizar()")
        linha = self._tfidf.transform([texto]).tocsr()
        return linha.indices.tolist(), linha.data.tolist()


def similaridade(a, b):
    """Similaridade do cosseno entre dois vetores."""
    va, vb = np.array(a), np.array(b)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))
