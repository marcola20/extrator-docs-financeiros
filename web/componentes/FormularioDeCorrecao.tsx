"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { CorrecaoNaResposta, ExtracaoNaResposta, SinalNaResposta } from "@/lib/api";
import { achata, agrupa, rotuloDe, type CampoEditavel } from "@/lib/campos";

interface Props {
  decisaoId: number;
  extracao: ExtracaoNaResposta;
  correcoes: CorrecaoNaResposta[];
  sinais: SinalNaResposta[];
  jaRevisada: boolean;
}

/**
 * Os campos extraídos, editáveis, com o que o revisor já corrigiu preservado.
 *
 * ## O valor de partida não é o payload
 *
 * Foi, e estava errado. O formulário nascia com o que **o modelo** leu, e
 * reabrir um item já revisado apagava o trabalho de quem o revisou: o campo
 * voltava ao valor original, a correção gravada no banco não aparecia em lugar
 * nenhum, e salvar de novo sem reparar teria regravado o valor errado por cima
 * do certo.
 *
 * Agora o valor de partida é **o que se sabe de melhor sobre o campo**: a
 * correção humana quando existe, o que o modelo leu quando não existe. É a
 * mesma ordem de confiança que o resto do projeto usa — pessoa que olhou a
 * página vale mais que leitura de modelo.
 *
 * ## O que ainda se envia como `valor_anterior`
 *
 * Sempre o valor do payload, mesmo numa segunda correção. `valor_anterior`
 * responde "o que o modelo errou?", que é o dado que a Fase 4 existe para
 * coletar; trocá-lo pela correção anterior transformaria a coluna em histórico
 * de edição e perderia a pergunta original. (A API também não o sobrescreve
 * numa atualização — este envio é para o caso de a correção ser a primeira.)
 *
 * ## Três decisões que continuam valendo
 *
 * **Envia só o que mudou.** Um PUT do formulário inteiro gravaria uma
 * "correção" por campo intocado, e a tabela deixaria de responder quais campos
 * o modelo erra na prática.
 *
 * **Marca os campos que algum sinal apontou.** O `escopo` dos sinais é o mesmo
 * endereço do campo, então "onde olhar" vira marca ao lado da caixa de texto.
 *
 * **O revisor volta preenchido.** Ele é quase sempre a mesma pessoa reabrindo o
 * próprio trabalho, e digitar o nome de novo a cada visita é atrito sem função.
 */
