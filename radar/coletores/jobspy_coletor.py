"""Coletor de Indeed, Glassdoor e LinkedIn pela biblioteca JobSpy (sem login).

O LinkedIn bloqueia quem pede muitas páginas, então o número de resultados fica baixo.
Se o pacote python-jobspy não estiver instalado, este coletor é pulado com um aviso.
"""

from __future__ import annotations

import math
from typing import Any

from ..modelos import VagaColetada

MODELOS_JOBSPY = {"remote": "remoto", "hybrid": "hibrido", "onsite": "presencial"}
REGIMES_JOBSPY = {"fulltime": "Tempo integral", "parttime": "Meio período",
                  "internship": "Estágio", "contract": "Contrato"}


class JobSpyAusente(RuntimeError):
    pass


def _texto(valor: Any) -> str | None:
    if valor is None:
        return None
    if isinstance(valor, float) and math.isnan(valor):
        return None
    texto = str(valor).strip()
    return texto or None


def _cidade_estado(local: str | None) -> tuple[str | None, str | None]:
    # JobSpy costuma devolver "Cidade, UF, BR" ou "Cidade, Estado".
    if not local:
        return None, None
    partes = [p.strip() for p in local.split(",") if p.strip()]
    partes = [p for p in partes if p.upper() not in {"BR", "BRAZIL", "BRASIL"}]
    if not partes:
        return None, None
    return partes[0], (partes[1] if len(partes) > 1 else None)


def converter(linha: dict[str, Any]) -> VagaColetada | None:
    titulo = _texto(linha.get("title"))
    url = _texto(linha.get("job_url"))
    if not titulo or not url:
        return None
    site = _texto(linha.get("site")) or "jobspy"
    cidade, uf = _cidade_estado(_texto(linha.get("location")))
    modelo = MODELOS_JOBSPY.get((_texto(linha.get("work_from_home_type")) or "").lower())
    if modelo is None and linha.get("is_remote") is True:
        modelo = "remoto"
    tipo = (_texto(linha.get("job_type")) or "").split(",")[0].strip().lower()
    publicada = linha.get("date_posted")
    return VagaColetada(
        fonte=site,
        id_externo=_texto(linha.get("id")) or url,
        titulo=titulo,
        empresa=_texto(linha.get("company")),
        url=_texto(linha.get("job_url_direct")) or url,
        cidade=cidade,
        estado_uf=uf,
        modelo=modelo,
        regime=REGIMES_JOBSPY.get(tipo),
        descricao=_texto(linha.get("description")),
        publicada_em=str(publicada)[:10] if _texto(publicada) else None,
    )


def coletar(config: dict[str, Any], scrape_jobs: Any = None) -> list[VagaColetada]:
    opcoes = config["fontes"]["jobspy"]
    if scrape_jobs is None:
        try:
            from jobspy import scrape_jobs  # type: ignore[no-redef]
        except ImportError as erro:
            raise JobSpyAusente(
                "Pacote python-jobspy não instalado. Rode o reinstalar.bat (veja o README)."
            ) from erro

    vagas: dict[tuple[str, str], VagaColetada] = {}
    erros: list[str] = []
    for termo in config["buscas"]:
        for site in opcoes.get("sites") or []:
            try:
                tabela = scrape_jobs(
                    site_name=[site],
                    search_term=termo,
                    location=opcoes.get("local") or "Brasil",
                    country_indeed=opcoes.get("pais_indeed") or "Brazil",
                    results_wanted=int(opcoes.get("resultados_por_site") or 25),
                    hours_old=int(opcoes.get("horas") or 72),
                    description_format="markdown",
                    verbose=0,
                )
            except Exception as erro:  # um site falhar não pode derrubar os outros
                erros.append(f"{site}: {erro}")
                continue
            for linha in tabela.to_dict(orient="records"):
                vaga = converter(linha)
                if vaga:
                    vagas[(vaga.fonte, vaga.id_externo)] = vaga
    if erros and not vagas:
        raise RuntimeError("; ".join(erros))
    return list(vagas.values())
