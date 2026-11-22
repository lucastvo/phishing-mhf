"""
Passo 4a — monta a base de templates (h, e, s e domínios por par template × tamanho de tela).

Uso:
    python scripts/construir_base.py --plano config/templates_snapshots.json --raiz-templates data/templates \
        --visual data/visual_templates --marcas config/marcas.json --saida data/base

Lê os templates aprovados (templates.templates_aprovados), a saída de extrair_visual.py para eles (h e e)
e o DOM renderizado de cada par (s). Grava <saida>/base.jsonl, base_small.npy, base_large.npy e
base_meta.json.

Desenho: docs/especificacoes/2026-11-22-base-e-busca.md
"""

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from importlib import metadata

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np  # noqa: E402

from mhf import base, marcas, templates  # noqa: E402


def ler_saida_visual(prefixo):
    """Linhas do JSONL e embeddings de cada modelo de uma saída de extrair_visual.py, conferindo que cada
    .npy tem uma linha por linha do JSONL."""
    with open(prefixo + ".jsonl", encoding="utf-8") as f:
        linhas = [json.loads(l) for l in f]
    emb = {m: np.load(f"{prefixo}_{m}.npy") for m in base.MODELOS}
    for m, v in emb.items():
        if v.shape[0] != len(linhas):
            raise ValueError(f"{prefixo}_{m}.npy tem {v.shape[0]} linhas, {prefixo}.jsonl tem {len(linhas)}")
    return linhas, emb


def _versao(pacote):
    try:
        return metadata.version(pacote)
    except metadata.PackageNotFoundError:
        return None


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    p.add_argument("--plano", default="config/templates_snapshots.json")
    p.add_argument("--raiz-templates", default="data/templates")
    p.add_argument("--visual", default="data/visual_templates", help="prefixo da saída de extrair_visual.py")
    p.add_argument("--marcas", default="config/marcas.json")
    p.add_argument("--saida", default="data/base")
    a = p.parse_args()

    inicio = time.perf_counter()
    with open(a.plano, encoding="utf-8") as f:
        plano = json.load(f)
    pares = templates.templates_aprovados(plano, a.raiz_templates)
    linhas, emb = ler_saida_visual(a.visual)
    itens, emb_base = base.construir_itens(pares, a.raiz_templates, linhas, emb, marcas.ler_tabela(a.marcas))

    meta = {"construida_em": datetime.now().isoformat(timespec="seconds"), "itens": len(itens),
            "por_classe": dict(sorted(Counter(i["classe"] for i in itens).items())),
            "por_entidade": dict(sorted(Counter(i["entidade"] for i in itens).items())),
            "sem_s": [i["id"] for i in itens if i["s"] is None],
            "versoes": {p_: _versao(p_) for p_ in ("numpy", "lxml", "imagehash", "torch", "torchvision")}}
    base.gravar(a.saida, itens, emb_base, meta)

    print(f"{len(itens)} itens em {a.saida} ({time.perf_counter() - inicio:.1f} s)")
    print("Por classe de tela:", meta["por_classe"])
    print("Por entidade:", meta["por_entidade"])
    print(f"Sem s (DOM ausente ou vazio): {len(meta['sem_s'])}")


if __name__ == "__main__":
    main()
