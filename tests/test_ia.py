import json

import pytest

from radar import db
from radar.ia import provedores
from radar.ia.servico import SemProvedor, ServicoIA, extrair_json


class RespostaHTTP:
    def __init__(self, status, corpo):
        self.status_code = status
        self._corpo = corpo
        self.text = json.dumps(corpo)

    def json(self):
        return self._corpo


class SessaoGravando:
    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def post(self, url, headers, json, timeout):
        self.chamadas.append({"url": url, "headers": headers, "json": json})
        return self.respostas.pop(0)


def test_anthropic_formato_da_chamada_e_leitura():
    sessao = SessaoGravando(RespostaHTTP(200, {
        "content": [{"type": "text", "text": '{"ok": 1}'}], "usage": {"input_tokens": 10, "output_tokens": 5}}))
    r = provedores.Anthropic("chave", sessao).gerar("claude-sonnet-5-5", "sis", "user", 100, json=True)
    chamada = sessao.chamadas[0]
    assert chamada["url"] == "https://api.anthropic.com/v1/messages"
    assert chamada["headers"]["x-api-key"] == "chave" and chamada["headers"]["anthropic-version"]
    assert chamada["json"]["system"] == "sis" and chamada["json"]["messages"][0]["content"] == "user"
    assert (r.texto, r.tokens_entrada, r.tokens_saida) == ('{"ok": 1}', 10, 5)


def test_openai_usa_responses_api_e_le_output():
    sessao = SessaoGravando(RespostaHTTP(200, {
        "output": [{"type": "reasoning"}, {"type": "message", "content": [{"type": "output_text", "text": "{}"}]}],
        "usage": {"input_tokens": 3, "output_tokens": 2}}))
    r = provedores.OpenAI("k", sessao).gerar("gpt-6-luna", "sis", "user", 100, json=True)
    chamada = sessao.chamadas[0]
    assert chamada["url"].endswith("/v1/responses")
    assert chamada["headers"]["Authorization"] == "Bearer k"
    assert chamada["json"]["instructions"] == "sis" and chamada["json"]["text"]["format"]["type"] == "json_object"
    assert r.texto == "{}"


def test_gemini_ignora_partes_de_pensamento():
    sessao = SessaoGravando(RespostaHTTP(200, {
        "candidates": [{"content": {"parts": [{"text": "pensando", "thought": True}, {"text": '{"a": 1}'}]}}],
        "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 4}}))
    r = provedores.Gemini("g", sessao).gerar("gemini-3.8-flash", "sis", "user", 100, json=True)
    chamada = sessao.chamadas[0]
    assert "gemini-3.8-flash:generateContent" in chamada["url"]
    assert chamada["headers"]["x-goog-api-key"] == "g"
    assert chamada["json"]["generationConfig"]["responseMimeType"] == "application/json"
    assert r.texto == '{"a": 1}' and r.tokens_entrada == 7


def test_tenta_de_novo_em_429_mas_nao_em_400():
    ok = RespostaHTTP(200, {"content": [{"type": "text", "text": "{}"}]})
    sessao = SessaoGravando(RespostaHTTP(429, {"error": "rate"}), ok)
    provedores.Anthropic("k", sessao, dormir=lambda s: None).gerar("m", "s", "u", 10, True)
    assert len(sessao.chamadas) == 2
    sessao = SessaoGravando(RespostaHTTP(400, {"error": "modelo inválido"}))
    with pytest.raises(provedores.ErroProvedor, match="HTTP 400"):
        provedores.Anthropic("k", sessao, dormir=lambda s: None).gerar("m", "s", "u", 10, True)
    assert len(sessao.chamadas) == 1


def test_extrair_json_tolera_cercas_e_texto_em_volta():
    assert extrair_json('```json\n{"score": 80}\n```') == {"score": 80}
    assert extrair_json('Aqui está: {"score": 70} espero ajudar') == {"score": 70}
    with pytest.raises(ValueError):
        extrair_json("sem json")


class ProvedorFalso(provedores.Provedor):
    def __init__(self, nome, respostas=None, falhar=False):
        super().__init__(chave="x")
        self.nome = nome
        self.respostas = respostas or []
        self.falhar = falhar
        self.chamadas = 0

    def gerar(self, modelo, sistema, usuario, max_tokens, json):
        self.chamadas += 1
        if self.falhar:
            raise provedores.ErroProvedor(f"{self.nome}: fora do ar")
        resposta = self.respostas.pop(0) if self.respostas else {"score": 50}
        texto = resposta if isinstance(resposta, str) else __import__("json").dumps(resposta)
        return provedores.Resposta(texto, 100, 20)


def test_servico_cai_para_o_proximo_e_registra_uso(banco, config):
    servico = ServicoIA(config, banco, {"gemini": ProvedorFalso("gemini", falhar=True),
                                        "openai": ProvedorFalso("openai", [{"score": 77}]),
                                        "anthropic": ProvedorFalso("anthropic")})
    resultado = servico.gerar_json("score", "s", "u")
    assert resultado.provedor == "openai" and resultado.dados == {"score": 77}
    assert resultado.modelo == config["ia"]["provedores"]["openai"]["modelo_rapido"]
    with db.conectar(banco) as conexao:
        uso = {u["provedor"]: u for u in db.resumo_uso_ia(conexao)}
    assert uso["gemini"]["erros"] == 1 and uso["openai"]["entrada"] == 100


def test_limite_diario_e_falta_de_chave(banco, config):
    config["ia"]["provedores"]["gemini"]["limite_chamadas_dia"] = 1
    sem_chave = ProvedorFalso("anthropic")
    sem_chave.chave = ""
    servico = ServicoIA(config, banco, {"gemini": ProvedorFalso("gemini"), "anthropic": sem_chave})
    servico.gerar_json("score", "s", "u")
    assert servico.candidatos("score") == []
    with pytest.raises(SemProvedor, match="Nenhum provedor"):
        servico.gerar_json("score", "s", "u")
