"use client";

import { useState } from "react";
import type { Diagnostico } from "@/lib/api";
import { FormularioDeCorrecao } from "./FormularioDeCorrecao";
import { TrechosSuspeitos } from "./TrechosSuspeitos";

/**
 * PDF de um lado, campos do outro — e a ponte entre os trechos suspeitos e a
 * página em que eles estão.
 *
 * Cliente porque o número da página é estado compartilhado entre o painel de
 * achados e o visor: clicar num trecho move o PDF. É a única interação da tela
 * que precisa de estado além do formulário.
 */
export function AreaDeRevisao({ diagnostico }: { diagnostico: Diagnostico }) {
  const [pagina, setPagina] = useState(1);
  const pdf = `/api/revisao/${diagnostico.decisao_id}/pdf#page=${pagina}`;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div className="space-y-5">
        <div className="lg:sticky lg:top-6">
          <div className="flex items-baseline justify-between pb-2">
            <h2 className="text-sm font-semibold">Documento</h2>
            <span className="font-mono text-xs text-tinta-fraca">
              {diagnostico.arquivo.split("/").pop()}
            </span>
          </div>
          <iframe
            key={pagina}
            src={pdf}
            title={`PDF de ${diagnostico.arquivo}`}
            className="h-[78vh] w-full rounded-md border border-borda bg-white"
          />
        </div>
      </div>

      <div className="space-y-8">
        <TrechosSuspeitos achados={diagnostico.achados} aoEscolherPagina={setPagina} />

        <section>
          <h2 className="text-sm font-semibold">Campos extraídos</h2>
          <p className="mt-1 text-xs text-tinta-fraca">
            O que o modelo escreveu, sem conversão. Corrija o que estiver errado
            comparando com o documento ao lado.
          </p>
          <div className="mt-3">
            {diagnostico.extracao ? (
              <FormularioDeCorrecao
                decisaoId={diagnostico.decisao_id}
                extracao={diagnostico.extracao}
                correcoes={diagnostico.correcoes}
                sinais={diagnostico.sinais}
                jaRevisada={diagnostico.revisada_em !== null}
              />
            ) : (
              <p className="rounded-md border border-dashed border-amber-300 bg-amber-50/40 px-3.5 py-3 text-sm">
                Este documento foi barrado <strong>antes</strong> de chegar ao
                modelo, então não há extração para corrigir. É o caso do PDF sem
                camada de texto: a decisão existe, a leitura não.
              </p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
