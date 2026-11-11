from radar import db, pipeline
from radar.modelos import VagaColetada


def vaga(fonte, id_externo, titulo="Analista de Dados", empresa="Acme Ltda", **extra):
    return VagaColetada(fonte=fonte, id_externo=id_externo, titulo=titulo, empresa=empresa,
                        url=f"https://{fonte}/{id_externo}", modelo="remoto", **extra)


def test_mesma_vaga_em_duas_fontes_vira_uma(banco, config):
    coletores = {
        "gupy": lambda cfg: [vaga("gupy", "1", descricao="curta")],
        "jobspy": lambda cfg: [vaga("indeed", "9", empresa="ACME", descricao="descrição bem mais longa")],
    }
    resumo = pipeline.executar(config, coletores=coletores, caminho=banco)
    assert resumo == {"gupy": {"total": 1, "novas": 1}, "jobspy": {"total": 1, "novas": 0}}
    with db.conectar(banco) as conexao:
        vagas = db.listar_vagas(conexao)
        assert len(vagas) == 1
        assert set(vagas[0]["fontes"].split(",")) == {"gupy", "indeed"}
        assert vagas[0]["descricao"] == "descrição bem mais longa"


def test_coletar_de_novo_nao_duplica(banco, config):
    coletores = {"gupy": lambda cfg: [vaga("gupy", "1")]}
    pipeline.executar(config, coletores=coletores, caminho=banco)
    resumo = pipeline.executar(config, coletores=coletores, caminho=banco)
    assert resumo["gupy"]["novas"] == 0


def test_fonte_com_erro_nao_derruba_as_outras(banco, config):
    def quebra(cfg):
        raise RuntimeError("site fora do ar")
    resumo = pipeline.executar(
        config, coletores={"ruim": quebra, "gupy": lambda cfg: [vaga("gupy", "1")]}, caminho=banco)
    assert resumo["ruim"] == {"erro": "site fora do ar"}
    assert resumo["gupy"]["novas"] == 1
    with db.conectar(banco) as conexao:
        erros = [c["erro"] for c in db.ultimas_coletas(conexao) if c["erro"]]
    assert erros == ["site fora do ar"]


def test_filtro_marca_vaga_e_refiltrar_reavalia(banco, config):
    config["filtros"]["titulo_nao_pode_conter"] = ["estágio"]
    pipeline.executar(config, coletores={"gupy": lambda cfg: [vaga("gupy", "1", titulo="Estágio em Dados")]},
                      caminho=banco)
    with db.conectar(banco) as conexao:
        assert db.listar_vagas(conexao) == []
        filtradas = db.listar_vagas(conexao, mostrar_filtradas=True)
        assert "estágio" in filtradas[0]["motivo_filtro"]
    config["filtros"]["titulo_nao_pode_conter"] = []
    pipeline.refiltrar_tudo(config, caminho=banco)
    with db.conectar(banco) as conexao:
        assert len(db.listar_vagas(conexao)) == 1


def test_fluxo_da_candidatura(banco, config):
    pipeline.executar(config, coletores={"gupy": lambda cfg: [vaga("gupy", "1")]}, caminho=banco)
    with db.conectar(banco) as conexao:
        vaga_id = db.listar_vagas(conexao)[0]["id"]
        cid = db.candidatura_da_vaga(conexao, vaga_id, "salva")
        assert db.obter_candidatura(conexao, cid)["data_candidatura"] is None
        db.mudar_status(conexao, cid, "candidatada")
        db.mudar_status(conexao, cid, "entrevistas")
        c = db.obter_candidatura(conexao, cid)
        assert c["status"] == "entrevistas" and c["data_candidatura"] and c["plataforma"] == "Outro"
        assert db.obter_vaga(conexao, vaga_id)["estado"] == "candidatada"
        # vaga candidatada sai da lista de vagas abertas
        assert db.listar_vagas(conexao) == []
        historico = [e["conteudo"] for e in db.eventos(conexao, cid)]
        assert historico[0] == "Candidatada → Entrevistas"
        assert len(historico) == 3


def test_bloquear_empresa_esconde_vagas_dela(banco, config):
    pipeline.executar(config, coletores={"gupy": lambda cfg: [vaga("gupy", "1"), vaga("gupy", "2", titulo="Outra")]},
                      caminho=banco)
    with db.conectar(banco) as conexao:
        empresa_id = db.listar_vagas(conexao)[0]["empresa_id"]
        db.bloquear_empresa(conexao, empresa_id)
        assert db.listar_vagas(conexao) == []


def test_plataforma_detectada_pelo_link(banco):
    with db.conectar(banco) as conexao:
        cid = db.criar_candidatura(conexao, "Dev", "X", "https://x.gupy.io/job/1", "candidatada")
        assert db.obter_candidatura(conexao, cid)["plataforma"] == "Gupy"


def test_erro_de_conexao_vira_frase_curta(banco, config):
    import requests

    def sem_internet(cfg):
        raise requests.ConnectionError("HTTPSConnectionPool(host=...) Max retries exceeded")
    resumo = pipeline.executar(config, coletores={"gupy": sem_internet}, caminho=banco)
    assert resumo["gupy"]["erro"].startswith("Sem conexão")
