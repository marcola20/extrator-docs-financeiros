import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Revisão — Extrator de Documentos Financeiros",
  description:
    "Fila de revisão humana: por que cada documento está aqui, e o que cada sinal conseguiu afirmar.",
};

export default function RaizDoLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body className="min-h-dvh">
        <header className="border-b border-borda bg-white">
          <div className="mx-auto flex max-w-[1400px] items-baseline gap-6 px-6 py-4">
            <Link href="/" className="text-sm font-semibold tracking-tight">
              Extrator de Documentos Financeiros
            </Link>
            <span className="text-sm text-tinta-fraca">fila de revisão</span>
            <span className="ml-auto text-xs text-tinta-fraca">
              demo local, sem autenticação
            </span>
          </div>
        </header>
        <main className="mx-auto max-w-[1400px] px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
