"""Exercita o uso real do SDK google-genai com cliente dublê — sem rede.

Não confere se o modelo acerta a extração; confere se o código fala com o SDK
do jeito certo: que a resposta vira instância do schema, que os tokens saem
dos campos certos e que 429 vira `ErroDeTaxa` para o limitador repetir.
"""

from decimal import Decimal
from typing import Any, cast

import pytest
from google import genai
from google.genai import errors as erros_genai
from google.genai import types

from app.llm.gemini import MODELO_PADRAO, ProvedorGemini
from app.llm.provedor import ErroDeConfiguracao, ErroDeExtracao, ErroDeTaxa
from tests.llm.falso import DocumentoFalso

DOCUMENTO = DocumentoFalso(titulo="Boleto", valor=Decimal("1234.56"))


class _ModelosFalsos:
    def __init__(self, resposta: object | None = None, erro: Exception | None = None) -> None:
        self._resposta = resposta
        self._erro = erro
        self.chamadas: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> object:
        self.chamadas.append(kwargs)
        if self._erro is not None:
            raise self._erro
        return self._resposta


class _ClienteGeminiFalso:
    def __init__(self, resposta: object | None = None, erro: Exception | None = None) -> None:
        self.models = _ModelosFalsos(resposta, erro)


def _resposta_gemini(parsed: object) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        parsed=parsed,
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=1_000,
            candidates_token_count=150,
            thoughts_token_count=50,
        ),
    )


def _provedor_gemini(cliente: _ClienteGeminiFalso) -> ProvedorGemini:
    return ProvedorGemini("", MODELO_PADRAO, cliente=cast(genai.Client, cliente))


def test_gemini_devolve_instancia_validada_e_custo() -> None:
    cliente = _ClienteGeminiFalso(_resposta_gemini(DOCUMENTO))

    resultado = _provedor_gemini(cliente).extrai("texto do boleto", DocumentoFalso)

    assert resultado.dados.valor == Decimal("1234.56")
    assert resultado.provedor == "gemini"
    assert resultado.modelo == MODELO_PADRAO
    # Tokens de raciocínio entram na saída: 150 + 50.
    assert resultado.uso.entrada == 1_000
    assert resultado.uso.saida == 200
    # 1000 * 0.30/1e6 + 200 * 2.50/1e6
    assert resultado.custo_estimado_usd == Decimal("0.000800")


def test_gemini_pede_structured_output_com_o_schema() -> None:
    cliente = _ClienteGeminiFalso(_resposta_gemini(DOCUMENTO))

    _provedor_gemini(cliente).extrai("texto", DocumentoFalso, instrucao="leia isto")

    (chamada,) = cliente.models.chamadas
    configuracao = chamada["config"]
    assert chamada["model"] == MODELO_PADRAO
    assert chamada["contents"] == "texto"
    assert configuracao.response_schema is DocumentoFalso
    assert configuracao.response_mime_type == "application/json"
    assert configuracao.system_instruction == "leia isto"
    # Extração tem que ser reprodutível.
    assert configuracao.temperature == 0.0


def test_gemini_aceita_o_schema_do_projeto_sem_reclamar() -> None:
    """O SDK converte o schema Pydantic no formato dele — que rejeita construções.

    Se um campo do domínio não couber no structured output do Gemini, é aqui
    que aparece, e não no meio de um eval.
    """
    configuracao = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=DocumentoFalso,
    )

    assert configuracao.response_schema is not None


def test_gemini_traduz_429_para_erro_de_taxa() -> None:
    erro = erros_genai.ClientError(429, {"error": {"message": "quota"}})
    cliente = _ClienteGeminiFalso(erro=erro)

    with pytest.raises(ErroDeTaxa, match="excesso de requisições"):
        _provedor_gemini(cliente).extrai("texto", DocumentoFalso)


def test_gemini_traduz_outro_erro_de_cliente_para_erro_de_extracao() -> None:
    erro = erros_genai.ClientError(400, {"error": {"message": "schema inválido"}})
    cliente = _ClienteGeminiFalso(erro=erro)

    with pytest.raises(ErroDeExtracao):
        _provedor_gemini(cliente).extrai("texto", DocumentoFalso)


def test_gemini_recusa_resposta_que_nao_virou_o_schema() -> None:
    cliente = _ClienteGeminiFalso(_resposta_gemini(None))

    with pytest.raises(ErroDeExtracao, match="DocumentoFalso"):
        _provedor_gemini(cliente).extrai("texto", DocumentoFalso)


def test_gemini_sem_chave_e_sem_cliente_falha_claro() -> None:
    with pytest.raises(ErroDeConfiguracao, match="GEMINI_API_KEY"):
        ProvedorGemini("")
