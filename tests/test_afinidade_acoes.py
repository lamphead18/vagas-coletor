import json
from datetime import date

from docx import Document

from radar import acoes, afinidade, db, perfil, pipeline, sugestoes
from radar.config import RAIZ
from radar.ia.servico import ServicoIA
from radar.modelos import VagaColetada
from tests.test_ia import ProvedorFalso

PERFIL = perfil.carregar(RAIZ / "perfil.yaml") if (RAIZ / "perfil.yaml").exists() else None


def perfil_teste():
    return {
        "pessoal": {"nome": "Fulano de Tal", "email": "f@x.com"},
        "objetivo": {"cargos_alvo": ["Desenvolvedor Backend", "Desenvolvedor Full Stack"]},
        "resumo": "Dev backend com Node.js.",
        "skills": {"principal": ["Node.js", "TypeScript", "PostgreSQL"], "secundaria": ["Docker"], "adicional": []},
        "experiencias": [
            {"id": "a", "empresa": "Acme", "cargo": "Dev", "inicio": "2023-02", "fim": "atual", "bullets": [
                {"id": "a-1", "texto": "Backend em Node.js e PostgreSQL com autenticação JWT."},
                {"id": "a-2", "texto": "Pipelines de CI/CD com Docker."}]},
            {"id": "b", "empresa": "Beta", "cargo": "Estagiário", "inicio": "2022-01", "fim": "2022-12", "bullets": [
                {"id": "b-1", "texto": "Telas em React."}]},
        ],
        "projetos": [{"id": "p", "nome": "Projeto X", "stack": ["Node.js"], "bullets": [
            {"id": "p-1", "texto": "API REST em Node.js."}]}],
        "formacao": [{"curso": "Ciência da Computação", "instituicao": "Uni",
                      "inicio": "2022-01", "fim": "em andamento"}],
    }


def semear(banco, config, n=3):
    vagas = [VagaColetada("gupy", str(i), f"Desenvolvedor Backend {i}", f"Empresa {i}", f"https://e{i}.gupy.io/job/{i}",
                          modelo="remoto", descricao="<p>Node.js, PostgreSQL, AWS</p>",
                          publicada_em=date.today().isoformat()) for i in range(n)]
    pipeline.executar(config, coletores={"gupy": lambda cfg: vagas}, caminho=banco)


def test_processar_da_nota_e_segunda_opiniao_de_outro_provedor(banco, config):
    semear(banco, config)
    gemini = ProvedorFalso("gemini", [{"score": 90, "resumo": "ótima", "palavras_chave": ["Node.js", "AWS"]},
                                      {"score": 40}, {"score": "70.4"}])
    openai = ProvedorFalso("openai", [{"score": 60, "resumo": "ok"}, {"score": 72}])
    servico = ServicoIA(config, banco, {"gemini": gemini, "openai": openai})
    resumo = afinidade.processar(config, servico, perfil_teste(), banco, pausa=0)
    assert resumo == {"avaliadas": 3, "segunda_opiniao": 2, "erros": 0}
    with db.conectar(banco) as conexao:
        vagas = {v["titulo"]: v for v in db.listar_vagas(conexao)}
    assert sorted(v["score"] for v in vagas.values()) == [40, 70, 90]
    melhor = max(vagas.values(), key=lambda v: v["score"])
    assert melhor["score2_provedor"] == "openai" and melhor["score2"] == 60
    assert afinidade.divergente(melhor, config)  # 90 vs 60


def test_plano_do_dia_respeita_o_tempo(banco, config):
    semear(banco, config, n=4)
    servico = ServicoIA(config, banco, {"gemini": ProvedorFalso("gemini", [{"score": 80}] * 4)})
    config["afinidade"]["segunda_opiniao_top"] = 0
    afinidade.processar(config, servico, perfil_teste(), banco, pausa=0)
    plano = afinidade.plano_do_dia(config, 45, banco)  # gupy = 20 min cada
    assert len(plano["cabe"]) == 2 and plano["usado"] == 40 and len(plano["depois"]) == 2


def test_montar_cv_valida_contra_o_perfil():
    proposta = {
        "titulo": "Arquiteto de Soluções",
        "resumo": "Resumo.",
        "skills": ["Node.js", "Kubernetes", "postgresql"],
        "experiencias": [{"id": "a", "bullets": [
            {"id": "a-1", "texto": "Desenvolvi backend em Node.js e PostgreSQL com JWT."},
            {"id": "a-2", "texto": "Automatizei deploy na AWS com Docker, reduzindo 50% do tempo."},
            {"id": "inventado", "texto": "Liderei time de 10 pessoas."},
            {"id": "b-1", "texto": "Trecho da outra empresa."}]}],
        "projetos": [{"id": "p", "bullets": [{"id": "p-1", "texto": "API REST em Node.js."}]}],
    }
    cv = acoes.montar_cv(perfil_teste(), proposta, ["Node.js", "PostgreSQL", "Docker", "AWS"])
    assert cv["titulo"] == "Desenvolvedor Backend"  # título fora dos cargos-alvo é trocado
    assert cv["skills"] == ["Node.js", "PostgreSQL"]  # Kubernetes não está no perfil
    acme, beta = cv["experiencias"]
    assert acme["bullets"][0].startswith("Desenvolvi backend")
    assert acme["bullets"][1] == "Pipelines de CI/CD com Docker."  # AWS e 50% inventados: volta ao original
    assert len(acme["bullets"]) == 2  # id inventado e bullet de outra empresa caem
    assert beta["empresa"] == "Beta" and beta["bullets"] == ["Telas em React."]  # experiência omitida volta
    assert beta["periodo"] == "Jan/2022 – Dez/2022"
    assert cv["cobertura"]["percentual"] == 75 and cv["cobertura"]["faltando_no_perfil"] == ["AWS"]
    assert len(cv["avisos"]) >= 4


