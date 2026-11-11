"""Banco SQLite: schema, conexão e operações."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .config import PASTA_DADOS
from .modelos import VagaColetada
from .normalizacao import chave_dedup, normalizar_empresa

CAMINHO_BANCO = PASTA_DADOS / "radar.db"

# Etapas da candidatura, na ordem do quadro. As três últimas são desfechos "encerrados".
STATUS = [
    ("salva", "Salva"),
    ("candidatada", "Candidatada"),
    ("em_analise", "Em análise"),
    ("teste", "Teste ou case"),
    ("entrevistas", "Entrevistas"),
    ("proposta", "Proposta"),
    ("contratado", "Contratado"),
    ("reprovada", "Reprovada"),
    ("desisti", "Desisti"),
    ("sem_retorno", "Sem retorno"),
]
NOMES_STATUS = dict(STATUS)
STATUS_EM_ANDAMENTO = ["salva", "candidatada", "em_analise", "teste", "entrevistas", "proposta"]
STATUS_ENCERRADOS = ["contratado", "reprovada", "desisti", "sem_retorno"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS empresa (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,
    nome_norm TEXT NOT NULL UNIQUE,
    bloqueada INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS vaga (
    id INTEGER PRIMARY KEY,
    titulo TEXT NOT NULL,
    empresa_id INTEGER REFERENCES empresa(id),
    cidade TEXT,
    estado_uf TEXT,
    modelo TEXT,
    regime TEXT,
    descricao TEXT,
    url TEXT,
    publicada_em TEXT,
    coletada_em TEXT NOT NULL,
    chave_dedup TEXT NOT NULL UNIQUE,
    estado TEXT NOT NULL DEFAULT 'nova',
    passou_filtro INTEGER NOT NULL DEFAULT 1,
    motivo_filtro TEXT
);
CREATE INDEX IF NOT EXISTS idx_vaga_estado ON vaga(estado, passou_filtro);

CREATE TABLE IF NOT EXISTS vaga_fonte (
    id INTEGER PRIMARY KEY,
    vaga_id INTEGER NOT NULL REFERENCES vaga(id) ON DELETE CASCADE,
    fonte TEXT NOT NULL,
    id_externo TEXT NOT NULL,
    url TEXT,
    visto_em TEXT NOT NULL,
    UNIQUE (fonte, id_externo)
);

CREATE TABLE IF NOT EXISTS candidatura (
    id INTEGER PRIMARY KEY,
    vaga_id INTEGER REFERENCES vaga(id),
    titulo TEXT NOT NULL,
    empresa TEXT,
    url TEXT,
    plataforma TEXT,
    status TEXT NOT NULL DEFAULT 'salva',
    data_candidatura TEXT,
    proxima_acao TEXT,
    prazo TEXT,
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evento (
    id INTEGER PRIMARY KEY,
    candidatura_id INTEGER NOT NULL REFERENCES candidatura(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL,
    data TEXT NOT NULL,
    conteudo TEXT
);

CREATE TABLE IF NOT EXISTS uso_ia (
    id INTEGER PRIMARY KEY,
    data TEXT NOT NULL,
    provedor TEXT NOT NULL,
    modelo TEXT,
    tarefa TEXT,
    tokens_entrada INTEGER DEFAULT 0,
    tokens_saida INTEGER DEFAULT 0,
    erro TEXT
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY,
    vaga_id INTEGER NOT NULL REFERENCES vaga(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL,
    motivo TEXT,
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS geracao (
    id INTEGER PRIMARY KEY,
    vaga_id INTEGER NOT NULL REFERENCES vaga(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL,
    entrada TEXT,
    conteudo TEXT NOT NULL,
    provedor TEXT,
    modelo TEXT,
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS versao_cv (
    id INTEGER PRIMARY KEY,
    vaga_id INTEGER NOT NULL REFERENCES vaga(id) ON DELETE CASCADE,
    dados TEXT NOT NULL,
    arquivo_docx TEXT,
    arquivo_pdf TEXT,
    cobertura INTEGER,
    provedor TEXT,
    modelo TEXT,
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS regra (
    id INTEGER PRIMARY KEY,
    tipo TEXT NOT NULL,
    termo TEXT NOT NULL,
    criado_em TEXT NOT NULL,
    UNIQUE (tipo, termo)
);

CREATE TABLE IF NOT EXISTS ajuste (
    chave TEXT PRIMARY KEY,
    valor TEXT
);

CREATE TABLE IF NOT EXISTS coleta (
    id INTEGER PRIMARY KEY,
    fonte TEXT NOT NULL,
    inicio TEXT NOT NULL,
    fim TEXT,
    total INTEGER DEFAULT 0,
    novas INTEGER DEFAULT 0,
    erro TEXT
);
"""


