"""
Indice vetorial persistido em disco.

Formato: um unico arquivo joblib (dados/indice.joblib) com
  - versao: inteiro que cresce a cada reindexacao (usado como ETag);
  - documentos: {origem: texto} -> fonte da verdade, permite reconstruir tudo;
  - trechos: [{id, origem, posicao, texto}];
  - vetorizador: o TF-IDF ajustado (precisa ser o MESMO para vetorizar perguntas);
  - vetores: [(indices, valores)] esparsos, um por trecho.

A gravacao e atomica (arquivo temporario + os.replace): quem le o arquivo
nunca ve um indice pela metade, mesmo que o worker morra no meio da escrita.
"""
import hashlib
import os
import tempfile
import threading
import time

import joblib

from servicos.comum.embeddings import Vetorizador
from servicos.comum.texto import dividir_em_trechos

TAMANHO_TRECHO = int(os.getenv("TAMANHO_TRECHO", "500"))


def _indice_vazio():
    return {"versao": 0, "atualizado_em": None, "documentos": {},
            "trechos": [], "vetorizador": None, "vetores": []}


def id_documento(origem, texto):
    """Documentos sem origem ganham um nome derivado do conteudo (idempotente)."""
    if origem:
        return origem
    return "doc-" + hashlib.sha256(texto.encode()).hexdigest()[:12]


def reindexar(indice, novos_documentos):
    """Acrescenta/substitui documentos e recalcula todos os vetores.

    Com TF-IDF o vocabulario depende do corpus inteiro, entao toda ingestao
    reajusta o vetorizador e revetoriza todos os trechos.
    """
    documentos = dict(indice["documentos"])
    for doc in novos_documentos:
        documentos[id_documento(doc.get("origem"), doc["texto"])] = doc["texto"]

    trechos = []
    for origem, texto in sorted(documentos.items()):
        for posicao, trecho in enumerate(dividir_em_trechos(texto, TAMANHO_TRECHO)):
            trechos.append({"id": f"{origem}#{posicao}", "origem": origem,
                            "posicao": posicao, "texto": trecho})

    vetorizador = Vetorizador()
    vetorizador.ajustar([t["texto"] for t in trechos])
    vetores = [vetorizador.vetorizar_esparso(t["texto"]) for t in trechos]

    return {"versao": indice["versao"] + 1, "atualizado_em": time.time(),
            "documentos": documentos, "trechos": trechos,
            "vetorizador": vetorizador, "vetores": vetores}


class Armazenamento:
    """Le e grava o indice; recarrega sozinho quando outro processo o altera."""

    def __init__(self, caminho):
        self.caminho = caminho
        self._trava = threading.Lock()
        self._indice = _indice_vazio()
        self._carimbo = None

    def atual(self):
        """Indice mais recente do disco (recarrega se o arquivo mudou)."""
        with self._trava:
            try:
                carimbo = os.stat(self.caminho).st_mtime_ns
            except FileNotFoundError:
                return self._indice
            if carimbo != self._carimbo:
                self._indice = joblib.load(self.caminho)
                self._carimbo = carimbo
            return self._indice

    def salvar(self, indice):
        pasta = os.path.dirname(os.path.abspath(self.caminho))
        os.makedirs(pasta, exist_ok=True)
        fd, temporario = tempfile.mkstemp(dir=pasta, suffix=".tmp")
        os.close(fd)
        try:
            joblib.dump(indice, temporario)
            os.replace(temporario, self.caminho)
        except BaseException:
            os.unlink(temporario)
            raise
        with self._trava:
            self._indice = indice
            self._carimbo = os.stat(self.caminho).st_mtime_ns
