import math

import pandas as pd
import pytest

from radar.coletores import gupy, jobspy_coletor

ITEM_GUPY = {
    "id": 123,
    "name": "Analista de Dados Pleno",
    "careerPageName": "Empresa X",
    "jobUrl": "https://empresax.gupy.io/job/abc",
    "city": "São Paulo",
    "state": "São Paulo",
    "workplaceType": "hybrid",
    "type": "vacancy_type_effective",
    "publishedDate": "2026-11-09T12:30:00.000Z",
    "description": "<p>Descrição</p>",
}


def test_gupy_converte_campos():
    vaga = gupy.converter(ITEM_GUPY)
    assert vaga.fonte == "gupy" and vaga.id_externo == "123"
    assert vaga.empresa == "Empresa X" and vaga.modelo == "hibrido" and vaga.regime == "CLT"
    assert vaga.publicada_em == "2026-11-09T12:30:00"


def test_gupy_remoto_pelo_flag_antigo():
    item = dict(ITEM_GUPY, workplaceType=None, isRemoteWork=True)
    assert gupy.converter(item).modelo == "remoto"


def test_gupy_ignora_item_sem_titulo():
    assert gupy.converter({"id": 1, "name": ""}) is None


class SessaoFalsa:
    """Simula a API: 23 vagas no total, 10 por página."""

    def __init__(self):
        self.chamadas = []

    def get(self, url, params, headers, timeout):
        self.chamadas.append(params)
        inicio = params["offset"]
        itens = [dict(ITEM_GUPY, id=i) for i in range(inicio, min(inicio + 10, 23))]
        resposta = type("R", (), {})()
        resposta.raise_for_status = lambda: None
        resposta.json = lambda: {"data": itens, "pagination": {"total": 23}}
        return resposta


def test_gupy_pagina_ate_acabar(config):
    sessao = SessaoFalsa()
    vagas = gupy.coletar(config, sessao=sessao, dormir=lambda s: None)
    assert len(vagas) == 23
    assert [c["offset"] for c in sessao.chamadas] == [0, 10, 20]


def test_gupy_respeita_max_paginas(config):
    config["fontes"]["gupy"]["max_paginas"] = 1
    assert len(gupy.coletar(config, sessao=SessaoFalsa(), dormir=lambda s: None)) == 10


def scrape_falso(**kwargs):
    site = kwargs["site_name"][0]
    if site == "glassdoor":
        raise RuntimeError("bloqueado")
    return pd.DataFrame([
        {"id": f"{site}-1", "site": site, "title": "Engenheiro de Dados", "company": "Acme",
         "job_url": f"https://{site}.com/1", "job_url_direct": math.nan,
         "location": "Curitiba, PR, BR", "is_remote": False, "job_type": "fulltime",
         "date_posted": "2026-11-08", "description": "texto"},
        {"id": f"{site}-2", "site": site, "title": math.nan, "job_url": "x"},
    ])


def test_jobspy_converte_e_ignora_site_com_erro(config):
    config["fontes"]["jobspy"]["sites"] = ["indeed", "glassdoor", "linkedin"]
    vagas = jobspy_coletor.coletar(config, scrape_jobs=scrape_falso)
    assert sorted(v.fonte for v in vagas) == ["indeed", "linkedin"]
    vaga = vagas[0]
    assert vaga.cidade == "Curitiba" and vaga.estado_uf == "PR"
    assert vaga.url.startswith("https://") and vaga.regime == "Tempo integral"


def test_jobspy_todos_falhando_vira_erro(config):
    config["fontes"]["jobspy"]["sites"] = ["glassdoor"]
    with pytest.raises(RuntimeError, match="bloqueado"):
        jobspy_coletor.coletar(config, scrape_jobs=scrape_falso)
