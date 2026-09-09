# Extrator de Documentos Financeiros

Pipeline de extração estruturada de documentos financeiros brasileiros
com validação determinística e roteamento para revisão humana.

## Contexto

Projeto de portfólio. Autor vem de C#/.NET, aprendendo Python de forma
aplicada. Preferir código explícito e tipado sobre "pythonices" mágicas.

## Princípios

- SDK do provedor direto, atrás de interface fina (`app/llm`). Sem
  framework de LLM (LangChain etc). Ver ADR 003.
- Valor monetário sempre `Decimal`, nunca `float`.
- Confiança vem de validação determinística, não do confidence do modelo.
  Ver ADR 002.
- Todo dado é sintético. Documento real nunca entra no repo, e não é
  enviado pelo tier gratuito — ele treina o modelo do provedor. Ver ADR 003.

## Escopo por fase

1. Boleto — pipeline vertical, structured output, eval básico — **concluída**
   1. Gerador sintético, schema e validadores determinísticos — concluída
   2. Sanitização e documentos adversariais (defesa contra prompt injection)
      — concluída
   3. Extração via LLM com structured output, e eval — concluída
2. Informe de Rendimentos — seções, listas, validação cruzada entre anos
   1. Gerador sintético, schema, validadores e métricas de linha — concluída
   2. Extração via LLM, seis sinais de confiança e eval por par — concluída
3. Extrato de investimento — multi-página, tabela com quebra
4. Revisão (Next.js) + observabilidade
   1. Persistência, API de revisão, realimentação, observabilidade e CI —
      concluída
   2. Interface de revisão em Next.js, e o pareamento de informes — concluída

## Stack

Python 3.12 / uv / FastAPI / Pydantic v2 / SQLAlchemy 2 / Postgres 16
pdfplumber / pypdfium2 / Pillow
google-genai (padrão) / SDK Anthropic (comparação)
Jinja2 + WeasyPrint (geração dos PDFs sintéticos)
pytest / ruff / mypy / Docker Compose / Langfuse / Next.js 15

## Convenções

- O front não decide nada: `bloqueia` e os estados de sinal vêm calculados da
  API. Estado derivado no navegador é uma segunda definição da política.
- Os **quatro** estados de sinal aparecem distintos na tela. Só `conferido`
  recebe marca de certo; `sem_cobertura` tem borda tracejada. Ver ADR 011.

- Type hints obrigatórios. mypy em modo strict (`app/` e `tests/`).
- Testes junto da feature, não depois.
- Commits pequenos, em português, no imperativo.
- Desenvolvimento sempre no WSL2, repo em `~/projetos` (nunca `/mnt/*`).
  Nada de comando PowerShell ou caminho Windows. Ver ADR 001.
- Decisões de arquitetura viram ADR em `docs/adr/`, numerados, no formato
  contexto / decisão / consequências.
- Relatório de eval é versionado em `resultados/`, e por isso não pode carregar
  valor extraído — só taxa, contagem e booleano. `tests/test_relatorios_versionados.py`
  é a trava.
- Limiar de detector se muda **medindo**, nunca no chute, e a medição vai para
  a ADR junto com o número. Ver ADR 008.
- Sinal que não teve o que conferir **não é sinal que aprovou**: conta como não
  executado e bloqueia a auto-aprovação, como a Fase 1.2 trata o PDF sem camada
  de texto. Ver ADR 009.
- O que é versionado não carrega conteúdo de documento; o que carrega conteúdo
  de documento não é versionado. Relatório de eval sobe (taxas e booleanos),
  banco não sobe (payload bruto), realimentação não sobe (gabarito real). Ver
  ADR 010.

## Comandos

