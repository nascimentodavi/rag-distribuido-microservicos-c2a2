from servicos.comum.texto import dividir_em_trechos, normalizar, palavras_relevantes


def test_normalizar_remove_acentos_e_caixa():
    assert normalizar("Partição de REDE") == "particao de rede"


def test_palavras_relevantes_ignora_stopwords():
    assert palavras_relevantes("O que diz o teorema CAP?") == {"teorema", "cap"}


def test_trechos_respeitam_tamanho_e_sobreposicao():
    texto = " ".join(f"Frase numero {i} com algum conteudo." for i in range(30))
    trechos = dividir_em_trechos(texto, tamanho_max=120, sobreposicao=1)
    assert len(trechos) > 1
    assert all(len(t) <= 120 for t in trechos)
    # a ultima frase de um trecho reaparece no inicio do seguinte
    ultima = trechos[0].split(". ")[-1]
    assert trechos[1].startswith(ultima.rstrip("."))


def test_paragrafos_viram_trechos_separados():
    assert dividir_em_trechos("Primeiro paragrafo.\n\nSegundo paragrafo.") == [
        "Primeiro paragrafo.", "Segundo paragrafo."]
