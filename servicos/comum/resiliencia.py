"""
Utilitarios de resiliencia compartilhados pelos servicos.

  - com_tempo_limite: executa uma funcao e desiste depois de N segundos,
    mesmo que a funcao nao tenha timeout proprio (ex.: modo simulado lento);
  - com_retentativa: repete chamadas que falharam de forma transitoria,
    com recuo exponencial (backoff) e jitter para nao sincronizar clientes.
"""
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FuturoTimeout

log = logging.getLogger(__name__)

# Pool compartilhado: evita criar uma thread nova a cada chamada.
_executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="tempo-limite")


class TempoEsgotado(Exception):
    """A chamada nao terminou dentro do tempo-limite."""


def com_tempo_limite(funcao, segundos, *args, **kwargs):
    """Executa funcao(*args, **kwargs) e levanta TempoEsgotado apos `segundos`.

    Observacao: em Python nao da para matar uma thread; a chamada atrasada
    continua em segundo plano, mas quem chamou e liberado no prazo.
    """
    futuro = _executor.submit(funcao, *args, **kwargs)
    try:
        return futuro.result(timeout=segundos)
    except _FuturoTimeout:
        futuro.cancel()
        raise TempoEsgotado(f"sem resposta em {segundos:.1f}s") from None


def com_retentativa(funcao, tentativas=3, espera_base=0.5, espera_maxima=4.0,
                    retentar_se=lambda erro: True, ao_retentar=None,
                    dormir=time.sleep):
    """Chama funcao() ate `tentativas` vezes.

    Espera espera_base * 2^(n-1) (+ jitter de ate 25%) entre as tentativas.
    Se retentar_se(erro) devolver False, o erro sobe imediatamente
    (ex.: circuito aberto ou erro 4xx, que nao melhoram repetindo).
    """
    for tentativa in range(1, tentativas + 1):
        try:
            return funcao()
        except Exception as erro:
            if tentativa == tentativas or not retentar_se(erro):
                raise
            espera = min(espera_maxima, espera_base * 2 ** (tentativa - 1))
            espera += random.uniform(0, espera * 0.25)
            log.warning("tentativa %d/%d falhou (%s: %s); nova tentativa em %.2fs",
                        tentativa, tentativas, type(erro).__name__, erro, espera)
            if ao_retentar:
                ao_retentar(tentativa, erro)
            dormir(espera)
