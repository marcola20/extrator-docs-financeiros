/**
 * Formatação de data e hora. Sempre no fuso de quem está olhando.
 *
 * ## O que estava errado, e não era o que parecia
 *
 * As datas apareciam três horas à frente. A causa não é a API: ela devolve
 * `datetime` com fuso, e o JSON sai com o deslocamento junto
 * (`2026-09-08T14:32:10+00:00`), então `new Date` o interpreta corretamente
 * como UTC. `DataHoraUTC`, no backend, já garante isso em qualquer dialeto.
 *
 * O erro era **onde** a formatação acontecia. `toLocaleString("pt-BR")` estava
 * sendo chamado dentro de um componente de servidor, e ali "local" é o fuso do
 * processo Node — UTC dentro do contêiner. O navegador de quem lê nunca entrou
 * na conta. Um documento gravado às 11:32 de Brasília aparecia como 14:32, e
 * apareceria diferente em cada máquina que servisse a página.
 *
 * Por isso a formatação vive num componente de cliente (`DataHora`) e não numa
 * função chamada de qualquer lugar: uma função assim voltaria a ser chamada do
 * servidor no primeiro componente novo, e o defeito voltaria calado. O que este
 * arquivo exporta é o **formato**; quem o executa é o navegador.
 */

/** O fuso de quem está olhando. `undefined` deixa o `Intl` resolver sozinho. */
const FUSO_DO_NAVEGADOR = undefined;

const COMPLETO = new Intl.DateTimeFormat("pt-BR", {
  dateStyle: "short",
  timeStyle: "short",
  timeZone: FUSO_DO_NAVEGADOR,
});

const SO_DATA = new Intl.DateTimeFormat("pt-BR", {
  dateStyle: "short",
  timeZone: FUSO_DO_NAVEGADOR,
});

export type Precisao = "completo" | "data";

/**
 * Formata um instante ISO-8601 no fuso do navegador.
 *
 * Devolve `null` — e não uma string de erro — quando a entrada não é uma data
 * válida: quem chama decide o que mostrar no lugar, e "Invalid Date" no meio de
 * uma tela de revisão não ajuda ninguém.
 */
export function formata(iso: string, precisao: Precisao = "completo"): string | null {
  const instante = new Date(iso);
  if (Number.isNaN(instante.getTime())) return null;
  return (precisao === "data" ? SO_DATA : COMPLETO).format(instante);
}

/** O nome do fuso em que a página está formatando, para a tela poder dizê-lo. */
export function fusoDoNavegador(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}