def _novo_id(cursor: sqlite3.Cursor) -> int:
    """Id da linha recém-inserida (sempre existe depois de um INSERT)."""
    if cursor.lastrowid is None:
        raise RuntimeError("INSERT não devolveu id")
    return cursor.lastrowid


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def conectar(caminho: Path | None = None) -> Iterator[sqlite3.Connection]:
    caminho = caminho or CAMINHO_BANCO
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conexao = sqlite3.connect(caminho, timeout=30)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA foreign_keys = ON")
    conexao.execute("PRAGMA journal_mode = WAL")
    try:
        yield conexao
        conexao.commit()
    finally:
        conexao.close()


COLUNAS_NOVAS = {
    "vaga": {
        "score": "INTEGER",
        "score_dados": "TEXT",
        "score_provedor": "TEXT",
        "score_em": "TEXT",
        "score2": "INTEGER",
        "score2_dados": "TEXT",
        "score2_provedor": "TEXT",
    },
    "candidatura": {"tempo_gasto_min": "INTEGER", "cv_versao_id": "INTEGER"},
}


def _migrar(conexao: sqlite3.Connection) -> None:
    """Adiciona colunas novas em bancos criados por versões anteriores."""
    for tabela, colunas in COLUNAS_NOVAS.items():
        existentes = {linha["name"] for linha in conexao.execute(f"PRAGMA table_info({tabela})")}
        for nome, tipo in colunas.items():
            if nome not in existentes:
                conexao.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}")


def iniciar(caminho: Path | None = None) -> None:
    with conectar(caminho) as conexao:
        conexao.executescript(SCHEMA)
        _migrar(conexao)


# ---------- empresas ----------

def obter_ou_criar_empresa(conexao: sqlite3.Connection, nome: str | None) -> int | None:
    nome = (nome or "").strip()
    if not nome:
        return None
    nome_norm = normalizar_empresa(nome) or nome.lower()
    linha = conexao.execute("SELECT id FROM empresa WHERE nome_norm = ?", (nome_norm,)).fetchone()
    if linha:
        return linha["id"]
    cursor = conexao.execute("INSERT INTO empresa (nome, nome_norm) VALUES (?, ?)", (nome, nome_norm))
    return _novo_id(cursor)


# ---------- vagas ----------

