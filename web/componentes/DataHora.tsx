"use client";

import { useEffect, useState } from "react";
import { formata, fusoDoNavegador, type Precisao } from "@/lib/datas";

interface Props {
  /** O instante como a API o devolveu: ISO-8601 com fuso. */
  iso: string;
  precisao?: Precisao;
  className?: string;
  /** Texto que precede a data no `title`, ex.: "revisado em". */
  rotulo?: string;
}

/**
 * Um instante, no fuso do navegador.
 *
 * ## Por que é componente de cliente, e por que a formatação vem depois
 *
 * A conversão só pode acontecer onde o fuso é o de quem lê. Num componente de
 * servidor o `Intl` usa o fuso do processo — UTC no contêiner —, e era essa a
 * origem das três horas a mais (ver `lib/datas.ts`).
 *
 * A formatação roda num `useEffect`, e não direto no corpo, porque o Next
 * renderiza este componente **duas** vezes: uma no servidor, para o HTML
 * inicial, e outra no navegador, ao hidratar. Formatar no corpo produziria
 * textos diferentes nas duas, e o React trata isso como erro de hidratação —
 * ele avisa no console e, pior, pode manter o texto do servidor. Com o estado
 * começando vazio nas duas renderizações, elas concordam, e o navegador
 * preenche logo em seguida.
 *
 * O `<time dateTime>` carrega o instante bruto desde o HTML inicial. É o que
 * mantém a informação disponível para leitor de tela e para quem inspeciona a
 * página antes de o script rodar.
 */
export function DataHora({ iso, precisao = "completo", className, rotulo }: Props) {
  const [texto, setTexto] = useState<string | null>(null);
  const [fuso, setFuso] = useState<string | null>(null);

  useEffect(() => {
    // Data inválida cai para o texto cru: esconder o instante seria pior que
    // mostrá-lo feio, porque some com a única pista do que veio errado.
    setTexto(formata(iso, precisao) ?? iso);
    setFuso(fusoDoNavegador());
  }, [iso, precisao]);

  const titulo = [rotulo, texto, fuso && `(${fuso})`].filter(Boolean).join(" ");

  return (
    <time dateTime={iso} title={titulo || undefined} className={className}>
      {/* Espaços de figura seguram a largura até a hidratação, para a lista não
          pular quando as datas aparecem. */}
      {texto ?? "     "}
    </time>
  );
}
