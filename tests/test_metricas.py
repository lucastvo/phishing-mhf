import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import metricas  # noqa: E402


class TestBinarias(unittest.TestCase):
    def test_sem_pesos(self):
        real = [1, 1, 1, 0, 0, 0, 0, 0]
        prev = [1, 1, 0, 1, 0, 0, 0, 0]
        m = metricas.binarias(real, prev)
        self.assertEqual((m["vp"], m["fn"], m["fp"], m["vn"]), (2, 1, 1, 4))
        self.assertAlmostEqual(m["precisao"], 2 / 3)
        self.assertAlmostEqual(m["revocacao"], 2 / 3)
        self.assertAlmostEqual(m["f1"], 2 / 3)
        self.assertAlmostEqual(m["fpr"], 1 / 5)
        self.assertAlmostEqual(m["especificidade"], 4 / 5)
        self.assertAlmostEqual(m["acuracia"], 6 / 8)

    def test_com_pesos(self):
        # o primeiro positivo vale por quatro cópias com peso 0,25 cada
        m = metricas.binarias([1, 1, 0], [1, 0, 0], pesos=[0.25, 1.0, 1.0])
        self.assertAlmostEqual(m["revocacao"], 0.25 / 1.25)

    def test_divisao_por_zero_da_nan(self):
        m = metricas.binarias([0, 0], [0, 0])
        self.assertTrue(math.isnan(m["precisao"]) and math.isnan(m["revocacao"]))
        self.assertEqual(m["fpr"], 0.0)


class TestAucTop1(unittest.TestCase):
    def test_auc(self):
        self.assertEqual(metricas.auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]), 1.0)
        self.assertEqual(metricas.auc([0, 0, 1, 1], [0.9, 0.8, 0.2, 0.1]), 0.0)
        self.assertTrue(math.isnan(metricas.auc([1, 1], [0.1, 0.2])))

    def test_top1(self):
        self.assertAlmostEqual(metricas.top1(["A", "B", "C"], ["A", None, "C"]), 2 / 3)
        self.assertAlmostEqual(metricas.top1(["A", "B"], ["A", "X"], pesos=[3, 1]), 0.75)


class TestLimiares(unittest.TestCase):
    def test_limiar_para_fpr(self):
        neg = np.arange(10) / 10  # 0,0 ... 0,9
        tau = metricas.limiar_para_fpr(neg, np.ones(10), 10.0, alvo=0.1)
        self.assertEqual(int((neg >= tau).sum()), 1)  # exatamente 1 de 10 acima do limiar
        self.assertGreater(tau, 0.8)
        # negativos liberados antes (fora da lista) contam só no total: com 20 no total, cabem 2
        tau2 = metricas.limiar_para_fpr(neg, np.ones(10), 20.0, alvo=0.1)
        self.assertEqual(int((neg >= tau2).sum()), 2)

    def test_limiar_para_fpr_com_empate(self):
        neg = np.array([0.9, 0.9, 0.5, 0.1])
        tau = metricas.limiar_para_fpr(neg, np.ones(4), 4.0, alvo=0.3)
        # os dois 0,9 juntos passariam de 30%: o limiar fica acima deles
        self.assertEqual(int((neg >= tau).sum()), 0)

    def test_limiar_para_fpr_sem_negativos(self):
        self.assertEqual(metricas.limiar_para_fpr(np.array([]), np.array([]), 5.0, 0.01), -np.inf)

    def test_limiar_f1(self):
        escores = np.array([0.9, 0.8, 0.7, 0.4, 0.3])
        positivo = np.array([True, True, False, True, False])
        tau = metricas.limiar_f1(escores, positivo, np.ones(5), peso_total_pos=3.0)
        self.assertAlmostEqual(tau, 0.4)  # vp 3, fp 1 → F1 = 6/7 (o melhor)


if __name__ == "__main__":
    unittest.main()