def salvar_vaga(conexao: sqlite3.Connection, vaga: VagaColetada) -> tuple[int, bool]:
    """Grava a vaga ou junta à existente (mesma chave de deduplicação).

    Devolve (id da vaga, True se a vaga é nova).
    """
    momento = agora()
    fonte_existente = conexao.execute(
        "SELECT vaga_id FROM vaga_fonte WHERE fonte = ? AND id_externo = ?",
        (vaga.fonte, vaga.id_externo),
    ).fetchone()
    if fonte_existente:
        conexao.execute(
            "UPDATE vaga_fonte SET visto_em = ? WHERE fonte = ? AND id_externo = ?",
            (momento, vaga.fonte, vaga.id_externo),
        )
        return fonte_existente["vaga_id"], False

    chave = chave_dedup(vaga.empresa, vaga.titulo, vaga.cidade, vaga.modelo)
    existente = conexao.execute("SELECT * FROM vaga WHERE chave_dedup = ?", (chave,)).fetchone()
    nova = existente is None
    if nova:
        empresa_id = obter_ou_criar_empresa(conexao, vaga.empresa)
        cursor = conexao.execute(
            """INSERT INTO vaga (titulo, empresa_id, cidade, estado_uf, modelo, regime, descricao,
                                 url, publicada_em, coletada_em, chave_dedup)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                vaga.titulo, empresa_id, vaga.cidade, vaga.estado_uf, vaga.modelo, vaga.regime,
                vaga.descricao, vaga.url, vaga.publicada_em, momento, chave,
            ),
        )
        vaga_id = _novo_id(cursor)
    else:
        vaga_id = existente["id"]
        # Completa campos vazios com o que a nova fonte trouxe.
        conexao.execute(
            """UPDATE vaga SET
                 descricao = CASE WHEN length(coalesce(descricao, '')) < length(coalesce(?, ''))
                                  THEN ? ELSE descricao END,
                 regime = coalesce(regime, ?),
                 publicada_em = coalesce(publicada_em, ?)
               WHERE id = ?""",
            (vaga.descricao, vaga.descricao, vaga.regime, vaga.publicada_em, vaga_id),
        )
    conexao.execute(
        "INSERT INTO vaga_fonte (vaga_id, fonte, id_externo, url, visto_em) VALUES (?, ?, ?, ?, ?)",
        (vaga_id, vaga.fonte, vaga.id_externo, vaga.url, momento),
    )
    return vaga_id, nova


def marcar_filtro(conexao: sqlite3.Connection, vaga_id: int, passou: bool, motivo: str | None) -> None:
    conexao.execute(
        "UPDATE vaga SET passou_filtro = ?, motivo_filtro = ? WHERE id = ?",
        (1 if passou else 0, motivo, vaga_id),
    )


def listar_vagas(
    conexao: sqlite3.Connection,
    estado: str | None = None,
    mostrar_filtradas: bool = False,
    busca: str | None = None,
    fonte: str | None = None,
    limite: int = 300,
    ordem: str = "score",
) -> list[sqlite3.Row]:
    condicoes, parametros = [], []
    if estado:
        condicoes.append("v.estado = ?")
        parametros.append(estado)
    else:
        condicoes.append("v.estado IN ('nova', 'vista')")
    if not mostrar_filtradas:
        condicoes.append("v.passou_filtro = 1")
    if busca:
        condicoes.append("(v.titulo LIKE ? OR e.nome LIKE ?)")
        parametros += [f"%{busca}%", f"%{busca}%"]
    if fonte:
        condicoes.append("EXISTS (SELECT 1 FROM vaga_fonte f WHERE f.vaga_id = v.id AND f.fonte = ?)")
        parametros.append(fonte)
    where = " AND ".join(condicoes)
    parametros.append(limite)
    recentes = "coalesce(v.publicada_em, v.coletada_em) DESC"
    ordenacao = f"v.score IS NULL, v.score DESC, {recentes}" if ordem == "score" else recentes
    return conexao.execute(
        f"""SELECT v.*, e.nome AS empresa,
                   (SELECT group_concat(DISTINCT fonte) FROM vaga_fonte f WHERE f.vaga_id = v.id) AS fontes,
                   (SELECT c.id FROM candidatura c WHERE c.vaga_id = v.id) AS candidatura_id
            FROM vaga v LEFT JOIN empresa e ON e.id = v.empresa_id
            WHERE {where}
            ORDER BY {ordenacao}
            LIMIT ?""",
        parametros,
    ).fetchall()


def obter_vaga(conexao: sqlite3.Connection, vaga_id: int) -> sqlite3.Row | None:
    return conexao.execute(
        """SELECT v.*, e.nome AS empresa, e.id AS empresa_id, e.bloqueada AS empresa_bloqueada,
                  (SELECT c.id FROM candidatura c WHERE c.vaga_id = v.id) AS candidatura_id
           FROM vaga v LEFT JOIN empresa e ON e.id = v.empresa_id WHERE v.id = ?""",
        (vaga_id,),
    ).fetchone()


def fontes_da_vaga(conexao: sqlite3.Connection, vaga_id: int) -> list[sqlite3.Row]:
    return conexao.execute(
        "SELECT * FROM vaga_fonte WHERE vaga_id = ? ORDER BY fonte", (vaga_id,)
    ).fetchall()


def mudar_estado_vaga(conexao: sqlite3.Connection, vaga_id: int, estado: str) -> None:
    conexao.execute("UPDATE vaga SET estado = ? WHERE id = ?", (estado, vaga_id))


def bloquear_empresa(conexao: sqlite3.Connection, empresa_id: int) -> None:
    conexao.execute("UPDATE empresa SET bloqueada = 1 WHERE id = ?", (empresa_id,))
    conexao.execute(
        """UPDATE vaga SET passou_filtro = 0, motivo_filtro = 'empresa bloqueada'
           WHERE empresa_id = ? AND estado IN ('nova', 'vista')""",
        (empresa_id,),
    )


def contar_vagas_novas(conexao: sqlite3.Connection) -> int:
    return conexao.execute(
        "SELECT count(*) FROM vaga WHERE estado = 'nova' AND passou_filtro = 1"
    ).fetchone()[0]


# ---------- candidaturas ----------

def plataforma_da_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.lower()
    for chave, nome in [
        ("gupy.io", "Gupy"), ("linkedin.com", "LinkedIn"), ("indeed.", "Indeed"),
        ("glassdoor.", "Glassdoor"), ("greenhouse.io", "Greenhouse"), ("lever.co", "Lever"),
        ("myworkdayjobs", "Workday"), ("vagas.com", "Vagas.com"), ("catho.com", "Catho"),
        ("infojobs", "InfoJobs"), ("solides", "Sólides"), ("kenoby", "Kenoby"),
    ]:
        if chave in url:
            return nome
    return "Outro"


def criar_candidatura(
    conexao: sqlite3.Connection,
    titulo: str,
    empresa: str | None,
    url: str | None,
    status: str = "salva",
    vaga_id: int | None = None,
) -> int:
    momento = agora()
    data_candidatura = momento if status != "salva" else None
    cursor = conexao.execute(
        """INSERT INTO candidatura (vaga_id, titulo, empresa, url, plataforma, status,
                                    data_candidatura, criado_em, atualizado_em)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (vaga_id, titulo, empresa, url, plataforma_da_url(url), status, data_candidatura, momento, momento),
    )
    candidatura_id = _novo_id(cursor)
    registrar_evento(conexao, candidatura_id, "status", f"Criada como {NOMES_STATUS.get(status, status)}")
    return candidatura_id


