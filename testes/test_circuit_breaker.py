import pytest

from servicos.comum.circuit_breaker import CircuitBreaker, CircuitoAberto


class Relogio:
    def __init__(self):
        self.agora = 0.0

    def __call__(self):
        return self.agora


def falha():
    raise ConnectionError("LLM fora do ar")


def test_abre_apos_limite_de_falhas_e_recusa_sem_chamar():
    relogio = Relogio()
    cb = CircuitBreaker(limite_falhas=3, espera_segundos=10, relogio=relogio)
    for _ in range(3):
        with pytest.raises(ConnectionError):
            cb.chamar(falha)
    assert cb.estado == "aberto"

    chamadas = []
    with pytest.raises(CircuitoAberto) as erro:
        cb.chamar(lambda: chamadas.append(1))
    assert chamadas == []  # nem tentou chamar a dependencia
    assert erro.value.tentar_novamente_em == pytest.approx(10)


def test_meio_aberto_fecha_quando_teste_tem_sucesso():
    relogio = Relogio()
    cb = CircuitBreaker(limite_falhas=1, espera_segundos=5, relogio=relogio)
    with pytest.raises(ConnectionError):
        cb.chamar(falha)
    relogio.agora = 5
    assert cb.chamar(lambda: "ok") == "ok"
    assert cb.estado == "fechado"
    assert cb.falhas == 0


def test_meio_aberto_reabre_quando_teste_falha():
    relogio = Relogio()
    cb = CircuitBreaker(limite_falhas=2, espera_segundos=5, relogio=relogio)
    for _ in range(2):
        with pytest.raises(ConnectionError):
            cb.chamar(falha)
    relogio.agora = 6
    with pytest.raises(ConnectionError):
        cb.chamar(falha)  # chamada de teste falhou
    assert cb.estado == "aberto"
    assert cb.aberto_em == 6


def test_meio_aberto_deixa_passar_so_um_teste():
    relogio = Relogio()
    cb = CircuitBreaker(limite_falhas=1, espera_segundos=1, relogio=relogio)
    with pytest.raises(ConnectionError):
        cb.chamar(falha)
    relogio.agora = 2

    def teste_lento():
        # enquanto o teste roda, outra chamada concorrente deve ser recusada
        with pytest.raises(CircuitoAberto):
            cb.chamar(lambda: "concorrente")
        return "ok"

    assert cb.chamar(teste_lento) == "ok"
    assert cb.estado == "fechado"


def test_excecoes_ignoradas_nao_contam_como_falha():
    cb = CircuitBreaker(limite_falhas=1, ignorar=(ValueError,))

    def erro_do_cliente():
        raise ValueError("pedido invalido")

    with pytest.raises(ValueError):
        cb.chamar(erro_do_cliente)
    assert cb.estado == "fechado"


def test_sucesso_zera_falhas_consecutivas():
    cb = CircuitBreaker(limite_falhas=3)
    for _ in range(2):
        with pytest.raises(ConnectionError):
            cb.chamar(falha)
    cb.chamar(lambda: None)
    assert cb.status()["falhas_consecutivas"] == 0
    assert cb.status()["total_falhas"] == 2
