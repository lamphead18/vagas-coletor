from datetime import date

from radar import filtros
from radar.normalizacao import chave_dedup, contem_termo, normalizar_empresa


def test_mesma_vaga_em_fontes_diferentes_tem_mesma_chave():
    a = chave_dedup("Itaú Unibanco S.A.", "Analista de Dados Pleno", "São Paulo", "presencial")
    b = chave_dedup("Itau Unibanco", "analista de dados - pleno", "Sao Paulo", "presencial")
    assert a == b


def test_vaga_remota_ignora_cidade_na_chave():
    a = chave_dedup("Empresa X", "Engenheiro de Dados", "São Paulo", "remoto")
    b = chave_dedup("Empresa X", "Engenheiro de Dados", None, "remoto")
    assert a == b


def test_senioridades_diferentes_nao_se_misturam():
    assert chave_dedup("X", "Analista Pleno", "", None) != chave_dedup("X", "Analista Sênior", "", None)


def test_normalizar_empresa_remove_sufixo_legal():
    assert normalizar_empresa("Acme Ltda.") == "acme"


def test_contem_termo_compara_sem_acentos_e_palavra_inteira():
    assert contem_termo("Estagiário de Dados", ["estagiario"]) == "estagiario"
    assert contem_termo("Engenheira de Dados", ["engenheiro"]) is None


FILTROS = {
    "titulo_deve_conter": ["dados"],
    "titulo_nao_pode_conter": ["estágio"],
    "modelos": ["remoto", "hibrido"],
    "cidades": ["São Paulo"],
    "idade_max_dias": 10,
    "empresas_bloqueadas": ["Empresa Chata"],
}
HOJE = date(2026, 11, 11)


def avaliar(**campos):
    vaga = {"titulo": "Analista de Dados", "empresa": "Boa", "modelo": "remoto",
            "cidade": None, "publicada_em": "2026-11-10"}
    vaga.update(campos)
    return filtros.avaliar(vaga, FILTROS, hoje=HOJE)


def test_vaga_que_atende_tudo_passa():
    assert avaliar() == (True, None)


def test_cada_regra_explica_o_motivo():
    assert avaliar(empresa="Empresa Chata Ltda")[1] == "empresa bloqueada"
    assert "estágio" in avaliar(titulo="Estágio em Dados")[1]
    assert avaliar(titulo="Analista Financeiro")[1] == "título sem nenhum termo obrigatório"
    assert avaliar(modelo="presencial")[1] == "modelo presencial"
    assert avaliar(modelo="hibrido", cidade="Curitiba")[1] == "cidade Curitiba"
    assert avaliar(publicada_em="2026-10-01")[1] == "publicada há 41 dias"


def test_campos_desconhecidos_nao_eliminam():
    assert avaliar(modelo=None, publicada_em=None)[0] is True
