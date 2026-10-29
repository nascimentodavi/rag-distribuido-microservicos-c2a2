"""
Circuit breaker (disjuntor) - adaptado do modelo de referencia da Aula 11.

Estados:
  fechado  -> deixa passar (normal)
  aberto   -> recusa na hora, sem tentar (dependencia esta quebrada)
  meio     -> deixa passar UMA chamada de teste para ver se voltou

Mudancas em relacao ao modelo do kit:
  - thread-safe: o FastAPI executa rotas sincronas em um pool de threads,
    entao varias requisicoes podem tocar o disjuntor ao mesmo tempo;
  - no estado "meio" so UMA chamada de teste passa; as demais sao recusadas
    ate o teste terminar (evita uma avalanche sobre um servico se recuperando);
  - expoe metricas (falhas, recusas, ultima falha) para a rota /saude;
  - permite informar quais excecoes NAO contam como falha da dependencia.
"""
import threading
import time


class CircuitoAberto(Exception):
    """Levantada quando o disjuntor esta aberto e recusa a chamada."""

    def __init__(self, mensagem, tentar_novamente_em=0.0):
        super().__init__(mensagem)
        self.tentar_novamente_em = tentar_novamente_em


class CircuitBreaker:

    def __init__(self, limite_falhas=5, espera_segundos=30, ignorar=(),
                 relogio=time.monotonic):
        self.limite_falhas = limite_falhas
        self.espera_segundos = espera_segundos
        self.ignorar = tuple(ignorar)
        self._relogio = relogio
        self._trava = threading.Lock()
        self.falhas = 0
        self.estado = "fechado"
        self.aberto_em = 0.0
        self._teste_em_andamento = False
        self.total_recusadas = 0
        self.total_falhas = 0
        self.ultima_falha = None

    def chamar(self, funcao, *args, **kwargs):
        self._antes_da_chamada()
        try:
            resultado = funcao(*args, **kwargs)
        except self.ignorar:
            self._liberar_teste()
            raise
        except Exception as erro:
            self._registrar_falha(erro)
            raise
        self._registrar_sucesso()
        return resultado

    def _antes_da_chamada(self):
        with self._trava:
            if self.estado == "aberto":
                restante = self.espera_segundos - (self._relogio() - self.aberto_em)
                if restante > 0:
                    self.total_recusadas += 1
                    raise CircuitoAberto("disjuntor aberto: chamada recusada",
                                         tentar_novamente_em=restante)
                self.estado = "meio"
            if self.estado == "meio":
                if self._teste_em_andamento:
                    self.total_recusadas += 1
                    raise CircuitoAberto("disjuntor meio-aberto: teste em andamento",
                                         tentar_novamente_em=1.0)
                self._teste_em_andamento = True

    def _liberar_teste(self):
        with self._trava:
            self._teste_em_andamento = False

    def _registrar_falha(self, erro):
        with self._trava:
            self.falhas += 1
            self.total_falhas += 1
            self.ultima_falha = f"{type(erro).__name__}: {erro}"[:200]
            if self.falhas >= self.limite_falhas or self.estado == "meio":
                self.estado = "aberto"
                self.aberto_em = self._relogio()
            self._teste_em_andamento = False

    def _registrar_sucesso(self):
        with self._trava:
            self.falhas = 0
            self.estado = "fechado"
            self._teste_em_andamento = False

    def status(self):
        with self._trava:
            restante = 0.0
            if self.estado == "aberto":
                restante = max(0.0, self.espera_segundos - (self._relogio() - self.aberto_em))
            return {
                "estado": self.estado,
                "falhas_consecutivas": self.falhas,
                "limite_falhas": self.limite_falhas,
                "espera_segundos": self.espera_segundos,
                "reabre_teste_em_segundos": round(restante, 1),
                "total_falhas": self.total_falhas,
                "total_recusadas": self.total_recusadas,
                "ultima_falha": self.ultima_falha,
            }
