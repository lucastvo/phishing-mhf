"""
Passo 5a — divide as amostras em desenvolvimento e teste, por estrutura do DOM.

Uso:
    python scripts/dividir.py \
        --tabelas data/similaridades_phish360 data/similaridades_phishpedia_phish data/similaridades_phishpedia_benign \
        --estrutural data/estrutural_phish360.jsonl data/estrutural_phishpedia_phish.jsonl \
                     data/estrutural_phishpedia_benign.jsonl \
        --exclusoes config/exclusoes.json --saida data/divisao.csv

As amostras são as das tabelas de similaridades (passo 4b); o hash do DOM vem do JSONL estrutural do
mesmo dataset, na mesma ordem dos argumentos. O nome do dataset é o do prefixo sem "similaridades_".
Grava <saida> (dataset, id, conjunto, dobra, grupo, estrato) e imprime a cobertura por entidade.

Desenho: docs/especificacoes/2026-11-22-cascata.md, seção 4.
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import divisao  # noqa: E402


def nome_do_dataset(prefixo):
    return os.path.basename(prefixo).removeprefix("similaridades_")


def ler_amostras(prefixos, arquivos_estrutural, exclusoes=frozenset()):
    """Amostras das tabelas (sem as excluídas), com o hash do DOM de cada uma."""
    if len(prefixos) != len(arquivos_estrutural):
        raise ValueError("--tabelas e --estrutural precisam ter o mesmo número de arquivos, na mesma ordem")
    amostras = []
    for prefixo, arq in zip(prefixos, arquivos_estrutural):
        ds = nome_do_dataset(prefixo)
        with open(arq, encoding="utf-8") as f:
            hashes = {d["id"]: d["hash_canonico"] for d in map(json.loads, f)}
        with open(prefixo + ".jsonl", encoding="utf-8") as f:
            for m in map(json.loads, f):
                if (ds, m["id"]) in exclusoes:
                    continue
                amostras.append({"dataset": ds, "id": m["id"], "particao": m.get("particao") or "",
                                 "rotulo": m.get("rotulo"), "entidade": m.get("entidade"),
                                 "marca": m.get("marca") or "", "elementos": m.get("elementos"),
                                 "hash": hashes.get(m["id"])})
    return amostras


def resumo(amostras, linhas):
    """Texto com as contagens por conjunto e dataset e a cobertura de cada estrato (amostras e estruturas)."""
    saida = []
    por_conj = Counter((l["conjunto"], l["dataset"]) for l in linhas)
    saida.append("Amostras por conjunto e dataset:")
    for (c, ds), n in sorted(por_conj.items()):
        saida.append(f"  {c:16s} {ds:20s} {n:6d}")
    movidos = {l["grupo"] for l, a in zip(linhas, amostras)
               if l["conjunto"] == divisao.TESTE and a["dataset"] == "phish360" and a["particao"] == "trainval"}
    saida.append(f"Grupos do trainval do Phish360 levados ao teste (mesma estrutura de uma amostra do test): "
                 f"{len(movidos)}")
    rotulos_por_grupo = defaultdict(set)
    for l in linhas:
        rotulos_por_grupo[l["grupo"]].add(l["estrato"] == "benigno")
    saida.append(f"Grupos com páginas legítimas e phishing juntas: "
                 f"{sum(len(v) > 1 for v in rotulos_por_grupo.values())}")
    saida.append("\nPor estrato: amostras / estruturas no desenvolvimento, no teste e em cada dobra (0–4):")
    por_estrato = defaultdict(lambda: defaultdict(list))
    for l in linhas:
        chave = l["conjunto"] if l["conjunto"] == divisao.TESTE else f"dobra{l['dobra']}"
        por_estrato[l["estrato"]][chave].append(l["grupo"])
        if l["conjunto"] == divisao.DESENVOLVIMENTO:
            por_estrato[l["estrato"]]["dev"].append(l["grupo"])
    for e in sorted(por_estrato, key=lambda e: -len(por_estrato[e]["dev"]) - len(por_estrato[e]["teste"])):
        d = por_estrato[e]
        cel = lambda k: f"{len(d[k])}/{len(set(d[k]))}"  # noqa: E731
        dobras = " ".join(cel(f"dobra{k}") for k in range(divisao.N_DOBRAS_CV))
        saida.append(f"  {e:16s} dev {cel('dev'):>13s} | teste {cel('teste'):>13s} | dobras {dobras}")
    return "\n".join(saida)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    p.add_argument("--tabelas", nargs="+", required=True, help="prefixos das tabelas de similaridades")
    p.add_argument("--estrutural", nargs="+", required=True, help="JSONL estruturais, na mesma ordem")
    p.add_argument("--exclusoes", default="config/exclusoes.json")
    p.add_argument("--saida", default="data/divisao.csv")
    p.add_argument("--semente", type=int, default=0)
    a = p.parse_args()

    exclusoes = divisao.ler_exclusoes(a.exclusoes) if a.exclusoes else set()
    amostras = ler_amostras(a.tabelas, a.estrutural, exclusoes)
    linhas = divisao.dividir(amostras, semente=a.semente)
    divisao.gravar_divisao(a.saida, linhas)
    print(f"{len(linhas)} amostras em {a.saida} ({len(exclusoes)} exclusões pedidas)")
    print(resumo(amostras, linhas))


if __name__ == "__main__":
    main()
