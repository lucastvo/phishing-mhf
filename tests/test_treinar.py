import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import base, divisao  # noqa: E402

_CAMINHO = os.path.join(os.path.dirname(__file__), "..", "scripts", "treinar.py")
_spec = importlib.util.spec_from_file_location("treinar", _CAMINHO)
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

CLASSE = "1366x768"
TABELA = [{"entidade": "PayPal", "dominios": ["paypal.com"]}, {"entidade": "Netflix", "dominios": ["netflix.com"]}]
S_VAZIO = {"hash_canonico": "t", "caminhos": ["/body"], "xpaths_criticos": [], "contagens": {"elementos": 40}}


def _norm(v):
    return (v / np.linalg.norm(v, axis=-1, keepdims=True)).astype(np.float32)


def montar_cenario(pasta, n_por_tipo=40, semente=0):
    """Base com 2 templates de PayPal e 2 de Netflix (1366x768) e tabelas sintéticas em que o phishing de
    cada marca tem pHash perto e cosseno alto com os templates dela. Devolve os caminhos."""
    rng = np.random.default_rng(semente)
    entidades_t = ["PayPal", "PayPal", "Netflix", "Netflix"]
    itens = [{"id": f"t{i}@{CLASSE}", "entidade": e, "variante": "login", "origem": "wayback",
              "timestamp": "20210101000000", "classe": CLASSE, "phash64": "0" * 16, "phash256": "0" * 64,
              "dominios": [d for t in TABELA if t["entidade"] == e for d in t["dominios"]], "s": S_VAZIO}
             for i, e in enumerate(entidades_t)]
    emb = {"small": _norm(rng.normal(size=(4, 576))), "large": _norm(rng.normal(size=(4, 960)))}
    pasta_base = os.path.join(pasta, "base")
    base.gravar(pasta_base, itens, emb, {})

    tipos = ["PayPal"] * n_por_tipo + ["Netflix"] * n_por_tipo + [None] * (2 * n_por_tipo)
    linhas, mats = [], {k: [] for k in ("dist_h64", "dist_h256", "cos_small", "cos_large", *base.SINAIS_S)}
    for i, ent in enumerate(tipos):
        proprio = np.array([e == ent for e in entidades_t])
        dist = np.where(proprio, rng.integers(4, 14, 4), rng.integers(26, 38, 4))
        cos = np.where(proprio, rng.uniform(0.85, 0.97, 4), rng.uniform(0.3, 0.75, 4))
        jac = np.where(proprio, rng.uniform(0.4, 0.8, 4), rng.uniform(0.0, 0.3, 4))
        mats["dist_h64"].append(dist)
        mats["dist_h256"].append(dist * 4)
        mats["cos_small"].append(cos)
        mats["cos_large"].append(cos)
        for k in base.SINAIS_S:
            mats[k].append(jac)
        id_ = f"a{i}"
        url = "https://www.paypal.com/" if i == 2 * n_por_tipo else f"http://golpe{i}.test/"  # 1 legítima própria
        linhas.append({"id": id_, "classe": CLASSE, "linha_na_classe": i, "particao": "",
                       "rotulo": "phishing" if ent else "benigno", "marca": ent or "", "entidade": ent,
                       "url": url, "elementos": 40})
    prefixo = os.path.join(pasta, "similaridades_phishpedia_phish")
    with open(prefixo + ".jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(l) + "\n" for l in linhas)
    tipos_npz = {"dist_h64": np.uint8, "dist_h256": np.uint16}
    np.savez(prefixo + ".npz", **{f"{CLASSE}__{k}": np.array(v, dtype=tipos_npz.get(k, np.float16))
                                  for k, v in mats.items()}, **{f"{CLASSE}__templates": np.arange(4)})

    amostras = [{"dataset": "phishpedia_phish", "id": l["id"], "particao": "", "rotulo": l["rotulo"],
                 "entidade": l["entidade"], "marca": l["marca"], "elementos": 40, "hash": f"k{l['id']}"}
                for l in linhas]
    caminho_divisao = os.path.join(pasta, "divisao.csv")
    divisao.gravar_divisao(caminho_divisao, divisao.dividir(amostras))
    caminho_marcas = os.path.join(pasta, "marcas.json")
    with open(caminho_marcas, "w", encoding="utf-8") as f:
        json.dump(TABELA, f)
    return {"prefixo": prefixo, "divisao": caminho_divisao, "base": pasta_base, "marcas": caminho_marcas}


class TestTreinar(unittest.TestCase):
    def test_pares_sem_dominio_proprio_e_pesos_equilibrados(self):
        with tempfile.TemporaryDirectory() as d:
            c = montar_cenario(d)
            b = base.Base.carregar(c["base"])
            nomes = script.cascata.nomes_caracteristicas()
            conj = script.carregar_conjunto([c["prefixo"]], divisao.ler_divisao(c["divisao"]), b, TABELA,
                                            None, nomes)
        self.assertEqual(conj["X"].shape, (160, 2, len(nomes)))
        self.assertEqual(conj["entidades"], ["Netflix", "PayPal"])
        i_propria = [m["id"] for m in conj["meta"]].index("a80")
        self.assertTrue(conj["legit"][i_propria, conj["entidades"].index("PayPal")])
        X, y, w = script.pares_de_treino(conj, np.ones(160, dtype=bool))
        self.assertEqual(len(X), 160 * 2 - 1)  # o par (página do PayPal em paypal.com, PayPal) sai do treino
        self.assertEqual(int(y.sum()), 80)
        self.assertAlmostEqual(float(w[y].sum()), float(w[~y].sum()), places=6)

    def test_main_treina_compara_e_salva(self):
        with tempfile.TemporaryDirectory() as d:
            c = montar_cenario(d)
            saida = os.path.join(d, "modelos")
            argv = ["treinar.py", "--tabelas", c["prefixo"], "--divisao", c["divisao"], "--base", c["base"],
                    "--marcas", c["marcas"], "--saida", saida, "--arvores", "10", "--n-jobs", "1"]
            with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
                script.main()
            for tipo in ("regressao", "floresta"):
                with open(os.path.join(saida, tipo, "modelo.json"), encoding="utf-8") as f:
                    m = json.load(f)
                self.assertIn("theta_h", m["cascata"])
                self.assertIn("tau", m["cascata"])
                self.assertEqual(m["caracteristicas"]["nomes"], script.cascata.nomes_caracteristicas())
            self.assertTrue(os.path.exists(os.path.join(saida, "floresta", "floresta.joblib")))
            self.assertTrue(os.path.exists(os.path.join(saida, "comparacao_dev.md")))
            with open(os.path.join(saida, "comparacao_dev.json"), encoding="utf-8") as f:
                comp = json.load(f)
            for tipo in ("regressao", "floresta"):
                self.assertGreater(comp["modelos"][tipo]["geral"]["por_amostra"]["auc"], 0.9)
                self.assertEqual(len(comp["modelos"][tipo]["dobras"]), 5)


if __name__ == "__main__":
    unittest.main()
