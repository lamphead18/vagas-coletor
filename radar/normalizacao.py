"""Normalização de texto e chave de deduplicação."""

from __future__ import annotations

import re
import unicodedata

_SUFIXOS_EMPRESA = re.compile(
    r"\b(ltda|s\.?\s?a\.?|sa|eireli|me|epp|inc|llc|ltd|corp)\b"
)
_NAO_ALFANUM = re.compile(r"[^a-z0-9]+")


def sem_acentos(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def normalizar(texto: str | None) -> str:
    """Minúsculas, sem acentos, só letras e números separados por espaço."""
    texto = sem_acentos(texto or "").lower()
    return _NAO_ALFANUM.sub(" ", texto).strip()


def normalizar_empresa(nome: str | None) -> str:
    texto = sem_acentos(nome or "").lower()
    texto = _SUFIXOS_EMPRESA.sub(" ", texto)
    return _NAO_ALFANUM.sub(" ", texto).strip()


def chave_dedup(empresa: str | None, titulo: str | None, cidade: str | None, modelo: str | None) -> str:
    """Mesma empresa + mesmo título + mesma cidade = mesma vaga, venha de onde vier.

    Vagas remotas usam 'remoto' no lugar da cidade, porque cada site escreve o local de um jeito.
    """
    lugar = "remoto" if modelo == "remoto" else normalizar(cidade)
    return "|".join([normalizar_empresa(empresa), normalizar(titulo), lugar])


def contem_termo(texto: str | None, termos: list[str]) -> str | None:
    """Devolve o primeiro termo encontrado no texto (comparação sem acentos), ou None."""
    alvo = f" {normalizar(texto)} "
    for termo in termos:
        termo_norm = normalizar(termo)
        if termo_norm and f" {termo_norm} " in alvo:
            return termo
    return None
