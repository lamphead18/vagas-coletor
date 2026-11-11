import pytest

from radar import config as configuracao
from radar import db


@pytest.fixture
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "teste.db"
    monkeypatch.setattr(db, "CAMINHO_BANCO", caminho)
    db.iniciar(caminho)
    return caminho


@pytest.fixture
def config():
    cfg = configuracao.carregar(configuracao.CAMINHO_EXEMPLO)
    cfg["buscas"] = ["analista de dados"]
    return cfg
