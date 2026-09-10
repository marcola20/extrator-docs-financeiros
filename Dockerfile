# Imagem da API de revisão.
#
# Enxuta de propósito: importar `app.main` não carrega WeasyPrint, pdfplumber,
# pypdfium2 nem os SDKs de LLM — conferido, e é consequência de a API só ler o
# banco e servir arquivo. Ela **não processa documento**: extrair custa cota e
# dezenas de segundos, e um endpoint que chamasse o modelo viraria porta para
# gastar orçamento (ver `app/api/revisao.py`).
#
# Quem gera corpus, roda o eval e semeia a fila continua fazendo isso fora
# daqui, com `uv` no WSL, onde as bibliotecas nativas do WeasyPrint e o
# tesseract já estão instalados.
#
# ## O que a demonstração pública acrescentou
#
# **O corpus sintético** (2,4 MB). Local, o `docker compose` monta `./dados`
# como volume; na hospedagem não há volume, e sem os PDFs dentro da imagem o
# visor responderia 404.
#
# O tesseract também entrou, e saiu. Ele estava aqui porque a demonstração
# semeava a fila na partida, e a semeadura roda o OCR. Sob a cota do plano
# gratuito ela não terminava antes de o serviço dormir, e passou a rodar uma vez,
# de fora, contra o banco — que não dorme. Com ela saiu o único motivo de o
# contêiner ter OCR. Ver ADR 012.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
# `PYTHONUNBUFFERED` não é preferência: o stdout do Python é bloco-bufferizado
# quando não é terminal, e dentro de um contêiner ele nunca é. Sem isso, o log
# da hospedagem fica em branco enquanto o processo trabalha, e um processo que
# demora sem imprimir nada é indistinguível de um processo travado — foi o que
# atrapalhou o diagnóstico do primeiro deploy.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

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
# migra antes de servir (`docker/inicia-demo.sh`).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