def candidatura_da_vaga(conexao: sqlite3.Connection, vaga_id: int, status: str) -> int:
    """Cria (ou atualiza) a candidatura ligada a uma vaga coletada."""
    existente = conexao.execute("SELECT id FROM candidatura WHERE vaga_id = ?", (vaga_id,)).fetchone()
    if existente:
        mudar_status(conexao, existente["id"], status)
        return existente["id"]
    vaga = obter_vaga(conexao, vaga_id)
    if vaga is None:
        raise ValueError("vaga não encontrada")
    mudar_estado_vaga(conexao, vaga_id, "salva" if status == "salva" else "candidatada")
    return criar_candidatura(conexao, vaga["titulo"], vaga["empresa"], vaga["url"], status, vaga_id)


def mudar_status(conexao: sqlite3.Connection, candidatura_id: int, status: str) -> None:
    if status not in NOMES_STATUS:
        raise ValueError(f"status inválido: {status}")
    atual = conexao.execute("SELECT status, data_candidatura, vaga_id FROM candidatura WHERE id = ?",
                            (candidatura_id,)).fetchone()
    if atual is None or atual["status"] == status:
        return
    momento = agora()
    data_candidatura = atual["data_candidatura"]
    if status != "salva" and not data_candidatura:
        data_candidatura = momento
    conexao.execute(
        "UPDATE candidatura SET status = ?, data_candidatura = ?, atualizado_em = ? WHERE id = ?",
        (status, data_candidatura, momento, candidatura_id),
    )
    if atual["vaga_id"] and status != "salva":
        mudar_estado_vaga(conexao, atual["vaga_id"], "candidatada")
    registrar_evento(
        conexao, candidatura_id, "status",
        f"{NOMES_STATUS.get(atual['status'], atual['status'])} → {NOMES_STATUS[status]}",
    )


def atualizar_detalhes(
    conexao: sqlite3.Connection, candidatura_id: int, proxima_acao: str | None, prazo: str | None
) -> None:
    conexao.execute(
        "UPDATE candidatura SET proxima_acao = ?, prazo = ?, atualizado_em = ? WHERE id = ?",
        (proxima_acao or None, prazo or None, agora(), candidatura_id),
    )


