# Boletos sintéticos

Lote de referência usado no desenvolvimento e no eval da Fase 1.
Cada PDF tem, ao lado, um `.json` com o gabarito da extração.

Todos os dados são fictícios: nomes, CNPJ, CPF e endereços vêm do Faker.
Nenhum documento real entra no repositório.

O lote versionado foi sorteado sem semente, então não dá para reproduzir
exatamente estes 15 boletos — eles valem pelo que estão: um corpus fixo,
versionado, para o eval comparar contra.

## Como gerar um lote novo

```bash
uv run python -m app.geradores.boleto_sintetico --quantidade 15 --forcar
```

O `--forcar` é necessário porque o gerador se recusa a sobrescrever um
lote que já existe. Com `--semente N` o lote sai sempre igual, o que ajuda
a investigar um caso específico sem mexer no corpus versionado.
