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

## O dado mais sensível do boleto é a linha digitável

Vale dizer separado, porque a intuição erra aqui.

Ao pensar em anonimizar um boleto, o instinto é apagar os nomes: pagador,
beneficiário, CPF, CNPJ, endereço. Só que **o campo mais sensível é a linha
digitável**, e ela costuma sobrar justamente por parecer "só um número".

Os 47 dígitos não identificam o boleto — eles **são** o boleto. É o que se
digita no aplicativo do banco para pagar, e o pagamento não confere quem
está pagando: quem tem os dígitos quita o documento. Publicar a linha é
publicar uma ordem de pagamento em aberto, não um identificador.

Eles também não são opacos. A linha carrega, decodificável por aritmética:

- o **banco emissor**, nos três primeiros dígitos;
- o **valor**, nos dez últimos;
- o **vencimento**, no fator de quatro dígitos;
- o **campo livre** (25 dígitos), cujo formato cada banco define e que
  **identifica o beneficiário** — agência, cooperativa, posto, convênio,
  conta e nosso número, conforme o banco. É o que amarra o documento a uma
  conta específica e a uma cobrança específica.

Ou seja: **remover nome e CPF não torna a linha digitável segura.** O que
sobra continua sendo pagável e continua apontando para o beneficiário. Uma
linha "anonimizada" para 47 dígitos não foi anonimizada — foi reduzida à
parte que mais importa proteger.

Vale para qualquer lugar do repositório, não só para esta pasta: código de
teste, README, comentário, mensagem de commit, issue. Um teste em
`tests/test_dados_reais_nao_versionados.py` reprova qualquer linha
digitável válida que apareça em `tests/` sem procedência declarada,
justamente porque foi por aí que quase escapou.

Para testar o algoritmo contra dado externo, o caminho é vetor público —
exemplo publicado em documentação ou em biblioteca validadora de terceiro,
que já é público e não é de ninguém. É o que
`tests/dominio/test_digito_verificador.py` usa.

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