def registrar_evento(conexao: sqlite3.Connection, candidatura_id: int, tipo: str, conteudo: str) -> None:
    conexao.execute(
        "INSERT INTO evento (candidatura_id, tipo, data, conteudo) VALUES (?, ?, ?, ?)",
        (candidatura_id, tipo, agora(), conteudo),
    )


def tocar_candidatura(conexao: sqlite3.Connection, candidatura_id: int) -> None:
    conexao.execute("UPDATE candidatura SET atualizado_em = ? WHERE id = ?", (agora(), candidatura_id))


def listar_candidaturas(conexao: sqlite3.Connection) -> list[sqlite3.Row]:
    return conexao.execute(
        "SELECT * FROM candidatura ORDER BY coalesce(prazo, '9999'), atualizado_em DESC"
    ).fetchall()


def obter_candidatura(conexao: sqlite3.Connection, candidatura_id: int) -> sqlite3.Row | None:
    return conexao.execute("SELECT * FROM candidatura WHERE id = ?", (candidatura_id,)).fetchone()


def eventos(conexao: sqlite3.Connection, candidatura_id: int) -> list[sqlite3.Row]:
    return conexao.execute(
        "SELECT * FROM evento WHERE candidatura_id = ? ORDER BY data DESC, id DESC", (candidatura_id,)
    ).fetchall()


# ---------- coletas ----------

def iniciar_coleta(conexao: sqlite3.Connection, fonte: str) -> int:
    return _novo_id(conexao.execute(
        "INSERT INTO coleta (fonte, inicio) VALUES (?, ?)", (fonte, agora())
    ))


def finalizar_coleta(
    conexao: sqlite3.Connection, coleta_id: int, total: int, novas: int, erro: str | None = None
) -> None:
    conexao.execute(
        "UPDATE coleta SET fim = ?, total = ?, novas = ?, erro = ? WHERE id = ?",
        (agora(), total, novas, erro, coleta_id),
    )


def ultimas_coletas(conexao: sqlite3.Connection, limite: int = 20) -> list[sqlite3.Row]:
    return conexao.execute(
        "SELECT * FROM coleta ORDER BY id DESC LIMIT ?", (limite,)
    ).fetchall()


def ultima_coleta_concluida(conexao: sqlite3.Connection) -> str | None:
    linha = conexao.execute("SELECT max(fim) FROM coleta WHERE fim IS NOT NULL").fetchone()
    return linha[0] if linha else None


# ---------- uso de IA ----------

