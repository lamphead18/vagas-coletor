"""Conversão de descrições (HTML da Gupy, markdown do JobSpy) em texto simples."""

from __future__ import annotations

import html
import re


def texto_da_descricao(valor: str | None) -> str:
    """Converte a descrição (HTML da Gupy ou markdown do JobSpy) em texto simples legível."""
    if not valor:
        return ""
    texto = re.sub(r"(?i)<\s*(br|/p|/li|/h\d|/div)\s*/?>", "\n", valor)
    texto = re.sub(r"(?i)<\s*li[^>]*>", "• ", texto)
    texto = re.sub(r"<[^>]+>", "", texto)
    texto = html.unescape(texto)
    texto = re.sub(r"\*\*|__|^#+\s*", "", texto, flags=re.M)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()
