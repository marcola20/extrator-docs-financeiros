# Imagem da API de revisão.
#
# Enxuta de propósito: importar `app.main` não carrega WeasyPrint, pdfplumber,
# pypdfium2 nem os SDKs de LLM — conferido, e é consequência de a API só ler o
# banco e servir arquivo. Ela **não processa documento**: extrair custa cota e
# dezenas de segundos, e um endpoint que chamasse o modelo viraria porta para
# gastar orçamento (ver `app/api/revisao.py`).
#
# Quem gera corpus e roda o eval continua fazendo isso fora daqui, com `uv` no
# WSL, onde as bibliotecas nativas do WeasyPrint já estão instaladas.
#
# ## O que a demonstração pública acrescentou
#
# Duas coisas, e as duas só valem na partida, não em requisição nenhuma:
#
# 1. **o corpus sintético** (2,4 MB). Local, o `docker compose` monta `./dados`
#    como volume; na hospedagem não há volume, e sem os PDFs dentro da imagem o
#    semeador não teria o que processar e o visor responderia 404;
# 2. **tesseract**. O semeador roda o pipeline inteiro, e sem a comparação
#    texto/imagem a política da Fase 1.2 barra **todo** documento — "não achar é
#    diferente de não procurar". A fila sairia com tudo bloqueado pelo mesmo
#    sinal, nenhum auto-aprovado, e o caso "boleto limpo" da entrada seria uma
#    mentira. É o preço de a demonstração ter contraste.
#
# `tesseract-ocr-por` não é opcional: os documentos são em português, e sem o
# pacote de idioma o OCR devolve lixo — o que aparece como divergência
# texto/imagem em documento limpo, ou seja, falso positivo de infraestrutura.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-por \
    && rm -rf /var/lib/apt/lists/*

# As dependências primeiro, para a camada delas ser reaproveitada quando só o
# código muda.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY app ./app
COPY migracoes ./migracoes
# `chmod` explícito: o bit de execução sobrevive ao git, mas não sobrevive a
# todo jeito de obter o código (um zip do GitHub, por exemplo), e a falha
# apareceria como "permission denied" na partida do serviço.
COPY docker ./docker
RUN chmod +x docker/*.sh
# O corpus sintético: PDFs e gabaritos. Ver a nota do topo.
COPY dados/sinteticos ./dados/sinteticos
# `alembic.ini` para rodar migração de dentro do contêiner; o README porque o
# `pyproject.toml` o declara e o hatchling recusa construir o pacote sem ele.
COPY alembic.ini README.md ./
RUN uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
# O padrão continua sendo servir e nada mais — é o que o `docker compose` local
# usa. A demonstração troca isto pelo `dockerCommand` do `render.yaml`, que
# migra e semeia antes de servir (`docker/inicia-demo.sh`).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
