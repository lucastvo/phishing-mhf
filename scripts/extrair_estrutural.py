"""
Extrai a impressão digital estrutural (s) de todas as amostras listadas num índice CSV
gerado por inspecionar_dataset.py e grava uma linha JSON por amostra.

Uso:
    python scripts/extrair_estrutural.py --indice data/phish360.csv \
        --raiz data/Phish360 --saida data/estrutural_phish360.jsonl

Uma amostra que não pode ser lida (arquivo apagado ou bloqueado, por exemplo pelo antivírus) ou que
faz o extrator falhar não interrompe a extração: ela é contada, listada em <saida>.erros.tsv e as
demais seguem. Amostras sem DOM útil (HTML vazio ou só com <body>) também são contadas à parte.
"""

import argparse
import csv
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import estrutural  # noqa: E402


def extrair_linhas(linhas, raiz, out, progresso=1000):
    """Extrai s de cada linha do índice e grava uma linha JSON por amostra em `out`.
    Devolve {"ok": n, "sem_dom": [ids], "erros": [(id, "Tipo: mensagem")]}."""
    resultado = {"ok": 0, "sem_dom": [], "erros": []}
    for i, l in enumerate(linhas, 1):
        try:
            with open(os.path.join(raiz, l["caminho_html"]), "rb") as f:
                s = estrutural.extrair(f.read(), l["url"])
        except Exception as erro:  # leitura bloqueada/apagada ou HTML que quebra o extrator: segue
            resultado["erros"].append((l["id"], f"{type(erro).__name__}: {erro}"))
            continue
        if s is None:
            resultado["sem_dom"].append(l["id"])
            continue
        out.write(json.dumps({"id": l["id"], "particao": l["particao"], "rotulo": l["rotulo"], "marca": l["marca"],
                              "url": l["url"], **s.para_dict()}, ensure_ascii=False) + "\n")
        resultado["ok"] += 1
        if progresso and i % progresso == 0:
            print(f"{i}/{len(linhas)}")
    return resultado


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--indice", required=True)
    p.add_argument("--raiz", required=True)
    p.add_argument("--saida", required=True)
    a = p.parse_args()

    with open(a.indice, encoding="utf-8") as f:
        linhas = [l for l in csv.DictReader(f) if l["html_util"] == "1"]

    inicio = time.perf_counter()
    with open(a.saida, "w", encoding="utf-8") as out:
        r = extrair_linhas(linhas, a.raiz, out)
    dt = time.perf_counter() - inicio

    caminho_erros = a.saida + ".erros.tsv"
    if r["erros"]:
        with open(caminho_erros, "w", encoding="utf-8") as f:
            f.write("id\terro\n")
            f.writelines(f"{id_}\t{erro}\n" for id_, erro in r["erros"])
    elif os.path.exists(caminho_erros):
        os.remove(caminho_erros)  # de uma rodada anterior: não vale para esta

    print(f"Extraídas: {r['ok']} | sem DOM útil: {len(r['sem_dom'])} | erros: {len(r['erros'])}"
          f" | {1000 * dt / max(r['ok'], 1):.1f} ms por página")
    if r["erros"]:
        print(f"Amostras com erro listadas em {caminho_erros} (primeiras: "
              + ", ".join(id_ for id_, _ in r["erros"][:5]) + ")")


if __name__ == "__main__":
    main()
