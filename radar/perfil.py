"""Leitura do perfil mestre (perfil.yaml) e utilidades para os prompts e o validador."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .config import RAIZ
from .normalizacao import normalizar

CAMINHO_PERFIL = RAIZ / "perfil.yaml"


class PerfilAusente(RuntimeError):
    pass


def carregar(caminho: Path | None = None) -> dict[str, Any]:
    caminho = caminho or CAMINHO_PERFIL
    if not caminho.exists():
        raise PerfilAusente(
            "Arquivo perfil.yaml não encontrado na pasta do projeto. Coloque-o ao lado do config.yaml."
        )
    with open(caminho, encoding="utf-8") as arquivo:
        dados = yaml.safe_load(arquivo) or {}
    dados.setdefault("experiencias", [])
    dados.setdefault("projetos", [])
    dados.setdefault("skills", {})
    dados.setdefault("objetivo", {})
    return dados


def existe(caminho: Path | None = None) -> bool:
    return (caminho or CAMINHO_PERFIL).exists()


def todas_skills(perfil: dict[str, Any]) -> list[str]:
    skills: list[str] = []
    for grupo in ("principal", "secundaria", "adicional"):
        skills += [str(s) for s in (perfil["skills"].get(grupo) or [])]
    return skills


def bullets_por_id(perfil: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """id do bullet → {texto, dono (id da experiência/projeto), tipo}."""
    indice: dict[str, dict[str, Any]] = {}
    for tipo in ("experiencias", "projetos"):
        for item in perfil[tipo]:
            for bullet in item.get("bullets") or []:
                indice[str(bullet["id"])] = {"texto": bullet["texto"], "dono": str(item["id"]), "tipo": tipo}
    return indice


def texto_completo(perfil: dict[str, Any]) -> str:
    """Todo o conteúdo factual do perfil, para checar se um termo existe nele."""
    partes = [perfil.get("resumo") or "", " ".join(todas_skills(perfil))]
    for tipo in ("experiencias", "projetos"):
        for item in perfil[tipo]:
            partes.append(" ".join(str(s) for s in item.get("stack") or []))
            for bullet in item.get("bullets") or []:
                partes.append(bullet["texto"])
                partes.append(" ".join(str(t) for t in bullet.get("tags") or []))
    return normalizar(" ".join(partes))


def _periodo(item: dict[str, Any]) -> str:
    return f"{item.get('inicio', '')} a {item.get('fim', '')}"


def para_prompt(perfil: dict[str, Any], com_ids: bool = False) -> str:
    """Perfil em texto compacto para enviar ao modelo."""
    objetivo = perfil["objetivo"]
    linhas = [
        f"Cargos-alvo: {', '.join(objetivo.get('cargos_alvo') or [])}",
        f"Senioridade-alvo: {', '.join(objetivo.get('senioridade_alvo') or [])}",
        f"Modelos aceitos: {', '.join(objetivo.get('modelos_aceitos') or [])}",
        f"Regimes aceitos: {', '.join(objetivo.get('regimes_aceitos') or [])}",
        f"Cidade: {(perfil.get('pessoal') or {}).get('cidade') or 'não informada'}",
        f"Interesses: {', '.join(objetivo.get('interesses') or [])}",
        "",
        f"Resumo: {' '.join(str(perfil.get('resumo') or '').split())}",
        "",
        f"Skills principais: {', '.join(perfil['skills'].get('principal') or [])}",
        f"Skills secundárias: {', '.join(perfil['skills'].get('secundaria') or [])}",
        f"Conhecimentos adicionais: {', '.join(perfil['skills'].get('adicional') or [])}",
    ]
    idiomas = perfil.get("idiomas") or []
    if idiomas:
        linhas.append("Idiomas: " + ", ".join(f"{i.get('idioma')} ({i.get('nivel')})" for i in idiomas))
    else:
        linhas.append("Idiomas: não informados")
    linhas += ["", "EXPERIÊNCIAS:"]
    for item in perfil["experiencias"]:
        cabecalho = f"{item['cargo']} — {item['empresa']} ({_periodo(item)})"
        linhas.append(f"[{item['id']}] {cabecalho}" if com_ids else f"- {cabecalho}")
        for bullet in item.get("bullets") or []:
            linhas.append(f"  [{bullet['id']}] {bullet['texto']}" if com_ids else f"  • {bullet['texto']}")
    linhas += ["", "PROJETOS:"]
    for item in perfil["projetos"]:
        stack = ", ".join(item.get("stack") or [])
        linhas.append(f"[{item['id']}] {item['nome']} (stack: {stack})" if com_ids else f"- {item['nome']} ({stack})")
        for bullet in item.get("bullets") or []:
            linhas.append(f"  [{bullet['id']}] {bullet['texto']}" if com_ids else f"  • {bullet['texto']}")
    formacao = perfil.get("formacao") or []
    if formacao:
        linhas += ["", "FORMAÇÃO:"] + [
            f"- {f.get('curso')} — {f.get('instituicao')} ({_periodo(f)})" for f in formacao
        ]
    return "\n".join(linhas)
