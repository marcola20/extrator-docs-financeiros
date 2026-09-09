import type { ApiIndisponivel } from "@/lib/api";

/**
 * A tela quando a API não responde.
 *
 * Diz o que fazer, e não só que deu errado — este projeto roda sem banco por
 * padrão, então "a fila está vazia" e "a persistência está desligada" são
 * situações diferentes que uma tela descuidada mostraria igual.
 */
export function AvisoDaApi({ erro }: { erro: ApiIndisponivel }) {
  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50/60 p-6">
      <h1 className="text-base font-semibold text-amber-900">
        {erro.status === 503 ? "A fila precisa de banco" : "A API não respondeu"}
      </h1>
      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-amber-900">{erro.detalhe}</p>
      {erro.status === 503 && (
        <pre className="mt-3 overflow-x-auto rounded border border-amber-300 bg-white/70 px-3 py-2 font-mono text-xs">
{`docker compose up -d
echo "PERSISTENCIA_ATIVA=1" >> .env
uv run alembic upgrade head`}
        </pre>
      )}
    </div>
  );
}
