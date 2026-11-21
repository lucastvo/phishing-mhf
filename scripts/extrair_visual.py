"""
Passo 3 — extrai a impressão digital visual (h, e) das capturas de um dataset ou dos templates aprovados.

Uso:
    python scripts/extrair_visual.py --indice data/phish360.csv --raiz data/Phish360 --saida data/visual_phish360
    python scripts/extrair_visual.py --plano config/templates_snapshots.json --raiz-templates data/templates \
        --saida data/visual_templates

Para cada captura: classe de tela (o tamanho de tela dos templates mais próximo), primeira dobra, pHash
de 64 e 256 bits e o embedding da MobileNetV3 de cada modelo pedido (--modelos small,large). Saídas:
    <saida>.jsonl         uma linha por captura: id, classe, tamanho original, hashes, metadados e tempos;
    <saida>_<modelo>.npy  embeddings (float32, norma 1), uma linha por captura, na ordem do JSONL;
    <saida>.erros.tsv     capturas que não puderam ser lidas (a rodada segue sem elas).
As imagens são processadas uma de cada vez, como no uso real, e o tempo de cada etapa é medido à parte:
ler (disco), abrir (decodificar, compor a transparência e recortar a dobra), phash64, phash256 e cada modelo.

Desenho: docs/especificacoes/2026-11-21-componente-visual.md
"""

import argparse
import csv
import io
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np  # noqa: E402

from mhf import templates, visual  # noqa: E402

_CAMPOS_DATASET = ("particao", "rotulo", "marca", "url")
_CAMPOS_TEMPLATE = ("entidade", "variante", "origem", "timestamp")


def itens_de_indice(indice, raiz):
    """Capturas legíveis de um índice CSV gerado por inspecionar_dataset.py."""
    with open(indice, encoding="utf-8") as f:
        return [{"id": l["id"], "caminho": os.path.join(raiz, l["caminho_shot"]),
                 **{c: l[c] for c in _CAMPOS_DATASET}}
                for l in csv.DictReader(f) if l["shot_ok"] == "1"]


def itens_de_pares(pares, raiz_templates):
    """Um item por par (entrada aprovada, resolução) de templates.templates_aprovados; a classe de tela
    é a própria resolução da captura."""
    return [{"id": f"{e['id']}@{r}", "classe": r, "resolucao": r,
             "caminho": os.path.join(templates.pasta_entrada(raiz_templates, e["id"]), f"shot_{r}.png"),
             **{c: e.get(c) for c in _CAMPOS_TEMPLATE}}
            for e, r in pares]


def extrair_itens(itens, embedders, out, progresso=1000):
    """Calcula h e e de cada item, uma imagem de cada vez, e grava uma linha JSON por captura em `out`.
    Devolve {"ids": [...], "emb": {modelo: [vetores]}, "erros": [(id, erro)], "tempos": {etapa: [ms]},
    "contagens": {...}}, com os embeddings na mesma ordem das linhas gravadas. As contagens são as do
    desenho (§5.1 e §5.2): capturas mais baixas que a dobra (usadas como estão) e capturas cuja largura
    difere da largura da classe (ex.: 800x600 na classe 1280x960, sem template do mesmo tamanho)."""
    r = {"ids": [], "emb": {m: [] for m in embedders}, "erros": [],
         "tempos": {etapa: [] for etapa in ("ler", "abrir", "phash64", "phash256", *embedders)},
         "contagens": {"abaixo_da_dobra": 0, "largura_diferente_da_classe": 0}}
    for i, item in enumerate(itens, 1):
        try:
            t0 = time.perf_counter()
            with open(item["caminho"], "rb") as f:
                dados = f.read()
            t1 = time.perf_counter()
            img = visual.abrir_imagem(io.BytesIO(dados))
            classe = item.get("classe") or visual.classe_de_tela(img.width)
            dobra = visual.primeira_dobra(img, classe)
            t2 = time.perf_counter()
            h64 = visual.phash(dobra)
            t3 = time.perf_counter()
            h256 = visual.phash(dobra, bits=256)
            t4 = time.perf_counter()
            tempos = {"ler": (t1 - t0) * 1000, "abrir": (t2 - t1) * 1000,
                      "phash64": (t3 - t2) * 1000, "phash256": (t4 - t3) * 1000}
            vetores = {}
            for modelo, emb in embedders.items():
                t = time.perf_counter()
                vetores[modelo] = emb.embed(dobra)
                tempos[modelo] = (time.perf_counter() - t) * 1000
        except Exception as erro:  # arquivo ausente, imagem ilegível...: registra e segue
            r["erros"].append((item["id"], f"{type(erro).__name__}: {erro}"))
            continue
        extras = {k: v for k, v in item.items() if k not in ("id", "caminho", "classe")}
        out.write(json.dumps({"id": item["id"], "classe": classe, "largura": img.width, "altura": img.height,
                              "phash64": h64, "phash256": h256, **extras,
                              "tempos_ms": {k: round(v, 2) for k, v in tempos.items()}},
                             ensure_ascii=False) + "\n")
        r["ids"].append(item["id"])
        r["contagens"]["abaixo_da_dobra"] += img.height < visual.altura_da_dobra(img.width, classe)
        r["contagens"]["largura_diferente_da_classe"] += img.width != visual.CLASSES_TELA[classe][0]
        for modelo, v in vetores.items():
            r["emb"][modelo].append(v)
        for etapa, ms in tempos.items():
            r["tempos"][etapa].append(ms)
        if progresso and i % progresso == 0:
            print(f"{i}/{len(itens)}", flush=True)
    return r


