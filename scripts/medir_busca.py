"""
Passo 4c — mede a busca na base real: exaustiva (a do código) × FAISS exato, uma consulta de cada vez.

Uso:
    python scripts/medir_busca.py --base data/base \
        --consultas data/visual_phish360 data/visual_phishpedia_phish data/visual_phishpedia_benign \
        --estrutural data/estrutural_phish360.jsonl data/estrutural_phishpedia_phish.jsonl \
                     data/estrutural_phishpedia_benign.jsonl

Por classe de tela, sorteia até --por-classe amostras das saídas visuais e mede, por consulta:
- o 1º vizinho por h64, Small e Large: pela busca do código (Base.vizinhos, que calcula também o h de 256
  bits quando o sinal é h), pelo núcleo numpy isolado e pelo FAISS (IndexBinaryFlat / IndexFlatIP);
- o s contra todos os templates da classe e a busca completa (h, e e s) de Base.similaridades;
- a concordância: fração de consultas em que Base.vizinhos e o FAISS acham um 1º vizinho com a mesma
  similaridade.
É o único lugar do projeto que usa o FAISS: a base usa a busca exaustiva (desenho, seção 4).

Desenho: docs/especificacoes/2026-11-22-base-e-busca.md
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import faiss  # noqa: E402
import numpy as np  # noqa: E402

from mhf import base, estrutural, visual  # noqa: E402

SINAIS = ("h64", "small", "large")


class _Classe:
    """Os dados de uma classe de tela nos dois formatos: arrays para a busca exaustiva e índices FAISS."""

    def __init__(self, b, classe):
        self.idx = b.indices(classe)
        self.h64 = np.stack([base.palavras_do_hash(b.itens[i]["phash64"]) for i in self.idx]) if len(self.idx) \
            else np.zeros((0, 1), np.uint64)
        self.emb = {m: np.ascontiguousarray(b.emb[m][self.idx]) for m in base.MODELOS}
        self.faiss = {"h64": faiss.IndexBinaryFlat(64)}
        self.faiss["h64"].add(np.ascontiguousarray(self.h64).view(np.uint8).reshape(-1, 8))
        for m in base.MODELOS:
            self.faiss[m] = faiss.IndexFlatIP(self.emb[m].shape[1])
            self.faiss[m].add(self.emb[m])

    def exaustivo(self, consulta, sinal):
        if sinal == "h64":
            d = np.bitwise_count(self.h64 ^ consulta).sum(axis=1)
            j = int(np.argmin(d))
            return int(self.idx[j]), 1 - float(d[j]) / 64
        s = self.emb[sinal] @ consulta
        j = int(np.argmax(s))
        return int(self.idx[j]), float(s[j])

    def via_faiss(self, consulta, sinal):
        if sinal == "h64":
            d, i = self.faiss["h64"].search(np.ascontiguousarray(consulta).view(np.uint8).reshape(1, 8), 1)
            return int(self.idx[i[0, 0]]), 1 - float(d[0, 0]) / 64
        s, i = self.faiss[sinal].search(consulta.reshape(1, -1), 1)
        return int(self.idx[i[0, 0]]), float(s[0, 0])


def _consulta_do_sinal(consultas, sinal, q):
    if sinal == "h64":
        return base.palavras_do_hash(consultas["phash64"][q])
    return np.ascontiguousarray(consultas[sinal][q], dtype=np.float32)


def _topo(b, classe, consultas, sinal, metodo):
    c = _Classe(b, classe)
    n = len(consultas["phash64"])
    res = [getattr(c, metodo)(_consulta_do_sinal(consultas, sinal, q), sinal) for q in range(n)]
    return np.array([r[0] for r in res]), np.array([r[1] for r in res])


def _consulta_base(consultas, sinal, q):
    """Consulta no formato de Base.similaridades/vizinhos, só com o campo do sinal."""
    campo = "phash64" if sinal == "h64" else sinal
    return {campo: consultas[campo][q]}


def topo_exaustivo(b, classe, consultas, sinal):
    """Índice na base e similaridade do 1º vizinho de cada consulta pela busca do código (Base.vizinhos)."""
    res = [b.vizinhos(_consulta_base(consultas, sinal, q), classe, sinal, k=1)[0]
           for q in range(len(consultas["phash64"]))]
    return np.array([r[0] for r in res]), np.array([r[1] for r in res])


def topo_faiss(b, classe, consultas, sinal):
    """O mesmo pelo FAISS exato (IndexBinaryFlat para h64, IndexFlatIP para os embeddings)."""
    return _topo(b, classe, consultas, sinal, "via_faiss")


def concordancia(sim_a, sim_b, tol=1e-5):
    """Fração de consultas em que os dois métodos acham um 1º vizinho com a mesma similaridade. Compara o
    valor, não o índice: em empate, cada método pode devolver um template diferente, igualmente certo."""
    return float(np.mean(np.abs(np.asarray(sim_a) - np.asarray(sim_b)) <= tol))


def _sortear_consultas(prefixos, arquivos_s, por_classe, semente):
    """Até `por_classe` amostras por classe de tela, sorteadas das saídas visuais, com h, e e s."""
    candidatos = {c: [] for c in visual.CLASSES_TELA}
    dados = []
    for p in prefixos:
        with open(p + ".jsonl", encoding="utf-8") as f:
            linhas = [json.loads(l) for l in f]
        emb = {m: np.load(f"{p}_{m}.npy", mmap_mode="r") for m in base.MODELOS}
        for m, v in emb.items():
            if v.shape[0] != len(linhas):
                raise ValueError(f"{p}_{m}.npy desalinhado do JSONL")
        dados.append((linhas, emb))
        for i, l in enumerate(linhas):
            candidatos[l["classe"]].append((len(dados) - 1, i))
    rng = np.random.default_rng(semente)
    escolhidos = {}
    for c, lista in candidatos.items():
        if lista:
            pos = rng.choice(len(lista), size=min(por_classe, len(lista)), replace=False)
            escolhidos[c] = [lista[k] for k in sorted(pos)]
    ids = {dados[d][0][i]["id"] for lst in escolhidos.values() for d, i in lst}
    s_por_id = {}
    for arq in arquivos_s or []:
        with open(arq, encoding="utf-8") as f:
            for l in f:
                d = json.loads(l)
                if d["id"] in ids:
                    s_por_id[d["id"]] = estrutural.ImpressaoEstrutural.de_dict(d)
    consultas = {}
    for c, lst in escolhidos.items():
        ls = [dados[d][0][i] for d, i in lst]
        consultas[c] = {"phash64": [l["phash64"] for l in ls], "phash256": [l["phash256"] for l in ls],
                        "s": [s_por_id.get(l["id"]) for l in ls],
                        **{m: np.stack([dados[d][1][m][i] for d, i in lst]).astype(np.float32)
                           for m in base.MODELOS}}
    return consultas


def _mediana_p95(valores):
    v = np.sort(np.asarray(valores))
    return float(np.median(v)), float(v[min(len(v) - 1, int(0.95 * len(v)))])


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    p.add_argument("--base", default="data/base")
    p.add_argument("--consultas", nargs="+", required=True, help="prefixos de saídas de extrair_visual.py")
    p.add_argument("--estrutural", nargs="*", default=[], help="JSONL de extrair_estrutural.py dos mesmos datasets")
    p.add_argument("--por-classe", type=int, default=2000)
    p.add_argument("--semente", type=int, default=0)
    a = p.parse_args()

    b = base.Base.carregar(a.base)
    consultas = _sortear_consultas(a.consultas, a.estrutural, a.por_classe, a.semente)
    print(f"FAISS {faiss.__version__}, numpy {np.__version__}; uma consulta de cada vez; tempos: mediana (p95)\n")
    print("| Classe | Templates | Consultas | Sinal | Base.vizinhos (µs) | Núcleo numpy (µs) | FAISS (µs) | "
          "Concordância Base.vizinhos × FAISS |")
    print("|---|---|---|---|---|---|---|---|")
    extras = []
    for classe, q in sorted(consultas.items()):
        c = _Classe(b, classe)
        n = len(q["phash64"])
        if not len(c.idx):
            continue
        for sinal in SINAIS:
            tempos = {"vizinhos": [], "exaustivo": [], "via_faiss": []}
            sims = {"vizinhos": [], "via_faiss": []}
            for k in range(n):
                x = _consulta_do_sinal(q, sinal, k)
                consulta = _consulta_base(q, sinal, k)
                t = time.perf_counter()
                _, sim = b.vizinhos(consulta, classe, sinal, k=1)[0]
                tempos["vizinhos"].append((time.perf_counter() - t) * 1e6)
                sims["vizinhos"].append(sim)
                for metodo in ("exaustivo", "via_faiss"):
                    t = time.perf_counter()
                    _, sim = getattr(c, metodo)(x, sinal)
                    tempos[metodo].append((time.perf_counter() - t) * 1e6)
                    if metodo == "via_faiss":
                        sims[metodo].append(sim)
            colunas = " | ".join("{:.1f} ({:.1f})".format(*_mediana_p95(tempos[m]))
                                 for m in ("vizinhos", "exaustivo", "via_faiss"))
            print(f"| {classe} | {len(c.idx)} | {n} | {sinal} | {colunas} | "
                  f"{concordancia(sims['vizinhos'], sims['via_faiss']):.1%} |")
        t_s, t_tudo = [], []
        for k in range(n):
            consulta = {"phash64": q["phash64"][k], "phash256": q["phash256"][k], "s": q["s"][k],
                        **{m: q[m][k] for m in base.MODELOS}}
            if consulta["s"] is not None:
                t = time.perf_counter()
                b.similaridades(consulta, classe, sinais=("s",))
                t_s.append((time.perf_counter() - t) * 1000)
            t = time.perf_counter()
            b.similaridades(consulta, classe)
            t_tudo.append((time.perf_counter() - t) * 1000)
        extras.append((classe, len(t_s), _mediana_p95(t_s) if t_s else (float("nan"),) * 2, _mediana_p95(t_tudo)))

    print("\n| Classe | Consultas com s | s contra a classe (ms) | Busca completa h + e + s (ms) |")
    print("|---|---|---|---|")
    for classe, n_s, (ms, ps), (mt, pt) in extras:
        print(f"| {classe} | {n_s} | {ms:.2f} ({ps:.2f}) | {mt:.2f} ({pt:.2f}) |")


if __name__ == "__main__":
    main()