def test_gerar_cv_cria_docx_e_pdf(banco, config, tmp_path):
    semear(banco, config, n=1)
    proposta = {"titulo": "Desenvolvedor Backend", "resumo": "Backend Node.js — PostgreSQL & Docker.",
                "skills": ["Node.js"],
                "experiencias": [{"id": "a", "bullets": [{"id": "a-1", "texto": "API <Node.js>."}]}],
                "projetos": []}
    servico = ServicoIA(config, banco, {"anthropic": ProvedorFalso("anthropic", [proposta])})
    with db.conectar(banco) as conexao:
        vaga_id = db.listar_vagas(conexao)[0]["id"]
    versao_id = acoes.gerar_cv(config, vaga_id, servico, perfil_teste(), banco, tmp_path)
    with db.conectar(banco) as conexao:
        versao = db.obter_versao_cv(conexao, versao_id)
    texto_docx = "\n".join(p.text for p in Document(versao["arquivo_docx"]).paragraphs)
    assert "Fulano de Tal" in texto_docx and "Experiência Profissional" in texto_docx and "API <Node.js>." in texto_docx
    pdf = open(versao["arquivo_pdf"], "rb").read()
    assert pdf.startswith(b"%PDF") and len(pdf) > 1500


def test_gerar_texto_salva_geracao(banco, config):
    semear(banco, config, n=1)
    servico = ServicoIA(config, banco, {"anthropic": ProvedorFalso("anthropic", [{"resposta": "Trabalhei com Node."}])})
    with db.conectar(banco) as conexao:
        vaga_id = db.listar_vagas(conexao)[0]["id"]
    acoes.gerar_texto(config, vaga_id, "resposta", "Fale de Node", servico, perfil_teste(), banco)
    with db.conectar(banco) as conexao:
        g = db.geracoes(conexao, vaga_id)[0]
    assert g["tipo"] == "resposta" and json.loads(g["conteudo"])["resposta"] == "Trabalhei com Node."


def test_sugestoes_de_regra_a_partir_do_feedback(banco, config):
    titulos = ["Desenvolvedor PHP Pleno", "Dev PHP Laravel", "Programador PHP", "Desenvolvedor Node.js"]
    pipeline.executar(config, coletores={"gupy": lambda cfg: [
        VagaColetada("gupy", str(i), t, f"E{i}", f"https://x/{i}") for i, t in enumerate(titulos)]}, caminho=banco)
    with db.conectar(banco) as conexao:
        ids = {v["titulo"]: v["id"] for v in db.listar_vagas(conexao)}
        for t in titulos[:3]:
            db.registrar_feedback(conexao, ids[t], "menos", "stack")
        db.registrar_feedback(conexao, ids["Desenvolvedor Node.js"], "mais", None)
        termos = [s["termo"] for s in sugestoes.sugerir(conexao)]
        assert termos == ["php"]
        db.adicionar_regra(conexao, "titulo_nao_pode_conter", "php")
        assert sugestoes.sugerir(conexao) == []
    pipeline.refiltrar_tudo(config, banco)
    with db.conectar(banco) as conexao:
        assert [v["titulo"] for v in db.listar_vagas(conexao)] == ["Desenvolvedor Node.js"]


def test_banco_da_fase_1_ganha_colunas_novas(tmp_path):
    import sqlite3
    caminho = tmp_path / "antigo.db"
    antigo = sqlite3.connect(caminho)
    antigo.executescript("""CREATE TABLE vaga (id INTEGER PRIMARY KEY, titulo TEXT NOT NULL, empresa_id INTEGER,
        cidade TEXT, estado_uf TEXT, modelo TEXT, regime TEXT, descricao TEXT, url TEXT, publicada_em TEXT,
        coletada_em TEXT NOT NULL, chave_dedup TEXT NOT NULL UNIQUE, estado TEXT NOT NULL DEFAULT 'nova',
        passou_filtro INTEGER NOT NULL DEFAULT 1, motivo_filtro TEXT);
        INSERT INTO vaga (titulo, coletada_em, chave_dedup) VALUES ('Antiga', '2026-11-10', 'k');""")
    antigo.close()
    db.iniciar(caminho)
    with db.conectar(caminho) as conexao:
        colunas = {c["name"] for c in conexao.execute("PRAGMA table_info(vaga)")}
        assert {"score", "score2", "score_dados"} <= colunas
        assert conexao.execute("SELECT titulo FROM vaga").fetchone()[0] == "Antiga"


def test_perfil_real_do_projeto_carrega():
    if PERFIL is None:
        return
    assert len(perfil.bullets_por_id(PERFIL)) > 10
    assert "[mangalab-3]" in perfil.para_prompt(PERFIL, com_ids=True)