```bash
uv sync                # instala dependências (cria .venv)
uv run pytest          # testes (a suíte inteira; leva ~6 min por causa do OCR)
uv run pytest -m "not slow"   # sem os testes de OCR, para revisar commit a commit
uv run ruff check .    # lint
uv run ruff format .   # formatação
uv run mypy            # tipos (strict em app/)
uv run uvicorn app.main:app --reload   # API em http://127.0.0.1:8000
docker compose up -d   # Postgres 16 local
docker compose --profile revisao up -d           # + API e tela (localhost:3001)
docker compose --profile observabilidade up -d   # + Langfuse (5 contêineres)

# O front vive em web/. Node NÃO está instalado no WSL e o npm do PATH é o do
# Windows, que a ADR 001 proíbe: build, lint e tipos rodam em container.
docker run --rm -v "$PWD/web":/app -w /app -u "$(id -u):$(id -g)" \
    node:22-alpine npm run build

# Persistência é OPCIONAL e desligada por padrão: o pipeline e o eval rodam sem
# banco. Só a fila de revisão precisa dele.
#   PERSISTENCIA_ATIVA=1 no .env, e então:
uv run alembic upgrade head          # aplica as migrações

# Povoa a fila para demonstrar a tela (gravar GIF, mostrar numa entrevista).
# NÃO gasta cota: o provedor lê o gabarito ao lado de cada PDF do corpus
# sintético, e não chama a API do modelo. --limpar apaga a fila antes.
PERSISTENCIA_ATIVA=1 uv run python -m app.geradores.semeia_fila --limpar

# Verificação contra Postgres de verdade: tipo de coluna, CHECK, timestamptz,
# e o ida-e-volta dos enums — o que o SQLite não prova. APAGA as tabelas ao
# terminar, e por isso exige a variável. Ver ADR 010.
PYTEST_POSTGRES=1 uv run pytest -m postgres
# Alembic não detecta CHECK no autogenerate: restrição de enum se escreve à
# mão, em batch_alter_table (o SQLite não sabe alterar constraint). Ver ADR 010.
uv run python -m app.avaliacao.exporta_realimentacao --simular

# Eval com os casos de correção humana (dados/realimentacao/, fora do git).
# Desligado por padrão: misturá-los ao corpus sintético sem distinção
# contaminaria a comparação com os baselines. Ver ADR 010.
uv run python eval.py --com-realimentacao

# Boletos sintéticos em dados/sinteticos/boletos/, PDF + gabarito JSON.
# Recusa sobrescrever um lote existente; use --forcar, --saida ou --prefixo.
uv run python -m app.geradores.boleto_sintetico --quantidade 15

# Cache de extrações do LLM, para não gastar cota reexecutando eval igual.
uv run python -m app.llm.cache --limpar

# Eval. Provedor instável derruba documento sem nada de errado; --retomar
# reprocessa só o que caiu num relatório anterior e soma as duas passadas.
uv run python eval.py
uv run python eval.py --retomar resultados/eval-AAAAMMDD-HHMMSS-<prompt>.json

# Eval do informe: corpus adicional, selecionado por flag. 28 pares = 56
# documentos. A unidade de processamento é o PAR — o cruzamento entre anos
# precisa dos dois —, e a retomada também: se um documento cai, o par inteiro
# volta. O relatório traz recall e precisão de linha, desempenho por layout e
# as duas contagens de auto-aprovação (com e sem cobertura de verificação).
uv run python eval.py --informes

# Informes sintéticos, em PARES de anos consecutivos: o cruzamento entre anos
# precisa de dois documentos, e o gabarito aponta para o par.
uv run python -m app.geradores.informe_sintetico \
    --pares 12 --semente 2026 --data-referencia 2026-09-04
uv run python -m app.geradores.informe_adversarial \
    --pares 16 --semente 2026 --data-referencia 2026-09-04
```

O relatório somado mede o corpus completo e registra em `passadas` de quantas
partes veio. Prompt, provedor, modo de consistência, modelo e corpus têm que
bater com os da passada anterior — divergir de qualquer um é recusado, porque a
média somada não descreveria execução nenhuma.

## Corpus reproduzível

Comparar dois evals exige que o corpus seja o mesmo, ou que a troca seja
visível. Reproduzir um lote precisa de **duas** coisas, não uma: a semente e a
data de referência. O vencimento é sorteado como deslocamento a partir dessa
data, então a mesma semente em outro dia gera outro corpus, silenciosamente.

As duas ficam gravadas em `gerado_com` no gabarito de cada documento. Para
regerar o corpus atual, é só repetir o que está lá:

```bash
uv run python -m app.geradores.boleto_sintetico \
    --quantidade 15 --semente 2026 --data-referencia 2026-09-03 --forcar
uv run python -m app.geradores.boleto_adversarial \
    --quantidade 28 --semente 2026 --data-referencia 2026-09-03 --forcar
```

Regerar com outra semente ou outra data é legítimo, mas invalida a comparação
com os evals anteriores em `resultados/` — o corpus passa a ser outro, e o
`gerado_com` dos gabaritos é o que denuncia isso.

## Provedor de LLM

Configurável por `LLM_PROVEDOR` e `LLM_MODELO` (ver ADR 003). A motivação é
restrição de custo: o tier gratuito do Gemini é o orçamento do projeto.

- Padrão: `gemini` / `gemini-3.5-flash-lite` — 15 RPM, 500 RPD.
- Comparação final: `gemini-3.8-flash` — 5 RPM, 20 RPD, ou seja uma passada
  de eval por dia.
- `anthropic` / `claude-opus-5` existe para comparação futura.

Cota e cache ficam fora do Protocol, num decorador montado pela fábrica.
Identificadores de modelo são fixos, sem apelido `-latest`, para dois evals
continuarem comparáveis.

## Estado atual

**Fase 1 (boleto) concluída e medida contra a API.** As três subfases
entregaram:

- 1.1 — gerador sintético reprodutível, schema de domínio e validadores
  determinísticos (4 DVs da linha digitável, cruzamento de banco, valor e
  vencimento, DV de CPF/CNPJ).
- 1.2 — sanitização com três detectores independentes, isolamento por
  delimitadores no prompt, e corpus adversarial de 28 documentos em 7
  famílias de ataque.
- 1.3 — extração via structured output do Gemini, quatro sinais de confiança
  com roteamento para revisão, e `eval.py` medindo taxa de escape,
  resistência a injection, custo e latência.

