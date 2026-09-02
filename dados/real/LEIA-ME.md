# Documentos reais

Esta pasta guarda documentos de verdade — boletos, informes, extratos —
usados só no teste local do extrator. Nada do que está aqui dentro é
versionado. Só existem no git este `LEIA-ME.md` e os `.gitkeep` das
subpastas, para que a estrutura chegue pronta em qualquer clone.

## Por quê

Documento financeiro real carrega dado pessoal de terceiros: nome, CPF,
CNPJ, endereço, agência e conta, valor devido. Esse repositório é público
e um commit é para sempre — nem `git rm` depois resolve, o arquivo fica no
histórico. Então o dado real nunca entra, nem por engano.

O que sustenta a regra:

- o `.gitignore` ignora tudo dentro de `dados/real/`, abrindo exceção
  apenas para este arquivo e para os `.gitkeep`;
- `tests/test_dados_reais_nao_versionados.py` falha se algum arquivo
  proibido daqui aparecer rastreado pelo git.

A trava é dupla de propósito: o `.gitignore` protege contra o `git add`
distraído, e o teste pega o caso em que alguém contornou o `.gitignore`
com `git add --force`.

## Como usar

Copie os documentos para a subpasta do tipo correspondente:

```
dados/real/boletos/     boletos de verdade
```

Precisando de outro tipo, crie a subpasta — ela já nasce ignorada, porque
a regra do `.gitignore` vale para `dados/real/` inteiro.

O eval versionado não usa nada daqui. Ele roda contra o corpus sintético
de `dados/sinteticos/`, que é fixo, reprodutível e pode ser comparado
entre execuções. Os documentos reais servem para conferir à mão que o
extrator aguenta layout de banco de verdade, que é o que o gerador
sintético não consegue imitar.
