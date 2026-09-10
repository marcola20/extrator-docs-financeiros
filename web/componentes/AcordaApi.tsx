"use client";

import { useEffect } from "react";

/**
 * Chama `/health` da API pela URL pública, do navegador, para acordá-la.
 *
 * ## Por que o navegador, e não o servidor
 *
 * Na hospedagem gratuita a API dorme, e acorda com tráfego de fora. A chamada
 * que o servidor do Next faz a ela — mesmo pela URL pública — não conta:
 * medido, o proxy recebeu 502 por 16 minutos seguidos com a API dormindo, e uma
 * única chamada de fora a acordou em 33 s (ADR 012). A espera com repetição de
 * `lib/espera.ts` continua valendo, mas sozinha ela esperava algo que nunca
 * acontecia.
 *
 * ## Por que no layout
 *
 * As páginas são componentes de servidor que buscam na API antes de chegar ao
 * navegador. Um componente dentro delas só seria montado depois de a API
 * responder, que é tarde demais por construção. O layout vai no primeiro pedaço
 * do HTML, junto do `loading.tsx`, e cobre qualquer rota — inclusive quem chega
 * por link direto numa revisão.
 *
 * ## Por que `no-cors`, e por que ninguém lê a resposta
 *
 * O que importa é a requisição chegar à hospedagem. A resposta é opaca, e falha
 * de rede é ignorada: esta chamada não informa nada à tela. Quem diz se a API
 * respondeu continua sendo a busca do servidor.
 */
export function AcordaApi({ url }: { url: string }) {
  useEffect(() => {
    fetch(`${url}/health`, { mode: "no-cors", cache: "no-store" }).catch(() => {});
  }, [url]);

  return null;
}
