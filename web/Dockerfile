# Build em estágios: o que vai para a imagem final é o `standalone` do Next,
# sem node_modules de desenvolvimento e sem o código-fonte.
FROM node:22-alpine AS dependencias
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS construcao
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=dependencias /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS producao
WORKDIR /app
# `PORT` aqui é só o padrão local: o `docker compose` publica 3001:3001. Na
# hospedagem quem manda é a variável injetada pelo Render, que sobrepõe esta —
# e o `server.js` do `standalone` a lê sozinho (`process.env.PORT`), sem
# precisar de `-p` como precisaria o `next start`.
#
# `HOSTNAME` não é redundância com o padrão do Next. O `server.js` faz
# `process.env.HOSTNAME || '0.0.0.0'`, e o Docker **define** HOSTNAME no
# ambiente do contêiner, com o id dele. Sem esta linha o `||` nunca chega no
# lado direito: o Next escuta no endereço daquele nome em vez de em todas as
# interfaces, e de fora do contêiner ninguém alcança. É o mesmo efeito de
# escutar em localhost, e era o 502 da tela com o deploy verde — o processo
# sobe, a porta abre, só que na interface errada.
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3001 HOSTNAME=0.0.0.0
# `standalone` traz só as dependências que o servidor usa em runtime.
COPY --from=construcao /app/.next/standalone ./
COPY --from=construcao /app/.next/static ./.next/static
COPY --from=construcao /app/public ./public
USER node
EXPOSE 3001
CMD ["node", "server.js"]
