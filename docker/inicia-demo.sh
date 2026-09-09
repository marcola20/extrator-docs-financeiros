#!/bin/sh
# Partida da API na demonstração pública.
#
# Ordem: migrar, **abrir a porta**, semear em segundo plano. O `docker compose`
# local não usa este script — lá o CMD da imagem é o uvicorn direto, e quem
# migra e semeia é quem desenvolve, com os comandos do README. Aqui é o
# `dockerCommand` do render.yaml.
#
# ## Por que a semeadura ficou para depois da porta
#
# Ela era o segundo passo, na frente do uvicorn, e o primeiro deploy falhou por
# isso: "No open ports detected" repetido até "Port scan timeout reached". A
# hospedagem espera o processo escutar numa porta dentro de uma janela curta, e
# a semeadura não cabe nela.
#
# Ela não é rápida por acaso: processa cada documento pelo **pipeline inteiro**,
# e a parte cara é o OCR — a página é renderizada a 300 DPI e o tesseract lê a
# imagem, para comparar com a camada de texto. Medido em máquina de
# desenvolvimento: 1,7 a 2,0 s por boleto, 4,5 s por par de informe, 23 s no
# total. Numa instância gratuita, compartilhada, isso é vários minutos.
#
# Encurtar não resolveria e pioraria a demonstração: sem a comparação
# texto/imagem a política da Fase 1.2 barra **todo** documento — "não achar é
# diferente de não procurar" —, a fila sairia inteira bloqueada pelo mesmo
# sinal, e o caso "boleto limpo, auto-aprovado" da entrada seria falso.
#
# Então a semeadura sai da frente: a API sobe em segundos, e a fila se povoa
# atrás dela. Quem visitar no meio vê os casos ainda não semeados como
# indisponíveis, que é uma tela que a entrada já sabe desenhar.
#
# ## Por que a migração continua na frente
#
# Ela é rápida (`alembic upgrade head` num banco já migrado é uma consulta e um
# "nada a fazer") e **é pré-requisito das duas coisas que vêm depois**: sem
# tabela, a API responde erro e o semeador não tem onde gravar. Aqui o `set -e`
# vale: subir sem schema não é degradação, é um serviço que não funciona.
#
# ## Por que `--completar` e não "só se a fila estiver vazia"
#
# Este script roda a cada despertar, e a semeadura precisa ser segura de
# repetir. A primeira forma disso foi "não faça nada se a fila tiver qualquer
# decisão", e ela tem um modo de falha ruim: uma semeadura interrompida no meio
# — o contêiner ficou sem memória, a instância foi reciclada — deixa parte dos
# documentos gravados, e a partida seguinte trata isso como trabalho concluído.
# A demonstração fica pela metade **em silêncio**, e o buraco só aparece para
# quem abre o link e não acha um caso.
#
# `--completar` compara documento a documento e semeia só o que falta. Uma
# semeadura interrompida se conserta sozinha no despertar seguinte, e no caso
# normal — nada faltando — ele sai em menos de dois segundos.
#
# ## Por que a semeadura não pode derrubar o deploy
#
# Ela é enfeite: sem ela a API sobe, a entrada mostra os casos como
# indisponíveis e diz como povoar. Com ela derrubando a partida, um documento
# problemático tira o serviço inteiro do ar — trocar uma fila vazia por uma
# página que não abre é o pior negócio possível. Em segundo plano isso é de
# graça: `set -e` não alcança job em background.
set -eu

echo "==> migrações"
alembic upgrade head

# `&` antes do `exec`: o processo em segundo plano nasce filho deste shell e,
# quando o `exec` substitui o shell pelo uvicorn, continua filho do mesmo PID 1
# — agora o uvicorn, que não faz `wait()`. Ao terminar, ele vira um zumbi e a
# entrada fica na tabela de processos até o contêiner morrer. É **um** zumbi,
# sem descritor e sem memória; o preço de evitá-lo seria não usar `exec`, e aí
# o SIGTERM da hospedagem chegaria ao shell em vez de chegar ao uvicorn, que é
# quem precisa dele para encerrar as conexões abertas.
echo "==> semeadura em segundo plano (não bloqueia a porta)"
{
    python -m app.geradores.semeia_fila --completar \
        || echo "!! a semeadura falhou; a API continua no ar com a fila como está"
} &

echo "==> API na porta ${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
