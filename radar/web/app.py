"""Interface web (Starlette + Jinja2), servida só para o seu computador (127.0.0.1)."""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .. import acoes, afinidade, db, documentos, pipeline, sugestoes
from .. import config as configuracao
from .. import perfil as perfil_mod
from ..agendador import agendador
from ..ia.provedores import NOMES_EXIBICAO
from ..ia.servico import SemProvedor, ServicoIA
from ..texto import texto_da_descricao

PASTA = Path(__file__).resolve().parent
jinja = Environment(loader=FileSystemLoader(PASTA / "templates"), autoescape=select_autoescape())


# ---------- filtros de template ----------

def _parse(valor: str | None) -> datetime | None:
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor)[:19])
    except ValueError:
        return None


def data_br(valor: str | None) -> str:
    momento = _parse(valor)
    return momento.strftime("%d/%m/%Y") if momento else ""


def tempo_relativo(valor: str | None) -> str:
    momento = _parse(valor)
    if not momento:
        return ""
    dias = (date.today() - momento.date()).days
    if dias <= 0:
        return "hoje"
    if dias == 1:
        return "ontem"
    if dias < 30:
        return f"há {dias} dias"
    meses = dias // 30
    return "há 1 mês" if meses == 1 else f"há {meses} meses"


ROTULOS_MODELO = {"remoto": "Remoto", "hibrido": "Híbrido", "presencial": "Presencial"}

jinja.filters.update(
    data_br=data_br,
    tempo_relativo=tempo_relativo,
    texto_descricao=texto_da_descricao,
    nome_status=lambda s: db.NOMES_STATUS.get(s, s),
    rotulo_modelo=lambda m: ROTULOS_MODELO.get(m or "", ""),
    from_json=lambda t: json.loads(t) if t else {},
    nome_motivo=lambda m: sugestoes.NOMES_MOTIVOS.get(m or "", m or ""),
    nome_provedor=lambda p: NOMES_EXIBICAO.get(p or "", p or ""),
)


def render(request: Request, nome: str, **contexto) -> HTMLResponse:
    contexto.setdefault("mensagem", request.query_params.get("msg"))
    contexto.setdefault("execucao", pipeline.estado_execucao)
    contexto.setdefault("estado_afinidade", afinidade.estado_afinidade)
    contexto["caminho"] = request.url.path
    return HTMLResponse(jinja.get_template(nome).render(request=request, **contexto))


def voltar(destino: str, mensagem: str | None = None) -> RedirectResponse:
    if mensagem:
        separador = "&" if "?" in destino else "?"
        destino = f"{destino}{separador}{urlencode({'msg': mensagem})}"
    return RedirectResponse(destino, status_code=303)


def campo(formulario, nome: str) -> str:
    """Valor de texto de um campo do formulário ('' se ausente)."""
    valor = formulario.get(nome)
    return valor.strip() if isinstance(valor, str) else ""


def _destino_seguro(valor: str | None, padrao: str) -> str:
    return valor if valor and valor.startswith("/") and not valor.startswith("//") else padrao


# ---------- páginas ----------

async def inicio(request: Request) -> Response:
    config = configuracao.carregar()
    dias = int(config["candidaturas"]["dias_sem_resposta"])
    limite_parado = (datetime.now() - timedelta(days=dias)).isoformat(timespec="seconds")
    limite_prazo = (date.today() + timedelta(days=7)).isoformat()
    with db.conectar() as conexao:
        db.iniciar()
        novas = db.contar_vagas_novas(conexao)
        candidaturas = db.listar_candidaturas(conexao)
        coletas = db.ultimas_coletas(conexao, 8)
    em_andamento = [c for c in candidaturas if c["status"] in db.STATUS_EM_ANDAMENTO]
    prazos = sorted(
        [c for c in em_andamento if c["prazo"] and c["prazo"] <= limite_prazo],
        key=lambda c: c["prazo"],
    )
    paradas = [
        c for c in em_andamento
        if c["status"] in ("candidatada", "em_analise") and c["atualizado_em"] < limite_parado
    ]
    return render(
        request, "inicio.html",
        novas=novas, em_andamento=len(em_andamento), prazos=prazos, paradas=paradas,
        dias_sem_resposta=dias, coletas=coletas, buscas=config["buscas"],
        hoje=date.today().isoformat(),
    )


