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
 * Os campos extraídos, editáveis, com o que o revisor mudou destacado.
 *
 * Três decisões de comportamento:
 *
 * **Envia só o que mudou.** Um PUT do formulário inteiro gravaria uma "correção"
 * para cada campo que o revisor não tocou, e a tabela de correções deixaria de
 * responder a pergunta que ela existe para responder — quais campos o modelo
 * erra na prática.
 *
 * **Manda o valor anterior junto.** É o que a API guarda em `valor_anterior`, e
 * sem ele a linha de correção não diz o que foi corrigido, só o que ficou.
 *
 * **Marca os campos que algum sinal apontou.** O `escopo` dos sinais é o mesmo
 * endereço que o campo tem aqui, então "onde olhar" vira uma marca ao lado da
 * caixa de texto em vez de uma lista que o revisor tem de casar na cabeça.
 */
export function FormularioDeCorrecao({
  decisaoId,
  extracao,
  correcoes,
  sinais,
  jaRevisada,
}: Props) {
  const router = useRouter();
  const originais = useMemo(() => achata(extracao.payload), [extracao.payload]);

  const [valores, setValores] = useState<Record<string, string>>(() =>
    Object.fromEntries(originais.map((c) => [c.caminho, c.valor])),
  );
  const [revisor, setRevisor] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const apontados = useMemo(
    () => new Set(sinais.filter((s) => s.escopo !== null).map((s) => s.escopo!)),
    [sinais],
  );
  const jaCorrigidos = useMemo(
    () => new Map(correcoes.map((c) => [c.campo, c])),
    [correcoes],
  );

  const alterados = originais.filter((c) => valores[c.caminho] !== c.valor);

  async function envia(evento: React.FormEvent) {
    evento.preventDefault();
    setEnviando(true);
    setErro(null);
    try {
      const resposta = await fetch(`/api/revisao/${decisaoId}/correcoes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          correcoes: alterados.map((c) => ({
            campo: c.caminho,
            valor_anterior: c.valor,
            valor_corrigido: valores[c.caminho] ?? "",
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

  const grupos = agrupa(originais);

  return (
    <form onSubmit={envia} className="space-y-6">
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
                apontado={apontados.has(campo.caminho)}
                corrigidoAntes={jaCorrigidos.get(campo.caminho)}
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
        {jaRevisada && (
          <p className="mt-2 text-xs text-tinta-fraca">
            Este item já foi encerrado antes. Gravar de novo sobrescreve as
            correções dos campos que você mudar.
          </p>
        )}
      </div>
    </form>
  );
}

function Campo({
  campo,
  valor,
  apontado,
  corrigidoAntes,
  aoMudar,
}: {
  campo: CampoEditavel;
  valor: string;
  apontado: boolean;
  corrigidoAntes: CorrecaoNaResposta | undefined;
  aoMudar: (valor: string) => void;
}) {
  const alterado = valor !== campo.valor;
  return (
    <label className="block">
      <span className="flex items-baseline gap-2 text-xs">
        <span className="font-medium capitalize">{rotuloDe(campo.caminho)}</span>
        {apontado && (
          <span
            title="algum sinal apontou este lugar"
            className="rounded-full border border-amber-300 bg-amber-50 px-1.5 text-[11px] text-amber-900"
          >
            apontado
          </span>
        )}
        {alterado && (
          <span className="rounded-full border border-sky-300 bg-sky-50 px-1.5 text-[11px] text-sky-900">
            alterado
          </span>
        )}
        {corrigidoAntes && !alterado && (
          <span className="text-[11px] text-tinta-fraca">
            corrigido antes de {corrigidoAntes.valor_anterior || "vazio"}
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
    </label>
  );
}
