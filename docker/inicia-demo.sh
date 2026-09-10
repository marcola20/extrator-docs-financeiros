#!/bin/sh
# Partida da API na demonstração pública: migrar e servir, nada mais.
#
# O `docker compose` local não usa este script — lá o CMD da imagem é o uvicorn
# direto, e quem migra é quem desenvolve, com os comandos do README. Aqui é o
# `dockerCommand` do render.yaml.
#
# ## Por que a fila não é semeada aqui
#
# Ela foi, de duas formas, e as duas saíram por medição (ADR 012).
#
# Na frente do uvicorn, o primeiro deploy não subiu: a hospedagem espera a porta
# abrir numa janela curta — "No open ports detected" até "Port scan timeout
# reached" —, e a semeadura processa cada documento pelo pipeline inteiro, com
# OCR a 300 DPI.
#
# Em segundo plano, a porta abria e a semeadura não terminava. Medido com os
# limites do plano gratuito (512 MB e 0,1 CPU, num cgroup local): 86 a 97 s por
# boleto, contra 1,7 s sem limite — os oito cenários passam de vinte minutos, num
# serviço que dorme depois de quinze sem visita. E no despertar comum, com o banco
# cheio e nada a fazer, ela ainda disputava a CPU só para descobrir isso: `/health`
# respondia aos 19–23 s com ela e aos 13–14 s sem ela.
#
# O Postgres não dorme; o contêiner, sim. Então a fila é semeada **uma vez**, da
# máquina de desenvolvimento, pela URL externa do banco — o comando está no
# render.yaml —, e o despertar não tem nada a reconstruir.
#
# ## Por que a migração fica
#
# É pré-requisito de a API funcionar: sem tabela, toda rota da fila responde erro.
# Num banco já migrado é uma consulta e um "nada a fazer", e é aqui que um deploy
# que muda o schema o aplica, porque o plano gratuito não tem `preDeployCommand`.
# O `set -e` vale: subir sem schema não é degradação, é um serviço que não
# funciona.
set -eu

echo "==> migrações"
alembic upgrade head

# `exec` para o uvicorn ser o PID 1 e receber o SIGTERM da hospedagem, que é o
# aviso para encerrar as conexões abertas quando o serviço vai dormir.
echo "==> API na porta ${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