async def vagas(request: Request) -> Response:
    parametros = request.query_params
    busca = (parametros.get("busca") or "").strip() or None
    fonte = parametros.get("fonte") or None
    estado = parametros.get("estado") or None
    mostrar_filtradas = parametros.get("filtradas") == "1"
    ordem = "data" if parametros.get("ordem") == "data" else "score"
    with db.conectar() as conexao:
        db.iniciar()
        lista = db.listar_vagas(conexao, estado=estado, mostrar_filtradas=mostrar_filtradas,
                                busca=busca, fonte=fonte, ordem=ordem)
        fontes = [linha[0] for linha in conexao.execute(
            "SELECT DISTINCT fonte FROM vaga_fonte ORDER BY fonte").fetchall()]
    return render(
        request, "vagas.html", vagas=lista, fontes=fontes, busca=busca or "", fonte=fonte or "",
        estado=estado or "", mostrar_filtradas=mostrar_filtradas, ordem=ordem,
        voltar_para=str(request.url.path) + (f"?{request.url.query}" if request.url.query else ""),
    )


async def vaga_detalhe(request: Request) -> Response:
    vaga_id = int(request.path_params["id"])
    with db.conectar() as conexao:
        vaga = db.obter_vaga(conexao, vaga_id)
        if vaga is None:
            return HTMLResponse("Vaga não encontrada", status_code=404)
        if vaga["estado"] == "nova":
            db.mudar_estado_vaga(conexao, vaga_id, "vista")
        fontes = db.fontes_da_vaga(conexao, vaga_id)
        geracoes = db.geracoes(conexao, vaga_id)
        versoes = db.versoes_cv(conexao, vaga_id)
        feedback = db.feedback_da_vaga(conexao, vaga_id)
    config = configuracao.carregar()
    servico = ServicoIA(config)
    return render(
        request, "vaga.html", vaga=vaga, fontes=fontes, geracoes=geracoes, versoes=versoes, feedback=feedback,
        analise=json.loads(vaga["score_dados"] or "{}"), analise2=json.loads(vaga["score2_dados"] or "{}"),
        divergente=vaga["score"] is not None and afinidade.divergente(vaga, config),
        motivos=sugestoes.MOTIVOS, acoes_texto=acoes.ACOES_TEXTO,
        ia_escrita=servico.disponivel("escrita"), ia_score=servico.disponivel("score"),
        perfil_ok=perfil_mod.existe(),
    )


async def vaga_acao(request: Request) -> Response:
    vaga_id = int(request.path_params["id"])
    formulario = await request.form()
    acao = campo(formulario, "acao")
    destino = _destino_seguro(campo(formulario, "voltar"), f"/vagas/{vaga_id}")
    with db.conectar() as conexao:
        vaga = db.obter_vaga(conexao, vaga_id)
        if vaga is None:
            return voltar("/vagas", "Vaga não encontrada")
        if acao == "descartar":
            db.mudar_estado_vaga(conexao, vaga_id, "descartada")
            mensagem = "Vaga descartada"
        elif acao == "restaurar":
            db.mudar_estado_vaga(conexao, vaga_id, "vista")
            mensagem = "Vaga de volta à lista"
        elif acao == "salvar":
            db.candidatura_da_vaga(conexao, vaga_id, "salva")
            mensagem = "Vaga salva no quadro de candidaturas"
        elif acao == "candidatei":
            candidatura_id = db.candidatura_da_vaga(conexao, vaga_id, "candidatada")
            versoes = db.versoes_cv(conexao, vaga_id)
            if versoes:
                db.vincular_cv(conexao, candidatura_id, versoes[0]["id"])
            mensagem = "Candidatura registrada" + (" com o último CV adaptado" if versoes else "")
        elif acao == "bloquear" and vaga["empresa_id"]:
            db.bloquear_empresa(conexao, vaga["empresa_id"])
            mensagem = f"Empresa {vaga['empresa']} bloqueada"
        else:
            mensagem = "Ação desconhecida"
    return voltar(destino, mensagem)


async def candidaturas(request: Request) -> Response:
    with db.conectar() as conexao:
        db.iniciar()
        lista = db.listar_candidaturas(conexao)
    colunas = [
        (codigo, nome, [c for c in lista if c["status"] == codigo])
        for codigo, nome in db.STATUS if codigo in db.STATUS_EM_ANDAMENTO
    ]
    encerradas = [c for c in lista if c["status"] in db.STATUS_ENCERRADOS]
    return render(request, "candidaturas.html", colunas=colunas, encerradas=encerradas,
                  status=db.STATUS, hoje=date.today().isoformat())


