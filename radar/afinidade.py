"""Score de afinidade com IA, segunda opinião e o plano do dia (o que cabe no seu tempo)."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import db
from . import perfil as perfil_mod
from .ia import prompts
from .ia.servico import SemProvedor, ServicoIA
from .texto import texto_da_descricao

log = logging.getLogger("radar")

_trava = threading.Lock()
estado_afinidade: dict[str, Any] = {"rodando": False, "mensagem": None}


def _inteiro(valor: Any) -> int:
    try:
        return max(0, min(100, int(round(float(valor)))))
    except (TypeError, ValueError):
        return 0


def _lista(valor: Any) -> list[str]:
    if not isinstance(valor, list):
        return []
    return [str(v).strip() for v in valor if str(v).strip()][:20]


def normalizar_resultado(dados: dict[str, Any]) -> dict[str, Any]:
    return {
        "score": _inteiro(dados.get("score")),
        "resumo": str(dados.get("resumo") or "").strip(),
        "senioridade_vaga": str(dados.get("senioridade_vaga") or "nao_informada"),
        "requisitos_atendidos": _lista(dados.get("requisitos_atendidos")),
        "requisitos_faltando": _lista(dados.get("requisitos_faltando")),
        "pontos_de_atencao": _lista(dados.get("pontos_de_atencao")),
        "palavras_chave": _lista(dados.get("palavras_chave"))[:15],
    }


def vaga_para_prompt(vaga: Any) -> str:
    dados = dict(vaga)
    dados["descricao_texto"] = texto_da_descricao(dados.get("descricao"))
    return prompts.vaga_texto(dados)


def exemplos_feedback(conexao) -> str:
    linhas = []
    for f in db.feedbacks_recentes(conexao, "mais", 5):
        linhas.append(f"- Gostou: {f['titulo']} ({f['empresa'] or 'empresa não informada'})")
    for f in db.feedbacks_recentes(conexao, "menos", 8):
        motivo = f" — motivo: {f['motivo']}" if f["motivo"] else ""
        linhas.append(f"- Não quis: {f['titulo']} ({f['empresa'] or 'empresa não informada'}){motivo}")
    return "\n".join(linhas)


def avaliar(
    servico: ServicoIA, perfil: dict[str, Any], vaga: Any, caminho: Path | None = None, segunda: bool = False
) -> dict[str, Any]:
    with db.conectar(caminho) as conexao:
        exemplos = exemplos_feedback(conexao)
    usuario = prompts.score_usuario(perfil_mod.para_prompt(perfil), vaga_para_prompt(vaga), exemplos)
    if segunda:
        excluir = {vaga["score_provedor"]} if vaga["score_provedor"] else set()
        resultado = servico.gerar_json("segunda_opiniao", prompts.SEGUNDA_OPINIAO_SISTEMA, usuario, 1500, excluir)
    else:
        resultado = servico.gerar_json("score", prompts.SCORE_SISTEMA, usuario, 1500)
    dados = normalizar_resultado(resultado.dados)
    dados["modelo"] = resultado.modelo
    with db.conectar(caminho) as conexao:
        db.salvar_score(conexao, vaga["id"], dados["score"], json.dumps(dados, ensure_ascii=False),
                        resultado.provedor, segunda=segunda)
    return dados


def processar(
    config: dict[str, Any],
    servico: ServicoIA | None = None,
    perfil: dict[str, Any] | None = None,
    caminho: Path | None = None,
    pausa: float = 1.0,
) -> dict[str, Any]:
    """Dá nota às vagas novas e pede segunda opinião para as melhores. Para cedo se faltar provedor."""
    opcoes = config["afinidade"]
    if not opcoes.get("ativo"):
        return {"ignorado": "afinidade desligada no config.yaml"}
    if not _trava.acquire(blocking=False):
        return {"ignorado": "já existe uma avaliação em andamento"}
    estado_afinidade["rodando"] = True
    resumo: dict[str, Any] = {"avaliadas": 0, "segunda_opiniao": 0, "erros": 0}
    try:
        try:
            perfil = perfil or perfil_mod.carregar()
        except perfil_mod.PerfilAusente as erro:
            estado_afinidade["mensagem"] = str(erro)
            return {"erro": str(erro)}
        servico = servico or ServicoIA(config, caminho)
        if not servico.disponivel("score"):
            estado_afinidade["mensagem"] = "Sem provedor de IA disponível para o score (veja Ajustes)."
            return {"erro": estado_afinidade["mensagem"]}

        with db.conectar(caminho) as conexao:
            pendentes = db.vagas_sem_score(conexao, int(opcoes["max_por_rodada"]))
        for i, vaga in enumerate(pendentes, 1):
            estado_afinidade["mensagem"] = f"Avaliando afinidade {i} de {len(pendentes)}…"
            try:
                avaliar(servico, perfil, vaga, caminho)
                resumo["avaliadas"] += 1
            except SemProvedor as erro:
                resumo["erro"] = str(erro)
                break
            except Exception:  # noqa: BLE001 - uma vaga problemática não para as outras
                log.exception("Erro ao avaliar vaga %s", vaga["id"])
                resumo["erros"] += 1
            time.sleep(pausa)

        with db.conectar(caminho) as conexao:
            melhores = db.vagas_para_segunda_opiniao(
                conexao, int(opcoes["score_minimo"]), int(opcoes["segunda_opiniao_top"]))
        for vaga in melhores:
            excluir = {vaga["score_provedor"]} if vaga["score_provedor"] else set()
            if not servico.disponivel("segunda_opiniao", excluir):
                break
            estado_afinidade["mensagem"] = "Pedindo segunda opinião nas melhores vagas…"
            try:
                avaliar(servico, perfil, vaga, caminho, segunda=True)
                resumo["segunda_opiniao"] += 1
            except SemProvedor:
                break
            except Exception:  # noqa: BLE001
                log.exception("Erro na segunda opinião da vaga %s", vaga["id"])
                resumo["erros"] += 1
            time.sleep(pausa)

        estado_afinidade["mensagem"] = (
            f"Afinidade: {resumo['avaliadas']} vagas avaliadas, {resumo['segunda_opiniao']} com segunda opinião"
            + (f", {resumo['erros']} com erro" if resumo["erros"] else "")
            + (f". Parou: {resumo['erro']}" if resumo.get("erro") else "")
        )
        return resumo
    finally:
        estado_afinidade["rodando"] = False
        _trava.release()


# ---------- plano do dia ----------

def esforco_min(vaga: Any, config: dict[str, Any], medias: dict[str, float]) -> int:
    plataforma = (db.plataforma_da_url(vaga["url"]) or "Outro").lower()
    if plataforma in medias:
        return max(1, round(medias[plataforma]))
    tabela = config["afinidade"]["esforco_min"]
    return int(tabela.get(plataforma, tabela.get("outro", 15)))


def frescor(vaga: Any, hoje: date | None = None) -> float:
    hoje = hoje or date.today()
    referencia = vaga["publicada_em"] or vaga["coletada_em"]
    try:
        dias = (hoje - datetime.fromisoformat(str(referencia)[:10]).date()).days
    except ValueError:
        dias = 7
    return max(0.4, 1 - max(dias, 0) / 30)


def divergente(vaga: Any, config: dict[str, Any]) -> bool:
    return vaga["score2"] is not None and abs(vaga["score"] - vaga["score2"]) >= int(config["afinidade"]["divergencia"])


def plano_do_dia(config: dict[str, Any], minutos: int, caminho: Path | None = None) -> dict[str, Any]:
    """Ordena por prioridade (afinidade × frescor ÷ esforço) e enche o tempo disponível."""
    with db.conectar(caminho) as conexao:
        vagas = db.vagas_com_score(conexao, int(config["afinidade"]["score_minimo"]))
        medias = db.media_tempo_por_plataforma(conexao)
    itens = []
    for vaga in vagas:
        nota = vaga["score"] if vaga["score2"] is None else (vaga["score"] + vaga["score2"]) / 2
        esforco = esforco_min(vaga, config, medias)
        itens.append({
            "vaga": vaga,
            "nota": round(nota),
            "esforco": esforco,
            # o esforço pesa pouco: serve para desempatar, não para esconder uma vaga muito aderente
            "prioridade": (nota / 100) * frescor(vaga) / (esforco ** 0.25),
            "divergente": divergente(vaga, config),
            "dados": json.loads(vaga["score_dados"] or "{}"),
        })
    itens.sort(key=lambda i: i["prioridade"], reverse=True)
    cabe, depois, usado = [], [], 0
    for item in itens:
        if usado + item["esforco"] <= minutos:
            cabe.append(item)
            usado += item["esforco"]
        else:
            depois.append(item)
    cabe.sort(key=lambda i: i["nota"], reverse=True)
    return {"cabe": cabe, "depois": depois, "usado": usado, "minutos": minutos}
