"""
Passo 4b — tabela de similaridades de todas as amostras de um dataset com os templates da sua classe de tela.

Uso:
    python scripts/similaridades.py --visual data/visual_phish360 --estrutural data/estrutural_phish360.jsonl \
        --dataset phish360 --saida data/similaridades_phish360

A lista de amostras é a da saída visual (todas as capturas legíveis); o s vem do JSONL estrutural, pelo id
(amostra sem HTML útil fica com as colunas de s em NaN). Cada amostra passa por Base.similaridades, o
mesmo caminho do uso real. Saídas:
    <saida>.jsonl  uma linha por amostra, na ordem da saída visual: id, classe, linha_na_classe, rótulo,
                   partição, marca, entidade de 𝒯 (ou null), URL e número de elementos do s (ou null);
    <saida>.npz    por classe de tela, matrizes amostras × templates "<classe>__<sinal>" (dist_h64 uint8,
                   dist_h256 uint16, cossenos e componentes de s em float16) e "<classe>__templates", os
                   índices na base das colunas.

Desenho: docs/especificacoes/2026-11-22-base-e-busca.md
"""

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np  # noqa: E402

from mhf import base, estrutural, marcas  # noqa: E402

TIPOS = {"dist_h64": np.uint8, "dist_h256": np.uint16, "cos_small": np.float16, "cos_large": np.float16,
         **{k: np.float16 for k in base.SINAIS_S}}


def conferir_alinhamento(linhas, emb):
    """Cada .npy da saída visual precisa ter uma linha por linha do JSONL (as saídas são gravadas em
    separado; uma rodada interrompida pode deixá-las desalinhadas)."""
    for m, v in emb.items():
        if v.shape[0] != len(linhas):
            raise ValueError(f"embeddings {m}: {v.shape[0]} linhas para {len(linhas)} amostras no JSONL")


def calcular_tabela(linhas_visual, emb_visual, s_por_id, b, tabela, dataset, progresso=0):
    """Similaridades de cada amostra com os templates da sua classe. Devolve (meta por amostra, matrizes)."""
    conferir_alinhamento(linhas_visual, emb_visual)
    meta, linhas_por_classe = [], defaultdict(lambda: defaultdict(list))
    for i, l in enumerate(linhas_visual, 1):
        s = s_por_id.get(l["id"])
        consulta = {"phash64": l["phash64"], "phash256": l["phash256"], "s": s,
                    **{m: emb_visual[m][i - 1] for m in base.MODELOS}}
        r = b.similaridades(consulta, l["classe"])
        if (r["dist_h64"] < 0).any() or (r["dist_h256"] < 0).any():
            raise ValueError(f"amostra {l['id']} sem pHash")
        grupo = linhas_por_classe[l["classe"]]
        meta.append({"id": l["id"], "classe": l["classe"], "linha_na_classe": len(grupo["dist_h64"]),
                     "rotulo": l.get("rotulo"), "particao": l.get("particao"), "marca": l.get("marca"),
                     "entidade": marcas.entidade_do_rotulo(tabela, dataset, l["marca"]) if l.get("marca") else None,
                     "url": l.get("url"), "elementos": s.contagens.get("elementos") if s else None})
        for sinal in TIPOS:
            grupo[sinal].append(r[sinal])
        if progresso and i % progresso == 0:
            print(f"{i}/{len(linhas_visual)}", flush=True)
    matrizes = {}
    for classe, grupo in linhas_por_classe.items():
        n_templates = len(b.indices(classe))
        for sinal, tipo in TIPOS.items():
            matrizes[f"{classe}__{sinal}"] = np.array(grupo[sinal], dtype=tipo).reshape(len(grupo[sinal]),
                                                                                       n_templates)
        matrizes[f"{classe}__templates"] = np.asarray(b.indices(classe), dtype=np.int64)
    return meta, matrizes


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    p.add_argument("--visual", required=True, help="prefixo da saída de extrair_visual.py do dataset")
    p.add_argument("--estrutural", required=True, help="JSONL de extrair_estrutural.py do dataset")
    p.add_argument("--dataset", required=True, choices=["phish360", "phishpedia"],
                   help="formato dos rótulos de marca (para a entidade de 𝒯)")
    p.add_argument("--base", default="data/base")
    p.add_argument("--visual-templates", default="data/visual_templates",
                   help="prefixo da saída visual dos templates, para conferir que a base está em dia")
    p.add_argument("--marcas", default="config/marcas.json")
    p.add_argument("--saida", required=True)
    a = p.parse_args()

    inicio = time.perf_counter()
    with open(a.visual + ".jsonl", encoding="utf-8") as f:
        linhas = [json.loads(l) for l in f]
    emb = {m: np.load(f"{a.visual}_{m}.npy") for m in base.MODELOS}
    s_por_id = {}
    with open(a.estrutural, encoding="utf-8") as f:
        for l in f:
            d = json.loads(l)
            s_por_id[d["id"]] = estrutural.ImpressaoEstrutural.de_dict(d)
    b = base.Base.carregar(a.base)
    with open(a.visual_templates + ".jsonl", encoding="utf-8") as f:
        b.conferir_visual([json.loads(l) for l in f])

    meta, matrizes = calcular_tabela(linhas, emb, s_por_id, b, marcas.ler_tabela(a.marcas), a.dataset,
                                     progresso=5000)
    with open(a.saida + ".jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(m, ensure_ascii=False) + "\n" for m in meta)
    np.savez_compressed(a.saida + ".npz", **matrizes)

    print(f"{len(meta)} amostras | {time.perf_counter() - inicio:.0f} s no total")
    print("Por classe de tela:", dict(sorted(Counter(m["classe"] for m in meta).items())))
    print(f"Sem s: {sum(m['elementos'] is None for m in meta)} | com entidade de 𝒯: "
          f"{sum(m['entidade'] is not None for m in meta)}")


if __name__ == "__main__":
    main()
