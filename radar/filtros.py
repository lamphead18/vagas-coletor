"""Filtro de regras: decide, sem IA, se uma vaga aparece na lista."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .normalizacao import contem_termo, normalizar, normalizar_empresa


def _data(texto: str | None) -> date | None:
    if not texto:
        return None
    try:
        return datetime.fromisoformat(str(texto)[:10]).date()
    except ValueError:
        return None


def avaliar(
    vaga: dict[str, Any], filtros: dict[str, Any], empresa_bloqueada: bool = False, hoje: date | None = None
) -> tuple[bool, str | None]:
    """Devolve (passou, motivo). O motivo explica por que a vaga foi filtrada."""
    hoje = hoje or date.today()
    titulo = vaga.get("titulo") or ""
    empresa = vaga.get("empresa") or ""

    bloqueadas = {normalizar_empresa(e) for e in filtros.get("empresas_bloqueadas") or []}
    if empresa_bloqueada or (empresa and normalizar_empresa(empresa) in bloqueadas):
        return False, "empresa bloqueada"

    proibido = contem_termo(titulo, filtros.get("titulo_nao_pode_conter") or [])
    if proibido:
        return False, f"título contém \"{proibido}\""

    obrigatorios = filtros.get("titulo_deve_conter") or []
    if obrigatorios and not contem_termo(titulo, obrigatorios):
        return False, "título sem nenhum termo obrigatório"

    modelos = [normalizar(m) for m in filtros.get("modelos") or []]
    modelo = vaga.get("modelo")
    if modelos and modelo and normalizar(modelo) not in modelos:
        return False, f"modelo {modelo}"

    cidades = [normalizar(c) for c in filtros.get("cidades") or []]
    if cidades and modelo != "remoto":
        cidade = normalizar(vaga.get("cidade"))
        if cidade and cidade not in cidades:
            return False, f"cidade {vaga.get('cidade')}"

    idade_max = int(filtros.get("idade_max_dias") or 0)
    publicada = _data(vaga.get("publicada_em"))
    if idade_max and publicada and (hoje - publicada).days > idade_max:
        return False, f"publicada há {(hoje - publicada).days} dias"

    return True, None
