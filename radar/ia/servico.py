"""Escolhe o provedor de cada tarefa, aplica o limite diário, registra o uso e lê o JSON da resposta."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import db
from .provedores import CLASSES, ErroProvedor, Provedor

log = logging.getLogger("radar")


class SemProvedor(RuntimeError):
    """Nenhum provedor disponível para a tarefa (sem chave, limite do dia atingido ou todos falharam)."""


@dataclass
class Resultado:
    dados: dict[str, Any]
    provedor: str
    modelo: str


def extrair_json(texto: str) -> dict[str, Any]:
    """Lê o primeiro objeto JSON do texto, tolerando cercas ```json e texto em volta."""
    texto = (texto or "").strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto)
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError:
        inicio, fim = texto.find("{"), texto.rfind("}")
        if inicio < 0 or fim <= inicio:
            raise ValueError("resposta sem JSON") from None
        dados = json.loads(texto[inicio : fim + 1])
    if not isinstance(dados, dict):
        raise ValueError("JSON não é um objeto")
    return dados


class ServicoIA:
    def __init__(
        self,
        config: dict[str, Any],
        caminho: Path | None = None,
        provedores: dict[str, Provedor] | None = None,
    ) -> None:
        self.config = config["ia"]
        self.caminho = caminho
        self.provedores = provedores if provedores is not None else {n: c() for n, c in CLASSES.items()}

    # ---------- disponibilidade ----------

    def configurados(self) -> list[str]:
        return [n for n, p in self.provedores.items() if p.configurado]

    def candidatos(self, tarefa: str, excluir: set[str] | None = None) -> list[str]:
        ordem = self.config["tarefas"].get(tarefa, {}).get("provedores") or []
        excluir = excluir or set()
        with db.conectar(self.caminho) as conexao:
            usados = db.chamadas_ia_hoje(conexao)
        disponiveis = []
        for nome in ordem:
            provedor = self.provedores.get(nome)
            if nome in excluir or provedor is None or not provedor.configurado:
                continue
            limite = int(self.config["provedores"].get(nome, {}).get("limite_chamadas_dia") or 0)
            if limite and usados.get(nome, 0) >= limite:
                continue
            disponiveis.append(nome)
        return disponiveis

    def disponivel(self, tarefa: str, excluir: set[str] | None = None) -> bool:
        return bool(self.candidatos(tarefa, excluir))

    # ---------- chamada ----------

    def gerar_json(
        self,
        tarefa: str,
        sistema: str,
        usuario: str,
        max_tokens: int = 2000,
        excluir: set[str] | None = None,
    ) -> Resultado:
        nivel = self.config["tarefas"].get(tarefa, {}).get("modelo", "rapido")
        erros: list[str] = []
        for nome in self.candidatos(tarefa, excluir):
            modelo = self.config["provedores"][nome][f"modelo_{nivel}"]
            try:
                resposta = self.provedores[nome].gerar(modelo, sistema, usuario, max_tokens, json=True)
                dados = extrair_json(resposta.texto)
            except (ErroProvedor, ValueError) as erro:
                erros.append(f"{nome}: {erro}")
                log.warning("IA %s falhou em %s: %s", nome, tarefa, erro)
                with db.conectar(self.caminho) as conexao:
                    db.registrar_uso_ia(conexao, nome, modelo, tarefa, 0, 0, str(erro)[:300])
                continue
            with db.conectar(self.caminho) as conexao:
                db.registrar_uso_ia(conexao, nome, modelo, tarefa, resposta.tokens_entrada, resposta.tokens_saida)
            return Resultado(dados, nome, modelo)
        if not erros:
            raise SemProvedor(
                f"Nenhum provedor disponível para '{tarefa}'. Confira as chaves no arquivo .env "
                "e o limite diário na tela Ajustes."
            )
        raise SemProvedor("Todos os provedores falharam: " + " | ".join(erros))
