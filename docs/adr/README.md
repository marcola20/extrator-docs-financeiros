# Decisões de arquitetura

Cada ADR registra uma decisão no formato contexto / decisão / consequências,
e o que ela custou. Elas são o histórico de por que o projeto é como é.

[← README](../../README.md)

| ADR | Decisão |
|---|---|
| [001](001-desenvolvimento-em-wsl2.md) | Desenvolvimento em WSL2, com o repositório no sistema de arquivos Linux |
| [002](002-validacao-por-digito-verificador.md) | Confiança derivada de dígito verificador, não do `confidence` do modelo |
| [003](003-abstracao-de-provedor-llm.md) | Provedor de LLM configurável, com Gemini como padrão |
| [004](004-defesa-contra-prompt-injection.md) | Defesa contra prompt injection em documentos |
| [005](005-sinais-de-confianca.md) | Três sinais de confiança independentes do modelo |
| [006](006-gabarito-do-impresso.md) | O gabarito guarda o que está impresso, não o que é verdadeiro |
| [007](007-estrutura-do-informe-de-rendimentos.md) | Estrutura do informe, e o que nele é verificável |
| [008](008-recalibracao-do-sanitizador-para-o-informe.md) | Recalibração do sanitizador para o informe, medida |
| [009](009-extracao-do-informe-e-cobertura-de-verificacao.md) | Um prompt para os dois layouts, e cobertura não é aprovação |
| [010](010-persistencia-e-fila-de-revisao.md) | Persistência opcional, e o que pode ou não ser versionado |
| [011](011-interface-de-revisao.md) | A interface de revisão, e o estado que ela não pode apagar |
