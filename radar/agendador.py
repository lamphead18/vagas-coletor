"""Agendador simples em thread: roda a coleta a cada N horas enquanto o app estiver aberto."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Any

from . import afinidade, db, pipeline
from . import config as configuracao

log = logging.getLogger("radar")


class Agendador:
    def __init__(self) -> None:
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None

    def coleta_atrasada(self, config: dict[str, Any]) -> bool:
        with db.conectar() as conexao:
            ultima = db.ultima_coleta_concluida(conexao)
        if not ultima:
            return True
        intervalo = timedelta(hours=float(config["coleta"]["intervalo_horas"]))
        return datetime.fromisoformat(ultima) + intervalo <= datetime.now()

    def rodar_agora(self) -> bool:
        """Dispara uma coleta em segundo plano. Devolve False se já houver uma rodando."""
        if pipeline.estado_execucao["rodando"]:
            return False
        threading.Thread(target=self._coletar, daemon=True).start()
        return True

    def _coletar(self) -> None:
        try:
            config = configuracao.carregar()
            pipeline.executar(config)
            afinidade.processar(config)
        except Exception:
            log.exception("Erro inesperado na coleta")

    def avaliar_agora(self) -> bool:
        """Roda só a avaliação de afinidade em segundo plano."""
        if afinidade.estado_afinidade["rodando"]:
            return False

        def rodar() -> None:
            try:
                afinidade.processar(configuracao.carregar())
            except Exception:
                log.exception("Erro inesperado na avaliação de afinidade")

        threading.Thread(target=rodar, daemon=True).start()
        return True

    def _laco(self) -> None:
        config = configuracao.carregar()
        if config["coleta"].get("coletar_ao_iniciar") and self.coleta_atrasada(config):
            self._coletar()
        while not self._parar.wait(60):
            config = configuracao.carregar()
            if self.coleta_atrasada(config):
                self._coletar()

    def iniciar(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._laco, daemon=True)
            self._thread.start()

    def parar(self) -> None:
        self._parar.set()


agendador = Agendador()
