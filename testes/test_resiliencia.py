import time

import pytest

from servicos.comum.resiliencia import TempoEsgotado, com_retentativa, com_tempo_limite


def test_tempo_limite_libera_quem_chamou():
    inicio = time.monotonic()
    with pytest.raises(TempoEsgotado):
        com_tempo_limite(time.sleep, 0.1, 2)
    assert time.monotonic() - inicio < 1


def test_tempo_limite_devolve_resultado_quando_rapido():
    assert com_tempo_limite(lambda x: x * 2, 1, 21) == 42


def test_retentativa_ate_dar_certo_com_backoff_exponencial():
    esperas, tentativas = [], []

    def instavel():
        tentativas.append(1)
        if len(tentativas) < 3:
            raise ConnectionError("instavel")
        return "ok"

    assert com_retentativa(instavel, tentativas=3, espera_base=1,
                           dormir=esperas.append) == "ok"
    assert len(tentativas) == 3
    assert 1 <= esperas[0] <= 1.25 and 2 <= esperas[1] <= 2.5


def test_retentativa_desiste_e_propaga_ultimo_erro():
    with pytest.raises(ConnectionError):
        com_retentativa(lambda: (_ for _ in ()).throw(ConnectionError("x")),
                        tentativas=2, dormir=lambda s: None)


def test_retentativa_nao_repete_erro_permanente():
    tentativas = []

    def permanente():
        tentativas.append(1)
        raise ValueError("4xx")

    with pytest.raises(ValueError):
        com_retentativa(permanente, tentativas=5, dormir=lambda s: None,
                        retentar_se=lambda e: not isinstance(e, ValueError))
    assert len(tentativas) == 1
