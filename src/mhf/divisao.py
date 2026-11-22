"""
Divisão das amostras em desenvolvimento e teste, sem vazamento de kits (etapa 5).

O mesmo kit de phishing aparece copiado em milhares de páginas, inclusive em "famílias" diferentes do
Phishpedia. Por isso o grupo de uma amostra é a estrutura do seu DOM (o hash canônico do componente s):
amostras com a mesma estrutura ficam sempre do mesmo lado, e na mesma dobra da validação cruzada.

Regras, nesta ordem:
1. exclusões (config/exclusoes.json) já saem antes;
2. grupo com amostra da partição test oficial do Phish360 → teste, inteiro;
3. grupo com amostra do trainval do Phish360 → desenvolvimento;
4. demais grupos (só Phishpedia): StratifiedGroupKFold(10); dobras 0, 1 e 2 → teste (~30%);
5. no desenvolvimento, StratifiedGroupKFold(5) dá a dobra da validação cruzada.

Desenho: docs/especificacoes/2026-11-22-cascata.md, seção 4.
"""

import csv
import json
from collections import Counter, defaultdict

import numpy as np
from sklearn.model_selection import StratifiedGroupKFold

ELEMENTOS_MIN_S = 6  # com 5 elementos ou menos, o DOM não carrega sinal estrutural (s ausente)
DOBRAS_TESTE = (0, 1, 2)
N_DOBRAS_DIVISAO = 10
N_DOBRAS_CV = 5
DESENVOLVIMENTO, TESTE = "desenvolvimento", "teste"


def s_util(elementos):
    """A amostra tem um DOM com sinal estrutural (HTML útil e mais de 5 elementos)?"""
    return elementos is not None and elementos >= ELEMENTOS_MIN_S


def grupo_da_amostra(a):
    """Estrutura do DOM ("h:<hash>") se o s é útil; senão, um grupo só da amostra."""
    if s_util(a.get("elementos")) and a.get("hash"):
        return f"h:{a['hash']}"
    return f"a:{a['dataset']}:{a['id']}"


def estrato(a):
    """Entidade de 𝒯 do phishing, "fora" (phishing de marca fora de 𝒯), "sem_marca" ou "benigno"."""
    if a.get("rotulo") != "phishing":
        return "benigno"
    if a.get("entidade"):
        return a["entidade"]
    return "fora" if a.get("marca") else "sem_marca"


def _dobras(indices, estratos, grupos, n, semente):
    """Dobra de cada índice por StratifiedGroupKFold(n), na ordem de `indices`."""
    if len({grupos[i] for i in indices}) < n:
        raise ValueError(f"são necessários pelo menos {n} grupos para dividir em {n} dobras")
    dobra = {}
    sgkf = StratifiedGroupKFold(n_splits=n, shuffle=True, random_state=semente)
    y = [estratos[i] for i in indices]
    g = [grupos[i] for i in indices]
    for k, (_, idx_teste) in enumerate(sgkf.split(np.zeros(len(indices)), y, g)):
        for j in idx_teste:
            dobra[indices[j]] = k
    return dobra


def dividir(amostras, semente=0):
    """Conjunto e dobra de cada amostra, na mesma ordem. Cada amostra: dataset, id, particao, rotulo,
    entidade, marca, elementos, hash."""
    n = len(amostras)
    grupos = [grupo_da_amostra(a) for a in amostras]
    estratos = [estrato(a) for a in amostras]
    membros = defaultdict(list)
    for i, g in enumerate(grupos):
        membros[g].append(i)

    conjunto = [None] * n
    for idx in membros.values():
        p360 = [amostras[i].get("particao") for i in idx if amostras[i]["dataset"] == "phish360"]
        destino = TESTE if "test" in p360 else (DESENVOLVIMENTO if p360 else None)
        for i in idx:
            conjunto[i] = destino

    restantes = [i for i in range(n) if conjunto[i] is None]
    if restantes:
        for i, k in _dobras(restantes, estratos, grupos, N_DOBRAS_DIVISAO, semente).items():
            conjunto[i] = TESTE if k in DOBRAS_TESTE else DESENVOLVIMENTO

    dobra = [-1] * n
    dev = [i for i in range(n) if conjunto[i] == DESENVOLVIMENTO]
    if dev:
        for i, k in _dobras(dev, estratos, grupos, N_DOBRAS_CV, semente).items():
            dobra[i] = k
    return [{"dataset": a["dataset"], "id": a["id"], "conjunto": conjunto[i], "dobra": dobra[i],
             "grupo": grupos[i], "estrato": estratos[i]} for i, a in enumerate(amostras)]


def pesos_por_estrutura(linhas):
    """1/(número de amostras do mesmo grupo no mesmo conjunto): cada estrutura de DOM pesa 1."""
    contagem = Counter((l["grupo"], l["conjunto"]) for l in linhas)
    return np.array([1.0 / contagem[(l["grupo"], l["conjunto"])] for l in linhas])


def ler_exclusoes(caminho):
    """Pares (dataset, id) excluídos da avaliação, de config/exclusoes.json."""
    with open(caminho, encoding="utf-8") as f:
        return {(e["dataset"], e["id"]) for e in json.load(f)["exclusoes"]}


def gravar_divisao(caminho, linhas):
    campos = ["dataset", "id", "conjunto", "dobra", "grupo", "estrato"]
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows({c: l[c] for c in campos} for l in linhas)


def ler_divisao(caminho):
    """data/divisao.csv → {(dataset, id): linha}, com a dobra como inteiro."""
    with open(caminho, encoding="utf-8") as f:
        return {(l["dataset"], l["id"]): {**l, "dobra": int(l["dobra"])} for l in csv.DictReader(f)}