def registrar_uso_ia(
    conexao: sqlite3.Connection, provedor: str, modelo: str, tarefa: str,
    tokens_entrada: int, tokens_saida: int, erro: str | None = None,
) -> None:
    conexao.execute(
        """INSERT INTO uso_ia (data, provedor, modelo, tarefa, tokens_entrada, tokens_saida, erro)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (agora(), provedor, modelo, tarefa, tokens_entrada or 0, tokens_saida or 0, erro),
    )


def chamadas_ia_hoje(conexao: sqlite3.Connection) -> dict[str, int]:
    hoje = agora()[:10]
    linhas = conexao.execute(
        "SELECT provedor, count(*) AS n FROM uso_ia WHERE substr(data, 1, 10) = ? GROUP BY provedor", (hoje,)
    ).fetchall()
    return {linha["provedor"]: linha["n"] for linha in linhas}


def resumo_uso_ia(conexao: sqlite3.Connection, dias: int = 30) -> list[sqlite3.Row]:
    return conexao.execute(
        """SELECT provedor, modelo,
                  sum(CASE WHEN substr(data, 1, 10) = substr(?, 1, 10) THEN 1 ELSE 0 END) AS hoje,
                  count(*) AS chamadas,
                  sum(CASE WHEN erro IS NOT NULL THEN 1 ELSE 0 END) AS erros,
                  sum(tokens_entrada) AS entrada, sum(tokens_saida) AS saida
           FROM uso_ia WHERE data >= date('now', ?)
           GROUP BY provedor, modelo ORDER BY provedor""",
        (agora(), f"-{dias} days"),
    ).fetchall()


def ultimos_erros_ia(conexao: sqlite3.Connection, limite: int = 5) -> list[sqlite3.Row]:
    return conexao.execute(
        "SELECT * FROM uso_ia WHERE erro IS NOT NULL ORDER BY id DESC LIMIT ?", (limite,)
    ).fetchall()


# ---------- score ----------

def salvar_score(
    conexao: sqlite3.Connection, vaga_id: int, score: int, dados: str, provedor: str, segunda: bool = False
) -> None:
    if segunda:
        conexao.execute(
            "UPDATE vaga SET score2 = ?, score2_dados = ?, score2_provedor = ? WHERE id = ?",
            (score, dados, provedor, vaga_id),
        )
    else:
        conexao.execute(
            """UPDATE vaga SET score = ?, score_dados = ?, score_provedor = ?, score_em = ?,
                               score2 = NULL, score2_dados = NULL, score2_provedor = NULL
               WHERE id = ?""",
            (score, dados, provedor, agora(), vaga_id),
        )


def limpar_score(conexao: sqlite3.Connection, vaga_id: int) -> None:
    conexao.execute(
        """UPDATE vaga SET score = NULL, score_dados = NULL, score_provedor = NULL, score_em = NULL,
                           score2 = NULL, score2_dados = NULL, score2_provedor = NULL WHERE id = ?""",
        (vaga_id,),
    )


def vagas_sem_score(conexao: sqlite3.Connection, limite: int) -> list[sqlite3.Row]:
    return conexao.execute(
        """SELECT v.*, e.nome AS empresa FROM vaga v LEFT JOIN empresa e ON e.id = v.empresa_id
           WHERE v.passou_filtro = 1 AND v.estado IN ('nova', 'vista') AND v.score IS NULL
           ORDER BY coalesce(v.publicada_em, v.coletada_em) DESC LIMIT ?""",
        (limite,),
    ).fetchall()


def contar_sem_score(conexao: sqlite3.Connection) -> int:
    return conexao.execute(
        "SELECT count(*) FROM vaga WHERE passou_filtro = 1 AND estado IN ('nova', 'vista') AND score IS NULL"
    ).fetchone()[0]


def vagas_para_segunda_opiniao(conexao: sqlite3.Connection, minimo: int, limite: int) -> list[sqlite3.Row]:
    return conexao.execute(
        """SELECT v.*, e.nome AS empresa FROM vaga v LEFT JOIN empresa e ON e.id = v.empresa_id
           WHERE v.passou_filtro = 1 AND v.estado IN ('nova', 'vista')
             AND v.score >= ? AND v.score2 IS NULL
           ORDER BY v.score DESC LIMIT ?""",
        (minimo, limite),
    ).fetchall()


def vagas_com_score(conexao: sqlite3.Connection, minimo: int) -> list[sqlite3.Row]:
    return conexao.execute(
        """SELECT v.*, e.nome AS empresa,
                  (SELECT group_concat(DISTINCT fonte) FROM vaga_fonte f WHERE f.vaga_id = v.id) AS fontes
           FROM vaga v LEFT JOIN empresa e ON e.id = v.empresa_id
           WHERE v.passou_filtro = 1 AND v.estado IN ('nova', 'vista') AND v.score >= ?
             AND NOT EXISTS (SELECT 1 FROM candidatura c WHERE c.vaga_id = v.id)""",
        (minimo,),
    ).fetchall()


# ---------- feedback e regras ----------

def registrar_feedback(conexao: sqlite3.Connection, vaga_id: int, tipo: str, motivo: str | None) -> None:
    conexao.execute(
        "INSERT INTO feedback (vaga_id, tipo, motivo, criado_em) VALUES (?, ?, ?, ?)",
        (vaga_id, tipo, motivo or None, agora()),
    )


def feedbacks_recentes(conexao: sqlite3.Connection, tipo: str, limite: int) -> list[sqlite3.Row]:
    return conexao.execute(
        """SELECT f.*, v.titulo, e.nome AS empresa FROM feedback f
           JOIN vaga v ON v.id = f.vaga_id LEFT JOIN empresa e ON e.id = v.empresa_id
           WHERE f.tipo = ? ORDER BY f.id DESC LIMIT ?""",
        (tipo, limite),
    ).fetchall()


def feedback_da_vaga(conexao: sqlite3.Connection, vaga_id: int) -> sqlite3.Row | None:
    return conexao.execute(
        "SELECT * FROM feedback WHERE vaga_id = ? ORDER BY id DESC LIMIT 1", (vaga_id,)
    ).fetchone()


def regras(conexao: sqlite3.Connection) -> list[sqlite3.Row]:
    return conexao.execute("SELECT * FROM regra ORDER BY tipo, termo").fetchall()


def adicionar_regra(conexao: sqlite3.Connection, tipo: str, termo: str) -> None:
    conexao.execute(
        "INSERT OR IGNORE INTO regra (tipo, termo, criado_em) VALUES (?, ?, ?)", (tipo, termo.strip(), agora())
    )


def remover_regra(conexao: sqlite3.Connection, regra_id: int) -> None:
    conexao.execute("DELETE FROM regra WHERE id = ?", (regra_id,))


# ---------- gerações e CVs ----------

def salvar_geracao(
    conexao: sqlite3.Connection, vaga_id: int, tipo: str, entrada: str | None, conteudo: str,
    provedor: str, modelo: str,
) -> int:
    return _novo_id(conexao.execute(
        """INSERT INTO geracao (vaga_id, tipo, entrada, conteudo, provedor, modelo, criado_em)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (vaga_id, tipo, entrada, conteudo, provedor, modelo, agora()),
    ))


