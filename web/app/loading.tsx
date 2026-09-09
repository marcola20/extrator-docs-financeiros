import { Carregando } from "@/componentes/Carregando";

/**
 * O que aparece enquanto a entrada busca os casos.
 *
 * Existe por causa do cold start: sem este arquivo o Next segura o HTML inteiro
 * até a API responder, e quem abre o link de um servidor adormecido fica olhando
 * uma aba em branco por quarenta segundos, sem saber se está carregando ou se
 * quebrou. Com ele, o cabeçalho aparece na hora e o miolo diz o que está
 * acontecendo.
 */
export default function Carregamento() {
  return <Carregando oQue="os casos" />;
}
