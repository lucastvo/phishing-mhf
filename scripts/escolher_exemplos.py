"""
Passo 7a — propõe candidatos a exemplos da interface, só do conjunto de teste.

Uso:
    python scripts/escolher_exemplos.py \
        --dataset phish360 <Downloads>/phish360.csv <Downloads>/phish360/Phish360 \
        --dataset phishpedia_phish <Downloads>/phishpedia_phish.csv <Downloads>/phishpedia/phish/phish_sample_30k \
        --dataset phishpedia_benign <Downloads>/phishpedia_benign.csv <Downloads>/phishpedia/benign/benign_sample_30k 1366x768

1. Fase A (tabelas de similaridades): veredito de cada página do teste pelo detector salvo e o tipo de
   candidato (acerto de marca, marca errada, phishing não detectado, alerta falso...); sorteia até
   --por-grupo páginas por (tipo, rótulo real, dataset).
2. Fase B (páginas brutas): analisa cada sorteada com Detector.analisar_pagina, como a interface fará, e
   grava <saida>/candidatos.json, uma folha de contato por tipo (<saida>/folha_<tipo>.jpg) e
   <saida>/datasets.json (caminhos locais dos índices e raízes, que a interface usa).

A escolha final dos 12 exemplos é feita olhando as folhas e vai para config/exemplos_interface.json. Nada
aqui é métrica: o conjunto de teste já foi avaliado (etapa 6) e esta seleção não entra no registro.

Desenho: docs/especificacoes/2026-11-22-interface.md, seção 6.
"""

import argparse
import csv
import io
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np  # noqa: E402

from mhf import base as base_mod  # noqa: E402
from mhf import cascata, divisao, exemplos, marcas, visual  # noqa: E402
from mhf.conjuntos import carregar_conjunto  # noqa: E402

TABELAS_PADRAO = ["data/similaridades_phish360", "data/similaridades_phishpedia_phish",
                  "data/similaridades_phishpedia_benign"]


def _veredito(rotulo, entidade, motivo, escore):
    return {"rotulo": rotulo, "entidade": entidade, "motivo": motivo,
            "escore": None if escore is None or np.isnan(escore) else round(float(escore), 4)}


def fase_a(a, b, tabela, info, modelo, rng):
    """Veredito pela tabela de cada página do teste e sorteio por (tipo, estrato, dataset)."""
    div = divisao.ler_divisao(a.divisao)
    c = carregar_conjunto(a.tabelas, div, b, tabela, divisao.TESTE, info["caracteristicas"]["nomes"])
    cal = info["cascata"]
    escores = cascata.pontuar_amostras(modelo, c["X"])
    r = cascata.aplicar_cascata(c["d1"], c["t1"], escores, c["legit"], cal.get("theta_h"), cal["tau"])
    grupos = defaultdict(list)
    for i, m in enumerate(c["meta"]):
        e = int(r["entidade"][i])
        entidade = c["entidades"][e] if e >= 0 else None
        rotulo = "phishing" if r["phishing"][i] else "legitima"
        tipo = exemplos.tipo_do_candidato(m["estrato"], rotulo, entidade, r["motivo"][i], bool(c["s_ausente"][i]))
        grupos[(tipo, m["estrato"], m["dataset"])].append(
            {"dataset": m["dataset"], "id": m["id"], "tipo": tipo, "estrato": m["estrato"],
             "marca_dataset": m.get("marca") or "", "url": m.get("url") or m["id"],
             "tabela": _veredito(rotulo, entidade, r["motivo"][i], float(r["escore"][i]))})
    sorteados = []
    for chave in sorted(grupos):
        lista = grupos[chave]
        for k in sorted(rng.choice(len(lista), size=min(a.por_grupo, len(lista)), replace=False)):
            sorteados.append(lista[int(k)])
    return sorteados, len(c["meta"])


def _ler_indice(caminho):
    with open(caminho, encoding="utf-8") as f:
        return {l["id"]: l for l in csv.DictReader(f)}


