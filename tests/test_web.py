import pytest

pytest.importorskip("httpx")  # o TestClient do Starlette precisa do httpx (requirements-dev.txt)

from starlette.testclient import TestClient  # noqa: E402

from radar import pipeline  # noqa: E402
from radar.modelos import VagaColetada  # noqa: E402


@pytest.fixture
def cliente(banco, config, monkeypatch):
    monkeypatch.setenv("RADAR_SEM_AGENDADOR", "1")
    pipeline.executar(config, coletores={"gupy": lambda cfg: [
        VagaColetada("gupy", "1", "Analista de Dados", "Acme", "https://acme.gupy.io/job/1", modelo="remoto"),
    ]}, caminho=banco)
    from radar.web.app import app
    with TestClient(app) as c:
        yield c


def test_paginas_abrem(cliente):
    for caminho in ["/", "/vagas", "/vagas/1", "/candidaturas", "/candidaturas/nova"]:
        assert cliente.get(caminho).status_code == 200, caminho


def test_me_candidatei_cria_cartao(cliente):
    resposta = cliente.post("/vagas/1/acao", data={"acao": "candidatei", "voltar": "/vagas"})
    assert resposta.status_code == 200
    quadro = cliente.get("/candidaturas").text
    assert "Analista de Dados" in quadro


def test_adicionar_sem_cargo_mostra_erro(cliente):
    resposta = cliente.post("/candidaturas/nova", data={"titulo": ""})
    assert "Informe o cargo" in resposta.text


def test_voltar_externo_e_ignorado(cliente):
    resposta = cliente.post("/vagas/1/acao", data={"acao": "descartar", "voltar": "//malicioso.com"},
                            follow_redirects=False)
    assert resposta.headers["location"].startswith("/vagas/1")
