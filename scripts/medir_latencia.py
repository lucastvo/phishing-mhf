"""
Passo 6b — latência por página do detector principal, em páginas brutas do conjunto de teste.

Uso:
    python scripts/medir_latencia.py \
        --dataset phish360 data/phish360.csv data/Phish360 \
        --dataset phishpedia_phish data/phishpedia_phish.csv data/phish_sample_30k \
        --dataset phishpedia_benign data/phishpedia_benign.csv data/benign_sample_30k 1366x768 \
        --divisao data/divisao.csv --modelo data/modelos/boosting --saida data/avaliacao

Cada --dataset é NOME ÍNDICE RAIZ [CLASSE], com o mesmo nome usado na divisão; a classe de tela é fixada
quando o dataset foi capturado num tamanho conhecido (Phishpedia benign). Sorteia --por-dataset páginas do
teste de cada dataset e analisa uma de cada vez com Detector.analisar_pagina:
- a captura é recortada na primeira dobra e regravada em PNG antes da medição, como a captura da aba
  (captureVisibleTab) no navegador; sem isso, as páginas inteiras do Phishpedia benign (até 85 mil px)
  mediriam o formato do dataset, não o detector;
- a captura e o HTML são lidos do disco antes (no navegador, já estão na memória); a parte "estrutural"
  inclui o parsing do HTML com o lxml, que o navegador não precisaria refazer;
- a MobileNetV3 é carregada antes, com uma página de aquecimento fora da medição.
Grava <saida>/latencia.json, tabelas/latencia.tex e figuras/latencia.pdf, e uma linha em registro.jsonl.

Desenho: docs/especificacoes/2026-11-22-avaliacao.md, seção 5.
"""

import argparse
import csv
import io
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np  # noqa: E402

from mhf import avaliacao, cascata, divisao, figuras, marcas, visual  # noqa: E402
from mhf import base as base_mod  # noqa: E402
from PIL import Image  # noqa: E402

PARTES = (("abrir", "Abrir a captura e recortar a dobra"), ("phash", "pHash"),
          ("busca_h", "Busca pelo pHash"), ("embedding", "Embedding (MobileNetV3 Small)"),
          ("estrutural", "Impressão estrutural (DOM)"), ("busca_es", "Busca por embedding e DOM"),
          ("classificador", "Características e classificador"), ("total", "Total"))


def sortear_paginas(nome, indice, raiz, classe, div, n, rng):
    with open(indice, encoding="utf-8") as f:
        linhas = [l for l in csv.DictReader(f) if l.get("shot_ok") == "1"
                  and div.get((nome, l["id"]), {}).get("conjunto") == divisao.TESTE]
    escolhidas = [linhas[i] for i in sorted(rng.choice(len(linhas), size=min(n, len(linhas)), replace=False))]
    paginas = []
    for l in escolhidas:
        with Image.open(os.path.join(raiz, l["caminho_shot"])) as img:
            img.load()
            largura, altura = visual.tamanho_da_dobra(img.width, classe or visual.classe_de_tela(img.width))
            dobra = img.crop((0, 0, min(largura, img.width), min(altura, img.height)))
        buf = io.BytesIO()
        dobra.save(buf, format="PNG")  # a "captura da aba": só a janela, no mesmo modo de cor (com o alfa)
        imagem = buf.getvalue()
        html = None
        if l.get("html_util") == "1":
            with open(os.path.join(raiz, l["caminho_html"]), "rb") as f:
                html = f.read()
        paginas.append({"dataset": nome, "id": l["id"], "imagem": imagem, "html": html,
                        "url": l.get("url") or l["id"], "classe": classe})
    return paginas