def _resumo_tempos(tempos):
    linhas = []
    for etapa, ms in tempos.items():
        if ms:
            ordenados = sorted(ms)
            p95 = ordenados[min(len(ordenados) - 1, int(0.95 * len(ordenados)))]
            linhas.append(f"  {etapa:8s} mediana {statistics.median(ordenados):7.1f} ms | p95 {p95:7.1f} ms")
    return "\n".join(linhas)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    origem = p.add_mutually_exclusive_group(required=True)
    origem.add_argument("--indice", help="índice CSV de um dataset (inspecionar_dataset.py)")
    origem.add_argument("--plano", help="plano de templates (config/templates_snapshots.json)")
    p.add_argument("--raiz", help="pasta do dataset (com --indice)")
    p.add_argument("--raiz-templates", help="pasta das capturas dos templates (com --plano)")
    p.add_argument("--saida", required=True, help="prefixo dos arquivos de saída (ex.: data/visual_phish360)")
    p.add_argument("--modelos", default="small,large", help="modelos da MobileNetV3, separados por vírgula")
    a = p.parse_args()

    if a.indice:
        if not a.raiz:
            p.error("--indice exige --raiz")
        itens = itens_de_indice(a.indice, a.raiz)
    else:
        if not a.raiz_templates:
            p.error("--plano exige --raiz-templates")
        with open(a.plano, encoding="utf-8") as f:
            plano = json.load(f)
        itens = itens_de_pares(templates.templates_aprovados(plano, a.raiz_templates), a.raiz_templates)

    embedders = {m: visual.Embedder(m) for m in a.modelos.split(",") if m}
    print(f"{len(itens)} capturas | modelos: {', '.join(embedders)}", flush=True)
    inicio = time.perf_counter()
    with open(a.saida + ".jsonl", "w", encoding="utf-8") as out:
        r = extrair_itens(itens, embedders, out)
    for modelo, vetores in r["emb"].items():
        matriz = np.stack(vetores) if vetores else np.zeros((0, embedders[modelo].dim), np.float32)
        np.save(f"{a.saida}_{modelo}.npy", matriz.astype(np.float32))

    caminho_erros = a.saida + ".erros.tsv"
    if r["erros"]:
        with open(caminho_erros, "w", encoding="utf-8") as f:
            f.write("id\terro\n")
            f.writelines(f"{id_}\t{erro}\n" for id_, erro in r["erros"])
    elif os.path.exists(caminho_erros):
        os.remove(caminho_erros)  # de uma rodada anterior: não vale para esta

    print(f"Extraídas: {len(r['ids'])} | erros: {len(r['erros'])} | {time.perf_counter() - inicio:.0f} s no total")
    c = r["contagens"]
    print(f"Mais baixas que a dobra (usadas como estão): {c['abaixo_da_dobra']} | "
          f"largura diferente da classe: {c['largura_diferente_da_classe']}")
    print("Tempo por imagem (uma de cada vez):\n" + _resumo_tempos(r["tempos"]))


if __name__ == "__main__":
    main()
