"""
Passo 7 — interface de demonstração: uma página local, no navegador, que analisa exemplos prontos do
conjunto de teste e URLs ao vivo com o detector principal e mostra o veredito e o porquê.

Uso:
    python scripts/interface.py            # abre http://127.0.0.1:8000

Os exemplos vêm de config/exemplos_interface.json e são lidos direto das pastas dos datasets; os caminhos
ficam em data/interface/datasets.json, gravado por scripts/escolher_exemplos.py. Sem esse arquivo, a aba de
exemplos explica como gerá-lo e a análise por URL continua funcionando.

Desenho: docs/especificacoes/2026-11-22-interface.md.
"""

import argparse
import io
import os
import sys
import webbrowser

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PIL import Image  # noqa: E402

from mhf import base as base_mod  # noqa: E402
from mhf import captura, cascata, divisao, exemplos, marcas, servidor, visual  # noqa: E402


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    p.add_argument("--modelo", default="data/modelos/boosting")
    p.add_argument("--base", default="data/base")
    p.add_argument("--marcas", default="config/marcas.json")
    p.add_argument("--templates", default="data/templates", help="pasta das capturas dos templates")
    p.add_argument("--exemplos", default="config/exemplos_interface.json")
    p.add_argument("--datasets", default="data/interface/datasets.json")
    p.add_argument("--divisao", default="data/divisao.csv")
    p.add_argument("--porta", type=int, default=8000)
    p.add_argument("--nao-abrir", action="store_true", help="não abrir o navegador do sistema")
    p.add_argument("--sem-navegador", action="store_true", help="desliga a análise por URL (sem Playwright)")
    p.add_argument("--sem-pesos", action="store_true", help=argparse.SUPPRESS)  # testes
    a = p.parse_args()

    print("Carregando a base, o detector e a MobileNetV3...")
    tabela = marcas.ler_tabela(a.marcas)
    det = cascata.Detector.carregar(a.modelo, base_mod.Base.carregar(a.base), tabela)
    div = divisao.ler_divisao(a.divisao) if os.path.exists(a.divisao) else {}
    lista, urls = exemplos.ler_exemplos(a.exemplos, a.datasets, div) if os.path.exists(a.exemplos) else ([], [])
    embedder = visual.Embedder(det.embedding, pesos=not a.sem_pesos)
    buf = io.BytesIO()
    Image.new("RGB", visual.CLASSES_TELA["1366x768"], "white").save(buf, format="PNG")
    det.analisar_pagina(io.BytesIO(buf.getvalue()), None, "http://aquecimento.test/", classe="1366x768",
                        embedder=embedder)  # a primeira análise é mais lenta (alocação da rede)
    disponiveis = sum(e.disponivel for e in lista)
    print(f"Exemplos: {disponiveis} de {len(lista)} disponíveis.")
    for e in lista:
        if not e.disponivel:
            print(f"  exemplo {e.numero} indisponível: {e.motivo}")

    app = servidor.Aplicacao(det, embedder, tabela, a.templates, lista, urls,
                             navegador=None if a.sem_navegador else captura.NavegadorAoVivo())
    try:
        srv = servidor.criar_servidor(app, a.porta)
    except OSError as erro:
        app.fechar()
        sys.exit(f"Não foi possível usar a porta {a.porta} ({erro}); tente outra com --porta.")
    endereco = f"http://127.0.0.1:{srv.server_address[1]}"
    print(f"Pronto: {endereco} (Ctrl+C para sair)")
    if not a.nao_abrir:
        webbrowser.open(endereco)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.fechar()
        srv.server_close()
        print("Interface encerrada.")


if __name__ == "__main__":
    main()
