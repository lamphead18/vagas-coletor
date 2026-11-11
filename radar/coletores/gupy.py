"""Coletor da Gupy pelo endereço que o próprio portal usa na busca (sem login).

Endpoint: https://portal.gupy.io/api/job-search/jobs?jobName=<termo>&offset=<n>&limit=10
A Gupy desligou o endereço antigo (portal.api.gupy.io/api/v1/jobs) em outubro de 2026.
Não é uma API oficial documentada: se a Gupy mudar de novo, este é o único arquivo a ajustar.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import requests

from ..modelos import VagaColetada

URL_API = "https://portal.gupy.io/api/job-search/jobs"
POR_PAGINA = 10
CABECALHOS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RadarDeVagas/1.0 (uso pessoal)",
    "Accept": "application/json",
    "Referer": "https://portal.gupy.io/",
}

REGIMES = {
    "vacancy_type_effective": "CLT",
    "vacancy_legal_entity": "PJ",
    "vacancy_type_internship": "Estágio",
    "vacancy_type_apprentice": "Aprendiz",
    "vacancy_type_temporary": "Temporário",
    "vacancy_type_trainee": "Trainee",
    "vacancy_type_freelancer": "Freelancer",
    "vacancy_type_autonomous": "Autônomo",
    "vacancy_type_associate": "Associado",
    "vacancy_type_talent_pool": "Banco de talentos",
}

MODELOS = {"remote": "remoto", "hybrid": "hibrido", "on-site": "presencial", "onsite": "presencial"}


def converter(item: dict[str, Any]) -> VagaColetada | None:
    """Converte um item da API da Gupy para o formato comum."""
    vaga_id = item.get("id")
    titulo = (item.get("name") or "").strip()
    if vaga_id is None or vaga_id == "" or not titulo:
        return None
    modelo = MODELOS.get(str(item.get("workplaceType") or "").lower())
    if modelo is None and item.get("isRemoteWork"):
        modelo = "remoto"
    publicada = item.get("publishedDate")
    return VagaColetada(
        fonte="gupy",
        id_externo=str(vaga_id),
        titulo=titulo,
        empresa=(item.get("careerPageName") or "").strip() or None,
        url=item.get("jobUrl"),
        cidade=(item.get("city") or "").strip() or None,
        estado_uf=(item.get("state") or "").strip() or None,
        modelo=modelo,
        regime=REGIMES.get(str(item.get("type") or "")),
        descricao=item.get("description"),
        publicada_em=str(publicada)[:19] if publicada else None,
    )


def coletar(
    config: dict[str, Any],
    sessao: requests.Session | None = None,
    dormir: Callable[[float], None] = time.sleep,
) -> list[VagaColetada]:
    opcoes = config["fontes"]["gupy"]
    max_paginas = int(opcoes.get("max_paginas") or 5)
    sessao = sessao or requests.Session()
    vagas: dict[str, VagaColetada] = {}

    for termo in config["buscas"]:
        for pagina in range(max_paginas):
            resposta = sessao.get(
                URL_API,
                params={"jobName": termo, "offset": pagina * POR_PAGINA, "limit": POR_PAGINA},
                headers=CABECALHOS,
                timeout=20,
            )
            resposta.raise_for_status()
            corpo = resposta.json()
            itens = corpo.get("data") or []
            for item in itens:
                vaga = converter(item)
                if vaga:
                    vagas[vaga.id_externo] = vaga
            total = (corpo.get("pagination") or {}).get("total")
            fim = len(itens) < POR_PAGINA or (total is not None and (pagina + 1) * POR_PAGINA >= total)
            if fim:
                break
            dormir(0.7)  # educação com o servidor
    return list(vagas.values())