def geracoes(conexao: sqlite3.Connection, vaga_id: int) -> list[sqlite3.Row]:
    return conexao.execute(
        "SELECT * FROM geracao WHERE vaga_id = ? ORDER BY id DESC", (vaga_id,)
    ).fetchall()


def salvar_versao_cv(
    conexao: sqlite3.Connection, vaga_id: int, dados: str, docx: str | None, pdf: str | None,
    cobertura: int | None, provedor: str, modelo: str,
) -> int:
    return _novo_id(conexao.execute(
        """INSERT INTO versao_cv (vaga_id, dados, arquivo_docx, arquivo_pdf, cobertura, provedor, modelo, criado_em)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (vaga_id, dados, docx, pdf, cobertura, provedor, modelo, agora()),
    ))


def versoes_cv(conexao: sqlite3.Connection, vaga_id: int) -> list[sqlite3.Row]:
    return conexao.execute(
        "SELECT * FROM versao_cv WHERE vaga_id = ? ORDER BY id DESC", (vaga_id,)
    ).fetchall()


def obter_versao_cv(conexao: sqlite3.Connection, versao_id: int) -> sqlite3.Row | None:
    return conexao.execute("SELECT * FROM versao_cv WHERE id = ?", (versao_id,)).fetchone()


def vincular_cv(conexao: sqlite3.Connection, candidatura_id: int, versao_id: int) -> None:
    conexao.execute("UPDATE candidatura SET cv_versao_id = ? WHERE id = ?", (versao_id, candidatura_id))


def salvar_tempo_gasto(conexao: sqlite3.Connection, candidatura_id: int, minutos: int | None) -> None:
    conexao.execute("UPDATE candidatura SET tempo_gasto_min = ? WHERE id = ?", (minutos, candidatura_id))


def media_tempo_por_plataforma(conexao: sqlite3.Connection) -> dict[str, float]:
    linhas = conexao.execute(
        """SELECT plataforma, avg(tempo_gasto_min) AS media, count(*) AS n FROM candidatura
           WHERE tempo_gasto_min > 0 GROUP BY plataforma HAVING n >= 2"""
    ).fetchall()
    return {(linha["plataforma"] or "Outro").lower(): linha["media"] for linha in linhas}


# ---------- ajustes ----------

def obter_ajuste(conexao: sqlite3.Connection, chave: str, padrao: str | None = None) -> str | None:
    linha = conexao.execute("SELECT valor FROM ajuste WHERE chave = ?", (chave,)).fetchone()
    return linha["valor"] if linha else padrao


def salvar_ajuste(conexao: sqlite3.Connection, chave: str, valor: str) -> None:
    conexao.execute(
        "INSERT INTO ajuste (chave, valor) VALUES (?, ?) ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
        (chave, valor),
    )
