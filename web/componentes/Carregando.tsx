"use client";

import { useEffect, useState } from "react";

/** Depois de quanto tempo a espera deixa de ser normal e merece explicação. */
const DEMORA_MS = 4000;

/**
 * O estado de carregamento, com a explicação chegando só quando ela é verdade.
 *
 * A demonstração roda num plano gratuito que desliga o serviço por inatividade,
 * e a primeira visita espera o contêiner subir. Mas a **maioria** das aberturas
 * não espera nada: uma vez de pé, a fila responde em milissegundos.
 *
 * Por isso a nota sobre o servidor adormecido aparece só depois de quatro
 * segundos. Mostrá-la desde o primeiro quadro seria mais simples e seria falso —
 * diria "o servidor está acordando" numa página que já carregou —, e uma
 * interface que avisa errado sobre o que está acontecendo ensina a ignorar os
 * avisos dela.
 */
export function Carregando({ oQue = "a fila" }: { oQue?: string }) {
  const [demorou, setDemorou] = useState(false);

  useEffect(() => {
    const relogio = setTimeout(() => setDemorou(true), DEMORA_MS);
    return () => clearTimeout(relogio);
  }, []);

  return (
    <div className="rounded-lg border border-borda bg-white/60 px-5 py-10 text-center">
      <p aria-live="polite" className="text-sm font-medium">
        Carregando {oQue}…
      </p>
      {demorou && (
        <p className="mx-auto mt-2 max-w-md text-xs leading-relaxed text-tinta-fraca">
          Está demorando mais que o normal, e o motivo provável é o servidor
          acordando: o plano gratuito desliga o serviço depois de alguns minutos
          sem visita, e ligá-lo de novo leva de 30 a 60 segundos. As próximas
          páginas abrem na hora.
        </p>
      )}
    </div>
  );
}
