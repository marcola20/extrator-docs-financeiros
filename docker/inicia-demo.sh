#!/bin/sh
# Partida da API na demonstração pública.
#
# Três passos, nesta ordem: migrar, semear se estiver vazio, servir. O
# `docker compose` local **não** usa este script — lá o CMD da imagem é o
# uvicorn direto, e quem migra e semeia é quem desenvolve, com os comandos do
# README. Aqui é o `dockerCommand` do render.yaml.
#
# ## Por que semear na partida, e não uma vez na implantação
#
# O plano gratuito desliga o serviço por inatividade e o liga de novo na visita
# seguinte, então este script roda muitas vezes, não uma. `--se-vazia` é o que o
# torna seguro de repetir: com a fila já povoada ele não faz nada. Sem isso, as
# duas alternativas seriam ruins — semear sempre duplicaria a fila a cada
# despertar, e semear com `--limpar` apagaria tudo no meio da visita de alguém.
#
# A migração pode rodar sempre: `alembic upgrade head` num banco já migrado é
# uma consulta e um "nada a fazer".
set -eu

echo "==> migrações"
alembic upgrade head

# A semeadura não derruba a partida. Se o corpus não estiver na imagem ou um
# documento falhar, a API sobe assim mesmo e a entrada mostra os casos como
# indisponíveis — que é uma tela honesta. Um serviço que não sobe não mostra
# nada, e o motivo fica só no log.
echo "==> semeando a fila, se estiver vazia"
python -m app.geradores.semeia_fila --se-vazia || \
    echo "!! a semeadura falhou; a API sobe mesmo assim, com a fila como está"

echo "==> API na porta ${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
