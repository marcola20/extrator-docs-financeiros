import type { NextConfig } from "next";

/**
 * O navegador nunca fala com a API diretamente: tudo passa por `/api/*`, servido
 * pelo route handler em `app/api/[...caminho]/route.ts`.
 *
 * Ligar CORS na API foi a alternativa recusada, por dois motivos. Primeiro,
 * exigiria mexer no backend da 4.1, e a restrição desta fase é consumir a API
 * como ela está. Segundo, o visor de PDF é um `<iframe>` apontando para um
 * endpoint — com origens diferentes isso vira uma conversa sobre cabeçalhos e
 * credenciais que a mesma origem simplesmente não tem.
 *
 * O proxy é route handler, e não `rewrites()`, porque o Next resolve os
 * rewrites **no build**: o destino ficaria congelado na imagem. Ver a nota do
 * route handler.
 */
const config: NextConfig = {
  // `standalone` para a imagem final não carregar node_modules inteiro nem o
  // código-fonte: o Next emite um servidor com só o que ele usa em runtime.
  output: "standalone",
};

export default config;