Última passada completa (2026-09-04, gabarito do ADR 006): 43/43 documentos,
escape rate 0% sobre 15 auto-aprovados, 0 ataques bem-sucedidos de 28
adversariais, acurácia média 99,5%. Ela confirmou o que se esperava do ADR
006 — `beneficiario_nome` e `valor` de 90,7% para 100%, os outros oito campos
parados. Os números e sua procedência estão no README.

O relatório veio de três passadas somadas por `eval.py --retomar`: o Gemini
passou o dia devolvendo 503, e completar o corpus de uma vez não estava em
questão. Retomar é legítimo e o relatório registra a composição em `passadas`,
mas **custo e latência daquela passada carregam as retentativas** (p50 de 38s,
contra 10s numa janela estável) e não valem como medida do pipeline. Refazer
a medição de custo e latência com o provedor estável é o que ficou pendente —
acurácia, escape rate e resistência a injection não dependem disso.

**Fase 2.1 (informe) concluída, sem LLM.** Estrutura conferida no Anexo I da IN
RFB antes de fixar o schema, e o documento desmentiu três suposições do escopo
inicial — ver ADR 007. O que entregou:

- domínio com a linha identificada e três resultados de conferência de quadro
  (`CONFERIDO`, `DIVERGENTE`, `SEM_TOTAL`), porque o modelo oficial não imprime
  total nos quadros 4 e 5;
- cruzamento entre anos casando conta a conta, o único sinal do projeto que um
  adversário com controle da página não satisfaz sozinho;
- gerador em pares de anos consecutivos, dois layouts estruturalmente
  diferentes, com quadro vazio, quadro de 46 linhas que quebra página, conta
  aberta e conta encerrada;
- métricas de linha em `app/avaliacao/` — recall, precisão e acurácia nas
  linhas casadas, separadas porque as três falhas que elas distinguem pedem
  correções opostas;
- corpus adversarial de 16 pares em 8 famílias, com `sinal_esperado` no
  gabarito;
- recalibração do sanitizador, medida: 24 falsos positivos viraram 0, sem
  mexer nos boletos. Ver ADR 008.

Duas coisas ficam registradas como buraco conhecido, não como pendência
esquecida:

- o layout de fonte pagadora é pobre em sinal, e é do documento: sem total, não
  há aritmética de soma. `linha_injetada` nele não é pego por nada, e está no
  corpus declarado como `sinal_esperado: nenhum`;
- o detector de texto invisível ficou conservador de propósito, e a evasão que
  ele admite está no ADR 008.

**Fase 2.2 (extração do informe) concluída e medida contra a API.** Ver ADR 009.
O que entregou:

- transporte em texto e prompt `informe-v1`, **um só para os dois layouts** — a
  medição por layout sustentou a escolha: acurácia 100% contra 99,5% e recall de
  linha 99,1% contra 98,3%, dentro de um ponto percentual em tudo que depende de
  leitura;
- pipeline por par (`app/pipeline_informe.py`), em duas fases: `le` é por
  documento e é onde a cota é gasta, `decide_par` cruza os anos e conclui as duas
  decisões sem tocar em rede. Cada PDF é extraído uma vez;
- seis sinais, com a regra que a fase existe para fixar: **sinal que não teve o
  que conferir conta como não executado, e não executado bloqueia**. Consequência
  assumida: nenhum comprovante de fonte pagadora é auto-aprovável, porque não tem
  total nem saldo;
- eval por par atrás de `--informes`, com recall e precisão de linha, desempenho
  por layout, as oito famílias contra o `sinal_esperado`, e as três contagens de
  auto-aprovação que não podem virar uma.

Passada de 2026-09-08: 56/56 documentos, acurácia média 99,7%, recall de linha
98,7%, escape rate 11,1% sobre 18 auto-aprovados, 1 ataque bem-sucedido de 16.

Três buracos conhecidos, registrados e não esquecidos:

- **sinal que roda sobre a saída extraída não pega omissão coerente** (issue #5).
  Medido: 1 dos 2 `quadro_duplicado` passou, porque o modelo devolveu quatro
  linhas onde a página imprime oito e a soma das quatro bate com o total. É
  limitação estrutural, não bug: "a página tinha quatro linhas" e "a página tinha
  oito e o modelo devolveu quatro" são a mesma entrada para o sinal. Vale para
  linha, quadro ou página inteira. O candidato é contar na página, sem passar
  pela extração;
- **o escape que sobra é de nome** (`Vitor Hugo Fernandes` onde a página imprime
  `Sr. Vitor Hugo Fernandes`), e o grounding aprova corretamente, porque é
  substring — a issue #2 se reproduz no informe, apesar dos seis sinais;
- `linha_injetada` no comprovante continua sem sinal, declarada no gabarito.

A métrica de linha tinha um ponto cego que a própria passada encontrou: casava
por chave distinta, e reportava recall de 100% no documento em que o modelo
deixou de devolver quatro linhas impressas. Corrigida para casar por ocorrência;
o recall caiu de 99,8% para 98,7% e o escape de 5,6% para 11,1%.

Próximo: Fase 3 — extrato de investimento, multi-página com tabela que quebra.
