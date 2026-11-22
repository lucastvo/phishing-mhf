import math
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import cascata  # noqa: E402

ENTIDADES = ["Netflix", "PayPal"]
COLUNAS = np.array(["PayPal", "PayPal", "Netflix"])
TABELA = [{"entidade": "PayPal", "dominios": ["paypal.com"]}, {"entidade": "Netflix", "dominios": ["netflix.com"]}]


def _sinais(n=1):
    """Duas amostras × três templates (PayPal, PayPal, Netflix)."""
    return {"dist_h64": np.array([[2, 30, 40], [33, 35, 34]]),
            "sim_h64": 1 - np.array([[2, 30, 40], [33, 35, 34]], dtype=np.float32) / 64,
            "cos_small": np.array([[0.70, 0.95, 0.30], [0.2, 0.1, 0.6]], dtype=np.float32),
            "jaccard_caminhos": np.array([[0.9, 0.2, 0.1], [np.nan, np.nan, np.nan]], dtype=np.float32),
            "jaccard_criticos": np.array([[1.0, 0.5, 0.0], [np.nan, np.nan, np.nan]], dtype=np.float32),
            "sim_contagens": np.array([[0.8, 0.9, 0.2], [np.nan, np.nan, np.nan]], dtype=np.float32),
            "hash_igual": np.array([[0.0, 1.0, 0.0], [np.nan, np.nan, np.nan]], dtype=np.float32)}


class TestCaracteristicas(unittest.TestCase):
    def test_nomes(self):
        self.assertEqual(cascata.nomes_caracteristicas(), ["sim_h64", "cos_small", "jaccard_caminhos",
                                                           "jaccard_criticos", "sim_contagens", "hash_igual",
                                                           "s_ausente"])
        self.assertEqual(cascata.nomes_caracteristicas(("e",), embedding="large"), ["cos_large"])
        self.assertEqual(cascata.nomes_caracteristicas(("h",), hash_bits=256), ["sim_h256"])
        with self.assertRaises(ValueError):
            cascata.nomes_caracteristicas(("x",))

    def test_caracteristicas_maximo_por_entidade_e_sinal(self):
        nomes = cascata.nomes_caracteristicas()
        X = cascata.caracteristicas(_sinais(), COLUNAS, ENTIDADES, np.array([False, True]), nomes)
        self.assertEqual(X.shape, (2, 2, 7))
        paypal = dict(zip(nomes, X[0, 1]))
        # o melhor pHash vem do 1º template do PayPal e o melhor cosseno do 2º: máximos separados por sinal
        self.assertAlmostEqual(paypal["sim_h64"], 1 - 2 / 64)
        self.assertAlmostEqual(paypal["cos_small"], 0.95, places=6)
        self.assertAlmostEqual(paypal["jaccard_caminhos"], 0.9, places=6)
        self.assertEqual((paypal["hash_igual"], paypal["s_ausente"]), (1.0, 0.0))
        self.assertAlmostEqual(dict(zip(nomes, X[0, 0]))["cos_small"], 0.30, places=6)  # Netflix

    def test_s_ausente_zera_s(self):
        nomes = cascata.nomes_caracteristicas()
        X = cascata.caracteristicas(_sinais(), COLUNAS, ENTIDADES, np.array([True, True]), nomes)
        s = [nomes.index(k) for k in ("jaccard_caminhos", "jaccard_criticos", "sim_contagens", "hash_igual")]
        self.assertTrue((X[:, :, s] == 0).all())  # inclusive a amostra 0, que tinha s mas foi marcada ausente
        self.assertTrue((X[:, :, nomes.index("s_ausente")] == 1).all())
        self.assertFalse(np.isnan(X).any())

    def test_entidade_sem_template_fica_nan(self):
        nomes = cascata.nomes_caracteristicas(("e",))
        X = cascata.caracteristicas(_sinais(), COLUNAS, ["Amazon", "PayPal"], np.array([False, False]), nomes)
        self.assertTrue(np.isnan(X[:, 0, :]).all())
        self.assertFalse(np.isnan(X[:, 1, :]).any())

    def test_estagio1_menor_distancia_e_empate(self):
        d1, t1 = cascata.estagio1(np.array([[2, 30, 40], [7, 9, 7]]), COLUNAS, ENTIDADES)
        self.assertEqual(list(d1), [2, 7])
        self.assertEqual([ENTIDADES[i] for i in t1], ["PayPal", "PayPal"])  # empate: a 1ª coluna

    def test_matriz_dominio_legitimo(self):
        legit = cascata.matriz_dominio_legitimo(["https://www.paypal.com/signin", "http://paypal.com.evil.net/",
                                                 "netflix.com"], ENTIDADES, TABELA)
        self.assertEqual(legit.tolist(), [[False, True], [False, False], [True, False]])