def resumo(valores):
    v = np.sort(np.asarray(valores, dtype=float))
    return {"mediana": float(np.median(v)), "p95": float(v[min(len(v) - 1, int(0.95 * len(v)))]),
            "media": float(v.mean())} if len(v) else {"mediana": None, "p95": None, "media": None}


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    p.add_argument("--dataset", nargs="+", action="append", required=True, metavar="NOME ÍNDICE RAIZ [CLASSE]")
    p.add_argument("--divisao", default="data/divisao.csv")
    p.add_argument("--modelo", default="data/modelos/boosting")
    p.add_argument("--base", default="data/base")
    p.add_argument("--marcas", default="config/marcas.json")
    p.add_argument("--por-dataset", type=int, default=100)
    p.add_argument("--semente", type=int, default=0)
    p.add_argument("--saida", default="data/avaliacao")
    p.add_argument("--sem-pesos", action="store_true", help=argparse.SUPPRESS)  # testes: rede sem pesos
    a = p.parse_args()

    for d in a.dataset:
        if len(d) not in (3, 4):
            p.error("--dataset espera NOME ÍNDICE RAIZ [CLASSE]")
    div = divisao.ler_divisao(a.divisao)
    rng = np.random.default_rng(a.semente)
    paginas = []
    for d in a.dataset:
        do_ds = sortear_paginas(d[0], d[1], d[2], d[3] if len(d) == 4 else None, div, a.por_dataset, rng)
        if not do_ds:
            print(f"Aviso: {d[0]} não tem páginas do teste no índice; fica de fora", flush=True)
        paginas += do_ds
    if not paginas:
        p.error("nenhuma página do teste encontrada nos índices")
    det = cascata.Detector.carregar(a.modelo, base_mod.Base.carregar(a.base), marcas.ler_tabela(a.marcas))
    embedder = visual.Embedder(det.embedding, pesos=not a.sem_pesos)
    print(f"{len(paginas)} páginas do teste; aquecimento...", flush=True)
    aquec = paginas[0]
    det.analisar_pagina(io.BytesIO(aquec["imagem"]), aquec["html"], aquec["url"], aquec["classe"], embedder)

    tempos = []
    for pg in paginas:
        v = det.analisar_pagina(io.BytesIO(pg["imagem"]), pg["html"], pg["url"], pg["classe"], embedder)
        tempos.append({"dataset": pg["dataset"], **v.tempos_ms})
    por_parte = {k: resumo([t[k] for t in tempos if k in t]) for k, _ in PARTES}
    por_dataset = {ds: resumo([t["total"] for t in tempos if t["dataset"] == ds]) for ds, *_ in a.dataset
                   if any(t["dataset"] == ds for t in tempos)}
    r = {"paginas": len(tempos), "por_parte": por_parte, "por_dataset": por_dataset,
         "condicoes": "uma página de cada vez; captura e HTML já na memória; MobileNetV3 carregada antes"}

    os.makedirs(os.path.join(a.saida, "tabelas"), exist_ok=True)
    os.makedirs(os.path.join(a.saida, "figuras"), exist_ok=True)
    with open(os.path.join(a.saida, "latencia.json"), "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    linhas = [[rot, avaliacao.numero(por_parte[k]["mediana"], 2), avaliacao.numero(por_parte[k]["p95"], 2)]
              for k, rot in PARTES]
    linhas += [[f"Total, {ds}", avaliacao.numero(v["mediana"], 2), avaliacao.numero(v["p95"], 2)]
               for ds, v in por_dataset.items()]
    with open(os.path.join(a.saida, "tabelas", "latencia.tex"), "w", encoding="utf-8") as f:
        f.write(avaliacao.tabela_latex(["Parte", "Mediana (ms)", "p95 (ms)"], linhas,
                                       f"Tempo por página do detector principal ({len(tempos)} páginas do teste)",
                                       "tab:latencia", fonte="Elaborada pelo autor."))
    figuras.latencia({rot: por_parte[k]["mediana"] for k, rot in PARTES if k != "total"
                      and por_parte[k]["mediana"] is not None},
                     os.path.join(a.saida, "figuras", "latencia.pdf"))
    with open(os.path.join(a.saida, "registro.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"status": "latencia", "em": datetime.now().isoformat(timespec="seconds"),
                            "paginas": len(tempos), "modelo": a.modelo, "semente": a.semente},
                           ensure_ascii=False) + "\n")
    print("Tempo por página (mediana / p95, ms):")
    for k, rot in PARTES:
        m, q = por_parte[k]["mediana"], por_parte[k]["p95"]
        if m is not None:
            print(f"  {rot:40s} {m:8.2f} / {q:8.2f}")


if __name__ == "__main__":
    main()
