import type { SinalNaResposta } from "@/lib/api";
import { nomeLegivel, ordenaParaLeitura } from "@/lib/sinais";
import { ChipDeSinal } from "./ChipDeSinal";

/**
 * A primeira coisa da página: por que este documento não foi aprovado sozinho.
 *
 * Separa **reprovou** de **não teve o que conferir**, porque o trabalho do
 * revisor é diferente nos dois casos. Um documento que falhou numa conferência
 * tem um erro concreto a investigar, e a mensagem do sinal aponta onde. Um
 * documento que ninguém conseguiu conferir não tem erro nenhum apontado — ele
 * precisa ser lido do zero, e é o caso mais fácil de despachar com um "parece
 * bom" justamente porque nada está gritando.
 *
 * Juntar os dois numa lista de "problemas" faria o segundo grupo parecer menos
 * urgente do que é — e no corpus de informes ele é a maioria da fila.
 */
export function PorQueEstaAqui({ sinais }: { sinais: SinalNaResposta[] }) {
  const bloqueadores = sinais.filter((s) => s.bloqueia && s.escopo === null);
  const reprovaram = bloqueadores.filter((s) => s.estado === "divergente");
  const naoConferiram = bloqueadores.filter((s) => s.estado === "sem_cobertura");
  const lugares = sinais.filter((s) => s.escopo !== null).map((s) => s.escopo!);

  if (bloqueadores.length === 0) {
    return (
      <p className="text-sm text-tinta-fraca">
        Nenhum sinal bloqueou este documento.
      </p>
    );
  }

  return (
    <div className="space-y-5">
      {reprovaram.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-rose-800">
            {reprovaram.length === 1 ? "Um sinal reprovou" : `${reprovaram.length} sinais reprovaram`}
          </h3>
          <ul className="mt-2 space-y-2.5">
            {ordenaParaLeitura(reprovaram).map((sinal) => (
              <li
                key={sinal.nome}
                className="rounded-md border border-rose-200 bg-rose-50/50 px-3.5 py-3"
              >
                <div className="flex items-baseline gap-2.5">
                  <span className="text-sm font-semibold capitalize">
                    {nomeLegivel(sinal.nome)}
                  </span>
                  <ChipDeSinal estado={sinal.estado} />
                </div>
                {/* A mensagem vem pronta do pipeline e é o produto das fases
                    anteriores: "banco 001 não confere com a linha digitável
                    (748)". Reescrevê-la aqui perderia a precisão. */}
                <p className="mt-1.5 text-sm leading-relaxed">{sinal.detalhe}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {naoConferiram.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-amber-800">
            {naoConferiram.length === 1
              ? "Um sinal não teve o que conferir"
              : `${naoConferiram.length} sinais não tiveram o que conferir`}
          </h3>
          <p className="mt-1 text-xs text-tinta-fraca">
            Não é aprovação: ninguém verificou. Estes campos precisam ser lidos do
            documento, não conferidos contra um apontamento.
          </p>
          <ul className="mt-2 space-y-2.5">
            {naoConferiram.map((sinal) => (
              <li
                key={sinal.nome}
                className="rounded-md border border-dashed border-amber-300 bg-amber-50/40 px-3.5 py-3"
              >
                <div className="flex items-baseline gap-2.5">
                  <span className="text-sm font-semibold capitalize">
                    {nomeLegivel(sinal.nome)}
                  </span>
                  <ChipDeSinal estado={sinal.estado} />
                </div>
                <p className="mt-1.5 text-sm leading-relaxed">{sinal.detalhe}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {lugares.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-tinta-fraca">
            Onde olhar
          </h3>
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {lugares.map((lugar) => (
              <li
                key={lugar}
                className="rounded border border-borda bg-white px-2 py-1 font-mono text-xs"
              >
                {lugar}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
