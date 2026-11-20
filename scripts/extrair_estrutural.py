"""
Extrai a impressão digital estrutural (s) de todas as amostras listadas num índice CSV
gerado por inspecionar_dataset.py e grava uma linha JSON por amostra.

Uso:
    python scripts/extrair_estrutural.py --indice data/phishing.csv \
        --raiz data/phishpedia/phishing --saida data/estrutural_phishing.jsonl
"""

import argparse
import csv
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import estrutural  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--indice", required=True)
    p.add_argument("--raiz", required=True)
    p.add_argument("--saida", required=True)
    a = p.parse_args()

    with open(a.indice, encoding="utf-8") as f:
        linhas = [l for l in csv.DictReader(f) if l["html_util"] == "1"]

    ok = falhas = 0
    inicio = time.perf_counter()
    with open(a.saida, "w", encoding="utf-8") as out:
        for i, l in enumerate(linhas, 1):
            with open(os.path.join(a.raiz, l["id"], "html.txt"), "rb") as f:
                s = estrutural.extrair(f.read(), l["url"])
            if s is None:
                falhas += 1
                continue
            out.write(json.dumps({"id": l["id"], "rotulo": l["rotulo"], "marca": l["marca"],
                                  "url": l["url"], **s.para_dict()}, ensure_ascii=False) + "\n")
            ok += 1
            if i % 1000 == 0:
                print(f"{i}/{len(linhas)}")

    dt = time.perf_counter() - inicio
    print(f"Extraídas: {ok} | sem DOM útil: {falhas} | {1000 * dt / max(ok, 1):.1f} ms por página")


if __name__ == "__main__":
    main()