class TestAplicarCascata(unittest.TestCase):
    def test_cascata_motivos(self):
        d1 = np.array([40, 5, 5, 5, 5])
        t1 = np.array([1, 1, 1, 1, 1])
        escores = np.array([[0.1, 0.9], [0.1, 0.9], [0.2, 0.3], [0.1, 0.9], [0.8, np.nan]])
        legit = np.zeros((5, 2), dtype=bool)
        legit[1, 1] = True   # está no domínio do PayPal, que é também t1
        legit[3, 1] = False
        r = cascata.aplicar_cascata(d1, t1, escores, legit, theta_h=20, tau=0.5)
        self.assertEqual(r["motivo"], ["sem_template_proximo", "dominio_legitimo_estagio1", "abaixo_do_limiar",
                                       "phishing", "phishing"])
        self.assertEqual(r["estagio"].tolist(), [1, 1, 2, 2, 2])
        self.assertEqual(r["phishing"].tolist(), [False, False, False, True, True])
        self.assertEqual(r["entidade"].tolist(), [-1, 1, 1, 1, 0])  # NaN não disputa o máximo
        self.assertTrue(math.isnan(r["escore"][0]))
        self.assertAlmostEqual(float(r["escore"][3]), 0.9)

    def test_dominio_legitimo_libera_no_estagio2(self):
        # t1 (pelo pHash) é o PayPal, mas o escore maior é da Netflix e a página está em netflix.com
        legit = np.array([[True, False]])
        r = cascata.aplicar_cascata(np.array([5]), np.array([1]), np.array([[0.9, 0.2]]), legit, 20, 0.5)
        self.assertEqual((r["motivo"][0], bool(r["phishing"][0]), int(r["entidade"][0])),
                         ("dominio_legitimo_estagio2", False, 0))


class TestModelos(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        self.X = rng.normal(size=(300, 3))
        self.y = (self.X[:, 0] + 0.5 * self.X[:, 1] + rng.normal(scale=0.5, size=300)) > 0
        self.w = rng.uniform(0.2, 1.0, size=300)
        self.nomes = ["a", "b", "c"]

    def test_regressao_json_igual_ao_sklearn(self):
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        m = cascata.RegressaoLogistica.treinar(self.X, self.y, self.w, self.nomes)
        esc = StandardScaler().fit(self.X, sample_weight=self.w)
        lr = LogisticRegression(C=1.0, max_iter=1000).fit(esc.transform(self.X), self.y, sample_weight=self.w)
        np.testing.assert_allclose(m.pontuar(self.X), lr.predict_proba(esc.transform(self.X))[:, 1], atol=1e-9)

    def test_salvar_e_carregar(self):
        for modelo in (cascata.RegressaoLogistica.treinar(self.X, self.y, self.w, self.nomes),
                       cascata.Floresta.treinar(self.X, self.y, self.w, self.nomes, arvores=20, n_jobs=1)):
            with tempfile.TemporaryDirectory() as pasta:
                cascata.salvar_modelo(pasta, modelo, {"cascata": {"theta_h": 20, "tau": 0.5}})
                lido, extras = cascata.carregar_modelo(pasta)
            self.assertEqual((lido.tipo, lido.nomes), (modelo.tipo, self.nomes))
            np.testing.assert_allclose(lido.pontuar(self.X), modelo.pontuar(self.X))
            self.assertEqual(extras["cascata"]["tau"], 0.5)

    def test_pontuar_amostras_respeita_nan(self):
        m = cascata.RegressaoLogistica.treinar(self.X, self.y, self.w, self.nomes)
        X3 = np.stack([self.X[:4], np.full((4, 3), np.nan)], axis=1)  # (4 amostras, 2 entidades, 3)
        e = cascata.pontuar_amostras(m, X3)
        self.assertEqual(e.shape, (4, 2))
        self.assertTrue(np.isnan(e[:, 1]).all())
        np.testing.assert_allclose(e[:, 0], m.pontuar(self.X[:4]))


if __name__ == "__main__":
    unittest.main()