def fase_b(sorteados, datasets, det, embedder):
    """Analisa cada sorteada a partir da página bruta, como a interface."""
    indices = {nome: _ler_indice(info["indice"]) for nome, info in datasets.items()}
    candidatos, imagens = [], []
    for cand in sorteados:
        info = datasets.get(cand["dataset"])
        linha = indices.get(cand["dataset"], {}).get(cand["id"]) if info else None
        if linha is None:
            print(f"  sem página bruta para {cand['dataset']}/{cand['id']} (dataset fora de --dataset?)")
            continue
        try:
            p = exemplos.ler_pagina_do_dataset(linha, info["raiz"], info["classe"])
        except OSError as erro:
            print(f"  não foi possível ler {cand['dataset']}/{cand['id']}: {erro}")
            continue
        v = det.analisar_pagina(io.BytesIO(p["imagem"]), p["html"], p["url"], classe=p["classe"], embedder=embedder)
        pagina = _veredito(v.rotulo, v.entidade, v.motivo, v.escore)
        t = cand["tabela"]
        concorda = pagina["rotulo"] == t["rotulo"] and (pagina["rotulo"] != "phishing" or
                                                        pagina["entidade"] == t["entidade"])
        candidatos.append({"numero": len(candidatos) + 1, **cand, "pagina": pagina, "concorda": concorda})
        imagens.append(p["imagem"])
    return candidatos, imagens


def _legenda(cand):
    p = cand["pagina"]
    veredito = f"phishing de {p['entidade']}" if p["rotulo"] == "phishing" else "legítima"
    escore = "—" if p["escore"] is None else f"{p['escore']:.3f}".replace(".", ",")
    return f"{cand['numero']} · {veredito} ({escore})"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    p.add_argument("--dataset", nargs="+", action="append", required=True, metavar="NOME ÍNDICE RAIZ [CLASSE]")
    p.add_argument("--tabelas", nargs="+", default=TABELAS_PADRAO)
    p.add_argument("--divisao", default="data/divisao.csv")
    p.add_argument("--modelo", default="data/modelos/boosting")
    p.add_argument("--base", default="data/base")
    p.add_argument("--marcas", default="config/marcas.json")
    p.add_argument("--por-grupo", type=int, default=3)
    p.add_argument("--semente", type=int, default=0)
    p.add_argument("--saida", default="data/interface")
    p.add_argument("--sem-pesos", action="store_true", help=argparse.SUPPRESS)  # testes
    a = p.parse_args()

    datasets = {}
    for item in a.dataset:
        if len(item) not in (3, 4):
            p.error("cada --dataset é NOME ÍNDICE RAIZ [CLASSE]")
        classe = item[3] if len(item) == 4 else None
        if classe is not None and classe not in visual.CLASSES_TELA:
            p.error(f"classe desconhecida: {classe}")
        datasets[item[0]] = {"indice": os.path.abspath(item[1]), "raiz": os.path.abspath(item[2]), "classe": classe}

    tabela = marcas.ler_tabela(a.marcas)
    b = base_mod.Base.carregar(a.base)
    modelo, info = cascata.carregar_modelo(a.modelo)
    det = cascata.Detector(b, modelo, info, tabela)
    rng = np.random.default_rng(a.semente)

    print("Fase A: vereditos pelas tabelas de similaridades (só o conjunto de teste)...")
    sorteados, n_teste = fase_a(a, b, tabela, info, modelo, rng)
    print(f"  {n_teste} páginas do teste; {len(sorteados)} sorteadas")
    print("Fase B: análise das páginas brutas...")
    embedder = visual.Embedder(det.embedding, pesos=not a.sem_pesos)
    candidatos, imagens = fase_b(sorteados, datasets, det, embedder)

    os.makedirs(a.saida, exist_ok=True)
    with open(os.path.join(a.saida, "candidatos.json"), "w", encoding="utf-8") as f:
        json.dump(candidatos, f, ensure_ascii=False, indent=1)
    por_tipo = defaultdict(list)
    for cand, img in zip(candidatos, imagens):
        por_tipo[cand["tipo"]].append({"imagem": img, "legenda": _legenda(cand)})
    for tipo, itens in sorted(por_tipo.items()):
        exemplos.folha_de_contato(itens, os.path.join(a.saida, f"folha_{tipo}.jpg"))
    exemplos.gravar_datasets(os.path.join(a.saida, "datasets.json"), datasets)

    print(f"\n{len(candidatos)} candidatos em {a.saida}/candidatos.json "
          f"({sum(not c['concorda'] for c in candidatos)} com veredito diferente entre tabela e página):")
    for tipo, itens in sorted(por_tipo.items()):
        print(f"  {tipo}: {len(itens)}")


if __name__ == "__main__":
    main()
