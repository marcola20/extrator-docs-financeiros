"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const ESPERA_ENTRE_TENTATIVAS_MS = 3000;

/**
 * Conta os segundos e recarrega a página sozinho, quantas vezes for preciso.
 *
 * Existe para o servidor adormecido: a primeira visita ao serviço gratuito
 * chega enquanto o contêiner ainda está subindo, e alguma requisição depois já
 * encontra tudo de pé. Sem isto, a pessoa vê uma tela de erro para um problema
 * que se resolve sozinho em menos de um minuto, e a única saída oferecida seria
 * apertar F5 sem saber se adianta.
 *
 * Tentar **uma** vez não bastaria: acordar pode levar mais que a espera, e o
 * componente ficaria parado em "tentando…" para sempre. Por isso a contagem
 * recomeça depois de cada tentativa — quando uma delas dá certo, esta tela sai
 * do ar junto com o erro que a trouxe.
 *
 * `router.refresh()` e não `location.reload()`: ele refaz a renderização no
 * servidor e preserva o estado do cliente, que é o que se quer numa nova
 * tentativa. O botão está ali para quem não quer esperar a contagem.
 */
export function TentaDeNovo({ segundos = 10 }: { segundos?: number }) {
  const router = useRouter();
  const [faltam, setFaltam] = useState(segundos);
  const [tentando, setTentando] = useState(false);

  const tenta = useCallback(() => {
    setTentando(true);
    setFaltam(0);
    router.refresh();
  }, [router]);

  useEffect(() => {
    if (faltam > 0 && !tentando) {
      const relogio = setTimeout(() => setFaltam((quantos) => quantos - 1), 1000);
      return () => clearTimeout(relogio);
    }
    if (faltam > 0) return;

    if (!tentando) {
      tenta();
      return;
    }
    // A tentativa saiu. Se a página continuar aqui, é porque ela não deu certo:
    // recomeça a contagem em vez de deixar "tentando…" parado na tela.
    const relogio = setTimeout(() => {
      setTentando(false);
      setFaltam(segundos);
    }, ESPERA_ENTRE_TENTATIVAS_MS);
    return () => clearTimeout(relogio);
  }, [faltam, tentando, segundos, tenta]);

  return (
    <div className="mt-4 flex flex-wrap items-center gap-3">
      <button
        type="button"
        onClick={tenta}
        disabled={tentando}
        className="rounded-md bg-tinta px-3.5 py-1.5 text-sm font-medium text-white disabled:opacity-50"
      >
        Tentar agora
      </button>
      <span aria-live="polite" className="text-xs text-tinta-fraca">
        {tentando ? "tentando de novo…" : `nova tentativa automática em ${faltam}s`}
      </span>
    </div>
  );
}