async def candidatura_nova(request: Request) -> Response:
    if request.method == "GET":
        return render(request, "candidatura_nova.html", status=db.STATUS)
    formulario = await request.form()
    titulo = campo(formulario, "titulo")
    if not titulo:
        return render(request, "candidatura_nova.html", status=db.STATUS,
                      erro="Informe o cargo.", form=formulario)
    status = campo(formulario, "status") or "candidatada"
    with db.conectar() as conexao:
        candidatura_id = db.criar_candidatura(
            conexao, titulo, campo(formulario, "empresa") or None,
            campo(formulario, "url") or None, status if status in db.NOMES_STATUS else "candidatada",
        )
    return voltar(f"/candidaturas/{candidatura_id}", "Candidatura adicionada")


async def candidatura_detalhe(request: Request) -> Response:
    candidatura_id = int(request.path_params["id"])
    with db.conectar() as conexao:
        candidatura = db.obter_candidatura(conexao, candidatura_id)
        if candidatura is None:
            return HTMLResponse("Candidatura não encontrada", status_code=404)
        historico = db.eventos(conexao, candidatura_id)
        cv = db.obter_versao_cv(conexao, candidatura["cv_versao_id"]) if candidatura["cv_versao_id"] else None
    return render(request, "candidatura.html", c=candidatura, eventos=historico, status=db.STATUS, cv=cv)


async def candidatura_status(request: Request) -> Response:
    candidatura_id = int(request.path_params["id"])
    formulario = await request.form()
    destino = _destino_seguro(campo(formulario, "voltar"), f"/candidaturas/{candidatura_id}")
    try:
        with db.conectar() as conexao:
            db.mudar_status(conexao, candidatura_id, campo(formulario, "status") or "")
    except ValueError as erro:
        return voltar(destino, str(erro))
    return voltar(destino, "Status atualizado")


async def candidatura_detalhes(request: Request) -> Response:
    candidatura_id = int(request.path_params["id"])
    formulario = await request.form()
    with db.conectar() as conexao:
        db.atualizar_detalhes(conexao, candidatura_id, campo(formulario, "proxima_acao"),
                              campo(formulario, "prazo") or None)
        tempo = campo(formulario, "tempo_gasto_min")
        db.salvar_tempo_gasto(conexao, candidatura_id, int(tempo) if tempo.isdigit() else None)
    return voltar(f"/candidaturas/{candidatura_id}", "Detalhes salvos")


async def candidatura_nota(request: Request) -> Response:
    candidatura_id = int(request.path_params["id"])
    formulario = await request.form()
    nota = campo(formulario, "nota")
    if nota:
        with db.conectar() as conexao:
            db.registrar_evento(conexao, candidatura_id, "nota", nota)
            db.tocar_candidatura(conexao, candidatura_id)
    return voltar(f"/candidaturas/{candidatura_id}", "Nota adicionada" if nota else None)


async def coletar(request: Request) -> Response:
    formulario = await request.form()
    destino = _destino_seguro(campo(formulario, "voltar"), "/")
    iniciou = agendador.rodar_agora()
    return voltar(destino, "Coleta iniciada. Atualize a página em alguns minutos." if iniciou
                  else "Já existe uma coleta em andamento.")


async def refiltrar(request: Request) -> Response:
    total = pipeline.refiltrar_tudo(configuracao.carregar())
    return voltar("/vagas", f"Filtro reaplicado em {total} vagas")


# ---------- fase 2: hoje, afinidade, ações de IA, ajustes ----------

async def hoje(request: Request) -> Response:
    config = configuracao.carregar()
    with db.conectar() as conexao:
        db.iniciar()
        padrao = str(config["afinidade"]["tempo_disponivel_padrao"])
        minutos = int(db.obter_ajuste(conexao, "tempo_disponivel", padrao) or padrao)
        sem_score = db.contar_sem_score(conexao)
    plano = await run_in_threadpool(afinidade.plano_do_dia, config, minutos)
    servico = ServicoIA(config)
    return render(
        request, "hoje.html", plano=plano, sem_score=sem_score, score_minimo=config["afinidade"]["score_minimo"],
        ia_score=servico.disponivel("score"), perfil_ok=perfil_mod.existe(),
    )


async def hoje_tempo(request: Request) -> Response:
    formulario = await request.form()
    minutos = campo(formulario, "minutos")
    if not minutos.isdigit() or not 5 <= int(minutos) <= 600:
        return voltar("/hoje", "Informe um tempo entre 5 e 600 minutos.")
    with db.conectar() as conexao:
        db.salvar_ajuste(conexao, "tempo_disponivel", minutos)
    return voltar("/hoje")


