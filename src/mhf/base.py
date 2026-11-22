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
SINAIS_S = ("hash_igual", "jaccard_caminhos", "jaccard_criticos", "sim_contagens")
SINAIS_VIZINHOS = {"h64": ("h", "sim_h64"), "h256": ("h", "sim_h256"), "small": ("e", "cos_small"),
                   "large": ("e", "cos_large"), "caminhos": ("s", "jaccard_caminhos")}
_HASHES = (("phash64", 64), ("phash256", 256))
_CAMPOS_ENTRADA = ("entidade", "variante", "origem", "timestamp")


def palavras_do_hash(h):
    """pHash em hexadecimal (16 ou 64 caracteres) → 1 ou 4 palavras de 64 bits, a mais significativa
    primeiro. A distância de Hamming é a soma de np.bitwise_count do XOR das palavras."""
    if len(h) not in (16, 64):
        raise ValueError(f"hash de {len(h)} caracteres; esperado 16 (64 bits) ou 64 (256 bits)")
    return np.array([int(h[i:i + 16], 16) for i in range(0, len(h), 16)], dtype=np.uint64)


def construir_itens(pares, raiz_templates, visual_linhas, visual_emb, tabela):
    """Itens da base, um por par (entrada aprovada, resolução) de `templates.templates_aprovados`, na
    ordem dos pares, e os embeddings reordenados para essa ordem. `visual_linhas`/`visual_emb` são a
    saída de extrair_visual.py para os templates. Um par sem linha visual faz a construção falhar (a
    base não pode ficar incompleta sem aviso); um par sem DOM fica com s nulo."""
    if not pares:
        raise ValueError("nenhum template aprovado (conferir --plano e --raiz-templates); a base não foi montada")
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
            idx = np.array([i for i, it in enumerate(itens) if it["classe"] == classe], dtype=np.int64)
            grupo = {"indices": idx,
                     "emb": {m: np.ascontiguousarray(emb[m][idx]) for m in MODELOS},
                     "s": [estrutural.ImpressaoEstrutural.de_dict(itens[i]["s"]) if itens[i]["s"] else None
                           for i in idx]}
            for campo, bits in _HASHES:
                grupo[campo] = (np.stack([palavras_do_hash(itens[i][campo]) for i in idx]) if len(idx)
                                else np.zeros((0, bits // 64), dtype=np.uint64))
            self._por_classe[classe] = grupo

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

    def conferir_visual(self, visual_linhas, permitir_sobras=False):
        """Confere a base contra a saída visual atual dos templates (extrair_visual.py): todo item precisa
        ter a linha visual de mesmo id e mesmo pHash de 64 bits (um template recapturado e reextraído sem
        reconstruir a base muda o hash). Linha visual sem item na base também é divergência, a não ser com
        `permitir_sobras` (construir_base: template que deixou de ser aprovado). Levanta ValueError listando
        os ids divergentes."""
        h_visual = {l["id"]: l.get("phash64") for l in visual_linhas}
        problemas = [f"{it['id']} (sem linha visual)" if it["id"] not in h_visual else f"{it['id']} (pHash mudou)"
                     for it in self.itens if h_visual.get(it["id"]) != it["phash64"]]
        if not permitir_sobras:
            ids_base = {it["id"] for it in self.itens}
            problemas += [f"{i} (fora da base)" for i in h_visual if i not in ids_base]
        if problemas:
            raise ValueError("base desatualizada em relação à saída visual dos templates (rodar construir_base.py "
                             "de novo): " + ", ".join(problemas))

    def _grupo(self, classe):
        if classe not in visual.CLASSES_TELA:
            raise ValueError(f"classe deve ser uma de {sorted(visual.CLASSES_TELA)}")
        return self._por_classe[classe]

    def indices(self, classe):
        """Posições na base dos itens dessa classe de tela, em ordem."""
        return self._grupo(classe)["indices"]

    def similaridades(self, consulta, classe, sinais=("h", "e", "s")):
        """Similaridades da página com cada template da sua classe de tela, na ordem de `indices(classe)`.

        `consulta` traz os campos que existirem: "phash64" e "phash256" (hexadecimal), "small" e "large"
        (embeddings de norma 1) e "s" (ImpressaoEstrutural ou None). Nada da página é recalculado aqui.
        `sinais` escolhe o que calcular ("h", "e", "s"); o estágio 1 da cascata só precisa de "h".

        Devolve "indices" e, por sinal pedido:
        - h: dist_h64, dist_h256 (Hamming; −1 se a consulta não tem o hash) e sim_h64, sim_h256 (1 − d/n);
        - e: cos_small, cos_large (produto interno);
        - s: hash_igual, jaccard_caminhos, jaccard_criticos, sim_contagens (estrutural.comparar).
        Similaridade sem dado de um dos lados (consulta ou template sem s, por exemplo) vale NaN."""
        if not set(sinais) <= {"h", "e", "s"}:
            raise ValueError("sinais deve conter só 'h', 'e' e 's'")
        g = self._grupo(classe)
        n = len(g["indices"])
        r = {"indices": g["indices"]}
        if "h" in sinais:
            for campo, bits in _HASHES:
                sufixo = campo.removeprefix("phash")
                if consulta.get(campo):
                    d = np.bitwise_count(g[campo] ^ palavras_do_hash(consulta[campo])).sum(axis=1).astype(np.int64)
                    r[f"dist_h{sufixo}"], r[f"sim_h{sufixo}"] = d, 1 - d / bits
                else:
                    r[f"dist_h{sufixo}"], r[f"sim_h{sufixo}"] = np.full(n, -1, np.int64), np.full(n, np.nan)
        if "e" in sinais:
            for m in MODELOS:
                q = consulta.get(m)
                r[f"cos_{m}"] = (g["emb"][m] @ np.asarray(q, np.float32)).astype(np.float64) if q is not None \
                    else np.full(n, np.nan)
        if "s" in sinais:
            for k in SINAIS_S:
                r[k] = np.full(n, np.nan)
            q = consulta.get("s")
            if q is not None:
                for j, s in enumerate(g["s"]):
                    if s is not None:
                        for k, v in estrutural.comparar(q, s).items():
                            r[k][j] = v
        return r

    def vizinhos(self, consulta, classe, sinal, k=5):
        """Os k templates da classe mais parecidos com a página por um sinal (h64, h256, small, large ou
        caminhos): lista de (índice na base, similaridade), do mais parecido para o menos. Empates ficam
        na ordem da base. Templates sem o sinal (NaN, como um template sem s) ficam de fora; se a consulta
        não tem o sinal (amostra sem HTML útil, por exemplo), a lista sai vazia."""
        if sinal not in SINAIS_VIZINHOS:
            raise ValueError(f"sinal deve ser um de {sorted(SINAIS_VIZINHOS)}")
        grupo_sinal, chave = SINAIS_VIZINHOS[sinal]
        r = self.similaridades(consulta, classe, sinais=(grupo_sinal,))
        valores = r[chave]
        validos = np.flatnonzero(~np.isnan(valores))
        ordem = validos[np.argsort(-valores[validos], kind="stable")][:k]
        return [(int(r["indices"][j]), float(valores[j])) for j in ordem]
