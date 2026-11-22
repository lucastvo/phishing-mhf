"""
Base de templates e busca (etapa 4).

Um item por par (template aprovado, tamanho de tela), com todos os sinais vindos da mesma captura:
h (pHash de 64 e 256 bits), e (embeddings da MobileNetV3 Small e Large, norma 1) e s (impressão
estrutural do DOM renderizado nesse tamanho de tela), mais a entidade, os metadados do snapshot e os
domínios legítimos da entidade. A busca é exaustiva: com centenas de templates ela é exata e custa
frações de milissegundo, e é a mesma conta que a extensão de navegador fará.

No disco (formatos abertos): base.jsonl (itens, sem embeddings), base_<modelo>.npy (float32, na ordem
do JSONL) e base_meta.json.

Desenho: docs/especificacoes/2026-11-22-base-e-busca.md
"""

import json
import os

import numpy as np

from mhf import estrutural, templates, visual

MODELOS = ("small", "large")
_CAMPOS_ENTRADA = ("entidade", "variante", "origem", "timestamp")


def construir_itens(pares, raiz_templates, visual_linhas, visual_emb, tabela):
    """Itens da base, um por par (entrada aprovada, resolução) de `templates.templates_aprovados`, na
    ordem dos pares, e os embeddings reordenados para essa ordem. `visual_linhas`/`visual_emb` são a
    saída de extrair_visual.py para os templates. Um par sem linha visual faz a construção falhar (a
    base não pode ficar incompleta sem aviso); um par sem DOM fica com s nulo."""
    linha_do_id = {l["id"]: i for i, l in enumerate(visual_linhas)}
    ids = [f"{e['id']}@{r}" for e, r in pares]
    faltando = [i for i in ids if i not in linha_do_id]
    if faltando:
        raise ValueError("templates aprovados sem linha na saída visual (rodar extrair_visual.py de novo): "
                         + ", ".join(faltando))
    dominios = {t["entidade"]: list(t["dominios"]) for t in tabela}

    itens = []
    for (e, r), id_ in zip(pares, ids):
        v = visual_linhas[linha_do_id[id_]]
        caminho_dom = os.path.join(templates.pasta_entrada(raiz_templates, e["id"]), f"dom_{r}.html")
        s = None
        if os.path.exists(caminho_dom):
            with open(caminho_dom, "rb") as f:
                s = estrutural.extrair(f.read(), e.get("url_login", ""))
        itens.append({"id": id_, **{c: e.get(c) for c in _CAMPOS_ENTRADA}, "classe": r,
                      "phash64": v["phash64"], "phash256": v["phash256"],
                      "dominios": dominios[e["entidade"]], "s": s.para_dict() if s else None})
    ordem = [linha_do_id[i] for i in ids]
    emb = {m: np.ascontiguousarray(visual_emb[m][ordem], dtype=np.float32) for m in MODELOS}
    return itens, emb


def gravar(pasta, itens, emb, meta):
    """Grava a base em `pasta`: base.jsonl, base_<modelo>.npy e base_meta.json."""
    os.makedirs(pasta, exist_ok=True)
    with open(os.path.join(pasta, "base.jsonl"), "w", encoding="utf-8") as f:
        f.writelines(json.dumps(i, ensure_ascii=False) + "\n" for i in itens)
    for m in MODELOS:
        np.save(os.path.join(pasta, f"base_{m}.npy"), emb[m].astype(np.float32))
    with open(os.path.join(pasta, "base_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


class Base:
    """Base de templates carregada na memória, com os sinais agrupados por classe de tela."""

    def __init__(self, itens, emb):
        self.itens = itens
        self.emb = emb
        self._por_classe = {}
        for classe in visual.CLASSES_TELA:
            self._por_classe[classe] = np.array([i for i, it in enumerate(itens) if it["classe"] == classe],
                                                dtype=np.int64)

    @classmethod
    def carregar(cls, pasta):
        """Lê a base gravada por `gravar`, conferindo que cada .npy tem uma linha por item e norma 1."""
        with open(os.path.join(pasta, "base.jsonl"), encoding="utf-8") as f:
            itens = [json.loads(l) for l in f]
        emb = {}
        for m in MODELOS:
            v = np.load(os.path.join(pasta, f"base_{m}.npy"))
            if v.shape[0] != len(itens):
                raise ValueError(f"base_{m}.npy tem {v.shape[0]} linhas, base.jsonl tem {len(itens)} itens")
            if len(v) and not np.allclose(np.linalg.norm(v, axis=1), 1, atol=1e-3):
                raise ValueError(f"base_{m}.npy tem vetores sem norma 1")
            emb[m] = v.astype(np.float32)
        return cls(itens, emb)

    def indices(self, classe):
        """Posições na base dos itens dessa classe de tela, em ordem."""
        if classe not in visual.CLASSES_TELA:
            raise ValueError(f"classe deve ser uma de {sorted(visual.CLASSES_TELA)}")
        return self._por_classe[classe]
