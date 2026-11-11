"""Transforma os feedbacks "menos disso" em sugestões de regra para o filtro (você aprova ou ignora)."""

from __future__ import annotations

import copy
import sqlite3
from collections import Counter
from typing import Any

from . import db
from .normalizacao import normalizar

TIPOS_REGRA = {
    "titulo_nao_pode_conter": "Título não pode conter",
    "empresa_bloqueada": "Empresa bloqueada",
}
MOTIVOS = [
    ("stack", "Stack ou área diferente"),
    ("senioridade", "Senioridade errada"),
    ("salario", "Salário ou regime"),
    ("local", "Local ou modelo de trabalho"),
    ("empresa", "Não quero esta empresa"),
    ("outro", "Outro motivo"),
]
NOMES_MOTIVOS = dict(MOTIVOS)

PALAVRAS_VAZIAS = set(
    "de da do das dos para com sem em e ou a o as os um uma na no nas nos por pl sr jr pleno junior senior "
    "remoto hibrido presencial vaga vagas pessoa analista desenvolvedor desenvolvedora developer engenheiro "
    "engenheira software sistemas dev time area".split()
)
MINIMO_OCORRENCIAS = 3


def filtros_efetivos(conexao: sqlite3.Connection, filtros: dict[str, Any]) -> dict[str, Any]:
    """Junta os filtros do config.yaml com as regras aprovadas na tela Ajustes."""
    efetivos = copy.deepcopy(filtros)
    for regra in db.regras(conexao):
        if regra["tipo"] == "titulo_nao_pode_conter":
            efetivos.setdefault("titulo_nao_pode_conter", []).append(regra["termo"])
        elif regra["tipo"] == "empresa_bloqueada":
            efetivos.setdefault("empresas_bloqueadas", []).append(regra["termo"])
    return efetivos


def _palavras(titulo: str) -> set[str]:
    return {p for p in normalizar(titulo).split() if len(p) >= 3 and p not in PALAVRAS_VAZIAS and not p.isdigit()}


def sugerir(conexao: sqlite3.Connection) -> list[dict[str, Any]]:
    """Palavras que aparecem em 3+ vagas recusadas e em nenhuma vaga que você quis."""
    negativos = db.feedbacks_recentes(conexao, "menos", 200)
    positivos_titulos = [f["titulo"] for f in db.feedbacks_recentes(conexao, "mais", 200)]
    positivos_titulos += [linha["titulo"] for linha in conexao.execute("SELECT titulo FROM candidatura")]
    protegidas = set().union(*(_palavras(t) for t in positivos_titulos)) if positivos_titulos else set()
    existentes = {(r["tipo"], normalizar(r["termo"])) for r in db.regras(conexao)}

    contagem: Counter[str] = Counter()
    exemplos: dict[str, list[str]] = {}
    for f in negativos:
        if f["motivo"] == "empresa":
            continue
        for palavra in _palavras(f["titulo"]):
            contagem[palavra] += 1
            exemplos.setdefault(palavra, []).append(f["titulo"])

    sugestoes = []
    for palavra, n in contagem.most_common():
        if n < MINIMO_OCORRENCIAS or palavra in protegidas:
            continue
        if ("titulo_nao_pode_conter", palavra) in existentes or ("ignorada", palavra) in existentes:
            continue
        sugestoes.append({"tipo": "titulo_nao_pode_conter", "termo": palavra, "vezes": n,
                          "exemplos": exemplos[palavra][:3]})
    return sugestoes[:10]
