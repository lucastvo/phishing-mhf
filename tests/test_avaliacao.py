import math
import os
import sys
import unittest
from datetime import date

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import avaliacao  # noqa: E402


def _conjunto():
    """6 amostras: 3 phishings de 𝒯 (PayPal, PayPal, Netflix), 3 legítimas (uma em paypal.com)."""
    return {"entidades": ["Netflix", "PayPal"],
            "meta": [{"id": f"x{i}", "grupo": g} for i, g in enumerate(["g1", "g1", "g2", "g3", "g4", "g5"])],
            "phishing_T": np.array([True, True, True, False, False, False]),
            "legitima": np.array([False, False, False, True, True, True]),
            "entidade_real": np.array(["PayPal", "PayPal", "Netflix", None, None, None], dtype=object),
            "dataset": np.array(["phishpedia_phish"] * 3 + ["phish360", "phishpedia_benign", "phishpedia_benign"]),
            "legit": np.array([[False, False]] * 5 + [[False, True]]),
            "cos_max": np.array([0.9, 0.9, 0.8, 0.5, 0.6, 0.95]),
            "s_ausente": np.array([False, False, True, False, False, False]),
            "pesos": np.array([0.5, 0.5, 1, 1, 1, 1])}


class TestBootstrap(unittest.TestCase):
    def test_metrica_constante_tem_intervalo_de_largura_zero(self):
        ic = avaliacao.ic_bootstrap(np.array(["a", "b", "c"]), lambda m: {"x": 0.7}, n=50)
        self.assertEqual(ic["x"], (0.7, 0.7))

    def test_reamostra_grupos_inteiros(self):
        # dois grupos: um com 3 amostras "1", outro com 1 amostra "0"; a média ponderada só pode valer
        # 0, 1 ou 0,75 (os dois grupos), nunca uma mistura de amostras de dentro do grupo
        grupos = np.array(["a", "a", "a", "b"])
        valores = np.array([1.0, 1.0, 1.0, 0.0])
        vistos = set()

        def calcular(mult):
            v = float((valores * mult).sum() / mult.sum())
            vistos.add(round(v, 6))
            return {"media": v}
        ic = avaliacao.ic_bootstrap(grupos, calcular, n=200, semente=1)
        self.assertTrue(vistos <= {0.0, 1.0, 0.75})
        self.assertLessEqual(ic["media"][0], ic["media"][1])

    def test_metrica_indefinida_da_nan(self):
        ic = avaliacao.ic_bootstrap(np.array(["a"]), lambda m: {"x": float("nan")}, n=20)
        self.assertTrue(math.isnan(ic["x"][0]) and math.isnan(ic["x"][1]))


class TestGruposERecortes(unittest.TestCase):
    def test_grupos_fpr(self):
        g = avaliacao.grupos_fpr(_conjunto())
        self.assertEqual(g["todas"].tolist(), [False, False, False, True, True, True])
        self.assertEqual(g["phish360"].tolist(), [False, False, False, True, False, False])
        self.assertEqual(g["phishpedia_benign"].tolist(), [False, False, False, False, True, True])
        self.assertEqual(g["paginas_das_marcas"].tolist(), [False] * 5 + [True])
        self.assertEqual(g["mais_parecidas"].tolist(), [False] * 5 + [True])  # decil superior do cosseno

    def test_tipo_de_pagina(self):
        c = _conjunto()
        senha = {"x0": 1, "x1": 0, "x2": 2, "x3": 0, "x4": None, "x5": 1}
        tipos = avaliacao.tipo_de_pagina(c, lambda m: senha[m["id"]])
        self.assertEqual(tipos.tolist(), ["com_senha", "sem_senha", "sem_dom", "sem_senha", "sem_senha", "com_senha"])

    def test_por_marca(self):
        c = _conjunto()
        decisao = {"phishing": np.array([True, False, True, False, False, False]),
                   "entidade": np.array([1, 1, 1, -1, -1, -1])}
        linhas = {l["entidade"]: l for l in avaliacao.por_marca(c, decisao)}
        self.assertEqual((linhas["PayPal"]["amostras"], linhas["PayPal"]["estruturas"]), (2, 1))
        self.assertAlmostEqual(linhas["PayPal"]["revocacao"], 0.5)
        self.assertAlmostEqual(linhas["PayPal"]["top1_detectados"], 1.0)
        self.assertAlmostEqual(linhas["Netflix"]["top1_detectados"], 0.0)  # detectado como PayPal


class TestDatas(unittest.TestCase):
    def test_datas(self):
        self.assertEqual(avaliacao.data_da_amostra("PayPal Inc.+2019-07-28-14`50`12"), date(2019, 7, 28))
        self.assertIsNone(avaliacao.data_da_amostra("trainval\\P10001_paypal"))
        self.assertEqual(avaliacao.data_do_template({"origem": "wayback", "timestamp": "20181229101010"}),
                         date(2018, 12, 29))
        self.assertEqual(avaliacao.data_do_template({"origem": "ao_vivo", "timestamp": None}), date(2026, 11, 21))

    def test_filtros(self):
        itens = [{"origem": "wayback", "timestamp": "20190101000000"},
                 {"origem": "wayback", "timestamp": "20260101000000"},
                 {"origem": "ao_vivo", "timestamp": None},
                 {"origem": "wayback", "timestamp": "20200601000000"}]
        self.assertEqual(avaliacao.filtro_2026({}, itens).tolist(), [False, True, True, False])
        f = avaliacao.filtro_ate_data(date(2020, 10, 31))
        phish = {"id": "PayPal Inc.+2019-07-28-14`50`12", "rotulo": "phishing"}
        self.assertEqual(f(phish, itens).tolist(), [True, False, False, False])
        legit = {"id": "exemplo.com", "rotulo": "benigno"}
        self.assertEqual(f(legit, itens).tolist(), [True, False, False, True])  # corte padrão
        sem_data = {"id": "Marca+sem-data", "rotulo": "phishing"}
        self.assertEqual(f(sem_data, itens).tolist(), [True, False, False, True])


class TestLatex(unittest.TestCase):
    def test_numero(self):
        self.assertEqual(avaliacao.numero(0.84912), "0,849")
        self.assertEqual(avaliacao.numero(float("nan")), "—")
        self.assertEqual(avaliacao.numero(None), "—")
        self.assertEqual(avaliacao.numero(12.345, 1), "12,3")
        self.assertEqual(avaliacao.percentual(0.3811), "38,1\\%")

    def test_tabela_latex(self):
        t = avaliacao.tabela_latex(["Modelo", "AUC"], [["Boosting", "0,849"], ["AT&T_x", "0,5"]],
                                   "Resultado no teste.", "tab:teste")
        for trecho in ("\\toprule", "\\midrule", "\\bottomrule", "\\caption{Resultado no teste.}",
                       "\\label{tab:teste}", "Modelo & AUC \\\\", "Boosting & 0,849 \\\\", "\\begin{tabular}{lr}"):
            self.assertIn(trecho, t)
        self.assertIn("AT\\&T\\_x", t)  # texto escapado


if __name__ == "__main__":
    unittest.main()
