"""
Conjuntos de amostras prontos para a cascata, a partir das tabelas de similaridades (etapas 5 e 6).

Para cada amostra de um conjunto (desenvolvimento, teste ou todos): as características do estágio 2 por
entidade, d₁ e t₁ do estágio 1, a matriz de domínios legítimos e os rótulos. Usado pelo treino, pela
verificação e pela avaliação.
"""

import json
import os

import numpy as np

from mhf import cascata, divisao


def nome_do_dataset(prefixo):
    return os.path.basename(prefixo).removeprefix("similaridades_")


def carregar_conjunto(prefixos, divisao_por_chave, b, tabela, conjunto, nomes):
    """Características, estágio 1 e rótulos das amostras de um conjunto ("desenvolvimento", "teste" ou
    None para todas as da divisão), a partir das tabelas de similaridades. Amostras fora da divisão
    (excluídas) ficam de fora. URL vazia (Phishpedia benign) → o id, que é o domínio, vira o host."""
    entidades = sorted({it["entidade"] for it in b.itens})
    ent_base = np.array([it["entidade"] for it in b.itens])
    meta, Xs, d1s, t1s, legits = [], [], [], [], []
    for prefixo in prefixos:
        ds = nome_do_dataset(prefixo)
        with open(prefixo + ".jsonl", encoding="utf-8") as f:
            linhas = [json.loads(l) for l in f]
        z = np.load(prefixo + ".npz")
        for classe in sorted({l["classe"] for l in linhas}):
            da_classe = [l for l in linhas if l["classe"] == classe]
            if z[f"{classe}__dist_h64"].shape[0] != len(da_classe):
                raise ValueError(f"{prefixo}: {len(da_classe)} amostras de {classe} no JSONL e "
                                 f"{z[f'{classe}__dist_h64'].shape[0]} linhas na matriz")
            sel = []
            for l in da_classe:
                d = divisao_por_chave.get((ds, l["id"]))
                if d is not None and (conjunto is None or d["conjunto"] == conjunto):
                    sel.append((l, d))
            if not sel:
                continue
            rows = np.array([l["linha_na_classe"] for l, _ in sel])
            sub = {k: z[k][rows] for k in z.files if k.startswith(f"{classe}__") and k != f"{classe}__templates"}
            sinais = cascata.sinais_da_tabela(sub, classe)
            colunas = ent_base[z[f"{classe}__templates"]]
            s_ausente = np.array([not divisao.s_util(l.get("elementos")) for l, _ in sel])
            Xs.append(cascata.caracteristicas(sinais, colunas, entidades, s_ausente, nomes))
            d1, t1 = cascata.estagio1(sinais["dist_h64"], colunas, entidades)
            d1s.append(d1)
            t1s.append(t1)
            legits.append(cascata.matriz_dominio_legitimo([l.get("url") or l["id"] for l, _ in sel],
                                                          entidades, tabela))
            meta += [{**l, "dataset": ds, "conjunto": d["conjunto"], "dobra": d["dobra"], "grupo": d["grupo"],
                      "estrato": d["estrato"]} for l, d in sel]
    rotulo = np.array([m["rotulo"] for m in meta])
    entidade_real = np.array([m["entidade"] if m["rotulo"] == "phishing" else None for m in meta], dtype=object)
    phishing_T = (rotulo == "phishing") & np.array([e is not None for e in entidade_real])
    return {"meta": meta, "entidades": entidades, "nomes": nomes,
            "X": np.concatenate(Xs) if Xs else np.zeros((0, len(entidades), len(nomes)), np.float32),
            "d1": np.concatenate(d1s) if d1s else np.zeros(0, int),
            "t1": np.concatenate(t1s) if t1s else np.zeros(0, int),
            "legit": np.concatenate(legits) if legits else np.zeros((0, len(entidades)), bool),
            "entidade_real": entidade_real, "phishing_T": phishing_T, "legitima": rotulo == "benigno",
            "fora_T": (rotulo == "phishing") & ~phishing_T,
            "pesos": divisao.pesos_por_estrutura(meta) if meta else np.zeros(0),
            "dobra": np.array([m["dobra"] for m in meta]), "dataset": np.array([m["dataset"] for m in meta])}
