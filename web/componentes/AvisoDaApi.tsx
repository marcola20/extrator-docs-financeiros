import type { ApiIndisponivel } from "@/lib/api";
import { TentaDeNovo } from "./TentaDeNovo";

/**
 * A tela quando a API não responde.
 *
 * Diz o que fazer, e não só que deu errado. São três situações que uma tela
 * descuidada mostraria igual, e elas pedem coisas diferentes de quem lê:
 *
 * - **o servidor está acordando** — a hospedagem gratuita desliga o serviço por
 *   inatividade, e a primeira visita paga a espera. Não é defeito e não há nada
 *   a fazer além de esperar, então a tela espera junto e tenta de novo sozinha;
 * - **a persistência está desligada** (503) — o pipeline roda sem banco por
 *   padrão, e a fila é a única parte que precisa dele. Aqui há três comandos a
 *   dar, e eles estão na tela;
 * - **qualquer outra falha** — mostra o que a API disse.
 *
 * A primeira e a segunda eram a mesma mensagem antes desta fase, e a diferença
 * importa: "suba o banco" é um conselho inútil para quem abriu um link público
 * e só precisa esperar quarenta segundos.
 */
export function AvisoDaApi({ erro }: { erro: ApiIndisponivel }) {
  if (erro.semResposta) return <Acordando detalhe={erro.detalhe} />;

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

/**
 * O servidor está subindo — o estado normal da primeira visita à demonstração.
 *
 * O texto diz o motivo em vez de pedir paciência genérica. Quem abre o link de
 * um portfólio e vê "ocorreu um erro" fecha a aba; quem lê que o servidor
 * gratuito dorme e está sendo acordado espera os quarenta segundos.
 */
function Acordando({ detalhe }: { detalhe: string }) {
  return (
    <div className="rounded-lg border border-sky-300 bg-sky-50/70 p-6">
      <h1 className="text-base font-semibold text-sky-900">Acordando o servidor…</h1>
      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-sky-900">
        Esta demonstração roda no plano gratuito, que desliga o serviço depois de
        alguns minutos sem visita. A primeira requisição depois disso liga o
        contêiner de novo, e isso costuma levar de <strong>30 a 60 segundos</strong>.
        Não há nada quebrado — as próximas páginas abrem na hora.
      </p>
      <TentaDeNovo />
      <p className="mt-4 border-t border-sky-200 pt-3 text-xs text-sky-900/80">
        Rodando o projeto localmente, esta mesma tela significa outra coisa: a API
        não está de pé. {detalhe} Suba-a com{" "}
        <code className="font-mono">uv run uvicorn app.main:app</code> ou com{" "}
        <code className="font-mono">docker compose --profile revisao up</code>.
      </p>
    </div>
  );
}
