"use client";

import type { AchadoNaResposta } from "@/lib/api";

const SEVERIDADE: Record<string, string> = {
  alta: "border-rose-300 bg-rose-50 text-rose-900",
  media: "border-amber-300 bg-amber-50 text-amber-900",
  baixa: "border-slate-300 bg-slate-50 text-slate-700",
};

const O_QUE_E: Record<string, string> = {
  texto_quase_invisivel: "texto na cor do papel ou quase transparente",
  fonte_minuscula: "corpo de fonte próximo de zero",
  texto_fora_da_pagina: "posicionado fora da área imprimível",
  padrao_de_injecao: "frase com forma de ordem dirigida ao modelo",
  delimitador_falso: "imita o fechamento do bloco de dados do prompt",
  divergencia_texto_imagem: "está na camada de texto e não aparece na página renderizada",
};

/**
 * Os trechos que o sanitizador achou, com onde eles estão.
 *
 * O ponto destes achados é que **o revisor não os encontraria olhando o PDF**:
 * texto branco sobre branco, corpo de fonte quase zero, conteúdo posicionado
 * fora da página. Mostrar o trecho em monoespaçado, com a página e as
 * coordenadas, é o que transforma "há algo escondido aqui" em algo conferível.
 *
 * Clicar leva o visor à página do achado. Desenhar o retângulo por cima do PDF
 * seria melhor e não foi feito: exigiria renderizar o documento com pdf.js e
 * converter as coordenadas do PDF para pixels de tela — uma dependência pesada
 * para esta fase, e o enunciado pedia sobriedade. Fica registrado no README.
 */
export function TrechosSuspeitos({
  achados,
  aoEscolherPagina,
}: {
  achados: AchadoNaResposta[];
  aoEscolherPagina: (pagina: number) => void;
}) {
  if (achados.length === 0) return null;

  return (
    <section>
      <div className="flex items-baseline gap-2">
        <h2 className="text-sm font-semibold">Trechos suspeitos</h2>
        <span className="text-xs text-tinta-fraca">
          {achados.length} {achados.length === 1 ? "achado" : "achados"} da sanitização
        </span>
      </div>
      <p className="mt-1 text-xs text-tinta-fraca">
        Você não encontraria estes trechos olhando a página: é isso que os torna
        suspeitos. Achado nunca é atestado de ataque — é indício, e tira a
        auto-aprovação.
      </p>

      <ul className="mt-3 space-y-2.5">
        {achados.map((achado, indice) => (
          <li
            key={`${achado.tipo}-${indice}`}
            className={`rounded-md border px-3.5 py-3 ${SEVERIDADE[achado.severidade] ?? SEVERIDADE.baixa}`}
          >
            <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
              <span className="text-sm font-semibold">
                {achado.tipo.replaceAll("_", " ")}
              </span>
              <span className="rounded-full border border-current/25 px-1.5 py-px text-[11px] uppercase tracking-wide">
                severidade {achado.severidade}
              </span>
              <button
                type="button"
                onClick={() => aoEscolherPagina(achado.pagina)}
                className="ml-auto text-xs underline underline-offset-2 hover:no-underline"
              >
                ir para a página {achado.pagina}
              </button>
            </div>

            <p className="mt-1 text-xs opacity-80">
              {O_QUE_E[achado.tipo] ?? achado.detalhe}
            </p>

            <p className="mt-2 rounded border border-current/20 bg-white/70 px-2.5 py-2 font-mono text-xs leading-relaxed break-words">
              {achado.trecho}
            </p>

            {achado.caixa.x0 !== null && (
              <p className="mt-1.5 font-mono text-[11px] opacity-70">
                página {achado.pagina} · x {achado.caixa.x0}–{achado.caixa.x1} · y{" "}
                {achado.caixa.topo}–{achado.caixa.base}
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
