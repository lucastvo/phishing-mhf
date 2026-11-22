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


def montar_cenario(pasta, n_por_tipo=40, semente=0, com_datas=False):
    """Base com 2 templates de PayPal e 2 de Netflix (1366x768) e tabelas sintéticas em que o phishing de
    cada marca tem pHash perto e cosseno alto com os templates dela. Devolve os caminhos."""
    rng = np.random.default_rng(semente)
    entidades_t = ["PayPal", "PayPal", "Netflix", "Netflix"]
    # com_datas: templates de anos diferentes (2019, ao vivo, 2019, 31/12/2025 com ano-alvo 2026) e amostras com a
    # data no id, como no Phishpedia, para exercitar os experimentos temporais da etapa 6
    origens = ["wayback", "ao_vivo", "wayback", "wayback"] if com_datas else ["wayback"] * 4
    stamps = ["20190101000000", None, "20190101000000", "20251231000000"] if com_datas else ["20210101000000"] * 4
    itens = [{"id": f"t{i}@{CLASSE}", "entidade": e, "variante": "login", "origem": origens[i],
              "timestamp": stamps[i], "classe": CLASSE, "phash64": "0" * 16, "phash256": "0" * 64,
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
        id_ = f"{ent or 'site'}+2020-05-15-{i // 60:02d}`{i % 60:02d}`00" if com_datas else f"a{i}"
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
    caminho_plano = os.path.join(pasta, "plano.json")
    with open(caminho_plano, "w", encoding="utf-8") as f:
        json.dump([{"id": f"t{i}", "anos_alvo": [2026 if i == 3 else 2019]} for i in range(4)], f)
    return {"prefixo": prefixo, "divisao": caminho_divisao, "base": pasta_base, "marcas": caminho_marcas,
            "plano": caminho_plano}


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
                    "--marcas", c["marcas"], "--saida", saida, "--arvores", "10", "--iteracoes", "10", "--n-jobs", "1"]
            with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
                script.main()
            for tipo in ("regressao", "floresta", "boosting"):
                with open(os.path.join(saida, tipo, "modelo.json"), encoding="utf-8") as f:
                    m = json.load(f)
                # padrão: um estágio só (sem filtro pelo pHash)
                self.assertEqual((m["cascata"]["estagio1"], m["cascata"]["theta_h"]), ("nenhum", None))
                self.assertIn("tau", m["cascata"])
                self.assertEqual(m["caracteristicas"]["nomes"], script.cascata.nomes_caracteristicas())
            self.assertTrue(os.path.exists(os.path.join(saida, "floresta", "floresta.joblib")))
            self.assertTrue(os.path.exists(os.path.join(saida, "comparacao_dev.md")))
            with open(os.path.join(saida, "comparacao_dev.json"), encoding="utf-8") as f:
                comp = json.load(f)
            for tipo in ("regressao", "floresta", "boosting"):
                self.assertGreater(comp["modelos"][tipo]["geral"]["por_amostra"]["auc"], 0.9)
                self.assertEqual(len(comp["modelos"][tipo]["dobras"]), 5)
                m = comp["modelos"][tipo]
                # resultado também no τ que maximiza o F1 e separado por s ausente (revisão final)
                self.assertIn("revocacao", m["geral_tau_f1"]["por_amostra"])
                self.assertEqual(set(m["por_s_ausente"]), {"com_s"})  # no cenário sintético todas têm s
                self.assertIn("phishing_T_no_estagio2", m["geral"]["por_estrutura"])
                self.assertIsNone(m["calibracao"]["theta_h"])
            with open(os.path.join(saida, "comparacao_dev.md"), encoding="utf-8") as f:
                md = f.read()
            self.assertIn("AUC do classificador", md)
            self.assertIn("No τ que maximiza o F1", md)

    def test_main_com_estagio1_e_floresta_compacta(self):
        with tempfile.TemporaryDirectory() as d:
            c = montar_cenario(d)
            saida = os.path.join(d, "modelos")
            argv = ["treinar.py", "--tabelas", c["prefixo"], "--divisao", c["divisao"], "--base", c["base"],
                    "--marcas", c["marcas"], "--saida", saida, "--modelos", "floresta", "--arvores", "5",
                    "--profundidade", "4", "--folha", "5", "--n-jobs", "1", "--estagio1", "phash"]
            with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
                script.main()
            modelo, info = script.cascata.carregar_modelo(os.path.join(saida, "floresta"))
            self.assertEqual(info["cascata"]["estagio1"], "phash")
            self.assertIsInstance(info["cascata"]["theta_h"], int)
            self.assertIn("fracao_legitimas_liberadas_estagio1_95", info["cascata"])
            self.assertEqual((modelo.rf.n_estimators, modelo.rf.max_depth, modelo.rf.min_samples_leaf), (5, 4, 5))


if __name__ == "__main__":
    unittest.main()
