# TAREFAS - Trabalho C2.A2 (RAG Distribuido)

## Nucleo obrigatorio

- [x] **1. Persistir o indice** - `servicos/ingestao/armazenamento.py`
      Indice em `indice.joblib` (volume Docker), gravacao atomica e recarga automatica.

- [x] **2. Busca por similaridade** - `servicos/recuperacao/app.py`
      Pergunta vetorizada pela ingestao (`POST /vetorizar`), cosseno contra todos os
      trechos e top_k; cache do indice com ETag.

- [x] **3. Circuit breaker no LLM** - `servicos/geracao/app.py`
      retentativa(disjuntor(tempo-limite(LLM))); 503 com Retry-After e trechos
      recuperados quando o circuito esta aberto ou o LLM falha.

- [x] **4. Mensageria** - `servicos/ingestao/{fila,worker}.py` + `docker-compose.yml`
      Ingestao assincrona por fila confiavel no Redis (ack, DLQ, recuperacao apos queda).

- [x] **5. Fluxo completo** - de ponta a ponta
      `scripts/carregar_documentos.py` + `scripts/perguntar.py`; teste em `testes/test_geracao.py`.

- [x] **6. README com diagrama** da arquitetura dos tres servicos.

## Extensoes opcionais

- [x] Reordenar os trechos por relevancia (reranking)
- [x] Citar quais documentos embasaram a resposta
- [x] Avaliacao automatica simples da qualidade da resposta
- [ ] Trocar TF-IDF por embeddings de verdade (sentence-transformers)

## Antes de entregar

- [x] Desligue a internet: o modo simulado do LLM mantem o sistema de pe?
- [x] Derrube o servico de recuperacao: a geracao responde 503 com mensagem clara?
- [x] O disjuntor abre como esperado? (`scripts/demo_resiliencia.py`)
- [x] A chave da API esta FORA do codigo (em variavel de ambiente)?
- [x] Apagar a pasta, clonar do zero e seguir o README.
