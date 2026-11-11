"""Clientes HTTP mínimos para os três provedores.

Cada cliente recebe um texto de sistema e um texto do usuário e devolve uma Resposta com o texto
gerado e a contagem de tokens. Chamadas por HTTP puro (requests) para não depender de SDKs.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests

TIMEOUT = 120
TENTATIVAS = 3
STATUS_TEMPORARIOS = {408, 409, 429, 500, 502, 503, 504, 529}


@dataclass
class Resposta:
    texto: str
    tokens_entrada: int = 0
    tokens_saida: int = 0


class ErroProvedor(RuntimeError):
    """Falha ao chamar o provedor (depois das novas tentativas)."""


class Provedor:
    nome = "base"
    variavel_chave = ""

    def __init__(
        self,
        chave: str | None = None,
        sessao: requests.Session | None = None,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self.chave = chave if chave is not None else os.environ.get(self.variavel_chave, "").strip()
        self.sessao = sessao or requests.Session()
        self.dormir = dormir

    @property
    def configurado(self) -> bool:
        return bool(self.chave)

    def gerar(self, modelo: str, sistema: str, usuario: str, max_tokens: int, json: bool) -> Resposta:
        raise NotImplementedError

    def _post(self, url: str, cabecalhos: dict[str, str], corpo: dict[str, Any]) -> dict[str, Any]:
        ultimo_erro = ""
        for tentativa in range(TENTATIVAS):
            try:
                resposta = self.sessao.post(url, headers=cabecalhos, json=corpo, timeout=TIMEOUT)
            except (requests.ConnectionError, requests.Timeout) as erro:
                ultimo_erro = f"sem conexão: {erro.__class__.__name__}"
            else:
                if resposta.status_code < 400:
                    return resposta.json()
                ultimo_erro = f"HTTP {resposta.status_code}: {resposta.text[:300]}"
                if resposta.status_code not in STATUS_TEMPORARIOS:
                    break
            if tentativa < TENTATIVAS - 1:
                self.dormir(2 * (tentativa + 1) ** 2)
        raise ErroProvedor(f"{self.nome}: {ultimo_erro}")


class Anthropic(Provedor):
    nome = "anthropic"
    variavel_chave = "ANTHROPIC_API_KEY"
    URL = "https://api.anthropic.com/v1/messages"

    def gerar(self, modelo: str, sistema: str, usuario: str, max_tokens: int, json: bool) -> Resposta:
        dados = self._post(
            self.URL,
            {"x-api-key": self.chave, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            {
                "model": modelo,
                "max_tokens": max_tokens,
                "system": sistema,
                "messages": [{"role": "user", "content": usuario}],
            },
        )
        texto = "".join(b.get("text", "") for b in dados.get("content") or [] if b.get("type") == "text")
        uso = dados.get("usage") or {}
        return Resposta(texto, uso.get("input_tokens", 0), uso.get("output_tokens", 0))


class OpenAI(Provedor):
    nome = "openai"
    variavel_chave = "OPENAI_API_KEY"
    URL = "https://api.openai.com/v1/responses"

    def gerar(self, modelo: str, sistema: str, usuario: str, max_tokens: int, json: bool) -> Resposta:
        corpo: dict[str, Any] = {
            "model": modelo,
            "instructions": sistema,
            "input": usuario,
            # modelos com raciocínio gastam tokens antes da resposta: folga para não cortar o JSON
            "max_output_tokens": max_tokens * 3,
        }
        if json:
            corpo["text"] = {"format": {"type": "json_object"}}
        dados = self._post(
            self.URL, {"Authorization": f"Bearer {self.chave}", "Content-Type": "application/json"}, corpo
        )
        texto = dados.get("output_text") or ""
        if not texto:
            partes = []
            for item in dados.get("output") or []:
                if item.get("type") == "message":
                    for conteudo in item.get("content") or []:
                        if conteudo.get("type") in ("output_text", "text"):
                            partes.append(conteudo.get("text", ""))
            texto = "".join(partes)
        uso = dados.get("usage") or {}
        return Resposta(texto, uso.get("input_tokens", 0), uso.get("output_tokens", 0))


class Gemini(Provedor):
    nome = "gemini"
    variavel_chave = "GEMINI_API_KEY"
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"

    def gerar(self, modelo: str, sistema: str, usuario: str, max_tokens: int, json: bool) -> Resposta:
        configuracao: dict[str, Any] = {"maxOutputTokens": max_tokens * 3}
        if json:
            configuracao["responseMimeType"] = "application/json"
        dados = self._post(
            self.URL.format(modelo=modelo),
            {"x-goog-api-key": self.chave, "Content-Type": "application/json"},
            {
                "systemInstruction": {"parts": [{"text": sistema}]},
                "contents": [{"role": "user", "parts": [{"text": usuario}]}],
                "generationConfig": configuracao,
            },
        )
        candidatos = dados.get("candidates") or []
        partes = (candidatos[0].get("content") or {}).get("parts") or [] if candidatos else []
        texto = "".join(p.get("text", "") for p in partes if not p.get("thought"))
        if not texto and candidatos:
            raise ErroProvedor(f"gemini: resposta vazia ({candidatos[0].get('finishReason')})")
        uso = dados.get("usageMetadata") or {}
        return Resposta(texto, uso.get("promptTokenCount", 0), uso.get("candidatesTokenCount", 0))


CLASSES: dict[str, type[Provedor]] = {"anthropic": Anthropic, "openai": OpenAI, "gemini": Gemini}
NOMES_EXIBICAO = {"anthropic": "Claude (Anthropic)", "openai": "OpenAI", "gemini": "Gemini (Google)"}
