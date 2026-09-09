import type { NextConfig } from "next";

/**
 * O navegador nunca fala com a API diretamente: tudo passa por `/api/*`, que o
 * Next reescreve para o FastAPI.
 *
 * A alternativa seria ligar CORS na API. Foi recusada por dois motivos. Primeiro,
 * exigiria mexer no backend da 4.1, e a restrição desta fase é consumir a API
 * como ela está. Segundo, o visor de PDF é um `<iframe>` apontando para um
 * endpoint — com origens diferentes isso vira uma conversa sobre cabeçalhos e
 * credenciais que a mesma origem simplesmente não tem.
 */
const config: NextConfig = {
  async rewrites() {
    const api = process.env.API_INTERNA ?? "http://127.0.0.1:8000";
    return [{ source: "/api/:caminho*", destination: `${api}/:caminho*` }];
  },
};

export default config;
