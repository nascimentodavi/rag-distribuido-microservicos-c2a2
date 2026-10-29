# Servico de recuperacao - build a partir da RAIZ do repositorio:
#   docker build -f servicos/recuperacao/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# so o codigo comum e o deste servico entram na imagem
COPY servicos/__init__.py servicos/__init__.py
COPY servicos/comum servicos/comum
COPY servicos/recuperacao servicos/recuperacao

RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8002
HEALTHCHECK --interval=10s --timeout=4s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8002/saude', timeout=3)"
CMD ["uvicorn", "servicos.recuperacao.app:app", "--host", "0.0.0.0", "--port", "8002"]
