"""Leitura do config.yaml com valores padrão."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

RAIZ = Path(__file__).resolve().parent.parent
CAMINHO_CONFIG = RAIZ / "config.yaml"
CAMINHO_EXEMPLO = RAIZ / "config.example.yaml"
PASTA_DADOS = RAIZ / "dados"

PADRAO: dict[str, Any] = {
    "servidor": {"porta": 8765},
    "coleta": {"intervalo_horas": 6, "coletar_ao_iniciar": True},
    "buscas": [],
    "fontes": {
        "gupy": {"ativo": True, "max_paginas": 5},
        "jobspy": {
            "ativo": True,
            "sites": ["indeed", "glassdoor", "linkedin"],
            "local": "Brasil",
            "pais_indeed": "Brazil",
            "resultados_por_site": 25,
            "horas": 72,
        },
    },
    "filtros": {
        "titulo_deve_conter": [],
        "titulo_nao_pode_conter": [],
        "modelos": [],
        "cidades": [],
        "idade_max_dias": 21,
        "empresas_bloqueadas": [],
    },
    "candidaturas": {"dias_sem_resposta": 14},
    "ia": {
        "provedores": {
            "gemini": {"modelo_rapido": "gemini-3.8-flash", "modelo_forte": "gemini-3.8-flash",
                       "limite_chamadas_dia": 300},
            "openai": {"modelo_rapido": "gpt-6-luna", "modelo_forte": "gpt-6.1-sol", "limite_chamadas_dia": 40},
            "anthropic": {"modelo_rapido": "claude-haiku-5-5", "modelo_forte": "claude-sonnet-5-5",
                          "limite_chamadas_dia": 40},
        },
        "tarefas": {
            "score": {"provedores": ["gemini", "openai", "anthropic"], "modelo": "rapido"},
            "segunda_opiniao": {"provedores": ["openai", "anthropic", "gemini"], "modelo": "forte"},
            "escrita": {"provedores": ["anthropic", "openai", "gemini"], "modelo": "forte"},
        },
    },
    "afinidade": {
        "ativo": True,
        "score_minimo": 60,
        "max_por_rodada": 60,
        "segunda_opiniao_top": 10,
        "divergencia": 20,
        "tempo_disponivel_padrao": 60,
        "esforco_min": {"gupy": 20, "linkedin": 8, "indeed": 10, "glassdoor": 10, "outro": 15},
    },
}


def _mesclar(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    resultado = copy.deepcopy(base)
    for chave, valor in (extra or {}).items():
        if isinstance(valor, dict) and isinstance(resultado.get(chave), dict):
            resultado[chave] = _mesclar(resultado[chave], valor)
        elif valor is not None:
            resultado[chave] = valor
    return resultado


def carregar_env() -> None:
    """Carrega as chaves de API do arquivo .env da pasta do projeto (se existir)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(RAIZ / ".env", override=False)


def carregar(caminho: Path | None = None) -> dict[str, Any]:
    """Lê o config.yaml; se não existir, usa o exemplo; sempre completa com os padrões."""
    carregar_env()
    caminho = caminho or (CAMINHO_CONFIG if CAMINHO_CONFIG.exists() else CAMINHO_EXEMPLO)
    dados: dict[str, Any] = {}
    if caminho.exists():
        with open(caminho, encoding="utf-8") as arquivo:
            dados = yaml.safe_load(arquivo) or {}
    config = _mesclar(PADRAO, dados)
    config["buscas"] = [str(b).strip() for b in config.get("buscas") or [] if str(b).strip()]
    return config
