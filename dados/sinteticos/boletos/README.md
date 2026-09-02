# Boletos sintéticos

Lote de referência usado no desenvolvimento e no eval da Fase 1.
Cada PDF tem, ao lado, um `.json` com o gabarito da extração.

Todos os dados são fictícios: nomes, CNPJ, CPF e endereços vêm do Faker.
Nenhum documento real entra no repositório.

## Como regerar

```bash
uv run python -m app.geradores.boleto_sintetico --quantidade 15 --semente 2026
```

A semente fixa mantém o lote estável entre execuções. Sem `--semente`, o
gerador sorteia um lote novo a cada chamada.