export function FormularioDeCorrecao({
  decisaoId,
  extracao,
  correcoes,
  sinais,
  jaRevisada,
}: Props) {
  const router = useRouter();
  const doModelo = useMemo(() => achata(extracao.payload), [extracao.payload]);

  const jaCorrigidos = useMemo(
    () => new Map(correcoes.map((c) => [c.campo, c])),
    [correcoes],
  );

  /** O melhor valor conhecido: correção humana, ou o que o modelo leu. */
  const partida = useMemo(
    () =>
      Object.fromEntries(
        doModelo.map((campo) => [
          campo.caminho,
          jaCorrigidos.get(campo.caminho)?.valor_corrigido ?? campo.valor,
        ]),
      ),
    [doModelo, jaCorrigidos],
  );

  const [valores, setValores] = useState<Record<string, string>>(partida);
  const [revisor, setRevisor] = useState(
    () => correcoes.find((c) => c.revisor)?.revisor ?? "",
  );
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const apontados = useMemo(
    () => new Set(sinais.filter((s) => s.escopo !== null).map((s) => s.escopo!)),
    [sinais],
  );

  // "Alterado" é em relação ao que estava ao abrir a tela, e não ao payload:
  // senão um item já revisado abriria com todas as correções anteriores
  // marcadas como mudanças novas, e o botão de gravar viria habilitado sem
  // ninguém ter tocado em nada.
  const alterados = doModelo.filter(
    (campo) => valores[campo.caminho] !== partida[campo.caminho],
  );

  async function envia(evento: React.FormEvent) {
    evento.preventDefault();
    setEnviando(true);
    setErro(null);
    try {
      const resposta = await fetch(`/api/revisao/${decisaoId}/correcoes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          correcoes: alterados.map((campo) => ({
            campo: campo.caminho,
            // O que o modelo leu, sempre — ver a nota do componente.
            valor_anterior: campo.valor,
            valor_corrigido: valores[campo.caminho] ?? "",
          })),
          revisor,
          encerra_revisao: true,
        }),
      });
      if (!resposta.ok) {
        const corpo = (await resposta.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(corpo?.detail ?? `a API respondeu ${resposta.status}`);
      }
      router.push("/");
      router.refresh();
    } catch (falha) {
      setErro(falha instanceof Error ? falha.message : "não foi possível gravar");
      setEnviando(false);
    }
  }

  const grupos = agrupa(doModelo);

  return (
    <form onSubmit={envia} className="space-y-6">
      {jaRevisada && correcoes.length > 0 && (
        <p className="rounded-md border border-sky-200 bg-sky-50/70 px-3.5 py-2.5 text-xs leading-relaxed text-sky-900">
          Este item já foi revisado. Os campos abaixo mostram{" "}
          <strong>o que a revisão deixou</strong>, não o que o modelo leu — onde
          houve correção, o valor original aparece embaixo do campo.
        </p>
      )}

      {[...grupos.entries()].map(([grupo, campos]) => (
        <fieldset key={grupo || "documento"}>
          {grupo && (
            <legend className="mb-2 text-xs font-semibold uppercase tracking-wide text-tinta-fraca">
              {grupo.replaceAll("_", " ")}
            </legend>
          )}
          <div className="space-y-2.5">
            {campos.map((campo) => (
              <Campo
                key={campo.caminho}
                campo={campo}
                valor={valores[campo.caminho] ?? ""}
                alterado={valores[campo.caminho] !== partida[campo.caminho]}
                apontado={apontados.has(campo.caminho)}
                correcaoAnterior={jaCorrigidos.get(campo.caminho)}
                aoMudar={(novo) =>
                  setValores((atuais) => ({ ...atuais, [campo.caminho]: novo }))
                }
              />
            ))}
          </div>
        </fieldset>
      ))}

      <div className="sticky bottom-0 -mx-1 border-t border-borda bg-papel/95 px-1 py-3 backdrop-blur">
        {erro && (
          <p className="mb-2 rounded border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-900">
            {erro}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-xs text-tinta-fraca">
            revisor
            <input
              value={revisor}
              onChange={(e) => setRevisor(e.target.value)}
              placeholder="seu nome"
              className="ml-2 w-40 rounded border border-borda bg-white px-2 py-1 text-sm text-tinta"
            />
          </label>
          <span className="text-sm text-tinta-fraca">
            {alterados.length === 0
              ? "nenhum campo alterado"
              : `${alterados.length} ${alterados.length === 1 ? "campo alterado" : "campos alterados"}`}
          </span>
          <button
            type="submit"
            disabled={enviando || alterados.length === 0}
            className="ml-auto rounded-md bg-tinta px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
          >
            {enviando ? "gravando…" : "Gravar e encerrar revisão"}
          </button>
        </div>
      </div>
    </form>
  );
}

function Campo({
  campo,
  valor,
  alterado,
  apontado,
  correcaoAnterior,
  aoMudar,
}: {
  campo: CampoEditavel;
  valor: string;
  alterado: boolean;
  apontado: boolean;
  correcaoAnterior: CorrecaoNaResposta | undefined;
  aoMudar: (valor: string) => void;
}) {
  return (
    <label className="block">
      <span className="flex flex-wrap items-baseline gap-2 text-xs">
        <span className="font-medium capitalize">{rotuloDe(campo.caminho)}</span>
        {apontado && (
          <span
            title="algum sinal apontou este lugar"
            className="rounded-full border border-amber-300 bg-amber-50 px-1.5 text-[11px] text-amber-900"
          >
            apontado
          </span>
        )}
        {correcaoAnterior && (
          <span
            title={`corrigido por ${correcaoAnterior.revisor || "alguém"}`}
            className="rounded-full border border-sky-300 bg-sky-50 px-1.5 text-[11px] text-sky-900"
          >
            corrigido na revisão
          </span>
        )}
        {alterado && (
          <span className="rounded-full border border-sky-400 bg-sky-100 px-1.5 text-[11px] text-sky-900">
            alterado agora
          </span>
        )}
      </span>
      <input
        value={valor}
        onChange={(e) => aoMudar(e.target.value)}
        className={`mt-1 w-full rounded border bg-white px-2.5 py-1.5 font-mono text-sm ${
          alterado ? "border-sky-400" : apontado ? "border-amber-300" : "border-borda"
        }`}
      />
      {correcaoAnterior && (
        // Diz de quem é cada valor. "corrigido antes de X" era ambíguo: com o
        // campo mostrando o payload, X aparecia duas vezes e a frase parecia
        // descrever o valor atual em vez do anterior.
        <span className="mt-1 block font-mono text-[11px] text-tinta-fraca">
          o modelo leu{" "}
          <span className="text-tinta">
            {correcaoAnterior.valor_anterior || "(vazio)"}
          </span>
        </span>
      )}
    </label>
  );
}
