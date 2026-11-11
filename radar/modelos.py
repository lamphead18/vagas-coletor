"""Formato comum das vagas que os coletores devolvem."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VagaColetada:
    fonte: str          # "gupy", "indeed", "linkedin", ...
    id_externo: str     # id da vaga na fonte (para não gravar duas vezes)
    titulo: str
    empresa: str | None
    url: str | None
    cidade: str | None = None
    estado_uf: str | None = None
    modelo: str | None = None        # "remoto", "hibrido", "presencial" ou None
    regime: str | None = None        # "CLT", "PJ", "Estágio", ...
    descricao: str | None = None
    publicada_em: str | None = None  # data ISO (AAAA-MM-DD ou com hora)
