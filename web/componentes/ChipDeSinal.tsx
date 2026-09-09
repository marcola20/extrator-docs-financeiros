import type { EstadoDoSinal } from "@/lib/api";
import { aparenciaDe } from "@/lib/sinais";

/**
 * O chip de estado. Curto no relance, explícito no hover e para leitor de tela.
 *
 * O glifo é `aria-hidden`: ele é reforço visual, e a informação de verdade está
 * no rótulo, que é texto. Uma interface que codificasse o estado só em cor e
 * símbolo deixaria de fora quem usa leitor de tela — e deixaria de fora,
 * exatamente, a distinção que o projeto passou três fases protegendo.
 */
export function ChipDeSinal({ estado }: { estado: EstadoDoSinal }) {
  const aparencia = aparenciaDe(estado);
  return (
    <span
      title={aparencia.explicacao}
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${aparencia.classes}`}
    >
      <span aria-hidden className="font-mono leading-none">
        {aparencia.glifo}
      </span>
      {aparencia.rotulo}
    </span>
  );
}