async def avaliar_afinidade(request: Request) -> Response:
    formulario = await request.form()
    destino = _destino_seguro(campo(formulario, "voltar"), "/hoje")
    iniciou = agendador.avaliar_agora()
    return voltar(destino, "Avaliação de afinidade iniciada. Atualize a página em alguns minutos." if iniciou
                  else "Já existe uma avaliação em andamento.")


async def vaga_feedback(request: Request) -> Response:
    vaga_id = int(request.path_params["id"])
    formulario = await request.form()
    tipo = campo(formulario, "tipo")
    motivo = campo(formulario, "motivo") or None
    destino = _destino_seguro(campo(formulario, "voltar"), f"/vagas/{vaga_id}")
    if tipo not in ("mais", "menos"):
        return voltar(destino, "Feedback inválido")
    with db.conectar() as conexao:
        vaga = db.obter_vaga(conexao, vaga_id)
        if vaga is None:
            return voltar("/vagas", "Vaga não encontrada")
        db.registrar_feedback(conexao, vaga_id, tipo, motivo)
        if tipo == "menos":
            db.mudar_estado_vaga(conexao, vaga_id, "descartada")
            if motivo == "empresa" and vaga["empresa_id"]:
                db.bloquear_empresa(conexao, vaga["empresa_id"])
    if tipo == "mais":
        return voltar(destino, "Anotado: vagas parecidas vão pesar mais no score")
    return voltar(destino, "Vaga descartada; o motivo vai ajudar a ajustar os filtros")


async def vaga_reavaliar(request: Request) -> Response:
    vaga_id = int(request.path_params["id"])
    config = configuracao.carregar()

    def tarefa() -> None:
        perfil = perfil_mod.carregar()
        servico = ServicoIA(config)
        with db.conectar() as conexao:
            db.limpar_score(conexao, vaga_id)
            vaga = db.obter_vaga(conexao, vaga_id)
        afinidade.avaliar(servico, perfil, vaga)

    try:
        await run_in_threadpool(tarefa)
    except (SemProvedor, perfil_mod.PerfilAusente) as erro:
        return voltar(f"/vagas/{vaga_id}", str(erro))
    return voltar(f"/vagas/{vaga_id}", "Afinidade recalculada")


async def vaga_gerar(request: Request) -> Response:
    vaga_id = int(request.path_params["id"])
    formulario = await request.form()
    tipo = campo(formulario, "tipo")
    entrada = campo(formulario, "entrada")
    config = configuracao.carregar()
    if tipo == "resposta" and not entrada:
        return voltar(f"/vagas/{vaga_id}#acoes", "Cole a pergunta do formulário antes de gerar a resposta.")
    try:
        if tipo == "cv":
            await run_in_threadpool(acoes.gerar_cv, config, vaga_id)
            mensagem = "CV adaptado gerado"
        else:
            await run_in_threadpool(acoes.gerar_texto, config, vaga_id, tipo, entrada)
            mensagem = f"{acoes.ACOES_TEXTO[tipo][0]} gerado"
    except (SemProvedor, perfil_mod.PerfilAusente, ValueError) as erro:
        return voltar(f"/vagas/{vaga_id}#acoes", str(erro))
    return voltar(f"/vagas/{vaga_id}#gerados", mensagem)


async def baixar_cv(request: Request) -> Response:
    versao_id = int(request.path_params["id"])
    extensao = request.path_params["ext"]
    with db.conectar() as conexao:
        versao = db.obter_versao_cv(conexao, versao_id)
        vaga = db.obter_vaga(conexao, versao["vaga_id"]) if versao else None
    if versao is None or extensao not in ("docx", "pdf"):
        return HTMLResponse("Arquivo não encontrado", status_code=404)
    caminho = Path(versao[f"arquivo_{extensao}"] or "")
    if not caminho.is_file():
        return HTMLResponse("Arquivo não encontrado na pasta dados/cvs", status_code=404)
    nome = json.loads(versao["dados"]).get("pessoal", {}).get("nome")
    return FileResponse(caminho, filename=documentos.nome_para_download(nome, vaga["empresa"] if vaga else None,
                                                                        extensao))


