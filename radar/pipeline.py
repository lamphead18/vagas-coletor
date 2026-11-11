"""Roda os coletores, grava as vagas sem duplicar e aplica o filtro de regras."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import db, filtros
from .coletores import gupy, jobspy_coletor
from .modelos import VagaColetada
from .sugestoes import filtros_efetivos

log = logging.getLogger("radar")

Coletor = Callable[[dict[str, Any]], list[VagaColetada]]

_trava = threading.Lock()
estado_execucao: dict[str, Any] = {"rodando": False, "mensagem": None}


def mensagem_de_erro(erro: Exception) -> str:
    """Traduz falhas comuns de rede para uma frase curta; o detalhe técnico vai para o radar.log."""
    import requests

    if isinstance(erro, requests.ConnectionError):
        return "Sem conexão com o site (internet fora do ar ou site indisponível)."
    if isinstance(erro, requests.Timeout):
        return "O site demorou demais para responder. Tente de novo mais tarde."
    if isinstance(erro, requests.HTTPError) and erro.response is not None:
        codigo = erro.response.status_code
        if codigo == 429:
            return "O site limitou as buscas (erro 429). Espere algumas horas."
        return f"O site respondeu com erro {codigo}. Pode ter mudado o formato."
    return str(erro)[:300]


def coletores_ativos(config: dict[str, Any]) -> dict[str, Coletor]:
    ativos: dict[str, Coletor] = {}
    if config["fontes"]["gupy"].get("ativo"):
        ativos["gupy"] = gupy.coletar
    if config["fontes"]["jobspy"].get("ativo"):
        ativos["jobspy"] = jobspy_coletor.coletar
    return ativos


def _aplicar_filtro(conexao, vaga_id: int, config: dict[str, Any], efetivos: dict[str, Any] | None = None) -> None:
    vaga = db.obter_vaga(conexao, vaga_id)
    if vaga is None:
        return
    efetivos = efetivos or filtros_efetivos(conexao, config["filtros"])
    passou, motivo = filtros.avaliar(dict(vaga), efetivos, bool(vaga["empresa_bloqueada"]))
    db.marcar_filtro(conexao, vaga_id, passou, motivo)


def refiltrar_tudo(config: dict[str, Any], caminho: Path | None = None) -> int:
    """Reaplica o filtro em todas as vagas abertas (use depois de mudar o config.yaml)."""
    with db.conectar(caminho) as conexao:
        ids = [linha["id"] for linha in conexao.execute(
            "SELECT id FROM vaga WHERE estado IN ('nova', 'vista')").fetchall()]
        efetivos = filtros_efetivos(conexao, config["filtros"])
        for vaga_id in ids:
            _aplicar_filtro(conexao, vaga_id, config, efetivos)
    return len(ids)


def executar(
    config: dict[str, Any],
    coletores: dict[str, Coletor] | None = None,
    caminho: Path | None = None,
) -> dict[str, Any]:
    """Roda todas as fontes ativas. Uma fonte com erro não impede as outras."""
    if not _trava.acquire(blocking=False):
        return {"ignorado": "já existe uma coleta em andamento"}
    estado_execucao["rodando"] = True
    resumo: dict[str, Any] = {}
    try:
        if not config["buscas"]:
            estado_execucao["mensagem"] = "Nenhum termo em 'buscas' no config.yaml"
            return {"erro": estado_execucao["mensagem"]}
        db.iniciar(caminho)
        for nome, coletor in (coletores if coletores is not None else coletores_ativos(config)).items():
            estado_execucao["mensagem"] = f"Coletando {nome}…"
            with db.conectar(caminho) as conexao:
                coleta_id = db.iniciar_coleta(conexao, nome)
            try:
                vagas = coletor(config)
            except Exception as erro:  # noqa: BLE001 - registrar qualquer falha da fonte
                log.exception("Falha na coleta de %s", nome)
                mensagem = mensagem_de_erro(erro)
                with db.conectar(caminho) as conexao:
                    db.finalizar_coleta(conexao, coleta_id, 0, 0, mensagem)
                resumo[nome] = {"erro": mensagem}
                continue
            novas = 0
            with db.conectar(caminho) as conexao:
                efetivos = filtros_efetivos(conexao, config["filtros"])
                for vaga in vagas:
                    vaga_id, nova = db.salvar_vaga(conexao, vaga)
                    if nova:
                        novas += 1
                        _aplicar_filtro(conexao, vaga_id, config, efetivos)
                db.finalizar_coleta(conexao, coleta_id, len(vagas), novas)
            resumo[nome] = {"total": len(vagas), "novas": novas}
            log.info("%s: %d vagas, %d novas", nome, len(vagas), novas)
        partes = [
            f"{nome}: erro" if "erro" in r else f"{nome}: {r['novas']} novas de {r['total']}"
            for nome, r in resumo.items()
        ]
        estado_execucao["mensagem"] = "Última coleta — " + "; ".join(partes) if partes else None
        return resumo
    finally:
        estado_execucao["rodando"] = False
        _trava.release()
