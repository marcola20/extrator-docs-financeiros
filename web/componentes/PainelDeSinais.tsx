import type { SinalNaResposta } from "@/lib/api";
import { O_QUE_O_SINAL_VERIFICA, nomeLegivel, ordenaParaLeitura } from "@/lib/sinais";
import { ChipDeSinal } from "./ChipDeSinal";

/**
 * Todos os sinais, com o que cada um verifica e o que ele disse deste documento.
 *
 * Mostra os que passaram junto com os que não passaram, e isso é deliberado: uma
 * lista só de problemas não deixa ver **quanto** do documento foi conferido, que
 * é a diferença entre "um sinal reprovou" e "quase nada foi verificado".
 */
export function PainelDeSinais({ sinais }: { sinais: SinalNaResposta[] }) {
  const doDocumento = sinais.filter((s) => s.escopo === null);

  return (
    <ul className="divide-y divide-borda">
      {ordenaParaLeitura(doDocumento).map((sinal) => (
        <li key={sinal.nome} className="py-3.5 first:pt-0 last:pb-0">
          <div className="flex items-baseline gap-3">
            <h3 className="text-sm font-semibold capitalize">{nomeLegivel(sinal.nome)}</h3>
            <ChipDeSinal estado={sinal.estado} />
          </div>
          <p className="mt-1 text-xs text-tinta-fraca">
            {O_QUE_O_SINAL_VERIFICA[sinal.nome] ?? "sinal do pipeline"}
          </p>
          {sinal.detalhe && (
            <p className="mt-1.5 text-sm leading-relaxed text-tinta">{sinal.detalhe}</p>
          )}
        </li>
      ))}
    </ul>
  );
}