async def ajustes(request: Request) -> Response:
    config = configuracao.carregar()
    servico = ServicoIA(config)
    with db.conectar() as conexao:
        db.iniciar()
        uso = db.resumo_uso_ia(conexao)
        erros = db.ultimos_erros_ia(conexao)
        hoje_por_provedor = db.chamadas_ia_hoje(conexao)
        lista_regras = db.regras(conexao)
        lista_sugestoes = sugestoes.sugerir(conexao)
    perfil_info = None
    perfil_erro = None
    try:
        perfil = perfil_mod.carregar()
        perfil_info = {
            "nome": (perfil.get("pessoal") or {}).get("nome"),
            "bullets": len(perfil_mod.bullets_por_id(perfil)),
            "skills": len(perfil_mod.todas_skills(perfil)),
            "cargos": perfil["objetivo"].get("cargos_alvo") or [],
        }
    except Exception as erro:  # noqa: BLE001 - mostra qualquer problema do YAML na tela
        perfil_erro = str(erro)
    provedores = []
    for nome, provedor in servico.provedores.items():
        opcoes = config["ia"]["provedores"].get(nome, {})
        provedores.append({
            "nome": nome, "exibicao": NOMES_EXIBICAO.get(nome, nome), "configurado": provedor.configurado,
            "variavel": provedor.variavel_chave, "rapido": opcoes.get("modelo_rapido"),
            "forte": opcoes.get("modelo_forte"), "limite": opcoes.get("limite_chamadas_dia"),
            "hoje": hoje_por_provedor.get(nome, 0),
        })
    tarefas = [
        {"nome": nome, "ordem": [NOMES_EXIBICAO.get(p, p) for p in t.get("provedores") or []],
         "modelo": t.get("modelo"), "ativo": servico.candidatos(nome)}
        for nome, t in config["ia"]["tarefas"].items()
    ]
    return render(
        request, "ajustes.html", provedores=provedores, tarefas=tarefas, uso=uso, erros=erros,
        regras=lista_regras, sugestoes=lista_sugestoes, tipos_regra=sugestoes.TIPOS_REGRA,
        perfil=perfil_info, perfil_erro=perfil_erro,
    )


async def ajustes_regra(request: Request) -> Response:
    formulario = await request.form()
    tipo = campo(formulario, "tipo")
    termo = campo(formulario, "termo")
    if tipo not in (*sugestoes.TIPOS_REGRA, "ignorada") or not termo:
        return voltar("/ajustes", "Informe o termo da regra.")
    with db.conectar() as conexao:
        db.adicionar_regra(conexao, tipo, termo)
    if tipo == "ignorada":
        return voltar("/ajustes", f"Sugestão \"{termo}\" ignorada")
    total = pipeline.refiltrar_tudo(configuracao.carregar())
    return voltar("/ajustes", f"Regra adicionada e filtro reaplicado em {total} vagas")


async def ajustes_regra_remover(request: Request) -> Response:
    with db.conectar() as conexao:
        db.remover_regra(conexao, int(request.path_params["id"]))
    pipeline.refiltrar_tudo(configuracao.carregar())
    return voltar("/ajustes", "Regra removida e filtro reaplicado")


@asynccontextmanager
async def ciclo_de_vida(app: Starlette):
    db.iniciar()
    if os.environ.get("RADAR_SEM_AGENDADOR") != "1":
        agendador.iniciar()
    yield
    agendador.parar()


rotas = [
    Route("/", inicio),
    Route("/vagas", vagas),
    Route("/vagas/{id:int}", vaga_detalhe),
    Route("/vagas/{id:int}/acao", vaga_acao, methods=["POST"]),
    Route("/candidaturas", candidaturas),
    Route("/candidaturas/nova", candidatura_nova, methods=["GET", "POST"]),
    Route("/candidaturas/{id:int}", candidatura_detalhe),
    Route("/candidaturas/{id:int}/status", candidatura_status, methods=["POST"]),
    Route("/candidaturas/{id:int}/detalhes", candidatura_detalhes, methods=["POST"]),
    Route("/candidaturas/{id:int}/nota", candidatura_nota, methods=["POST"]),
    Route("/hoje", hoje),
    Route("/hoje/tempo", hoje_tempo, methods=["POST"]),
    Route("/afinidade/avaliar", avaliar_afinidade, methods=["POST"]),
    Route("/vagas/{id:int}/feedback", vaga_feedback, methods=["POST"]),
    Route("/vagas/{id:int}/reavaliar", vaga_reavaliar, methods=["POST"]),
    Route("/vagas/{id:int}/gerar", vaga_gerar, methods=["POST"]),
    Route("/cv/{id:int}.{ext}", baixar_cv),
    Route("/ajustes", ajustes),
    Route("/ajustes/regra", ajustes_regra, methods=["POST"]),
    Route("/ajustes/regra/{id:int}/remover", ajustes_regra_remover, methods=["POST"]),
    Route("/coletar", coletar, methods=["POST"]),
    Route("/refiltrar", refiltrar, methods=["POST"]),
    Mount("/static", StaticFiles(directory=PASTA / "static"), name="static"),
]

app = Starlette(routes=rotas, lifespan=ciclo_de_vida)
