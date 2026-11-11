"""Ponto de entrada.

    python -m radar            abre o app no navegador (http://127.0.0.1:8765)
    python -m radar coletar    roda uma coleta e mostra o resumo no terminal
    python -m radar refiltrar  reaplica os filtros do config.yaml em todas as vagas abertas
    python -m radar avaliar    calcula a afinidade das vagas sem nota (usa as chaves do .env)
"""

from __future__ import annotations

import logging
import sys
import threading
import webbrowser

from . import afinidade, db, pipeline
from . import config as configuracao


def _configurar_log() -> None:
    configuracao.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(configuracao.PASTA_DADOS / "radar.log", encoding="utf-8"),
        ],
    )


def main(argv: list[str]) -> int:
    _configurar_log()
    comando = argv[0] if argv else "web"
    config = configuracao.carregar()
    db.iniciar()

    if comando == "coletar":
        resumo = pipeline.executar(config)
        for fonte, resultado in resumo.items():
            print(f"{fonte}: {resultado}")
        print(f"afinidade: {afinidade.processar(config)}")
        return 0
    if comando == "avaliar":
        print(afinidade.processar(config))
        return 0
    if comando == "refiltrar":
        print(f"Filtro reaplicado em {pipeline.refiltrar_tudo(config)} vagas")
        return 0
    if comando != "web":
        print(__doc__)
        return 1

    import uvicorn

    porta = int(config["servidor"]["porta"])
    endereco = f"http://127.0.0.1:{porta}"
    if "--sem-navegador" not in argv:
        threading.Timer(1.5, lambda: webbrowser.open(endereco)).start()
    print(f"Radar de Vagas rodando em {endereco}  (feche esta janela para parar)")
    uvicorn.run("radar.web.app:app", host="127.0.0.1", port=porta, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
