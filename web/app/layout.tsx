import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Extrator de Documentos Financeiros",
  description:
    "Extração com validação determinística e revisão humana: por que cada documento " +
    "está na fila, e o que cada sinal conseguiu afirmar.",
};

const REPOSITORIO = "https://github.com/marcola20/extrator-docs-financeiros";

export default function RaizDoLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body className="min-h-dvh">
        <header className="border-b border-borda bg-white">
          <div className="mx-auto flex max-w-[1400px] items-baseline gap-6 px-6 py-4">
            <Link href="/" className="text-sm font-semibold tracking-tight">
              Extrator de Documentos Financeiros
            </Link>
            <Link
              href="/fila"
              className="text-sm text-tinta-fraca underline-offset-2 hover:underline"
            >
              fila de revisão
            </Link>
            {/* O cabeçalho não diz em que modo a instância está. Dizê-lo exigiria
                consultar a API em toda navegação, e a nota que importa — a de
                somente-leitura — já aparece onde ela muda o que dá para fazer:
                na entrada e no formulário de correção. */}
            <a
              href={REPOSITORIO}
              className="ml-auto text-xs text-tinta-fraca underline-offset-2 hover:underline"
              target="_blank"
              rel="noreferrer"
            >
              código no GitHub ↗
            </a>
          </div>
        </header>
        <main className="mx-auto max-w-[1400px] px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
